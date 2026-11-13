"""Patches de código (config/patches.yaml, ferramentas/patches.py)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ferramentas.config import ErroConfig, Projeto
from ferramentas.patches import ErroPatch, aplicar_patches, carregar_patches, etapa_patches

RAIZ = Path(__file__).resolve().parent.parent


def _projeto(tmp_path, itens):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "patches.yaml").write_text(
        yaml.safe_dump({"patches": itens}, allow_unicode=True), encoding="utf-8")
    return Projeto(raiz=tmp_path, rom={})


def _item(**kw):
    base = {"id": "teste", "end": 4, "original": "AABB", "novo": "CCDD",
            "descricao": "x", "origem": "y"}
    base.update(kw)
    return base


def test_aplica_quando_original_confere(tmp_path):
    rom = bytearray(b"\x00" * 4 + b"\xAA\xBB" + b"\x00" * 4)
    etapa_patches(rom, _projeto(tmp_path, [_item()]))
    assert rom[4:6] == b"\xCC\xDD"
    assert rom[:4] == b"\x00" * 4 and rom[6:] == b"\x00" * 4


def test_original_diferente_e_erro_sem_gravar(tmp_path):
    rom = bytearray(b"\x00" * 10)
    with pytest.raises(ErroPatch, match="teste"):
        etapa_patches(rom, _projeto(tmp_path, [_item()]))
    assert rom == bytearray(b"\x00" * 10)


def test_segundo_patch_invalido_nao_grava_o_primeiro(tmp_path):
    rom = bytearray(b"\xAA\xBB" + b"\x00" * 8)
    itens = [_item(id="a", end=0), _item(id="b", end=6)]
    with pytest.raises(ErroPatch, match="b"):
        etapa_patches(rom, _projeto(tmp_path, itens))
    assert rom[:2] == b"\xAA\xBB"


@pytest.mark.parametrize("ruim, msg", [
    ({"novo": "CC"}, "tamanho"),
    ({"original": "XYZ"}, "hex"),
    ({"end": "0x4"}, "end"),
    ({"end": -1}, "end"),
])
def test_config_invalida(tmp_path, ruim, msg):
    with pytest.raises(ErroConfig, match=msg):
        carregar_patches(_projeto(tmp_path, [_item(**ruim)]))


def test_sobreposicao_e_id_duplicado(tmp_path):
    with pytest.raises(ErroConfig, match="sobrep"):
        carregar_patches(_projeto(tmp_path, [_item(id="a", end=4), _item(id="b", end=5)]))
    with pytest.raises(ErroConfig, match="duplicado"):
        carregar_patches(_projeto(tmp_path, [_item(id="a", end=0), _item(id="a", end=8)]))


def test_sem_config_nao_faz_nada(tmp_path):
    rom = bytearray(b"\xAA\xBB")
    etapa_patches(rom, Projeto(raiz=tmp_path, rom={}))
    assert rom == bytearray(b"\xAA\xBB")


def test_patch_real_da_eeprom_confere_com_a_rom(rom_base):
    """O patch versionado casa com a ROM base e troca o laço infinito por um jmp."""
    itens = carregar_patches(Projeto(raiz=RAIZ, rom={}))
    eeprom = [p for p in itens if p.id == "eeprom.nack_sem_trava"]
    assert len(eeprom) == 1
    p = eeprom[0]
    assert p.end == 0x1C552
    assert rom_base[p.end:p.end + len(p.original)] == p.original
    rom = bytearray(rom_base)
    aplicar_patches(rom, itens)
    assert rom[0x1C552:0x1C558] == bytes.fromhex("4EF90001C57E")  # jmp $1C57E.l


# ------------------------------------------------------------ save na estalagem
#
# Em processo à parte (um emulador por processo): a entrada 0 da tabela de diálogos
# vira a da estalagem (dialogo.046); no NEW GAME o jogador aceita a diária e o jogo
# grava na EEPROM; o console reinicia, o menu mostra CONTINUE e o jogo é carregado.
# O mesmo roteiro roda na ROM base e na base + patch: tudo tem de sair igual.
_SCRIPT_SAVE = r'''
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador

saida = Path(sys.argv[3])
emu = Emulador(CORE_PADRAO, Path(sys.argv[2]))
# mesmos tempos do roteiro de testes/test_graficos.py (_SCRIPT_SPRITES), que comprovadamente grava
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(100); emu.avancar(80)
emu.avancar(2, {"start"}); emu.avancar(80)
emu.quadro_png(saida / "menu_sem_save.png")
emu.avancar(2, {"start"}); emu.avancar(600)
for _ in range(10):                      # estalagem: C em cada página (SIM = 1.ª opção)
    emu.avancar(2, {"c"}); emu.avancar(600)
emu._lib.retro_reset()
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
emu.avancar(2, {"start"}); emu.avancar(80)
emu.quadro_png(saida / "menu.png")
emu.avancar(2, {"baixo"}); emu.avancar(30)   # seta para CONTINUE
emu.quadro_png(saida / "menu_continue.png")
emu.avancar(2, {"start"}); emu.avancar(600)
emu.quadro_png(saida / "carregado.png")
print(json.dumps({"ram": hashlib.sha1(emu.ram()).hexdigest()}))
emu.fechar()
'''


def _rodar_save(rom: bytes, pasta: Path) -> dict:
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / "rom.bin"
    arq.write_bytes(rom)
    script = pasta / "save.py"
    script.write_text(_SCRIPT_SAVE, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(RAIZ), str(arq), str(pasta)],
                       cwd=str(RAIZ), capture_output=True, timeout=900)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-2000:]
    return json.loads(r.stdout.decode().strip().splitlines()[-1])


def test_save_e_load_iguais_com_patch(rom_base, tmp_path):
    from PIL import Image, ImageChops

    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    estalagem = bytearray(rom_base)
    tab = int.from_bytes(estalagem[0x1CC14:0x1CC18], "big")
    estalagem[tab:tab + 3] = estalagem[tab + 3 * 46:tab + 3 * 46 + 3]
    com_patch = bytearray(estalagem)
    # só o patch da EEPROM: os do HUD (hud.*) mudam a tela de propósito (test_hud.py)
    aplicar_patches(com_patch, [p for p in carregar_patches(Projeto(raiz=RAIZ, rom={}))
                                if p.id == "eeprom.nack_sem_trava"])
    assert com_patch != estalagem

    def igual(x, y):
        with Image.open(x) as i, Image.open(y) as j:
            return ImageChops.difference(i.convert("RGB"), j.convert("RGB")).getbbox() is None

    a = _rodar_save(bytes(estalagem), tmp_path / "base")
    b = _rodar_save(bytes(com_patch), tmp_path / "patch")
    for pasta in ("base", "patch"):
        d = tmp_path / pasta
        # o save existe: depois de gravar e reiniciar, o menu mudou (apareceu o CONTINUE)
        assert not igual(d / "menu_sem_save.png", d / "menu.png"), pasta
        # a seta desceu para o CONTINUE e, com START, o jogo carregou (saiu do menu)
        assert not igual(d / "menu.png", d / "menu_continue.png"), pasta
        assert not igual(d / "menu_continue.png", d / "carregado.png"), pasta
    for nome in ("menu_sem_save.png", "menu.png", "menu_continue.png", "carregado.png"):
        assert igual(tmp_path / "base" / nome, tmp_path / "patch" / nome), nome
    # carregar o save leva ao mesmo estado de RAM com e sem o patch
    assert a["ram"] == b["ram"]
