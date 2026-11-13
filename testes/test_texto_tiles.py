"""Texto desenhado em tiles (mapa-rom.md §8, "Texto desenhado em tiles"): o final ("FIM" e
"CONTINUA..."), as placas "HOT" e "SAÍDA" e o game over ("FIM DE JOGO"), com captura de
cada tela no emulador."""

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

from ferramentas.cli import main
from ferramentas.config import ErroConfig, Projeto
from ferramentas.graficos import (RETOQUES, ErroGraficos, Retoque, aplicar_retoque,
                                  bloco_para_folha, carregar_itens, compor_game_over,
                                  folha_para_bloco, importar_tiles, item_por_nome, ler_png,
                                  tiles_da_rom)
from ferramentas.patches import carregar_patches

RAIZ = Path(__file__).resolve().parent.parent
BASE_SHA1 = "87a968f773c7e807e647c0737132457b06b78276"

BLOCOS_HOT = (0x37, 0x88, 0xD3, 0x10B, 0x11C)
BLOCO_SAIDA = 0xB8
BLOCO_FINAL = 0x2EE
#: o final usa o bloco 0x2EE no slot 34: tiles 16–31 = 0x450–0x45F
SLOT_FINAL = 34
TILE_FINAL = SLOT_FINAL * 32 + 16
#: fluxo do tilemap do final: 64 colunas × (word de cima, word de baixo)
FLUXO = 0x1B61A

#: words (cima-esq, cima-dir, baixo-esq, baixo-dir) de cada letra de 16 × 16 pixels no
#: fluxo novo; "." é uma coluna só, com o ponto embaixo
LETRAS = {
    "F": (0x8452, 0x845B, 0x8454, 0x8455), "I": (0x845F, 0x8C5F, 0x945F, 0x9C5F),
    "M": (0x8453, 0x8C53, 0x9459, 0x9C59), "C": (0x8458, 0x845E, 0x9458, 0x945E),
    "O": (0x8458, 0x8C58, 0x9458, 0x9C58), "N": (0x8456, 0x8457, 0x9C57, 0x9C56),
    "T": (0x8C50, 0x8450, 0x8C51, 0x8451), "U": (0x8459, 0x8C59, 0x9458, 0x9C58),
    "A": (0x845D, 0x8C5D, 0x945A, 0x9C5A),
}
PONTO = (0x8000, 0x845C)
VAZIO = (0x8000, 0x8000)


def _tela(texto: str, inicio: int) -> list[tuple[int, int]]:
    """32 colunas (cima, baixo) com ``texto`` a partir da coluna ``inicio``."""
    cols, c = [VAZIO] * 32, inicio
    for ch in texto:
        if ch == ".":
            cols[c] = PONTO
            c += 1
        else:
            a, b, d, e = LETRAS[ch]
            cols[c], cols[c + 1] = (a, d), (b, e)
            c += 2
    return cols


#: "FIM" (6 colunas) e "CONTINUA..." (19 colunas) centralizados nas 32 colunas como os
#: originais: THE END (13 colunas) deixa 10 livres à esquerda e 9 à direita
TELA_FIM = _tela("FIM", 13)
TELA_CONTINUA = _tela("CONTINUA...", 7)


def _colunas(dados: bytes) -> list[tuple[int, int]]:
    w = [int.from_bytes(dados[i:i + 2], "big") for i in range(0, len(dados), 2)]
    return list(zip(w[0::2], w[1::2]))


# ------------------------------------------------------------- configuração e PNG

def test_config_dos_itens():
    hot = item_por_nome(RAIZ, "placas_hot")
    saida = item_por_nome(RAIZ, "placa_saida")
    final = item_por_nome(RAIZ, "final")
    assert tuple(hot.blocos) == BLOCOS_HOT
    assert saida.blocos == [BLOCO_SAIDA] and final.blocos == [BLOCO_FINAL]
    for item in (hot, saida, final):
        assert item.disposicao == "fundo" and item.formato == "02"
        assert item.origem["sha1"] == BASE_SHA1
        assert RETOQUES[item.nome]


