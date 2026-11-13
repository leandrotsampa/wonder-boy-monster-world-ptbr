"""Frontend libretro mínimo (ctypes) para rodar o Genesis Plus GX sem janela.

Uso típico::

    emu = Emulador(CORE_PADRAO, Path("rom/jogo.bin"))
    emu.avancar(600)
    emu.quadro_png(Path("build/boot.png"))
    emu.fechar()

Atenção: um core libretro é uma biblioteca com estado global. Só pode haver
**uma** instância de ``Emulador`` viva por processo; criar outra antes de
``fechar()`` a primeira levanta ``RuntimeError``. Para recomeçar do zero use
``reiniciar()`` (volta ao estado salvo logo depois de carregar a ROM).
"""

from __future__ import annotations

import ctypes
import hashlib
import warnings
from ctypes import (POINTER, c_bool, c_char_p, c_int16, c_size_t, c_uint, c_uint64,
                    c_void_p)
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parents[2]
CORE_PADRAO = RAIZ / "emu" / "genesis_plus_gx_libretro.dll"
DIR_SISTEMA = RAIZ / "emu" / "sistema"

# --- constantes da API libretro (libretro.h) ---
RETRO_DEVICE_JOYPAD = 1
RETRO_MEMORY_SYSTEM_RAM = 2
RETRO_MEMORY_VIDEO_RAM = 3

ENV_GET_CAN_DUPE = 3
ENV_GET_SYSTEM_DIRECTORY = 9
ENV_SET_PIXEL_FORMAT = 10
ENV_GET_VARIABLE = 15
ENV_GET_VARIABLE_UPDATE = 17
ENV_GET_SAVE_DIRECTORY = 31
ENV_SET_MEMORY_MAPS = 36 | 0x10000  # RETRO_ENVIRONMENT_EXPERIMENTAL

FORMATO_0RGB1555 = 0
FORMATO_XRGB8888 = 1
FORMATO_RGB565 = 2
_MODO_RAW = {FORMATO_0RGB1555: "BGR;15", FORMATO_XRGB8888: "BGRX", FORMATO_RGB565: "BGR;16"}

# RetroPad (RETRO_DEVICE_ID_JOYPAD_*)
_PAD_B, _PAD_Y, _PAD_SELECT, _PAD_START = 0, 1, 2, 3
_PAD_CIMA, _PAD_BAIXO, _PAD_ESQ, _PAD_DIR = 4, 5, 6, 7
_PAD_A, _PAD_X = 8, 9

# Mapeamento botão do Mega Drive -> RetroPad usado pelo Genesis Plus GX (controle
# de 3 botões): Y -> A, B -> B, A -> C. Conferido empiricamente na ROM base: cada
# botão do RetroPad acende o bit esperado (SACBRLDU) no byte de controle da RAM.
BOTOES: dict[str, int] = {
    "cima": _PAD_CIMA,
    "baixo": _PAD_BAIXO,
    "esq": _PAD_ESQ,
    "dir": _PAD_DIR,
    "a": _PAD_Y,
    "b": _PAD_B,
    "c": _PAD_A,
    "start": _PAD_START,
}

TAM_RAM = 0x10000
TAM_VRAM = 0x10000


class _GameInfo(ctypes.Structure):
    _fields_ = [("path", c_char_p), ("data", c_void_p), ("size", c_size_t), ("meta", c_char_p)]


class _SystemInfo(ctypes.Structure):
    _fields_ = [("library_name", c_char_p), ("library_version", c_char_p),
                ("valid_extensions", c_char_p), ("need_fullpath", c_bool),
                ("block_extract", c_bool)]


class _MemoryDescriptor(ctypes.Structure):
    _fields_ = [("flags", c_uint64), ("ptr", c_void_p), ("offset", c_size_t),
                ("start", c_size_t), ("select", c_size_t), ("disconnect", c_size_t),
                ("len", c_size_t), ("addrspace", c_char_p)]


