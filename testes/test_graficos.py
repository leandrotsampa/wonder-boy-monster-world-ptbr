"""Itens gráficos (config/graficos.yaml): tela de título (arte do projeto) e a etapa do build."""

import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

from ferramentas.cli import main
from ferramentas.compressao import (TAMANHO_BLOCO, TIPO_00, TIPO_CRU, TIPO_HUFFMAN, TIPO_VAZIO,
                                    comprimir, escrever_entrada, ler_entrada)
from ferramentas.config import Projeto
from ferramentas.espaco import ErroEspaco
from ferramentas.graficos import (SPRITES_TITULO, ErroGraficos, _ordem_png, _ordem_sprite,
                                  carregar_itens, etapa_graficos, faixa_para_tiles,
                                  importar_tiles, item_por_nome, ler_bloco, ler_png,
                                  tiles_da_rom, tiles_para_faixa)

RAIZ = Path(__file__).resolve().parent.parent
BLOCOS_TITULO = (0x166, 0x167, 0x168)
#: tiles 0x3C0–0x41F (slots 30–32) no VRAM
VRAM_TEXTO = slice(0x3C0 * 32, 0x420 * 32)
#: colunas de sprite do "NOVO JOGO" (tiles 0x3C0–0x3D3)
COLUNAS_NOVO_JOGO = range(0, 10)
#: retângulo da tela com os sprites de texto (título e menu, seta incluída)
CAIXA_TEXTO = (40, 116, 226, 142)   # x0, y0, x1, y1 (exclusivo)


def _cfg_item(raiz: Path, blocos=BLOCOS_TITULO, formato="02", nome="titulo",
              origem=True) -> None:
    (raiz / "config").mkdir(parents=True, exist_ok=True)
    (raiz / "config" / "texto.yaml").write_text("regiao_destino: [0xA4C80, 0xC0000]\n",
                                                encoding="utf-8")
    cfg = {"itens": {nome: {"blocos": list(blocos), "formato": formato,
                            "png": f"graficos/telas/{nome}.png",
                            "meta": f"graficos/telas/{nome}.yaml"}}}
    if origem:
        cfg["itens"][nome]["origem"] = {"descricao": "teste"}
    (raiz / "config" / "graficos.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")