@pytest.mark.parametrize("nome", ["placas_hot", "placa_saida", "final", "game_over"])
def test_png_versionado_confere(rom_base, tmp_path, nome):
    """PNG e metadados = importar-tiles da ROM base + retoques do projeto (determinístico);
    fora dos retoques, o PNG é a arte da base sem mudança."""
    shutil.copytree(RAIZ / "config", tmp_path / "config")
    item = item_por_nome(tmp_path, nome)
    importar_tiles(rom_base, rom_base, item, tmp_path)
    assert ler_png(tmp_path / item.png, item) == ler_png(RAIZ / item.png, item)
    meta = (RAIZ / item.meta).read_text(encoding="utf-8")
    assert (tmp_path / item.meta).read_text(encoding="utf-8") == meta
    nova = ler_png(RAIZ / item.png, item)
    base = tiles_da_rom(rom_base, item)
    for i, b in enumerate(item.blocos):
        f_base = bloco_para_folha(base[i * 1024:(i + 1) * 1024])
        f_nova = bloco_para_folha(nova[i * 1024:(i + 1) * 1024])
        editados = {(r.x + dx, r.y + dy) for r in RETOQUES[nome] if r.bloco == b
                    for dy, linha in enumerate(r.linhas) for dx, ch in enumerate(linha)
                    if ch != "-"}
        diferentes = {(x, y) for y in range(16) for x in range(128)
                      if f_base[y][x] != f_nova[y][x]}
        assert diferentes and diferentes <= editados, hex(b)
    for r in RETOQUES[nome]:
        assert r.descricao in meta


def test_folha_ida_e_volta():
    rnd = random.Random(7)
    dados = bytes(rnd.randrange(256) for _ in range(1024))
    folha = bloco_para_folha(dados)
    assert len(folha) == 16 and len(folha[0]) == 128
    assert folha_para_bloco(folha) == dados
    # tile 17 = coluna 1 da 2.ª linha de tiles
    assert folha[8][8] == dados[17 * 32] >> 4


def test_retoque():
    folha = [[1] * 128 for _ in range(16)]
    r = Retoque("teste", 0, 2, 3, ("#-s", ".#."), (("#", 15), ("s", 9), (".", 0)))
    aplicar_retoque(r, folha)
    assert folha[3][2:5] == [15, 1, 9] and folha[4][2:5] == [0, 15, 0]
    with pytest.raises(ErroGraficos, match="cor"):
        aplicar_retoque(Retoque("x", 0, 0, 0, ("?",), (("#", 1),)), folha)
    with pytest.raises(ErroGraficos, match="fora"):
        aplicar_retoque(Retoque("x", 0, 127, 0, ("##",), (("#", 1),)), folha)