class _MemoryMap(ctypes.Structure):
    _fields_ = [("descriptors", POINTER(_MemoryDescriptor)), ("num_descriptors", c_uint)]


_ENV_CB = ctypes.CFUNCTYPE(c_bool, c_uint, c_void_p)
_VIDEO_CB = ctypes.CFUNCTYPE(None, c_void_p, c_uint, c_uint, c_size_t)
_AUDIO_CB = ctypes.CFUNCTYPE(None, c_int16, c_int16)
_AUDIO_BATCH_CB = ctypes.CFUNCTYPE(c_size_t, c_void_p, c_size_t)
_POLL_CB = ctypes.CFUNCTYPE(None)
_STATE_CB = ctypes.CFUNCTYPE(c_int16, c_uint, c_uint, c_uint, c_uint)

_instancia_viva: "Emulador | None" = None


def _desembaralhar(dados: bytes) -> bytes:
    """Troca os bytes de cada palavra de 16 bits (o GPGX guarda RAM/VRAM em
    little-endian no host; o 68000 enxerga big-endian)."""
    b = bytearray(dados)
    b[0::2], b[1::2] = dados[1::2], dados[0::2]
    return bytes(b)


# Formato do save state do GPGX (core/state.c, modo Mega Drive), em bytes:
#   16      string de versão "GENPLUS-GX x.y.z"
#   0x10000 work_ram (RAM do 68000)      0x2000 zram (RAM do Z80)
#   1       zstate                       4      zbank
#   0x10    io_reg                       0x400  sat (cache da tabela de sprites)
#   0x10000 vram    0x80 cram    0x80 vsram    0x20 registradores do VDP ...
# Esse layout vale SÓ para o modo Mega Drive (sem Mega CD / 32X / Master System),
# que é o único que este projeto usa. Conferido no core validado (abaixo):
# work_ram do estado == retro_get_memory_data(SYSTEM_RAM); o registrador 5 aponta
# a tabela de sprites (0xD000 na ROM base) e o cache `sat` bate com a VRAM nesse
# endereço. Como a RAM, a VRAM vem em palavras little-endian (ver _desembaralhar).
#
# Guardas: a versão de 16 bytes tem de ser exatamente a validada, o tamanho do
# estado tem de ser o validado (retro_serialize_size() == 0xFD000) e o cache
# `sat` tem de reaparecer na VRAM extraída no endereço do registrador 5.
VERSAO_ESTADO_VALIDADA = b"GENPLUS-GX 1.7.6"
TAM_ESTADO_VALIDADO = 0xFD000
_OFFSET_VRAM_ESTADO = 16 + 0x10000 + 0x2000 + 1 + 4 + 0x10 + 0x400
_REL_REGS_VRAM = TAM_VRAM + 0x80 + 0x80  # registradores, relativos ao início da VRAM

# Core validado: genesis_plus_gx_libretro.dll (Windows x86_64, buildbot nightly
# baixado em 2026-11-11), library_version "v1.7.4 b9c2316", estado "GENPLUS-GX 1.7.6".
# Com outro core, Emulador avisa (RuntimeWarning) e vram() fica desativada.
SHA256_CORE_VALIDADO = "eb8cf338bb7b6468777edbaf2f44dd9920a506b64e52e642cb116610eeecd28f"


