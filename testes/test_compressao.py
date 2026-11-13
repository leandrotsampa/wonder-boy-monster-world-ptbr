"""Compressão de gráficos (tipo 02 da tabela 0x41000: árvore de Huffman + LZ)."""

import random
from pathlib import Path

import pytest

from ferramentas.compressao import (BLOCOS_FONTE, END_FONTE, MAX_FOLHAS, TABELA_GRAFICOS,
                                    TAMANHO_BLOCO, TIPO_00, TIPO_CRU, TIPO_HUFFMAN, TIPO_VAZIO,
                                    TOTAL_BLOCOS, ErroCompressao, comprimir, descomprimir, escrever_entrada,
                                    ler_entrada)
from ferramentas.emulador.roteiro import executar_roteiro

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def vram_dialogo(_emulador_sessao, tmp_path_factory) -> bytes:
    """VRAM com a janela da primeira fala aberta (roteiros/dialogo.yaml)."""
    # fixture de módulo: o roteiro leva ~1000 quadros e serve a vários testes
    _emulador_sessao.reiniciar()
    destino = tmp_path_factory.mktemp("dialogo")
    executar_roteiro(RAIZ / "roteiros" / "dialogo.yaml", destino, emulador=_emulador_sessao)
    return (destino / "dialogo.vram").read_bytes()


def test_ler_entrada(rom_base):
    assert [ler_entrada(rom_base, b)[0] for b in range(8)] == [TIPO_HUFFMAN] * 8
    assert ler_entrada(rom_base, 2) == (2, END_FONTE)
    assert ler_entrada(rom_base, 4) == (2, 0x42019)


def test_tabela_tem_768_entradas(rom_base):
    # 0x41000–0x41BFF; o primeiro blob (fonte, bloco 0) começa logo depois, em 0x41C00
    assert TOTAL_BLOCOS == 768
    assert ler_entrada(rom_base, 0) == (TIPO_HUFFMAN, 0x41C00)
    assert ler_entrada(rom_base, 0x235) == (TIPO_HUFFMAN, 0x0815AE)  # HUD (slot 4 em jogo)
    assert ler_entrada(rom_base, 767) == (TIPO_VAZIO, 0xFFFFFF)
    with pytest.raises(ErroCompressao, match="fora da tabela"):
        ler_entrada(rom_base, 768)
    assert ler_entrada(rom_base, 5) == (2, 0x4214F)


#: tiles que o jogo zera logo depois de carregar a fonte (¥, ] e _ estão no
#: blob, mas somem do VRAM entre ~12 e ~68 quadros após NEW GAME).
TILES_ZERADOS_EM_JOGO = (0x5C, 0x5D, 0x5F)


def _como_no_jogo(bloco: int, dados: bytes) -> bytes:
    saida = bytearray(dados)
    for tile in TILES_ZERADOS_EM_JOGO:
        if tile // 32 == bloco:
            i = (tile % 32) * 32
            saida[i:i + 32] = bytes(32)
    return bytes(saida)


def test_descomprime_fonte_bate_com_vram(rom_base, vram_dialogo):
    dados, consumidos = descomprimir(rom_base, END_FONTE)
    assert len(dados) == TAMANHO_BLOCO
    assert END_FONTE + consumidos == ler_entrada(rom_base, 3)[1]
    vram = 2 * TAMANHO_BLOCO  # bloco 2 → slot 2 → tiles 0x40–0x5F
    assert _como_no_jogo(2, dados) == vram_dialogo[vram:vram + TAMANHO_BLOCO]
    assert dados[0x1C * 32:0x1D * 32] != bytes(32)  # o ¥ existe no blob


def test_descomprime_todos_os_blocos_da_fonte(rom_base, vram_dialogo):
    for bloco in BLOCOS_FONTE:
        tipo, end = ler_entrada(rom_base, bloco)
        assert tipo == 2
        dados, _ = descomprimir(rom_base, end)
        ini = bloco * TAMANHO_BLOCO
        assert _como_no_jogo(bloco, dados) == vram_dialogo[ini:ini + TAMANHO_BLOCO], f"bloco {bloco}"


