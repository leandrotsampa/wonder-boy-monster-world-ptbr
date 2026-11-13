"""Bolha d'água (sala 0x69, embaixo d'água): os tiles 0xC0-0xC5 e 0xD0 da área da fonte
não são glifos, são gráficos de sprite (bolhas que sobem do herói). O rótulo MOEDAS do HUD
não pode ocupá-los (docs/tecnico/vram.md, mapa-rom.md §8)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ferramentas.cli import main
from ferramentas.fonte import (ARQ_PNG, BYTES_TILE, HUD_CODIGOS_BAIXO, HUD_CODIGOS_CIMA,
                               fonte_da_rom, ler_png)

RAIZ = Path(__file__).resolve().parent.parent
#: tiles da área da fonte que o jogo usa em sprites (vistos na SAT da sala 0x69: 0xC4,
#: 0xC5 e 0xD0; 0xC0-0xC3 têm o mesmo tipo de arte, cores 0/3/F, sem fundo 1 de glifo)
TILES_BOLHA = (0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xD0)
SALA_AGUA = 0x69
TILE_BOLHA = 0xC5


def _tile(dados: bytes, t: int) -> bytes:
    return dados[BYTES_TILE * t:BYTES_TILE * (t + 1)]


def test_hud_fora_dos_tiles_da_bolha():
    assert not set(HUD_CODIGOS_CIMA + HUD_CODIGOS_BAIXO) & set(TILES_BOLHA)


def test_tiles_de_efeito_sao_os_da_base_que_nao_sao_glifo(rom_base):
    """Na faixa 0xA0-0xFF da fonte base, só os TILES_EFEITO fogem do formato de glifo
    (fundo 1, traço 15); o rótulo do HUD não pode cair neles."""
    from ferramentas.fonte import TILES_EFEITO

    base = fonte_da_rom(rom_base)
    fora = [t for t in range(0xA0, 0x100)
            if not {b >> 4 for b in _tile(base, t)} | {b & 15 for b in _tile(base, t)}
            <= {1, 15}]
    assert tuple(fora) == TILES_EFEITO
    assert set(TILES_BOLHA) <= set(TILES_EFEITO)
    assert not set(HUD_CODIGOS_CIMA + HUD_CODIGOS_BAIXO) & set(TILES_EFEITO)


def test_fonte_do_projeto_nao_altera_tiles_de_efeito(rom_base):
    from ferramentas.fonte import TILES_EFEITO

    png, base = ler_png(RAIZ / ARQ_PNG), fonte_da_rom(rom_base)
    errados = [hex(t) for t in TILES_EFEITO if _tile(png, t) != _tile(base, t)]
    assert not errados, f"tiles de efeito alterados na fonte: {errados}"


def test_hud_fora_dos_caracteres_do_texto_base(rom_base):
    """Nenhum texto da ROM base (trechos e itens inline) usa como caractere um código do
    rótulo do HUD (as strings japonesas que sobraram usam 0xCF, 0xD1, 0xD2 e 0xDD)."""
    from ferramentas.config import carregar_cfg_texto
    from ferramentas.inline import itens_inline
    from ferramentas.script.extracao import extrair_texto
    from test_vram_cenas import _chars_altos

    cfg = carregar_cfg_texto(RAIZ)
    esqueleto, _ = extrair_texto(rom_base, cfg)
    usados = {b for h in esqueleto["trechos"].values() for b in _chars_altos(bytes.fromhex(h))}
    for it in itens_inline(cfg):
        usados |= {b for b in rom_base[it["end"]:it["end"] + it["tam"]] if b >= 0x80}
    assert {0xCF, 0xD1, 0xD2, 0xDD} <= usados
    assert not usados & set(HUD_CODIGOS_CIMA + HUD_CODIGOS_BAIXO)


def test_png_mantem_os_tiles_da_bolha(rom_base):
    png, base = ler_png(RAIZ / ARQ_PNG), fonte_da_rom(rom_base)
    errados = [hex(t) for t in TILES_BOLHA if _tile(png, t) != _tile(base, t)]
    assert not errados, f"tiles da bolha sobrescritos na fonte: {errados}"


# A ROM (base ou nova) começa na sala 0x69 (word de 0x8FAA trocado numa cópia, checksum
# refeito; ver test_texto_tiles.py). Espera uma bolha (sprite com o tile 0xC5) na SAT e
# grava a tela, o recorte ampliado em volta da bolha e o tile 0xC5 do VRAM.
_SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PIL import Image
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador
from ferramentas.emulador.vram_cenas import regs_do_estado
from ferramentas.rom import corrigir_cabecalho

def sat(emu):
    vram, regs = emu.vram(), regs_do_estado(emu.salvar_estado())
    h40 = bool(regs[12] & 1)
    base = (regs[5] & (0x7E if h40 else 0x7F)) << 9
    i, vistos, saida = 0, set(), []
    while i not in vistos and i < 80:
        vistos.add(i)
        e = base + 8 * i
        y = int.from_bytes(vram[e:e + 2], "big") & 0x3FF
        attr = int.from_bytes(vram[e + 4:e + 6], "big")
        x = int.from_bytes(vram[e + 6:e + 8], "big") & 0x1FF
        if x and y:
            saida.append((x - 128, y - 128, attr & 0x7FF))
        i = vram[e + 3] & 0x7F
        if i == 0:
            break
    return saida

rom = bytearray(Path(sys.argv[2]).read_bytes())
destino, nome, sala, tile = Path(sys.argv[3]), sys.argv[4], int(sys.argv[5]), int(sys.argv[6])
destino.mkdir(parents=True, exist_ok=True)
assert rom[0x8FAA:0x8FAC] == bytes(2)
rom[0x8FAA:0x8FAC] = sala.to_bytes(2, "big")
corrigir_cabecalho(rom)
arq = destino / f"{nome}.bin"
arq.write_bytes(rom)
emu = Emulador(CORE_PADRAO, arq)
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
emu.avancar(2, {"start"}); emu.avancar(120); emu.avancar(2, {"start"}); emu.avancar(500)
bolha = None
for _ in range(300):
    emu.avancar(1)
    bolha = next(((x, y) for x, y, t in sat(emu) if t == tile), None)
    if bolha:
        break
ram, vram = emu.ram(), emu.vram()
res = {"sala": int.from_bytes(ram[0x9676:0x9678], "big"), "bolha": bolha,
       "tile": vram[32 * tile:32 * (tile + 1)].hex()}
emu.quadro_png(destino / f"{nome}.png")
if bolha:
    x, y = bolha
    with Image.open(destino / f"{nome}.png") as img:
        img.convert("RGB").crop((x - 24, y - 24, x + 32, y + 32)).resize(
            (224, 224), Image.NEAREST).save(destino / f"{nome}_zoom.png")
emu.fechar()
arq.unlink()
print(json.dumps(res))
'''


def _rodar(tmp_path: Path, rom: Path, nome: str) -> dict:
    arq = tmp_path / "bolha.py"
    arq.write_text(_SCRIPT, encoding="utf-8")
    destino = RAIZ / "build" / "capturas" / "bolha"
    r = subprocess.run([sys.executable, str(arq), str(RAIZ), str(rom), str(destino), nome,
                        str(SALA_AGUA), str(TILE_BOLHA)],
                       cwd=str(RAIZ), capture_output=True, timeout=600)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(r.stdout.decode().strip().splitlines()[-1])


def test_bolha_no_jogo(rom_base, tmp_path):
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    base = tmp_path / "base.bin"
    base.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(base)]) == 0
    nova = tmp_path / "build" / "wbmw-ptbr.bin"

    res_base = _rodar(tmp_path, base, "sala69_base")
    res_nova = _rodar(tmp_path, nova, "sala69_ptbr")
    esperado = _tile(fonte_da_rom(rom_base), TILE_BOLHA).hex()
    for res in (res_base, res_nova):
        assert res["sala"] == SALA_AGUA
        assert res["bolha"], "nenhuma bolha (tile 0xC5) na SAT"
    assert res_base["tile"] == esperado
    assert res_nova["tile"] == esperado, "a bolha usa um tile sobrescrito (rótulo do HUD?)"
