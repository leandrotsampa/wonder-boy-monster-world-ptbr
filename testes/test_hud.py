"""HUD com "MOEDAS": tiles na fonte (0xC6–0xCB e 0xD3–0xD8), patch de duas linhas e captura no jogo."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

from ferramentas.cli import main
from ferramentas.config import Projeto
from ferramentas.fonte import (ARQ_META, ARQ_PNG, HUD_CODIGOS_BAIXO, HUD_CODIGOS_CIMA,
                               HUD_SUBIDA, HUD_TEXTO, fonte_da_rom, ler_png, tiles_hud)
from ferramentas.patches import aplicar_patches, carregar_patches
from ferramentas.tabela import Tabela

RAIZ = Path(__file__).resolve().parent.parent
#: chamada do rótulo no código do HUD (0x8596): 'lea $84E7(pc),a1; bsr.w $786A'
END_CHAMADA = 0x85A0
#: rotina nova (espaço livre 0x9F777–0xA0000, mapa-rom.md §7)
END_ROTINA = 0x9F780
#: janela (plano W, 32 colunas em 0xD800): rótulo nas colunas 23–28, linhas 4 e 5
COLUNA_ROTULO, LINHA_CIMA, LINHA_BAIXO = 23, 4, 5
#: retângulo do quadro do ouro na tela (colunas 21–30, linhas 4–6 da janela)
CAIXA_OURO = (21 * 8, 4 * 8, 31 * 8, 7 * 8)
#: retângulo dos tiles do rótulo (base: GOLD nas colunas 22–25; nova: 23–28)
CAIXA_ROTULO = (22 * 8, 4 * 8, 29 * 8, 6 * 8)
OURO_RAM = 0x962C
OURO_MAXIMO = 999999


def _tile(linhas: list[str]) -> bytes:
    px = [[15 if c == "#" else 1 for c in l] for l in linhas]
    return b"".join(bytes((p[x] << 4) | p[x + 1] for x in range(0, 8, 2)) for p in px)


def _faixa(tiles: bytes, colunas: int) -> list[list[int]]:
    """2 linhas de tiles (cima: os ``colunas`` primeiros) -> 16 linhas de pixels."""
    px = [[0] * (8 * colunas) for _ in range(16)]
    for t in range(2 * colunas):
        lin, c = divmod(t, colunas)
        for y in range(8):
            for x in range(8):
                b = tiles[32 * t + 4 * y + x // 2]
                px[8 * lin + y][8 * c + x] = b >> 4 if x % 2 == 0 else b & 15
    return px


# ------------------------------------------------------------- unidades

def test_tiles_hud_sintetico():
    """Cada letra é o tile da fonte de referência, HUD_SUBIDA pixels acima da linha de
    baixo; o resto é fundo (índice 1) e as HUD_SUBIDA linhas de baixo ficam livres."""
    fonte = bytearray(_tile(["." * 8] * 8) * 256)
    for i, ch in enumerate(HUD_TEXTO):
        linhas = ["#" * 8] * 8
        linhas[0] = "#" * (i + 1) + "." * (7 - i)   # marca qual letra é
        fonte[32 * ord(ch):32 * ord(ch) + 32] = _tile(linhas)
    tiles = tiles_hud(bytes(fonte))
    n = len(HUD_TEXTO)
    assert len(tiles) == 2 * n * 32
    px = _faixa(tiles, n)
    topo = 8 - HUD_SUBIDA
    for i, ch in enumerate(HUD_TEXTO):
        letra = _faixa(fonte[32 * ord(ch):32 * ord(ch) + 32] + bytes(32), 1)[:8]
        assert [l[8 * i:8 * i + 8] for l in px[topo:topo + 8]] == letra, ch
    assert all(v == 1 for l in px[:topo] + px[topo + 8:] for v in l)
    assert 1 <= HUD_SUBIDA <= 7


def test_codigos_hud_livres():
    """Os 12 tiles do HUD ficam na faixa livre da fonte (vram.md §5): fora dos acentos,
    da tabela de caracteres e dos tiles reservados 0xBE/0xBF."""
    cfg = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))
    codigos = list(HUD_CODIGOS_CIMA) + list(HUD_CODIGOS_BAIXO)
    assert len(codigos) == len(set(codigos)) == 2 * len(HUD_TEXTO)
    assert all(0xC0 <= c <= 0xFD for c in codigos)
    assert not set(codigos) & set(cfg["acentos"].values())
    tabela = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")
    for c in codigos:   # sem caractere na tabela: decodifica como byte cru
        assert tabela.decodificar(bytes([c])) == f"[${c:02X}]", hex(c)


def test_fonte_versionada_tem_tiles_hud(rom_base):
    """graficos/fonte/fonte.png traz os tiles do HUD (iguais a tiles_hud da fonte) e o
    fonte.yaml registra o rótulo como desenho do projeto."""
    tiles = ler_png(RAIZ / ARQ_PNG)
    hud = tiles_hud(tiles)
    codigos = list(HUD_CODIGOS_CIMA) + list(HUD_CODIGOS_BAIXO)
    for i, c in enumerate(codigos):
        assert tiles[32 * c:32 * c + 32] == hud[32 * i:32 * i + 32], hex(c)
        assert tiles[32 * c:32 * c + 32] != fonte_da_rom(rom_base)[32 * c:32 * c + 32]
    meta = yaml.safe_load((RAIZ / ARQ_META).read_text(encoding="utf-8"))
    assert meta["hud"]["texto"] == HUD_TEXTO
    assert meta["hud"]["subida"] == HUD_SUBIDA
    assert [int(c, 16) if isinstance(c, str) else c for c in meta["hud"]["cima"]] == \
        list(HUD_CODIGOS_CIMA)
    assert "projeto" in meta["hud"]["origem"]


# ------------------------------------------------------------- verificar

def _ctx_hud(tbl: str = "41=A\n", fonte: bytes | None = None, acentos: dict | None = None,
             hud: bool = True):
    from ferramentas.verificacao import Contexto

    ctx = Contexto(tabela=Tabela.de_texto(tbl), textos={}, glossario=[])
    if fonte is not None:
        ctx.extra["fonte"] = fonte
    if acentos is not None:
        ctx.extra["acentos"] = acentos
    ctx.extra["hud"] = hud
    return ctx


def _fonte_com_hud(tiles: bytes) -> bytes:
    fonte = bytearray(tiles)
    hud = tiles_hud(bytes(fonte))
    for i, c in enumerate(list(HUD_CODIGOS_CIMA) + list(HUD_CODIGOS_BAIXO)):
        fonte[32 * c:32 * c + 32] = hud[32 * i:32 * i + 32]
    return bytes(fonte)


def test_checar_hud_proibe_caractere_nos_codigos_do_hud():
    """0xC6-0xCB e 0xD3-0xD8 são o rótulo MOEDAS: nem a tabela nem os acentos podem
    usá-los."""
    from ferramentas.verificacao import checar_hud

    fonte = _fonte_com_hud(bytes(32 * 256))
    assert checar_hud(_ctx_hud("41=A\nBF=x\nCC=y\nD9=z\n", fonte, {"é": 0xA5})) == []
    achados = checar_hud(_ctx_hud("41=A\nC8=ã\nFED5=õ\nC7=[cor]\n", fonte,
                                  {"é": 0xA5, "ç": 0xD8}))
    assert [(a.nivel, a.checagem, a.local) for a in achados] == [
        ("erro", "hud", "tabela.tbl"), ("erro", "hud", "tabela.tbl"),
        ("erro", "hud", "config/texto.yaml")]
    msgs = " ".join(a.mensagem for a in achados)
    assert "'ã'" in msgs and "0xC8" in msgs and "'õ'" in msgs and "0xD5" in msgs
    assert "'ç'" in msgs and "0xD8" in msgs and "MOEDAS" in msgs


def test_checar_hud_confere_os_tiles_da_fonte():
    """Com o patch do HUD, os tiles 0xC6-0xCB e 0xD3-0xD8 do PNG têm de ser tiles_hud(PNG); sem PNG,
    o HUD mostraria os kana da fonte original."""
    from ferramentas.verificacao import checar_hud

    base = bytearray(32 * 256)
    for c in range(256):
        base[32 * c:32 * c + 32] = bytes([c & 0xFF]) * 32
    assert checar_hud(_ctx_hud(fonte=_fonte_com_hud(bytes(base)))) == []
    achados = checar_hud(_ctx_hud(fonte=bytes(base)))
    assert [(a.nivel, a.checagem, a.local) for a in achados] == [
        ("erro", "hud", ARQ_PNG.as_posix())]
    assert "0xC6" in achados[0].mensagem and "0xD8" in achados[0].mensagem
    assert "MOEDAS" in achados[0].mensagem
    sem_png = checar_hud(_ctx_hud())
    assert [(a.nivel, a.checagem) for a in sem_png] == [("erro", "hud")]
    # sem o patch do HUD os tiles não importam
    assert checar_hud(_ctx_hud(fonte=bytes(base), hud=False)) == []
    assert checar_hud(_ctx_hud(hud=False)) == []


def test_checar_hud_projeto_real():
    from ferramentas.verificacao import checar_hud

    cfg = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))
    ctx = _ctx_hud((RAIZ / "traducao" / "tabela.tbl").read_text(encoding="utf-8"),
                   ler_png(RAIZ / ARQ_PNG), cfg["acentos"])
    assert checar_hud(ctx) == []


def test_verificar_e_construir_recusam_fonte_sem_hud(rom_base, tmp_path, capsys):
    """PNG sem o rótulo do HUD (tiles do HUD = kana da base): erro no verificar e o
    build aborta, em vez de gravar kana no HUD."""
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    png = tmp_path / ARQ_PNG
    tiles = bytearray(ler_png(png))
    base = fonte_da_rom(rom_base)
    for c in list(HUD_CODIGOS_CIMA) + list(HUD_CODIGOS_BAIXO):
        tiles[32 * c:32 * c + 32] = base[32 * c:32 * c + 32]
    from ferramentas.fonte import PALETA_EXIBICAO
    from ferramentas.tiles import tiles_para_png
    tiles_para_png(bytes(tiles), 16, PALETA_EXIBICAO, png)
    assert main(["--raiz", str(tmp_path), "verificar"]) == 1
    assert "[hud]" in capsys.readouterr().out
    arq_base = tmp_path / "base.bin"
    arq_base.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq_base)]) == 1
    assert not (tmp_path / "build").exists()


def _desmontar(dados: bytes, end: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    return [(i.mnemonic, i.op_str.replace(" ", "")) for i in md.disasm(dados, end)]


def test_patches_hud_desmontam():
    """O rótulo passa a ser impresso pela rotina nova em duas linhas (cima: linha 4,
    baixo: linha 5, coluna 23) com os tiles do HUD da fonte."""
    patches = {p.id: p for p in carregar_patches(Projeto(raiz=RAIZ, rom={}))}
    chamada, rotina = patches["hud.moedas_chamada"], patches["hud.moedas_rotina"]
    assert chamada.end == END_CHAMADA and rotina.end == END_ROTINA
    assert chamada.original == bytes.fromhex("43FAFF456100F2C4")
    assert _desmontar(chamada.novo, END_CHAMADA) == [("jsr", f"${END_ROTINA:x}.l"),
                                                      ("nop", "")]
    assert rotina.original == b"\xFF" * len(rotina.original)
    d7_cima = (COLUNA_ROTULO << 8) | LINHA_CIMA
    d7_baixo = (COLUNA_ROTULO << 8) | LINHA_BAIXO
    codigo = rotina.novo[:34]
    instr = _desmontar(codigo, END_ROTINA)
    s_cima = END_ROTINA + 34
    assert instr == [
        ("move.w", f"#${d7_cima:x},d7"), ("jsr", "$83b0.l"),
        ("lea.l", f"${s_cima:x}(pc),a1"), ("jsr", "$786a.w"),
        ("move.w", f"#${d7_baixo:x},d7"), ("jsr", "$83b0.l"),
        ("jsr", "$786a.w"), ("rts", ""),
    ]
    strings = rotina.novo[34:]
    assert strings == bytes(HUD_CODIGOS_CIMA) + b"\x00" + bytes(HUD_CODIGOS_BAIXO) + b"\x00"
    # fora da região livre que o build aloca (texto, fonte e gráficos)
    cfg = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))
    assert END_ROTINA + len(rotina.novo) <= cfg["regiao_destino"][0]


def test_patches_hud_conferem_na_base(rom_base):
    rom = bytearray(rom_base)
    aplicar_patches(rom, carregar_patches(Projeto(raiz=RAIZ, rom={})))
    # o espaço da rotina era livre (FF desde 0x9F777)
    assert set(rom_base[0x9F777:0xA0000]) == {0xFF}
    # a rotina original do HUD continua: d7 = $1605 + bsr $83B0 antes da chamada
    assert rom[0x8596:0x85A0] == rom_base[0x8596:0x85A0]


def test_hud_documentado():
    mapa = (RAIZ / "docs" / "tecnico" / "mapa-rom.md").read_text(encoding="utf-8")
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    for trecho in ("$FF962C", "0x8596", "0x85A0", "0x9F780", "0xC6–0xCB", "0xD3–0xD8", "999999"):
        assert trecho in mapa, trecho
    assert "MOEDAS" in readme


# ------------------------------------------------------------- no jogo

# Roda num processo à parte (o emulador da sessão está preso à ROM base): NEW GAME, fim
# da fala de abertura, sai de casa (campo), grava tela e VRAM; depois põe o ouro no
# máximo na RAM, abre e fecha o menu (o fechamento redesenha o HUD inteiro, 0x7EE4 ->
# 0x8596) e grava de novo.
_SCRIPT_HUD = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador

saida = Path(sys.argv[3])
saida.mkdir(parents=True, exist_ok=True)
emu = Emulador(CORE_PADRAO, Path(sys.argv[2]))
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
emu.avancar(2, {"start"}); emu.avancar(120)
emu.avancar(2, {"start"}); emu.avancar(120)
emu.avancar(2, {"start"}); emu.avancar(120)
for _ in range(144):
    emu.avancar(2, {"c"}); emu.avancar(18)
emu.avancar(20, {"baixo"}); emu.avancar(60)
emu.quadro_png(saida / "campo.png")
(saida / "campo.vram").write_bytes(emu.vram())
emu.escrever_ram(0x962C, (999999).to_bytes(4, "big"))
emu.avancar(2, {"start"}); emu.avancar(30)
emu.avancar(2, {"start"}); emu.avancar(30)
emu.quadro_png(saida / "maximo.png")
(saida / "maximo.vram").write_bytes(emu.vram())
print(json.dumps({"ouro": int.from_bytes(emu.ram()[0x962C:0x9630], "big")}))
emu.fechar()
'''


def _rodar(rom: Path, destino: Path) -> dict:
    script = destino.parent / "hud.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_SCRIPT_HUD, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(RAIZ), str(rom), str(destino)],
                       cwd=str(RAIZ), capture_output=True, timeout=900)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(r.stdout.decode().strip().splitlines()[-1])


def _linhas_por_cor(img: Image.Image) -> tuple[set[int], set[int], tuple]:
    """No quadro do ouro: linhas com pixels da cor do rótulo e da cor do valor."""
    px = img.convert("RGB").load()
    x0, y0, x1, y1 = CAIXA_OURO
    fundo = px[x0 + 1, y0 + 1]
    # cor do valor: a que mais aparece na linha 6 da janela; a do rótulo, nas 4–5
    def mais_comum(ya, yb):
        cont = {}
        for y in range(ya, yb):
            for x in range(x0, x1):
                if px[x, y] != fundo:
                    cont[px[x, y]] = cont.get(px[x, y], 0) + 1
        return max(cont, key=cont.get)
    cor_valor = mais_comum(6 * 8, 7 * 8)
    cor_rotulo = mais_comum(4 * 8, 6 * 8)
    assert cor_valor != cor_rotulo
    rotulo = {y for y in range(y0, y1) for x in range(x0, x1) if px[x, y] == cor_rotulo}
    valor = {y for y in range(y0, y1) for x in range(x0, x1) if px[x, y] == cor_valor}
    return rotulo, valor, (fundo, cor_rotulo, cor_valor)


def _janela(vram: bytes, col: int, lin: int) -> int:
    end = 0xD800 + 2 * (32 * lin + col)
    return int.from_bytes(vram[end:end + 2], "big")


def test_hud_moedas_no_jogo(rom_base, tmp_path):
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    arq_base = tmp_path / "base.bin"
    arq_base.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq_base)]) == 0
    nova = tmp_path / "build" / "wbmw-ptbr.bin"

    cap_base = RAIZ / "build" / "capturas" / "hud_base"
    cap_nova = RAIZ / "build" / "capturas" / "hud_ptbr"
    assert _rodar(arq_base, cap_base)["ouro"] == OURO_MAXIMO
    assert _rodar(nova, cap_nova)["ouro"] == OURO_MAXIMO
    png = ler_png(RAIZ / ARQ_PNG)

    for tela in ("campo", "maximo"):
        vram = (cap_nova / f"{tela}.vram").read_bytes()
        base = (cap_base / f"{tela}.vram").read_bytes()
        # tiles do HUD carregados com a fonte; tilemap: rótulo em duas linhas, paleta 1
        for c in list(HUD_CODIGOS_CIMA) + list(HUD_CODIGOS_BAIXO):
            assert vram[32 * c:32 * c + 32] == png[32 * c:32 * c + 32], (tela, hex(c))
        for i, c in enumerate(HUD_CODIGOS_CIMA):
            assert _janela(vram, COLUNA_ROTULO + i, LINHA_CIMA) == 0xA000 | c, tela
        for i, c in enumerate(HUD_CODIGOS_BAIXO):
            assert _janela(vram, COLUNA_ROTULO + i, LINHA_BAIXO) == 0xA000 | c, tela
        # base: GOLD (fonte) na linha 5, colunas 22–25
        assert [_janela(base, 22 + i, 5) for i in range(4)] == [0xA000 | ord(ch)
                                                                for ch in "GOLD"]
        # fora do rótulo, a janela é a mesma da base (o 'G' da coluna 22 vira fundo)
        for lin in range(8):
            for col in range(32):
                if lin in (4, 5) and 22 <= col <= 28:
                    continue
                assert _janela(vram, col, lin) == _janela(base, col, lin), (tela, col, lin)
        assert _janela(vram, 22, 5) == _janela(base, 21, 5)

    with Image.open(cap_base / "maximo.png") as a, Image.open(cap_nova / "maximo.png") as b:
        a.load()
        b.load()
        # valor máximo: 6 dígitos (colunas 24–29 da linha 6)
        rot_b, val_b, cores_b = _linhas_por_cor(a)
        rot_n, val_n, cores_n = _linhas_por_cor(b)
        assert cores_b == cores_n   # mesmas cores de fundo, rótulo e valor
        # base: GOLD encosta no valor (sem linha livre); nova: >= 1 linha livre
        assert max(rot_b) + 1 == min(val_b)
        assert max(rot_n) + 1 < min(val_n), (sorted(rot_n), sorted(val_n))
        assert not rot_n & val_n
        assert len(rot_n) == 8 and min(rot_n) == 5 * 8 - HUD_SUBIDA
        # o resto do HUD (linhas 0–7 da janela, 64 pixels) é idêntico ao da base
        pa, pb = a.convert("RGB").load(), b.convert("RGB").load()
        x0, y0, x1, y1 = CAIXA_ROTULO
        diferentes = [(x, y) for y in range(64) for x in range(a.size[0])
                      if pa[x, y] != pb[x, y]]
        assert diferentes
        assert all(x0 <= x < x1 and y0 <= y < y1 for x, y in diferentes)