def _gravar_png(raiz: Path, item, tiles: bytes) -> None:
    from ferramentas.fonte import PALETA_EXIBICAO
    from ferramentas.tiles import tiles_para_png

    arq = raiz / item.png
    arq.parent.mkdir(parents=True, exist_ok=True)
    tiles_para_png(_ordem_png(tiles), item.tiles // 2, PALETA_EXIBICAO, arq)


# ------------------------------------------------------------- unidades

def test_faixa_ida_e_volta():
    rnd = random.Random(5)
    tiles = bytes(rnd.randrange(256) for _ in range(96 * 32))
    faixa = tiles_para_faixa(tiles)
    assert len(faixa) == 16 and len(faixa[0]) == 48 * 8
    assert faixa_para_tiles(faixa) == tiles
    assert _ordem_sprite(_ordem_png(tiles)) == tiles
    # coluna de sprite c = tiles 2c (em cima) e 2c+1 (embaixo)
    assert faixa[8][8] == tiles[3 * 32] >> 4


def test_ler_bloco_tipos():
    rom = bytearray(b"\xFF" * 0x50000)
    escrever_entrada(rom, 1, TIPO_VAZIO, 0)
    rom[0x48000:0x48400] = bytes(range(256)) * 4
    escrever_entrada(rom, 2, TIPO_CRU, 0x48000)
    escrever_entrada(rom, 3, TIPO_00, 0x48000)
    assert ler_bloco(bytes(rom), 1)[0] == bytes(1024)
    dados, tipo, end, tam = ler_bloco(bytes(rom), 2)
    assert (dados, tipo, end, tam) == (bytes(range(256)) * 4, TIPO_CRU, 0x48000, 1024)
    with pytest.raises(ErroGraficos, match="tipo 00"):
        ler_bloco(bytes(rom), 3)


def _rom_sintetica() -> bytearray:
    rom = bytearray(b"\xFF" * 0xC0000)
    pos = 0x60001   # ímpar: tipo 02 aceita
    for i, b in enumerate(BLOCOS_TITULO):
        dados = bytes([0x11 * (i + 1)]) * 512 + bytes(512)
        comp = comprimir(dados)
        rom[pos:pos + len(comp)] = comp
        escrever_entrada(rom, b, TIPO_HUFFMAN, pos)
        pos += len(comp)
    return rom


def test_etapa_graficos_sintetica(tmp_path):
    _cfg_item(tmp_path)
    (item,) = carregar_itens(tmp_path)
    projeto = Projeto(raiz=tmp_path, rom={})
    rom = _rom_sintetica()
    original = bytes(rom)
    # sem PNG: nada
    etapa_graficos(rom, projeto)
    assert rom == original
    # PNG igual à ROM: nada
    tiles = tiles_da_rom(original, item)
    _gravar_png(tmp_path, item, tiles)
    assert ler_png(tmp_path / item.png, item) == tiles
    etapa_graficos(rom, projeto)
    assert rom == original
    # bloco 0x167 vira ruído (não cabe): realocado e reapontado; os outros intactos
    rnd = random.Random(9)
    novo = bytearray(tiles)
    novo[TAMANHO_BLOCO:2 * TAMANHO_BLOCO] = bytes(rnd.randrange(16) * 0x11
                                                  for _ in range(TAMANHO_BLOCO))
    _gravar_png(tmp_path, item, bytes(novo))
    etapa_graficos(rom, projeto)
    assert tiles_da_rom(bytes(rom), item) == bytes(novo)
    tipo, end = ler_entrada(rom, 0x167)
    assert tipo == TIPO_HUFFMAN and end == 0xA4C80
    assert ler_entrada(rom, 0x166) == ler_entrada(original, 0x166)
    assert projeto.regiao.usos == [("titulo bloco 0x167", 0xA4C80,
                                    len(comprimir(bytes(novo[1024:2048]))))]


def test_etapa_graficos_no_lugar(tmp_path):
    _cfg_item(tmp_path)
    (item,) = carregar_itens(tmp_path)
    rom = _rom_sintetica()
    original = bytes(rom)
    tiles = bytearray(tiles_da_rom(original, item))
    tiles[0:512] = bytes(512)   # bloco 0x166 todo zero: comprime menos que o original
    _gravar_png(tmp_path, item, bytes(tiles))
    projeto = Projeto(raiz=tmp_path, rom={})
    etapa_graficos(rom, projeto)
    assert ler_entrada(rom, 0x166) == ler_entrada(original, 0x166)
    assert tiles_da_rom(bytes(rom), item) == bytes(tiles)
    assert projeto.regiao is None   # nada foi para a região livre


def test_etapa_graficos_sem_espaco(tmp_path):
    _cfg_item(tmp_path)
    (tmp_path / "config" / "texto.yaml").write_text("regiao_destino: [0xA4C80, 0xA4C90]\n",
                                                    encoding="utf-8")
    (item,) = carregar_itens(tmp_path)
    rom = _rom_sintetica()
    original = bytes(rom)
    rnd = random.Random(3)
    _gravar_png(tmp_path, item, bytes(rnd.randrange(256) for _ in range(3 * TAMANHO_BLOCO)))
    projeto = Projeto(raiz=tmp_path, rom={})
    with pytest.raises(ErroEspaco, match="gráficos"):
        etapa_graficos(rom, projeto)
    assert rom == original and projeto.regiao.usos == []


def test_png_tamanho_errado(tmp_path):
    _cfg_item(tmp_path)
    (item,) = carregar_itens(tmp_path)
    arq = tmp_path / item.png
    arq.parent.mkdir(parents=True)
    Image.new("P", (64, 16)).save(arq)
    with pytest.raises(ErroGraficos, match="384x16"):
        ler_png(arq, item)


def test_config_invalida(tmp_path):
    from ferramentas.config import ErroConfig

    assert carregar_itens(tmp_path) == []
    _cfg_item(tmp_path, formato="07")
    with pytest.raises(ErroConfig, match="formato"):
        carregar_itens(tmp_path)
    _cfg_item(tmp_path)
    with pytest.raises(ErroConfig, match="não existe"):
        item_por_nome(tmp_path, "outro")


def test_importar_item_sem_origem_erro(tmp_path):
    """Item sem 'origem' (arte do projeto): importar-tiles recusa e não grava nada."""
    _cfg_item(tmp_path, origem=False)
    (item,) = carregar_itens(tmp_path)
    assert item.origem == {}
    rom = bytes(_rom_sintetica())
    with pytest.raises(ErroGraficos, match="sem 'origem'"):
        importar_tiles(rom, rom, item, tmp_path)
    assert not (tmp_path / item.png).exists() and not (tmp_path / item.meta).exists()


# ------------------------------------------------------------- ROMs reais

def test_config_do_projeto():
    item = item_por_nome(RAIZ, "titulo")
    assert tuple(item.blocos) == BLOCOS_TITULO and item.formato == "02"
    assert item.origem == {}   # arte do projeto, editada à mão (sem importação)


def test_titulo_png_reinserido(rom_base, tmp_path):
    """O PNG versionado do título vai para a ROM: os blocos descomprimem nele, o texto
    muda em relação à base e o logo (0x140–0x15D) não muda."""
    for rel in ("config", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    item = item_por_nome(tmp_path, "titulo")
    png = ler_png(tmp_path / item.png, item)
    base = tiles_da_rom(rom_base, item)
    assert png != base
    # cada texto (NOVO JOGO, CONTINUAR, APERTE START) difere da base
    for texto in ("NOVO JOGO", "CONTINUAR", "APERTE START"):
        fatias = [slice((a - 0x3C0) * 32, (b - 0x3C0 + 1) * 32) for a, b in SPRITES_TITULO[texto]]
        assert any(png[f] != base[f] for f in fatias), texto
    rom = bytearray(rom_base)
    etapa_graficos(rom, Projeto(raiz=tmp_path, rom={}))
    assert tiles_da_rom(bytes(rom), item) == png
    for b in range(0x140, 0x15E):
        assert ler_entrada(rom, b) == ler_entrada(rom_base, b)
    inicio_logo, fim_logo = ler_entrada(rom_base, 0x140)[1], ler_entrada(rom_base, 0x166)[1]
    assert rom[inicio_logo:fim_logo] == rom_base[inicio_logo:fim_logo]   # blobs do logo


def test_meta_titulo_confere(rom_base):
    """graficos/telas/titulo.yaml descreve os blocos na ROM base e as colunas de cada texto
    (as mesmas de SPRITES_TITULO)."""
    item = item_por_nome(RAIZ, "titulo")
    meta = yaml.safe_load((RAIZ / item.meta).read_text(encoding="utf-8"))
    assert meta["origem"]["base_sha1"] == "87a968f773c7e807e647c0737132457b06b78276"
    assert meta["png"] == item.png.name and meta["tiles"] == item.tiles
    assert [b["bloco"] for b in meta["blocos"]] == list(BLOCOS_TITULO)
    for b in meta["blocos"]:
        _, tipo, end, tam = ler_bloco(rom_base, b["bloco"])
        assert b["base"] == {"tipo": f"{tipo:02X}", "endereco": end, "bytes": tam}
    colunas = {p["texto"]: p["colunas_png"] for p in meta["partes"]}
    nomes = {"NOVO JOGO": "NOVO JOGO", "CONTINUAR": "CONTINUAR",
             "APERTE START": "APERTE START", "seta": "seta do menu"}
    for chave, texto in nomes.items():
        partes = []
        for a, b in SPRITES_TITULO[chave]:
            ca, cb = (a - 0x3C0) // 2, (b - 0x3C0) // 2
            partes.append(f"{ca}-{cb}" if ca != cb else f"{ca}")
        esperado = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
        assert colunas[texto] == esperado, texto


def test_png_continuar_fica_nas_proprias_colunas():
    """O "CONTINUAR" (colunas 10–19, pixels 80–159) não invade a coluna 20, que é o 1.º
    tile do APERTE START (sprite à esquerda do A), e o R não perde o contorno."""
    item = item_por_nome(RAIZ, "titulo")
    faixa = tiles_para_faixa(ler_png(RAIZ / item.png, item))
    assert all(faixa[y][x] == 0 for y in range(16) for x in range(160, 168))
    traco = {(x, y) for y in range(16) for x in range(80, 160) if faixa[y][x] == 15}
    assert traco and all(81 <= x <= 158 for x, _ in traco)
    r = [(x, y) for x, y in traco if x >= 152]   # o R (pixels 152–159 depois do ajuste)
    assert r
    for x, y in r:   # todo pixel de traço do R tem contorno ou traço nos 8 vizinhos
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if 0 <= y + dy < 16:
                    assert faixa[y + dy][x + dx] != 0, (x, y, dx, dy)


def test_importar_tiles_cli(rom_base, tmp_path):
    for rel in ("config", "traducao"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "rom").mkdir()
    base = tmp_path / "rom" / "Wonder Boy In Monster World (UE) [!].bin"
    base.write_bytes(rom_base)
    # item com origem (a ROM base): grava o PNG
    assert main(["--raiz", str(tmp_path), "importar-tiles", "--origem", str(base),
                 "--item", "placa_saida"]) == 0
    assert (tmp_path / "graficos" / "telas" / "placa_saida.png").is_file()
    # título sem origem (arte do projeto): erro sem traceback, nada gravado
    assert main(["--raiz", str(tmp_path), "importar-tiles", "--origem", str(base),
                 "--item", "titulo"]) == 1
    assert not (tmp_path / "graficos" / "telas" / "titulo.png").exists()
    # origem errada (sha1 não confere): erro sem traceback
    errada = tmp_path / "errada.bin"
    errada.write_bytes(rom_base[:-1] + b"\x00")
    assert main(["--raiz", str(tmp_path), "importar-tiles", "--origem", str(errada),
                 "--item", "placa_saida"]) == 1


# ------------------------------------------------------------- no jogo

def _fora_da_caixa(a: Image.Image, b: Image.Image) -> bool:
    """As imagens são iguais fora de CAIXA_TEXTO."""
    x0, y0, x1, y1 = CAIXA_TEXTO
    pa, pb = a.convert("RGB").load(), b.convert("RGB").load()
    w, h = a.size
    return all(pa[x, y] == pb[x, y] for y in range(h) for x in range(w)
               if not (x0 <= x < x1 and y0 <= y < y1))


def _dentro_da_caixa(img: Image.Image) -> bytes:
    return img.convert("RGB").crop(CAIXA_TEXTO).tobytes()


def test_titulo_no_jogo(rom_base, emulador, tmp_path):
    from ferramentas.emulador.roteiro import executar_roteiro

    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    arq_rom = tmp_path / "base.bin"
    arq_rom.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq_rom)]) == 0
    nova = tmp_path / "build" / "wbmw-ptbr.bin"
    item = item_por_nome(RAIZ, "titulo")
    png = ler_png(RAIZ / item.png, item)
    assert tiles_da_rom(nova.read_bytes(), item) == png

    roteiro = RAIZ / "roteiros" / "titulo.yaml"
    cap_base = RAIZ / "build" / "capturas" / "titulo_base"
    executar_roteiro(roteiro, cap_base, emulador=emulador)
    # o emulador da sessão está preso à ROM base: a ROM nova roda num processo à parte
    cap_nova = RAIZ / "build" / "capturas" / "titulo_ptbr"
    r = subprocess.run([sys.executable, "-m", "ferramentas.emulador", str(roteiro),
                        "--rom", str(nova), "--destino", str(cap_nova)],
                       cwd=str(RAIZ), capture_output=True, timeout=600)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")

    for tela in ("titulo", "menu"):
        # VRAM: os tiles do texto (APERTE START, NOVO JOGO, CONTINUAR, seta) = PNG
        vram = (cap_nova / f"{tela}.vram").read_bytes()
        assert vram[VRAM_TEXTO] == png, tela
        # coluna de pixels mais à esquerda do 1.º sprite do APERTE START (tiles 0x3E8 e
        # 0x3E9, à esquerda do A): vazia (nibble alto do 1.º byte de cada linha)
        assert all(vram[t * 32 + 4 * lin] >> 4 == 0
                   for t in (0x3E8, 0x3E9) for lin in range(8)), tela
        assert (cap_base / f"{tela}.vram").read_bytes()[VRAM_TEXTO] != png
        with Image.open(cap_base / f"{tela}.png") as a, Image.open(cap_nova / f"{tela}.png") as b:
            a.load()
            b.load()
            # o logo e o resto da tela não mudam; o texto (visível nesse quadro) muda
            assert _fora_da_caixa(a, b), tela
            assert _dentro_da_caixa(a) != _dentro_da_caixa(b), tela
    # na tela: o 1.º sprite do APERTE START começa em x = 173 − 128 = 45, y = 251 − 128 =
    # 123; no menu não há sprite ali, então essa coluna do título = a do menu (só fundo)
    with Image.open(cap_nova / "titulo.png") as t, Image.open(cap_nova / "menu.png") as m:
        pt, pm = t.convert("RGB").load(), m.convert("RGB").load()
        assert [pt[45, y] for y in range(123, 139)] == [pm[45, y] for y in range(123, 139)]