def _casos_sinteticos() -> dict[str, bytes]:
    rnd = random.Random(2026)
    tile_a = bytes(rnd.randrange(16) * 0x11 for _ in range(32))
    tile_b = bytes(rnd.randrange(256) for _ in range(32))
    return {
        "zeros": bytes(TAMANHO_BLOCO),
        "aleatorio": bytes(rnd.randrange(256) for _ in range(TAMANHO_BLOCO)),
        "tiles_repetidos": (tile_a + tile_b + tile_a) * 10 + tile_b * 2,
        "um_byte": b"\x5a" * TAMANHO_BLOCO,
        "dois_bytes": bytes(rnd.choice((0x11, 0xFF)) for _ in range(TAMANHO_BLOCO)),
    }


@pytest.mark.parametrize("caso", list(_casos_sinteticos()))
def test_comprimir_ida_e_volta(caso):
    dados = _casos_sinteticos()[caso]
    assert len(dados) == TAMANHO_BLOCO
    comp = comprimir(dados)
    saida, consumidos = descomprimir(comp + b"\xAA" * 8, 0)
    assert saida == dados
    assert consumidos == len(comp)


def test_comprimir_ida_e_volta_fonte_real(rom_base):
    for bloco in (*BLOCOS_FONTE, 4):
        _, end = ler_entrada(rom_base, bloco)
        original, consumidos_orig = descomprimir(rom_base, end)
        comp = comprimir(original)
        assert descomprimir(comp, 0) == (original, len(comp))
        # o compressor deve ficar perto do original (não precisa ser idêntico)
        assert len(comp) <= consumidos_orig * 1.25


def test_todos_os_blocos_tipo_02_ida_e_volta(rom_base):
    for bloco in range(TOTAL_BLOCOS):
        tipo, end = ler_entrada(rom_base, bloco)
        if tipo != 2:
            continue
        original, _ = descomprimir(rom_base, end)
        assert descomprimir(comprimir(original), 0)[0] == original, f"bloco {bloco:#x}"


def test_comprimir_deterministico():
    for dados in _casos_sinteticos().values():
        assert comprimir(dados) == comprimir(dados)


def test_comprimir_rejeita_tamanho_errado():
    with pytest.raises(ValueError, match="1024"):
        comprimir(b"\x00" * 100)


def _folhas(comp: bytes) -> int:
    """Conta as folhas da árvore serializada no início de ``comp``."""
    bits = "".join(f"{b:08b}" for b in comp)
    pos, pendentes, folhas = 1, 2, 0
    while pendentes:
        pendentes -= 1
        if bits[pos] == "1":
            pos, pendentes = pos + 1, pendentes + 2
        else:
            pos += 7 if bits[pos + 1] == "1" else 10
            folhas += 1
    return folhas


def test_comprimir_respeita_max_folhas(rom_base):
    rnd = random.Random(7)
    aleatorio = bytes(rnd.randrange(256) for _ in range(TAMANHO_BLOCO))
    comp = comprimir(aleatorio)
    assert _folhas(comp) <= MAX_FOLHAS
    assert descomprimir(comp, 0)[0] == aleatorio
    for limite in (2, 3, 16):
        comp = comprimir(aleatorio, max_folhas=limite)
        assert _folhas(comp) <= limite
        assert descomprimir(comp, 0)[0] == aleatorio
    maior = 0
    for bloco in range(TOTAL_BLOCOS):
        tipo, end = ler_entrada(rom_base, bloco)
        if tipo == TIPO_HUFFMAN:
            maior = max(maior, _folhas(rom_base[end:end + 600]))
            assert _folhas(comprimir(descomprimir(rom_base, end)[0])) <= MAX_FOLHAS
    # o limite vem dos originais: algum bloco original usa pelo menos MAX_FOLHAS folhas
    # (os blocos 0–404 chegam a 59; os de cima, a 61)
    assert maior >= MAX_FOLHAS