def _vram_do_estado(estado: bytes) -> bytes:
    """Extrai a VRAM crua (palavras little-endian) de um save state do GPGX."""
    versao = bytes(estado[:16])
    if versao != VERSAO_ESTADO_VALIDADA:
        raise RuntimeError(f"save state de versão não validada: {versao!r} "
                           f"(esperado {VERSAO_ESTADO_VALIDADA!r})")
    if len(estado) != TAM_ESTADO_VALIDADO:
        raise RuntimeError(f"save state com tamanho inesperado: {len(estado):#x} "
                           f"(esperado {TAM_ESTADO_VALIDADO:#x})")
    o = _OFFSET_VRAM_ESTADO
    dados = bytes(estado[o:o + TAM_VRAM])
    regs = estado[o + _REL_REGS_VRAM:o + _REL_REGS_VRAM + 0x20]
    h40 = bool(regs[12] & 0x01)
    end_sat = (regs[5] & (0x7E if h40 else 0x7F)) << 9
    sat = estado[o - 0x400:o]
    # O cache guarda pelo menos os 4 primeiros bytes de cada entrada (Y, tamanho, link).
    for i in range(0, (80 if h40 else 64) * 8, 8):
        if sat[i:i + 4] != dados[(end_sat + i) % TAM_VRAM:(end_sat + i) % TAM_VRAM + 4]:
            raise RuntimeError(f"cache da SAT não bate com a VRAM em {end_sat:#06x}: "
                               "layout do save state diferente do validado")
    return dados