# ------------------------------------------------------- tiles de cada texto (sprites)

# Roda num processo à parte (o emulador da sessão está preso à ROM base sem alteração):
# lê na tabela de sprites do VRAM os tiles 0x3C0–0x41F usados no título, no menu sem jogo
# salvo e no menu com jogo salvo. Para ter o save, a entrada 0 da tabela de diálogos vira
# a da estalagem (dialogo.046): no NEW GAME o jogador aceita a diária e o jogo grava;
# depois o console reinicia (a SRAM fica) e o menu mostra CONTINUE.
_SCRIPT_SPRITES = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador
from ferramentas.emulador.vram_cenas import regs_do_estado

def tiles(emu):
    regs = regs_do_estado(emu.salvar_estado())
    vram = emu.vram()
    h40 = bool(regs[12] & 1)
    end = (regs[5] & (0x7E if h40 else 0x7F)) << 9
    i, vistos, res = 0, set(), set()
    while i not in vistos and i < (80 if h40 else 64):
        vistos.add(i)
        e = end + 8 * i
        tam, link = vram[e + 2], vram[e + 3] & 0x7F
        t = int.from_bytes(vram[e + 4:e + 6], "big") & 0x7FF
        x = int.from_bytes(vram[e + 6:e + 8], "big") & 0x1FF
        n = (((tam >> 2) & 3) + 1) * ((tam & 3) + 1)
        if x and 0x3C0 <= t < 0x420:
            res.update(range(t, t + n))
        if link == 0:
            break
        i = link
    return res

