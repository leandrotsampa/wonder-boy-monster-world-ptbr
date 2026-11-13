"""Testes do frontend libretro (precisam do core em emu/ e da ROM base)."""

from pathlib import Path

import pytest
from PIL import Image

from ferramentas.emulador.roteiro import executar_roteiro


def _cores(caminho: Path) -> int:
    with Image.open(caminho) as img:
        return len(img.convert("RGB").getcolors(maxcolors=1 << 24) or [])


def test_boot_mostra_imagem(emulador, tmp_path):
    emulador.avancar(600)
    destino = tmp_path / "boot.png"
    emulador.quadro_png(destino)
    assert destino.is_file()
    assert _cores(destino) > 1


def test_deterministico(emulador, caminho_rom_base, tmp_path):
    roteiro = tmp_path / "det.yaml"
    roteiro.write_text(
        "- esperar: 300\n- apertar: [start]\n  quadros: 2\n- esperar: 120\n- capturar: fim\n",
        encoding="utf-8",
    )
    saidas = []
    for i in range(2):
        destino = tmp_path / f"exec{i}"
        emulador.reiniciar()
        executar_roteiro(roteiro, destino, emulador=emulador)
        saidas.append((destino / "fim.png").read_bytes())
    assert saidas[0] == saidas[1]


def test_vram_tamanho(emulador):
    emulador.avancar(600)
    vram = emulador.vram()
    assert len(vram) == 0x10000
    assert any(vram)
    assert len(emulador.ram()) == 0x10000


def test_estado_ida_e_volta(emulador, tmp_path):
    emulador.avancar(400)
    estado = emulador.salvar_estado()
    emulador.avancar(60, {"start"})
    emulador.avancar(60)
    emulador.quadro_png(tmp_path / "a.png")
    emulador.carregar_estado(estado)
    emulador.avancar(60, {"start"})
    emulador.avancar(60)
    emulador.quadro_png(tmp_path / "b.png")
    assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()


def test_roteiro_grava_saidas(emulador, tmp_path):
    roteiro = tmp_path / "r.yaml"
    roteiro.write_text(
        "- esperar: 10\n- capturar: c\n- vram: v\n- estado_salvar: s\n"
        "- esperar: 5\n- estado_carregar: s\n- capturar: c2\n",
        encoding="utf-8",
    )
    destino = tmp_path / "saida"
    emulador.reiniciar()
    executar_roteiro(roteiro, destino, emulador=emulador)
    assert (destino / "c.png").is_file()
    assert (destino / "c.png").read_bytes() == (destino / "c2.png").read_bytes()
    assert len((destino / "v.vram").read_bytes()) == 0x10000
    assert (destino / "s.estado").is_file()


# --- extração da VRAM do save state (sem core) ---

def _estado_sintetico(versao: bytes | None = None, tamanho: int | None = None) -> bytearray:
    from ferramentas.emulador import libretro as lr

    estado = bytearray(lr.TAM_ESTADO_VALIDADO if tamanho is None else tamanho)
    estado[:16] = lr.VERSAO_ESTADO_VALIDADA if versao is None else versao
    o = lr._OFFSET_VRAM_ESTADO
    estado[o + lr._REL_REGS_VRAM + 5] = 0x68  # tabela de sprites em 0xD000
    sat = bytes((i * 7 + 3) & 0xFF for i in range(0x200))
    estado[o - 0x400:o - 0x200] = sat
    estado[o + 0xD000:o + 0xD200] = sat
    estado[o:o + 32] = bytes(range(1, 33))
    return estado


def test_vram_do_estado_valido():
    from ferramentas.emulador.libretro import _OFFSET_VRAM_ESTADO, _vram_do_estado

    estado = _estado_sintetico()
    vram = _vram_do_estado(bytes(estado))
    assert vram == bytes(estado[_OFFSET_VRAM_ESTADO:_OFFSET_VRAM_ESTADO + 0x10000])


_CASOS_INVALIDOS = {
    "assinatura_errada": (lambda: _estado_sintetico(versao=b"SNES9X 1.60     "), "SNES9X"),
    "versao_errada": (lambda: _estado_sintetico(versao=b"GENPLUS-GX 1.7.5"), "GENPLUS-GX 1.7.5"),
    "curto": (lambda: _estado_sintetico()[:0x20000], "tamanho"),
    "longo": (lambda: _estado_sintetico(tamanho=0xFD000 + 16), "tamanho"),
}


@pytest.mark.parametrize("caso", list(_CASOS_INVALIDOS))
def test_vram_do_estado_rejeita(caso):
    from ferramentas.emulador.libretro import _vram_do_estado

    fabrica, trecho = _CASOS_INVALIDOS[caso]
    with pytest.raises(RuntimeError, match=trecho):
        _vram_do_estado(bytes(fabrica()))


def test_vram_do_estado_rejeita_sat_divergente():
    from ferramentas.emulador.libretro import _OFFSET_VRAM_ESTADO, _vram_do_estado

    estado = _estado_sintetico()
    estado[_OFFSET_VRAM_ESTADO + 0xD000] ^= 0xFF  # a SAT na VRAM não bate com o cache
    with pytest.raises(RuntimeError, match="SAT"):
        _vram_do_estado(bytes(estado))


def test_vram_conteudo_tabela_de_sprites(emulador):
    """Na tela de título a tabela de sprites (0xD000, modo H32) é uma lista
    encadeada válida: links < 64, sem ciclo, terminando em 0."""
    emulador.avancar(600)
    vram = emulador.vram()
    vistos, atual = set(), 0
    while True:
        assert atual not in vistos and atual < 64
        vistos.add(atual)
        entrada = vram[0xD000 + atual * 8:0xD000 + atual * 8 + 8]
        link = entrada[3] & 0x7F
        if link == 0:
            break
        atual = link
    assert len(vistos) > 1
    # primeira entrada observada na tela de título (Y=0xC3, tamanho 4, link 1)
    assert vram[0xD000:0xD004] == bytes([0x00, 0xC3, 0x04, 0x01])


def test_core_validado_por_sha256(emulador):
    from ferramentas.emulador.libretro import SHA256_CORE_VALIDADO

    assert emulador.core_validado
    assert len(SHA256_CORE_VALIDADO) == 64


def test_escrever_ram(emulador):
    """escrever_ram grava na ordem do 68000 (endereço par ou ímpar) e ram() lê de volta."""
    emulador.avancar(10)
    emulador.escrever_ram(0xF000, bytes([0x12, 0x34, 0x56]))
    emulador.escrever_ram(0xF101, b"\xAB")
    ram = emulador.ram()
    assert ram[0xF000:0xF003] == bytes([0x12, 0x34, 0x56]) and ram[0xF101] == 0xAB
    with pytest.raises(ValueError):
        emulador.escrever_ram(0xFFFF, b"\x00\x00")
