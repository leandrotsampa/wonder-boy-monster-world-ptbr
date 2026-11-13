"""CRC32 e checksum do cabeçalho iguais aos da ROM original (ferramentas/compensacao.py)."""

import random
import shutil
import zlib
from pathlib import Path

import pytest
import yaml

from ferramentas.compensacao import (TAMANHO, ErroCompensacao, area_compensacao, compensar,
                                     forjar_crc32)
from ferramentas.config import Projeto, carregar_cfg_texto, carregar_projeto
from ferramentas.espaco import ErroEspaco, regiao_livre
from ferramentas.ips import aplicar_ips
from ferramentas.patches import ErroPatch, etapa_patches
from ferramentas.rom import OFFSET_CHECKSUM, calcular_checksum, corrigir_cabecalho

RAIZ = Path(__file__).resolve().parent.parent


def _crc(dados: bytes) -> int:
    return zlib.crc32(dados) & 0xFFFFFFFF


# ------------------------------------------------------------------ forja do CRC

@pytest.mark.parametrize("semente", range(25))
def test_forjar_crc32_aleatorio(semente):
    rnd = random.Random(semente)
    prefixo = bytes(rnd.randrange(256) for _ in range(rnd.randrange(0, 300)))
    alvo = rnd.getrandbits(32)
    sufixo = forjar_crc32(_crc(prefixo), alvo)
    assert len(sufixo) == 4
    assert _crc(prefixo + sufixo) == alvo


def test_forjar_crc32_casos_limite():
    for estado in (0, 0xFFFFFFFF):
        for alvo in (0, 0xFFFFFFFF, 0x1592F5B0):
            assert zlib.crc32(forjar_crc32(estado, alvo), estado) & 0xFFFFFFFF == alvo


# ------------------------------------------------------- compensação (sintética)

def _rom_sintetica(semente: int, tamanho: int = 0x4000) -> bytearray:
    rnd = random.Random(semente)
    rom = bytearray(rnd.randrange(256) for _ in range(tamanho))
    rom[0x100:0x110] = b"SEGA MEGA DRIVE "
    rom[-0x40:] = b"\xFF" * 0x40
    corrigir_cabecalho(rom)
    return rom


@pytest.mark.parametrize("semente", range(6))
def test_compensar_restaura_crc_e_checksum(semente):
    original = bytes(_rom_sintetica(semente))
    inicio = len(original) - TAMANHO
    rom = bytearray(original)
    rnd = random.Random(1000 + semente)
    for _ in range(50):
        rom[rnd.randrange(0x200, inicio)] = rnd.randrange(256)
    corrigir_cabecalho(rom)
    assert compensar(rom, original, inicio) is True
    assert len(rom) == len(original)
    assert _crc(rom) == _crc(original)
    assert rom[OFFSET_CHECKSUM:OFFSET_CHECKSUM + 2] == original[OFFSET_CHECKSUM:OFFSET_CHECKSUM + 2]
    assert calcular_checksum(rom) == int.from_bytes(original[OFFSET_CHECKSUM:OFFSET_CHECKSUM + 2],
                                                    "big")
    # só a área de compensação (e o que foi mudado antes) difere
    outra = bytearray(rom)
    outra[inicio:] = original[inicio:]
    assert rom[:inicio] == outra[:inicio]


def test_compensar_deterministico():
    original = bytes(_rom_sintetica(7))
    inicio = len(original) - TAMANHO
    saidas = []
    for _ in range(2):
        rom = bytearray(original)
        rom[0x300] ^= 0x5A
        compensar(rom, original, inicio)
        saidas.append(bytes(rom))
    assert saidas[0] == saidas[1]


def test_compensar_rom_igual_nao_muda_nada():
    original = bytes(_rom_sintetica(8))
    rom = bytearray(original)
    assert compensar(rom, original, len(original) - TAMANHO) is False
    assert bytes(rom) == original


def test_compensar_recusa_area_alterada_por_outra_etapa():
    original = bytes(_rom_sintetica(9))
    inicio = len(original) - TAMANHO
    rom = bytearray(original)
    rom[0x300] ^= 1
    rom[inicio + 3] = 0x12
    with pytest.raises(ErroCompensacao, match="compensação"):
        compensar(rom, original, inicio)


def test_compensar_recusa_area_fora_do_fim_ou_impar():
    original = bytes(_rom_sintetica(10))
    rom = bytearray(original)
    rom[0x300] ^= 1
    for inicio in (len(original) - TAMANHO - 2, len(original) - TAMANHO + 1, 0x100):
        with pytest.raises(ErroCompensacao):
            compensar(bytearray(rom), original, inicio)