@pytest.mark.parametrize("limite", [1, MAX_FOLHAS + 1])
def test_comprimir_rejeita_max_folhas_invalido(limite):
    with pytest.raises(ErroCompressao, match="max_folhas"):
        comprimir(bytes(TAMANHO_BLOCO), max_folhas=limite)


# --- tabela 0x41000 ---

def _rom_com_entrada(valor: int) -> bytearray:
    rom = bytearray(TABELA_GRAFICOS + 4 * TOTAL_BLOCOS)
    rom[TABELA_GRAFICOS:TABELA_GRAFICOS + 4] = valor.to_bytes(4, "big")
    return rom


@pytest.mark.parametrize("valor, esperado", [
    (0x02041C00, (TIPO_HUFFMAN, 0x041C00)),
    (0x01041C00, (TIPO_CRU, 0x041C00)),
    (0x03041C00, (TIPO_CRU, 0x041C00)),       # bit 24 é testado antes do 25
    (0x00041C00, (TIPO_00, 0x041C00)),
    (0x83041C00, (TIPO_VAZIO, 0x041C00)),     # bit 31 vence tudo
    (0x7C041C01, (TIPO_00, 0x041C01)),        # bits 26–30 não contam
])
def test_ler_entrada_bits_em_ordem(valor, esperado):
    assert ler_entrada(_rom_com_entrada(valor), 0) == esperado


def test_escrever_entrada_ida_e_volta():
    rom = _rom_com_entrada(0)
    for tipo, end in ((TIPO_HUFFMAN, 0x0A0001), (TIPO_CRU, 0x0AC800), (TIPO_00, 0x0B0003),
                      (TIPO_VAZIO, 0)):
        escrever_entrada(rom, 0x235, tipo, end)
        assert ler_entrada(rom, 0x235) == (tipo, end)
    escrever_entrada(rom, 7, TIPO_HUFFMAN, 0x123457)
    assert rom[TABELA_GRAFICOS + 28:TABELA_GRAFICOS + 32] == bytes.fromhex("02123457")


@pytest.mark.parametrize("args, trecho", [
    ((0, TIPO_CRU, 0x0AC801), "ímpar"),
    ((0, 0x04, 0x0AC800), "tipo"),
    ((0, TIPO_HUFFMAN, 0x1000000), "24 bits"),
    ((768, TIPO_HUFFMAN, 0x0AC800), "fora da tabela"),
])
def test_escrever_entrada_rejeita(args, trecho):
    rom = _rom_com_entrada(0x02041C00)
    with pytest.raises(ErroCompressao, match=trecho):
        escrever_entrada(rom, *args)
    assert ler_entrada(rom, 0) == (TIPO_HUFFMAN, 0x041C00)


# --- fluxos inválidos ---

def _bits(texto: str) -> bytes:
    texto = texto.replace(" ", "")
    texto += "0" * (-len(texto) % 8)
    return int(texto, 2).to_bytes(len(texto) // 8, "big")


def test_descomprimir_fluxo_truncado():
    comp = comprimir(bytes(range(256)) * 4)
    with pytest.raises(ErroCompressao, match="termina"):
        descomprimir(comp[:len(comp) // 2], 0)


def test_descomprimir_primeiro_bit_zero():
    with pytest.raises(ErroCompressao, match="nó interno"):
        descomprimir(bytes(64), 0)


def test_descomprimir_copia_antes_do_inicio():
    # raiz: esquerda = 0x100 (cópia de 3), direita = 0x00; dados: cópia, distância 0
    fluxo = _bits("1" + "0 1 00000" + "0 0 00000000" + "0" + "1")
    with pytest.raises(ErroCompressao, match="antes do início"):
        descomprimir(fluxo, 0)


def test_descomprimir_endereco_negativo():
    with pytest.raises(ErroCompressao, match="negativo"):
        descomprimir(bytes([0xFF]) * 64, -1)