class Emulador:
    """Genesis Plus GX controlado quadro a quadro (uma instância por processo)."""

    def __init__(self, caminho_core: Path, caminho_rom: Path):
        global _instancia_viva
        if _instancia_viva is not None:
            raise RuntimeError("já existe um Emulador aberto neste processo; feche-o antes")
        caminho_core = Path(caminho_core)
        caminho_rom = Path(caminho_rom)
        if not caminho_core.is_file():
            raise FileNotFoundError(f"core libretro não encontrado: {caminho_core}")
        if not caminho_rom.is_file():
            raise FileNotFoundError(f"ROM não encontrada: {caminho_rom}")

        self.core_validado = (hashlib.sha256(caminho_core.read_bytes()).hexdigest()
                              == SHA256_CORE_VALIDADO)
        if not self.core_validado:
            warnings.warn(f"core libretro diferente do validado ({caminho_core.name}); "
                          "capturas funcionam, mas vram() fica desativada (ver README)",
                          RuntimeWarning, stacklevel=2)
        self._lib = ctypes.CDLL(str(caminho_core))
        self._configurar_assinaturas()

        DIR_SISTEMA.mkdir(parents=True, exist_ok=True)
        self._dir_sistema = ctypes.create_string_buffer(str(DIR_SISTEMA).encode("utf-8"))
        self._formato = FORMATO_0RGB1555
        self._quadro: tuple[bytes, int, int, int] | None = None
        self._botoes: set[int] = set()
        self._mapas: list[_MemoryDescriptor] = []

        # Guardar referências aos callbacks: se o GC os coletar, o core chama lixo.
        self._cbs = (
            _ENV_CB(self._cb_ambiente),
            _VIDEO_CB(self._cb_video),
            _AUDIO_CB(lambda e, d: None),
            _AUDIO_BATCH_CB(lambda dados, quadros: quadros),
            _POLL_CB(lambda: None),
            _STATE_CB(self._cb_estado_entrada),
        )
        lib = self._lib
        lib.retro_set_environment(self._cbs[0])
        lib.retro_init()
        lib.retro_set_video_refresh(self._cbs[1])
        lib.retro_set_audio_sample(self._cbs[2])
        lib.retro_set_audio_sample_batch(self._cbs[3])
        lib.retro_set_input_poll(self._cbs[4])
        lib.retro_set_input_state(self._cbs[5])

        info = _SystemInfo()
        lib.retro_get_system_info(ctypes.byref(info))
        self._rom = caminho_rom.read_bytes()
        self._buf_rom = ctypes.create_string_buffer(self._rom, len(self._rom))
        self._caminho_rom_c = ctypes.create_string_buffer(str(caminho_rom).encode("utf-8"))
        jogo = _GameInfo(ctypes.cast(self._caminho_rom_c, c_char_p),
                         None if info.need_fullpath else ctypes.cast(self._buf_rom, c_void_p),
                         0 if info.need_fullpath else len(self._rom), None)
        if not lib.retro_load_game(ctypes.byref(jogo)):
            lib.retro_deinit()
            raise RuntimeError(f"o core recusou a ROM: {caminho_rom}")
        _instancia_viva = self
        self._aberto = True
        self._estado_inicial = self.salvar_estado()

    # --- ciclo de vida ---
    def _configurar_assinaturas(self) -> None:
        lib = self._lib
        lib.retro_load_game.restype = c_bool
        lib.retro_load_game.argtypes = [POINTER(_GameInfo)]
        lib.retro_get_memory_data.restype = c_void_p
        lib.retro_get_memory_data.argtypes = [c_uint]
        lib.retro_get_memory_size.restype = c_size_t
        lib.retro_get_memory_size.argtypes = [c_uint]
        lib.retro_serialize_size.restype = c_size_t
        lib.retro_serialize.restype = c_bool
        lib.retro_serialize.argtypes = [c_void_p, c_size_t]
        lib.retro_unserialize.restype = c_bool
        lib.retro_unserialize.argtypes = [c_void_p, c_size_t]

    def reiniciar(self) -> None:
        """Volta ao estado de logo depois de ligar (determinístico)."""
        self.carregar_estado(self._estado_inicial)
        self._quadro = None

    def fechar(self) -> None:
        global _instancia_viva
        if not getattr(self, "_aberto", False):
            return
        self._lib.retro_unload_game()
        self._lib.retro_deinit()
        self._aberto = False
        _instancia_viva = None

    def __enter__(self) -> "Emulador":
        return self

    def __exit__(self, *_exc) -> None:
        self.fechar()

    # --- callbacks ---
    def _cb_ambiente(self, cmd: int, dados: int) -> bool:
        if cmd == ENV_SET_PIXEL_FORMAT:
            formato = ctypes.cast(dados, POINTER(ctypes.c_int)).contents.value
            if formato in (FORMATO_XRGB8888, FORMATO_RGB565):
                self._formato = formato
                return True
            return False
        if cmd in (ENV_GET_SYSTEM_DIRECTORY, ENV_GET_SAVE_DIRECTORY):
            ctypes.cast(dados, POINTER(c_char_p))[0] = ctypes.cast(self._dir_sistema, c_char_p)
            return True
        if cmd == ENV_GET_CAN_DUPE:
            ctypes.cast(dados, POINTER(c_bool))[0] = True
            return True
        if cmd == ENV_GET_VARIABLE:
            return False  # sem opções: o core usa os padrões
        if cmd == ENV_GET_VARIABLE_UPDATE:
            ctypes.cast(dados, POINTER(c_bool))[0] = False
            return True
        if cmd == ENV_SET_MEMORY_MAPS:
            mapa = ctypes.cast(dados, POINTER(_MemoryMap)).contents
            self._mapas = [_MemoryDescriptor.from_buffer_copy(mapa.descriptors[i])
                           for i in range(mapa.num_descriptors)]
            return True
        return False

    def _cb_video(self, dados: int, largura: int, altura: int, pitch: int) -> None:
        if dados:  # NULL = repetir o quadro anterior (GET_CAN_DUPE)
            self._quadro = (ctypes.string_at(dados, pitch * altura), largura, altura, pitch)

    def _cb_estado_entrada(self, porta: int, dispositivo: int, indice: int, ident: int) -> int:
        if porta == 0 and dispositivo == RETRO_DEVICE_JOYPAD and ident in self._botoes:
            return 1
        return 0

    # --- API pública ---
    def avancar(self, quadros: int, botoes: set[str] = frozenset()) -> None:
        """Roda ``quadros`` quadros segurando ``botoes`` (nomes em ``BOTOES``)."""
        desconhecidos = set(botoes) - BOTOES.keys()
        if desconhecidos:
            raise ValueError(f"botões desconhecidos: {sorted(desconhecidos)}")
        self._botoes = {BOTOES[b] for b in botoes}
        try:
            for _ in range(quadros):
                self._lib.retro_run()
        finally:
            self._botoes = set()

    def quadro_png(self, caminho: Path) -> None:
        """Grava o último quadro de vídeo como PNG RGB (tamanho que o core entregou)."""
        if self._quadro is None:
            raise RuntimeError("nenhum quadro de vídeo ainda; avance pelo menos 1 quadro")
        dados, largura, altura, pitch = self._quadro
        img = Image.frombuffer("RGB", (largura, altura), dados, "raw",
                               _MODO_RAW[self._formato], pitch, 1)
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        img.save(caminho, format="PNG")

    def _memoria(self, ident: int) -> bytes | None:
        ptr = self._lib.retro_get_memory_data(ident)
        tam = self._lib.retro_get_memory_size(ident)
        if not ptr or not tam:
            return None
        return ctypes.string_at(ptr, tam)

    def ram(self) -> bytes:
        """64 KB da RAM do 68000 (0xFF0000–0xFFFFFF), na ordem do 68000."""
        dados = self._memoria(RETRO_MEMORY_SYSTEM_RAM)
        if dados is None or len(dados) < TAM_RAM:
            raise RuntimeError("o core não expõe a RAM do sistema")
        return _desembaralhar(dados[:TAM_RAM])

    def escrever_ram(self, endereco: int, dados: bytes) -> None:
        """Grava ``dados`` na RAM do 68000 a partir de ``endereco`` (0–0xFFFF, ordem do
        68000; o core guarda as palavras invertidas, ver ``_desembaralhar``)."""
        if endereco < 0 or endereco + len(dados) > TAM_RAM:
            raise ValueError(f"escrita fora da RAM: {endereco:#x} + {len(dados)} bytes")
        ptr = self._lib.retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM)
        if not ptr or self._lib.retro_get_memory_size(RETRO_MEMORY_SYSTEM_RAM) < TAM_RAM:
            raise RuntimeError("o core não expõe a RAM do sistema")
        ram = (ctypes.c_uint8 * TAM_RAM).from_address(ptr)
        for i, v in enumerate(dados):
            ram[(endereco + i) ^ 1] = v

    def vram(self) -> bytes:
        """64 KB da VRAM do VDP, na ordem em que o VDP a enxerga.

        Ruling (core validado, ver SHA256_CORE_VALIDADO): o core NÃO expõe a VRAM
        por ``retro_get_memory_data(RETRO_MEMORY_VIDEO_RAM)`` (tamanho 0) nem
        manda ``SET_MEMORY_MAPS``. O caminho que funciona é extrair do save
        state (ver ``_vram_do_estado``). Os dois primeiros caminhos continuam
        aqui para o caso de outra versão do core passar a expô-la.
        """
        dados = self._memoria(RETRO_MEMORY_VIDEO_RAM)
        if dados is None:
            for desc in self._mapas:
                nome = (desc.addrspace or b"").lower()
                if desc.ptr and desc.len >= TAM_VRAM and b"vram" in nome:
                    dados = ctypes.string_at(desc.ptr + desc.offset, TAM_VRAM)
                    break
        if dados is None or len(dados) < TAM_VRAM:
            if not self.core_validado:
                raise RuntimeError("vram() desativada: o core não é o validado "
                                   f"(sha256 esperado {SHA256_CORE_VALIDADO})")
            dados = _vram_do_estado(self.salvar_estado())
        return _desembaralhar(dados[:TAM_VRAM])

    def salvar_estado(self) -> bytes:
        tam = self._lib.retro_serialize_size()
        buf = ctypes.create_string_buffer(tam)
        if not self._lib.retro_serialize(buf, tam):
            raise RuntimeError("retro_serialize falhou")
        return buf.raw

    def carregar_estado(self, dados: bytes) -> None:
        buf = ctypes.create_string_buffer(dados, len(dados))
        if not self._lib.retro_unserialize(buf, len(dados)):
            raise RuntimeError("retro_unserialize falhou")