def test_disposicao_invalida_e_png_errado(tmp_path):
    (tmp_path / "config").mkdir()
    cfg = {"itens": {"x": {"blocos": [1, 2], "formato": "02", "disposicao": "torta",
                           "png": "g/x.png", "meta": "g/x.yaml"}}}
    (tmp_path / "config" / "graficos.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ErroConfig, match="disposicao"):
        carregar_itens(tmp_path)
    cfg["itens"]["x"]["disposicao"] = "fundo"
    (tmp_path / "config" / "graficos.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (item,) = carregar_itens(tmp_path)
    arq = tmp_path / "x.png"
    Image.new("P", (256, 16)).save(arq)
    with pytest.raises(ErroGraficos, match="128x32"):
        ler_png(arq, item)


def _placa(folha, x, y, w, h):
    return [linha[x:x + w] for linha in folha[y:y + h]]


def test_hot_e_saida_desenhados():
    """As letras novas estão onde estavam as antigas: HOT nas colunas de pixels 98–109 de
    cada placa (tiles 12–13 / 28–29) e SAÍDA nos pixels 73–100 da placa de saída."""
    hot = item_por_nome(RAIZ, "placas_hot")
    tiles = ler_png(RAIZ / hot.png, hot)
    for i, b in enumerate(BLOCOS_HOT):
        folha = bloco_para_folha(tiles[i * 1024:(i + 1) * 1024])
        (r,) = [r for r in RETOQUES["placas_hot"] if r.bloco == b]
        cores = dict(r.cores)
        letras = _placa(folha, r.x, r.y, 12, 4)
        traco = ["".join("#" if v == cores["#"] else "." for v in l) for l in letras]
        assert traco == ["#.#..##..###", "###.#..#..#.", "#.#.#..#..#.", "#.#..##...#."], hex(b)
    saida = item_por_nome(RAIZ, "placa_saida")
    folha = bloco_para_folha(ler_png(RAIZ / saida.png, saida))
    # as 5 letras: grupos de colunas com traço (cor 0xA) nas linhas 8–14
    grupos, ant = [], False
    for x in range(72, 104):
        tem = any(folha[y][x] == 0xA for y in range(8, 15))
        if tem and not ant:
            grupos.append([x])
        elif tem:
            grupos[-1].append(x)
        ant = tem
    assert [(g[0], g[-1]) for g in grupos] == [(73, 77), (79, 84), (86, 87), (89, 93), (95, 100)]
    # acento do Í acima da haste (pixels 85–87, linhas 5–6), com uma linha livre (7)
    assert {(x, y) for y in range(4, 8) for x in range(84, 90) if folha[y][x] == 0xA} == \
        {(86, 5), (87, 5), (85, 6), (86, 6)}
    assert all(folha[7][x] == 1 for x in range(73, 101))


# ------------------------------------------------------------- tilemap do final (patches)

def test_patches_do_final(rom_base):
    patches = {p.id: p for p in carregar_patches(Projeto(raiz=RAIZ, rom={}))}
    fim, continua = patches["final.fim"], patches["final.continua"]
    assert (fim.end, continua.end) == (FLUXO, FLUXO + 128)
    assert rom_base[FLUXO:FLUXO + 128] == fim.original
    assert rom_base[FLUXO + 128:FLUXO + 256] == continua.original
    assert _colunas(fim.novo) == TELA_FIM
    assert _colunas(continua.novo) == TELA_CONTINUA
    # só tiles do bloco do final (0x450–0x45F) ou o tile vazio 0, com prioridade e paleta 0
    for a, b in TELA_FIM + TELA_CONTINUA:
        for w in (a, b):
            assert w & 0xE000 == 0x8000 and (w & 0x7FF == 0 or 0x450 <= w & 0x7FF <= 0x45F)


def test_tiles_do_final_desenhados():
    """Tiles novos do bloco 0x2EE: alto do M e do A, pé do F e ponto."""
    item = item_por_nome(RAIZ, "final")
    folha = bloco_para_folha(ler_png(RAIZ / item.png, item))

    def tile(t):   # tile do bloco -> 8 linhas de '#'/'.'
        x, y = (t % 16) * 8, (t // 16) * 8
        return ["".join("#" if folha[y + j][x + i] == 15 else "." for i in range(8))
                for j in range(8)]

    assert tile(0x453 - 0x440) == ["........", ".###....", ".####...", ".#####..",
                                   ".######.", ".#######", ".####.##", ".####..#"]
    assert tile(0x454 - 0x440) == [".#######"] + [".####..."] * 6 + ["........"]
    assert tile(0x455 - 0x440) == ["######.."] + ["........"] * 7
    assert tile(0x45C - 0x440) == ["........"] * 4 + ["..###..."] * 3 + ["........"]
    assert tile(0x45D - 0x440) == ["........", "......##", ".....###", "....####",
                                   "...####.", "..####..", ".####...", ".####..."]


# ------------------------------------------------------------- no jogo

def _construir(rom_base: bytes, tmp_path: Path) -> tuple[Path, Path]:
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    base = tmp_path / "base.bin"
    base.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(base)]) == 0
    return base, tmp_path / "build" / "wbmw-ptbr.bin"


def _rodar(script: str, tmp_path: Path, *args) -> dict:
    arq = tmp_path / "script.py"
    arq.write_text(script, encoding="utf-8")
    r = subprocess.run([sys.executable, str(arq), str(RAIZ), *map(str, args)], cwd=str(RAIZ),
                       capture_output=True, timeout=1200)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(r.stdout.decode().strip().splitlines()[-1])


def _localizar(img: Image.Image, padrao: list[list[int]],
               cores: dict[int, tuple] | None = None) -> list[tuple[int, int, dict]]:
    """Posições (x, y) em que os pixels não transparentes de ``padrao`` (índices) aparecem
    na tela com uma cor por índice (``cores`` fixa as cores, se dada)."""
    px = img.convert("RGB").load()
    w, h = img.size
    alt, larg = len(padrao), len(padrao[0])
    pontos = [(x, y, v) for y, l in enumerate(padrao) for x, v in enumerate(l) if v]
    achados = []
    for oy in range(h - alt + 1):
        for ox in range(w - larg + 1):
            mapa = dict(cores or {})
            for x, y, v in pontos:
                c = px[ox + x, oy + y]
                if mapa.setdefault(v, c) != c:
                    break
            else:
                if len(set(mapa.values())) == len(mapa):   # índices distintos, cores distintas
                    achados.append((ox, oy, mapa))
    return achados


# Para cada cena: a ROM (base ou nova) ganha numa cópia temporária a sala de início trocada
# (word de 0x8FAA = 1.ª entrada da tabela de salas de 0x8F98, lida no NEW GAME; checksum
# refeito). A fala de abertura começa por cima da cena, mas a placa fica visível embaixo.
_SCRIPT_PLACAS = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador
from ferramentas.rom import corrigir_cabecalho

rom_orig = Path(sys.argv[2]).read_bytes()
destino = Path(sys.argv[3])
destino.mkdir(parents=True, exist_ok=True)
temp = Path(sys.argv[5])     # cópias da ROM (fora de build/capturas)
res = {}
for sala in json.loads(sys.argv[4]):
    rom = bytearray(rom_orig)
    assert rom[0x8FAA:0x8FAC] == bytes(2)
    rom[0x8FAA:0x8FAC] = sala.to_bytes(2, "big")
    corrigir_cabecalho(rom)
    arq = temp / "sala.bin"
    arq.write_bytes(rom)
    emu = Emulador(CORE_PADRAO, arq)
    emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
    emu.avancar(2, {"start"}); emu.avancar(120); emu.avancar(2, {"start"}); emu.avancar(500)
    nome = f"sala_{sala:02x}"
    emu.quadro_png(destino / f"{nome}.png")
    (destino / f"{nome}.vram").write_bytes(emu.vram())
    ram = emu.ram()
    res[nome] = {"sala": int.from_bytes(ram[0x9676:0x9678], "big"),
                 "slots": [int.from_bytes(ram[0x8E08 + 2 * i:0x8E0A + 2 * i], "big")
                           for i in range(64)]}
    emu.fechar()
    arq.unlink()
print(json.dumps(res))
'''

#: sala -> (bloco, retângulo da placa na folha do bloco (x, y, larg, alt) ou None se a placa
#: não aparece na tela do início da sala)
CENAS_PLACAS = {
    0x57: (0xD3, (96, 0, 16, 16)),
    0x59: (0x88, (96, 0, 16, 16)),
    0x0A: (BLOCO_SAIDA, (64, 0, 48, 16)),
    0x58: (0x37, None),
    0x20: (0x10B, None),
    0x5C: (0x11C, None),
}


def test_placas_no_jogo(rom_base, tmp_path):
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    arq_base, nova = _construir(rom_base, tmp_path)
    salas = json.dumps(sorted(CENAS_PLACAS))
    cap_base = RAIZ / "build" / "capturas" / "placas_base"
    cap_nova = RAIZ / "build" / "capturas" / "placas_ptbr"
    res_base = _rodar(_SCRIPT_PLACAS, tmp_path, arq_base, cap_base, salas, tmp_path)
    res_nova = _rodar(_SCRIPT_PLACAS, tmp_path, nova, cap_nova, salas, tmp_path)
    itens = {b: item for item in (item_por_nome(RAIZ, "placas_hot"),
                                  item_por_nome(RAIZ, "placa_saida")) for b in item.blocos}

    for sala, (bloco, caixa) in CENAS_PLACAS.items():
        nome = f"sala_{sala:02x}"
        item = itens[bloco]
        i = item.blocos.index(bloco)
        png = ler_png(RAIZ / item.png, item)[i * 1024:(i + 1) * 1024]
        original = tiles_da_rom(rom_base, item)[i * 1024:(i + 1) * 1024]
        assert png != original
        for res, cap, esperado in ((res_base, cap_base, original), (res_nova, cap_nova, png)):
            assert res[nome]["sala"] == sala
            slot = res[nome]["slots"].index(bloco)
            vram = (cap / f"{nome}.vram").read_bytes()
            assert vram[slot * 1024:(slot + 1) * 1024] == esperado, (nome, cap.name)
        if caixa is None:
            continue
        x, y, w, h = caixa
        with Image.open(cap_base / f"{nome}.png") as a, Image.open(cap_nova / f"{nome}.png") as b:
            a.load()
            b.load()
            antes = _placa(bloco_para_folha(original), x, y, w, h)
            depois = _placa(bloco_para_folha(png), x, y, w, h)
            # a placa antiga aparece uma vez na tela da base; a nova, no mesmo lugar e com
            # as mesmas cores, na tela da ROM traduzida
            (achado,) = _localizar(a, antes)
            ox, oy, cores = achado
            assert not _localizar(b, antes), nome
            achados = _localizar(b, depois, {k: v for k, v in cores.items()
                                             if any(k in l for l in depois)})
            assert [(ax, ay) for ax, ay, _ in achados] == [(ox, oy)], nome


# Final: cópia temporária da ROM com 'jmp $4F58' em 0x4CEC (o NEW GAME vai direto para o
# desfecho) e checksum refeito. O botão A a cada 240 quadros passa as falas. A 1.ª tela do
# texto ("THE END"/"FIM") é capturada 60 quadros depois de aparecer (o bloco 0x2EE no slot
# 34 e tiles 0x450–0x45F no plano A); a 2.ª ("TO BE CONTINUED"/"CONTINUA..."), quando o
# plano A fica 300 quadros sem mudar depois da troca.
_SCRIPT_FINAL = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador
from ferramentas.emulador.vram_cenas import regs_do_estado
from ferramentas.rom import corrigir_cabecalho

rom = bytearray(Path(sys.argv[2]).read_bytes())
destino = Path(sys.argv[3])
destino.mkdir(parents=True, exist_ok=True)
temp = Path(sys.argv[4])     # cópia da ROM (fora de build/capturas)
assert rom[0x4CEC:0x4CF2] == bytes.fromhex("4A3880C86B18")
rom[0x4CEC:0x4CF2] = bytes.fromhex("4EF900004F58")
corrigir_cabecalho(rom)
arq = temp / "final.bin"
arq.write_bytes(rom)
emu = Emulador(CORE_PADRAO, arq)

def plano():
    regs = regs_do_estado(emu.salvar_estado())
    vram = emu.vram()
    end = (regs[2] & 0x38) << 10
    return [int.from_bytes(vram[end + 2 * i:end + 2 * i + 2], "big") for i in range(64 * 32)]

def texto(ws):
    ram = emu.ram()
    if int.from_bytes(ram[0x8E08 + 68:0x8E08 + 70], "big") != 0x2EE:
        return None
    return [w for w in ws if 0x450 <= w & 0x7FF <= 0x45F]

def gravar(nome, ws):
    emu.quadro_png(destino / f"{nome}.png")
    (destino / f"{nome}.vram").write_bytes(emu.vram())
    linhas = sorted({i // 64 for i, w in enumerate(ws) if 0x450 <= w & 0x7FF <= 0x45F})
    res[nome] = {"linhas": linhas, "words": [ws[64 * l:64 * l + 32] for l in linhas],
                 "quadro": quadro}

res, quadro, fase, ant, estavel = {}, 0, 0, None, 0
while quadro < 30000 and fase < 3:
    if quadro % 240 == 0:
        emu.avancar(2, {"a"}); quadro += 2
    emu.avancar(8); quadro += 8
    ws = plano()
    t = texto(ws)
    if fase == 0 and t:
        emu.avancar(60); quadro += 60
        ws = plano()
        gravar("fim", ws)
        ant, fase = texto(ws), 1
    elif fase == 1 and t != ant:
        ant, fase = t, 2
    elif fase == 2:
        if t != ant:
            ant, estavel = t, 0
        else:
            estavel += 10
            if estavel >= 300:
                gravar("continua", ws)
                fase = 3
emu.fechar()
arq.unlink()
print(json.dumps(res))
'''


def _pixels_texto(vram: bytes, words: list[list[int]]) -> list[list[int]]:
    """16 linhas × 256 pixels (índices) das duas linhas de tiles do plano A."""
    px = [[0] * 256 for _ in range(16)]
    for lin in range(2):
        for col, w in enumerate(words[lin]):
            t = w & 0x7FF
            for y in range(8):
                for x in range(8):
                    sx = 7 - x if w & 0x800 else x
                    sy = 7 - y if w & 0x1000 else y
                    b = vram[t * 32 + sy * 4 + sx // 2]
                    px[lin * 8 + y][col * 8 + x] = b >> 4 if sx % 2 == 0 else b & 15
    return px


def test_final_no_jogo(rom_base, tmp_path):
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    arq_base, nova = _construir(rom_base, tmp_path)
    cap_base = RAIZ / "build" / "capturas" / "final_base"
    cap_nova = RAIZ / "build" / "capturas" / "final_ptbr"
    res_base = _rodar(_SCRIPT_FINAL, tmp_path, arq_base, cap_base, tmp_path)
    res_nova = _rodar(_SCRIPT_FINAL, tmp_path, nova, cap_nova, tmp_path)
    item = item_por_nome(RAIZ, "final")
    png = ler_png(RAIZ / item.png, item)
    original = tiles_da_rom(rom_base, item)
    fluxo = _colunas(rom_base[FLUXO:FLUXO + 256])

    for tela, novo in (("fim", TELA_FIM), ("continua", TELA_CONTINUA)):
        antigo = fluxo[:32] if tela == "fim" else fluxo[32:]
        for res, cap, tiles, cols in ((res_base, cap_base, original, antigo),
                                      (res_nova, cap_nova, png, novo)):
            r = res[tela]
            vram = (cap / f"{tela}.vram").read_bytes()
            # tiles 0x450–0x45F = tiles 16–31 do bloco (PNG na ROM nova)
            assert vram[TILE_FINAL * 32:(TILE_FINAL + 16) * 32] == tiles[16 * 32:], \
                (tela, cap.name)
            # plano A: as duas linhas do texto = as 32 colunas do fluxo dessa tela
            assert len(r["linhas"]) == 2 and r["linhas"][1] == r["linhas"][0] + 1
            assert list(zip(*r["words"])) == cols, (tela, cap.name)
        assert res_base[tela]["linhas"] == res_nova[tela]["linhas"]
        # na tela (plano A sem rolagem: linha de tiles l = pixel 8·l): os pixels de traço
        # (índice 15) do texto numa cor só, clara e cinza (branco), que quase não aparece
        # fora do traço; o texto antigo não aparece na tela nova
        vb = (cap_base / f"{tela}.vram").read_bytes()
        vn = (cap_nova / f"{tela}.vram").read_bytes()
        traco_b = _pixels_texto(vb, res_base[tela]["words"])
        traco_n = _pixels_texto(vn, res_nova[tela]["words"])
        y0 = 8 * res_base[tela]["linhas"][0]
        with Image.open(cap_base / f"{tela}.png") as a, Image.open(cap_nova / f"{tela}.png") as b:
            a.load()
            b.load()
            cor_b = _texto_na_tela(a, traco_b, y0)
            cor_n = _texto_na_tela(b, traco_n, y0)
            assert cor_b == cor_n, tela
            # o traço antigo que não é traço novo: quase todo sem a cor do texto (sobram
            # só estrelas que caiam ali)
            pn = b.convert("RGB").load()
            so_antigo = [pn[x, y0 + y] for y, l in enumerate(traco_b)
                         for x, v in enumerate(l) if v == 15 and traco_n[y][x] != 15]
            assert so_antigo, tela
            assert sum(c != cor_n for c in so_antigo) >= len(so_antigo) * 98 // 100, tela


def _texto_na_tela(img: Image.Image, pixels: list[list[int]], y0: int) -> tuple:
    """Cor dos pixels de traço (índice 15) de ``pixels`` na tela a partir da linha ``y0``;
    confere que é uma só, cinza claro, e rara no resto da faixa."""
    px = img.convert("RGB").load()
    traco = {px[x, y0 + y] for y, l in enumerate(pixels) for x, v in enumerate(l) if v == 15}
    assert len(traco) == 1, traco
    (cor,) = traco
    assert len(set(cor)) == 1 and cor[0] >= 128, cor
    fora = [px[x, y0 + y] for y, l in enumerate(pixels) for x, v in enumerate(l) if v != 15]
    assert sum(c == cor for c in fora) <= len(fora) // 50
    return cor


# ------------------------------------------------------------- game over

BLOCO_GO = 0xFF
#: o game over põe o bloco 0xFF no slot 9 (script 0x91BE): tiles 0x120–0x13F
TILE_GO = 9 * 32
#: tilemap de 0x91C2 (desenhado por 0x69AE): posição (coluna 8, linha 12), atributo 0x01,
#: 16 tiles por linha, tiles 0x20–0x3F (= 0x120–0x13F), fim
TILEMAP_GO = bytes([1, 8, 12, 2, 1, 9, 15, *range(0x20, 0x40), 0])
COLUNA_GO = 8
#: letras do original reaproveitadas: primeira coluna da célula de 14 pixels na folha base
LETRAS_ORIGINAIS_GO = {"G": 3, "M": 33, "E": 48, "O": 66}
#: células (pixel inicial, final) de "FIM DE JOGO" na folha nova
CELULAS_GO = [(0, 13), (15, 18), (20, 33), (38, 51), (53, 66), (71, 82), (84, 97),
              (99, 112), (114, 127)]
_CHAR_GO = {0: ".", 1: "o", 0xB: "b", 0xC: "c", 0x9: "9", 0xF: "f"}


def _celulas(folha: list[list[int]]) -> list[tuple[int, int]]:
    cols = [x for x in range(128) if any(folha[y][x] for y in range(16))]
    grupos: list[list[int]] = []
    for x in cols:
        if grupos and x == grupos[-1][-1] + 1:
            grupos[-1].append(x)
        else:
            grupos.append([x])
    return [(g[0], g[-1]) for g in grupos]


def test_config_e_tilemap_do_game_over(rom_base):
    item = item_por_nome(RAIZ, "game_over")
    assert item.blocos == [BLOCO_GO] and item.disposicao == "fundo" and item.formato == "02"
    assert item.origem["sha1"] == BASE_SHA1 and RETOQUES["game_over"]
    # script de slots (slot 9 = bloco 0xFF) e tilemap, que não mudam
    assert rom_base[0x91BE:0x91C2] == bytes.fromhex("8900FFFF")
    assert rom_base[0x91C2:0x91C2 + len(TILEMAP_GO)] == TILEMAP_GO
    # o laço do jogo vai para o game over (0x9144) com o bit 7 de $9F03
    assert rom_base[0x9038:0x9042] == bytes.fromhex("4A389F036A0460000104")


def test_letras_do_game_over(rom_base):
    """G, M, E e O são as do original, pixel a pixel; as 9 letras de FIM DE JOGO ficam nas
    células esperadas (1 pixel entre letras e 4 entre palavras, como no GAME OVER), com o
    degradê por linha e o contorno nos 8 vizinhos do traço."""
    item = item_por_nome(RAIZ, "game_over")
    base = bloco_para_folha(tiles_da_rom(rom_base, item))
    for ch, x0 in LETRAS_ORIGINAIS_GO.items():
        nova = compor_game_over(ch, x0)
        for y in range(16):
            assert nova[y][x0:x0 + 14] == "".join(_CHAR_GO[v] for v in base[y][x0:x0 + 14]), ch
    # espaçamento do original: 1 pixel entre letras e 4 entre palavras (GAME | OVER)
    assert _celulas(base) == [(3, 16), (18, 31), (33, 46), (48, 61), (66, 79), (81, 94),
                              (96, 109), (111, 124)]
    folha = bloco_para_folha(ler_png(RAIZ / item.png, item))
    assert _celulas(folha) == CELULAS_GO
    assert [b - a - 1 for (_, a), (b, _) in zip(CELULAS_GO, CELULAS_GO[1:])] == \
        [1, 1, 4, 1, 4, 1, 1, 1]
    # mesmas cores por linha que o original (o traço tem uma cor por linha)
    for y in range(16):
        assert set(folha[y]) - {0, 1} == set(base[y]) - {0, 1}, y
    assert list(compor_game_over()) == ["".join(_CHAR_GO[v] for v in l) for l in folha]
    with pytest.raises(ErroGraficos, match="cabe"):
        compor_game_over("FIM DE JOGO", 1)


# Game over: cópia temporária da ROM em que o laço do jogo (0x9038: 'tst.b $9F03; bpl')
# sempre cai no 'bra $9144' (o 'bpl' vira 'nop'; checksum refeito). Passada a fala de
# abertura (A a cada 60 quadros), o jogo vai para o game over. A tela é capturada 60
# quadros depois de o bloco 0xFF entrar no slot 9 e os 32 tiles aparecerem no plano A,
# sem apertar mais nada (a tela espera 240 quadros ou um botão).
_SCRIPT_GAME_OVER = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador
from ferramentas.emulador.vram_cenas import regs_do_estado
from ferramentas.rom import corrigir_cabecalho

rom = bytearray(Path(sys.argv[2]).read_bytes())
destino = Path(sys.argv[3])
destino.mkdir(parents=True, exist_ok=True)
temp = Path(sys.argv[4])     # cópia da ROM (fora de build/capturas)
assert rom[0x9038:0x903E] == bytes.fromhex("4A389F036A04")
rom[0x903C:0x903E] = bytes.fromhex("4E71")
corrigir_cabecalho(rom)
arq = temp / "game_over.bin"
arq.write_bytes(rom)
emu = Emulador(CORE_PADRAO, arq)
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
emu.avancar(2, {"start"}); emu.avancar(120); emu.avancar(2, {"start"})

def plano():
    regs = regs_do_estado(emu.salvar_estado())
    vram = emu.vram()
    end = (regs[2] & 0x38) << 10
    return [int.from_bytes(vram[end + 2 * i:end + 2 * i + 2], "big") for i in range(64 * 32)]

res, quadro, passo = {}, 0, 0
while quadro < 6000:
    slot9 = int.from_bytes(emu.ram()[0x8E08 + 18:0x8E08 + 20], "big")
    if slot9 != 0xFF and passo % 6 == 0:
        emu.avancar(2, {"a"}); quadro += 2
    emu.avancar(8); quadro += 8; passo += 1
    ws = plano()
    pos = [i for i, w in enumerate(ws) if 0x120 <= w & 0x7FF <= 0x13F]
    if slot9 == 0xFF and len(pos) == 32:
        emu.avancar(60); quadro += 60
        ws = plano()
        emu.quadro_png(destino / "game_over.png")
        (destino / "game_over.vram").write_bytes(emu.vram())
        res = {"quadro": quadro, "slot9": slot9,
               "linhas": [ws[64 * l:64 * l + 32] for l in (12, 13)],
               "pos": [i for i, w in enumerate(ws) if 0x120 <= w & 0x7FF <= 0x13F]}
        break
emu.fechar()
arq.unlink()
print(json.dumps(res))
"""


def _ampliar(png: Path, destino: Path) -> None:
    """Faixa do texto (pixels 48–207 × 80–127 da tela) ampliada 4 vezes."""
    with Image.open(png) as img:
        faixa = img.convert("RGB").crop((48, 80, 208, 128))
        faixa.resize((faixa.width * 4, faixa.height * 4), Image.NEAREST).save(destino)


def test_game_over_no_jogo(rom_base, tmp_path):
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    arq_base, nova = _construir(rom_base, tmp_path)
    cap_base = RAIZ / "build" / "capturas" / "game_over_base"
    cap_nova = RAIZ / "build" / "capturas" / "game_over_ptbr"
    res_base = _rodar(_SCRIPT_GAME_OVER, tmp_path, arq_base, cap_base, tmp_path)
    res_nova = _rodar(_SCRIPT_GAME_OVER, tmp_path, nova, cap_nova, tmp_path)
    item = item_por_nome(RAIZ, "game_over")
    png = ler_png(RAIZ / item.png, item)
    original = tiles_da_rom(rom_base, item)
    assert png != original

    esperado = [[0] * COLUNA_GO + [0x100 | (0x20 + 16 * l + c) for c in range(16)]
                + [0] * (32 - COLUNA_GO - 16) for l in range(2)]
    cores_linha = None
    for res, cap, tiles in ((res_base, cap_base, original), (res_nova, cap_nova, png)):
        assert res and res["slot9"] == BLOCO_GO, cap.name
        vram = (cap / "game_over.vram").read_bytes()
        # tiles 0x120–0x13F = o bloco (o PNG na ROM nova)
        assert vram[TILE_GO * 32:(TILE_GO + 32) * 32] == tiles, cap.name
        # plano A: 16 × 2 tiles nas colunas 8–23 das linhas 12–13, e só ali
        assert res["linhas"] == esperado, cap.name
        assert len(res["pos"]) == 32
        # na tela (sem rolagem: linha 12 = pixel 96, coluna 8 = pixel 64): fundo e
        # contorno pretos, o traço com a cor da sua linha (a mesma nas duas ROMs)
        folha = bloco_para_folha(tiles)
        with Image.open(cap / "game_over.png") as img:
            px = img.convert("RGB").load()
            cores = []
            for y in range(16):
                traco = {px[64 + x, 96 + y] for x in range(128) if folha[y][x] > 1}
                fundo = {px[64 + x, 96 + y] for x in range(128) if folha[y][x] <= 1}
                assert fundo == {(0, 0, 0)}, (cap.name, y)
                assert len(traco) <= 1 and (0, 0, 0) not in traco, (cap.name, y)
                cores.append(traco)
            # fora da faixa do texto, a tela é preta
            assert all(px[x, y] == (0, 0, 0) for y in range(224) for x in range(256)
                       if not (64 <= x < 192 and 96 <= y < 112)), cap.name
        if cores_linha is None:
            cores_linha = cores
        assert cores == cores_linha, cap.name
        _ampliar(cap / "game_over.png", cap / "game_over_4x.png")
    # degradê: vermelho, laranja, amarelo e branco no meio
    assert [next(iter(c)) for c in cores_linha[1:8:2]] == [
        (205, 0, 0), (238, 101, 0), (238, 238, 0), (238, 238, 238)]