# ------------------------------------------------- reserva (alocador e patches)

def _projeto(tmp_path, regiao, compensacao=0xBFFF8, patches=None) -> Projeto:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "texto.yaml").write_text(
        f"regiao_destino: [{regiao[0]:#x}, {regiao[1]:#x}]\n", encoding="utf-8")
    if patches is not None:
        (tmp_path / "config" / "patches.yaml").write_text(
            yaml.safe_dump({"patches": patches}), encoding="utf-8")
    rom = {"compensacao": compensacao} if compensacao is not None else {}
    return Projeto(raiz=tmp_path, rom=rom)


def test_area_compensacao_da_config(tmp_path):
    assert area_compensacao(_projeto(tmp_path, (0xA4C80, 0xBFFF8)), 0xC0000) == 0xBFFF8
    assert area_compensacao(_projeto(tmp_path, (0xA4C80, 0xBFFF8), None), 0xC0000) is None
    with pytest.raises(ErroCompensacao):
        area_compensacao(_projeto(tmp_path, (0xA4C80, 0xBFFF8), 0xBFFF0), 0xC0000)


def test_regiao_livre_nao_pode_cobrir_a_area(tmp_path):
    with pytest.raises(ErroEspaco, match="compensação"):
        regiao_livre(_projeto(tmp_path, (0xA4C80, 0xC0000)), 0xC0000)
    assert regiao_livre(_projeto(tmp_path, (0xA4C80, 0xBFFF8)), 0xC0000).limite == 0xBFFF8


def test_patch_nao_pode_tocar_a_area(tmp_path):
    patch = {"id": "x", "end": 0xBFFF6, "original": "FFFFFFFF", "novo": "00000000"}
    projeto = _projeto(tmp_path, (0xA4C80, 0xBFFF8), patches=[patch])
    with pytest.raises(ErroPatch, match="compensação"):
        etapa_patches(bytearray(b"\xFF" * 0xC0000), projeto)


# ------------------------------------------------------------------ build real

def test_config_real_reserva_a_area():
    projeto = carregar_projeto(RAIZ)
    inicio = projeto.rom["compensacao"]
    assert inicio + TAMANHO == projeto.rom["tamanho"]
    assert carregar_cfg_texto(RAIZ)["regiao_destino"][1] <= inicio


def test_area_livre_na_rom_base(rom_base):
    inicio = carregar_projeto(RAIZ).rom["compensacao"]
    assert rom_base[inicio:] == b"\xFF" * TAMANHO


def _construir(destino: Path, rom_base: bytes) -> tuple[bytes, bytes]:
    from ferramentas.cli import main

    for rel in ("config", "traducao", "graficos"):
        if not (destino / rel).exists():
            shutil.copytree(RAIZ / rel, destino / rel)
    (destino / "dados" / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", destino / "dados" / "scripts")
    arq = destino / "base.bin"
    arq.write_bytes(rom_base)
    assert main(["--raiz", str(destino), "construir", "--rom", str(arq)]) == 0
    return ((destino / "build" / "wbmw-ptbr.bin").read_bytes(),
            (destino / "build" / "wbmw-ptbr.ips").read_bytes())


def test_build_real_crc_e_checksum_iguais_ao_original(rom_base, tmp_path):
    rom, ips = _construir(tmp_path, rom_base)
    assert rom != rom_base  # o build muda a ROM (patches, fonte, textos)
    assert "%08x" % _crc(rom) == "1592f5b0"
    assert rom[OFFSET_CHECKSUM:OFFSET_CHECKSUM + 2] == b"\x9D\x79"
    assert calcular_checksum(rom) == 0x9D79
    assert aplicar_ips(rom_base, ips) == rom
    assert _construir(tmp_path, rom_base) == (rom, ips)
    assert (tmp_path / "patch" / "wbmw-ptbr.ips").read_bytes() == ips


def test_patch_versionado_atualizado(rom_base, tmp_path):
    """patch/wbmw-ptbr.ips (o que vai na release) é o que o build gera hoje."""
    _, ips = _construir(tmp_path, rom_base)
    assert (RAIZ / "patch" / "wbmw-ptbr.ips").read_bytes() == ips, \
        "patch/wbmw-ptbr.ips desatualizado: rode 'python -m ferramentas construir'"