def ver(emu, quadros=8, passo=10):     # o texto pisca: junta vários quadros
    vistos = set()
    for _ in range(quadros):
        emu.avancar(passo)
        vistos |= tiles(emu)
    return sorted(vistos)

emu = Emulador(CORE_PADRAO, Path(sys.argv[2]))
res = {}
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(100)
res["titulo"] = ver(emu)
emu.avancar(2, {"start"})
res["menu"] = ver(emu)
emu.avancar(2, {"start"}); emu.avancar(600)
for _ in range(10):                    # estalagem: C em cada página (SIM = 1.ª opção)
    emu.avancar(2, {"c"}); emu.avancar(600)
emu._lib.retro_reset()
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240); emu.avancar(2, {"start"})
res["menu_salvo"] = ver(emu)
emu.fechar()
print(json.dumps(res))
'''


def _faixas_hex(tiles) -> list[tuple[int, int]]:
    faixas = []
    for t in sorted(tiles):
        if faixas and faixas[-1][1] == t - 1:
            faixas[-1] = (faixas[-1][0], t)
        else:
            faixas.append((t, t))
    return faixas


def test_tiles_de_cada_texto_do_titulo_no_jogo(rom_base, caminho_rom_base, tmp_path):
    from ferramentas import graficos
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    rom = bytearray(rom_base)
    tab = int.from_bytes(rom[0x1CC14:0x1CC18], "big")
    rom[tab:tab + 3] = rom[tab + 3 * 46:tab + 3 * 46 + 3]
    arq = tmp_path / "estalagem.bin"
    arq.write_bytes(rom)
    script = tmp_path / "sprites.py"
    script.write_text(_SCRIPT_SPRITES, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(RAIZ), str(arq)], cwd=str(RAIZ),
                       capture_output=True, timeout=900)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    import json
    vistos = {k: set(v) for k, v in json.loads(r.stdout.decode().splitlines()[-1]).items()}

    def tiles(texto):
        return {t for a, b in graficos.SPRITES_TITULO[texto] for t in range(a, b + 1)}

    assert vistos["titulo"] == tiles("APERTE START")
    assert vistos["menu"] == tiles("NOVO JOGO") | tiles("seta")
    assert vistos["menu_salvo"] - vistos["menu"] == tiles("CONTINUAR")
    assert _faixas_hex(tiles("CONTINUAR")) == [(0x3D4, 0x3E7)]
    assert _faixas_hex(tiles("APERTE START")) == [(0x3E8, 0x3FF), (0x404, 0x413),
                                                  (0x416, 0x417)]


def test_faixas_do_titulo_documentadas():
    """Docstring de graficos.py, README e mapa-rom.md citam as mesmas faixas."""
    from ferramentas import graficos

    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    mapa = (RAIZ / "docs" / "tecnico" / "mapa-rom.md").read_text(encoding="utf-8")
    todos = set()
    for texto, faixas in graficos.SPRITES_TITULO.items():
        for a, b in faixas:
            assert not todos & set(range(a, b + 1)), texto      # faixas disjuntas
            todos |= set(range(a, b + 1))
            tiles = f"0x{a:03X}–0x{b:03X}"
            ca, cb = (a - 0x3C0) // 2, (b - 0x3C0) // 2
            colunas = f"colunas {ca}–{cb}" if ca != cb else f"coluna {ca}"
            assert tiles in graficos.__doc__ and colunas in graficos.__doc__, texto
            assert tiles in mapa, (texto, tiles)
            assert colunas in readme, (texto, colunas)
    assert todos <= set(range(0x3C0, 0x420))
