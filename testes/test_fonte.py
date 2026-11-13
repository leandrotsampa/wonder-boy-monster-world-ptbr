"""Fonte editável (graficos/fonte/fonte.png <-> blocos 0–7 da tabela 0x41000)."""

import random
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest
import yaml
from PIL import Image

from ferramentas import cli
from ferramentas.cli import main
from ferramentas.compressao import (TABELA_GRAFICOS, TAMANHO_BLOCO, TIPO_HUFFMAN, comprimir,
                                    descomprimir, escrever_entrada, ler_entrada)
from ferramentas.config import Projeto
from ferramentas.espaco import ErroEspaco, RegiaoLivre
from ferramentas.fonte import (ARQ_META, ARQ_PNG, GLIFOS_ACENTOS, HUD_CODIGOS_BAIXO,
                               HUD_CODIGOS_CIMA, LARGURA_TILES, TILES, ErroFonte, etapa_fonte,
                               extrair_fonte, fonte_da_rom, ler_png, tiles_hud)
from ferramentas.tabela import Tabela
from ferramentas.verificacao import Contexto, checar_glifos

RAIZ = Path(__file__).resolve().parent.parent
BYTES_FONTE = TILES * 32


def _cfg() -> dict:
    return yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))


def _gravar_png(tiles: bytes, caminho: Path) -> None:
    from ferramentas.fonte import PALETA_EXIBICAO
    from ferramentas.tiles import tiles_para_png

    caminho.parent.mkdir(parents=True, exist_ok=True)
    tiles_para_png(tiles, LARGURA_TILES, PALETA_EXIBICAO, caminho)


def _projeto(raiz: Path, regiao=(0xA4C80, 0xC0000)) -> Projeto:
    (raiz / "config").mkdir(parents=True, exist_ok=True)
    (raiz / "config" / "texto.yaml").write_text(
        f"regiao_destino: [{regiao[0]:#x}, {regiao[1]:#x}]\n", encoding="utf-8")
    return Projeto(raiz=raiz, rom={})


# ------------------------------------------------------------- ROM sintética

def _tile(valor: int) -> bytes:
    return bytes([valor * 0x11]) * 32


def _rom_sintetica() -> tuple[bytearray, bytes]:
    """ROM com 8 blocos tipo 02 da fonte (tiles lisos, bem compressíveis) em 0x41C00+."""
    rom = bytearray(b"\xFF" * 0x48000)
    fonte = bytearray()
    pos = 0x41C00
    for b in range(8):
        dados = b"".join(_tile(1 if t % 3 else 15) for t in range(32))
        fonte += dados
        comp = comprimir(dados)
        rom[pos:pos + len(comp)] = comp
        escrever_entrada(rom, b, TIPO_HUFFMAN, pos)
        pos += len(comp)
    return rom, bytes(fonte)


def test_fonte_da_rom_sintetica():
    rom, fonte = _rom_sintetica()
    assert fonte_da_rom(rom) == fonte


def test_fonte_maior_realoca(tmp_path):
    rom, fonte = _rom_sintetica()
    original = bytes(rom)
    rnd = random.Random(3)
    novo = bytearray(fonte)
    # bloco 3 vira ruído (incompressível: não cabe no lugar)
    novo[3 * TAMANHO_BLOCO:4 * TAMANHO_BLOCO] = bytes(rnd.randrange(256)
                                                      for _ in range(TAMANHO_BLOCO))
    projeto = _projeto(tmp_path, (0x44000, 0x48000))
    _gravar_png(bytes(novo), tmp_path / ARQ_PNG)
    # o texto (etapa anterior) já ocupou o começo da região: a fonte vai depois dele
    projeto.regiao = RegiaoLivre(0x44000, 0x48000)
    projeto.regiao.reservar("texto", 0x101, alinhamento=2)
    etapa_fonte(rom, projeto)
    assert ler_entrada(rom, 3) == (TIPO_HUFFMAN, 0x44101)  # tipo 02 aceita endereço ímpar
    assert fonte_da_rom(rom) == bytes(novo)
    usos = {nome: (ini, tam) for nome, ini, tam in projeto.regiao.usos}
    assert usos["fonte bloco 3"][0] == 0x44101
    # os outros blocos não mudaram: nem a entrada nem os bytes
    for b in (0, 1, 2, 4, 5, 6, 7):
        assert ler_entrada(rom, b) == ler_entrada(original, b)
    fim = 0x44101 + usos["fonte bloco 3"][1]
    assert rom[0x41C00:0x44000] == original[0x41C00:0x44000]
    assert rom[fim:] == original[fim:]


def test_fonte_menor_fica_no_lugar(tmp_path):
    rom, fonte = _rom_sintetica()
    original = bytes(rom)
    novo = bytearray(fonte)
    novo[2 * TAMANHO_BLOCO:3 * TAMANHO_BLOCO] = _tile(1) * 32  # bloco 2 liso: menor
    projeto = _projeto(tmp_path, (0x44000, 0x48000))
    _gravar_png(bytes(novo), tmp_path / ARQ_PNG)
    etapa_fonte(rom, projeto)
    assert ler_entrada(rom, 2) == ler_entrada(original, 2)
    assert fonte_da_rom(rom) == bytes(novo)
    assert rom[0x44000:] == original[0x44000:]


def test_fonte_sem_espaco_erro(tmp_path):
    rom, fonte = _rom_sintetica()
    original = bytes(rom)
    rnd = random.Random(4)
    novo = bytes(rnd.randrange(256) for _ in range(BYTES_FONTE))
    projeto = _projeto(tmp_path, (0x44000, 0x44100))
    _gravar_png(novo, tmp_path / ARQ_PNG)
    with pytest.raises(ErroEspaco, match="fonte"):
        etapa_fonte(rom, projeto)
    assert rom == original  # nada gravado pela metade


def test_etapa_fonte_sem_png_nao_faz_nada(tmp_path):
    rom, _ = _rom_sintetica()
    original = bytes(rom)
    etapa_fonte(rom, _projeto(tmp_path))
    assert rom == original


def test_png_tamanho_errado(tmp_path):
    img = Image.new("P", (64, 64))
    img.save(tmp_path / "f.png")
    with pytest.raises(ErroFonte, match="128x128"):
        ler_png(tmp_path / "f.png")


def test_fonte_bloco_nao_huffman(tmp_path):
    rom, fonte = _rom_sintetica()
    escrever_entrada(rom, 6, 0x01, 0x42000)
    with pytest.raises(ErroFonte, match="bloco 6"):
        fonte_da_rom(rom)


def test_espaco_regiao():
    r = RegiaoLivre(0x100, 0x110)
    assert r.reservar("a", 3) == 0x100
    assert r.reservar("b", 2, alinhamento=2) == 0x104
    assert r.usado == 6
    with pytest.raises(ErroEspaco, match="c"):
        r.reservar("c", 11)
    assert r.reservar("d", 10) == 0x106


# --------------------------------------------------------------- ROM real

def test_fonte_ida_e_volta(rom_base, tmp_path):
    projeto = _projeto(tmp_path)
    extrair_fonte(rom_base, {}, tmp_path / ARQ_PNG.parent, desenhos=False)
    assert ler_png(tmp_path / ARQ_PNG) == fonte_da_rom(rom_base)
    meta = yaml.safe_load((tmp_path / ARQ_META).read_text(encoding="utf-8"))
    assert [b["blob"] for b in meta["blocos"]][:3] == [0x41C00, 0x41CCF, 0x41DEB]
    # PNG sem mudanças: a ROM fica byte a byte igual
    rom = bytearray(rom_base)
    etapa_fonte(rom, projeto)
    assert rom == rom_base
    # um pixel trocado no bloco 2: só ele é recomprimido, e descomprime certo
    img = Image.open(tmp_path / ARQ_PNG)
    img.putpixel((0, 4 * 8), 15)
    img.save(tmp_path / ARQ_PNG)
    novo = ler_png(tmp_path / ARQ_PNG)
    assert novo != fonte_da_rom(rom_base)
    etapa_fonte(rom, projeto)
    assert fonte_da_rom(rom) == novo
    diferentes = [b for b in range(8) if rom[TABELA_GRAFICOS + 4 * b:TABELA_GRAFICOS + 4 * b + 4]
                  != rom_base[TABELA_GRAFICOS + 4 * b:TABELA_GRAFICOS + 4 * b + 4]]
    assert diferentes in ([], [2])


def test_extrair_fonte_reproduz_png_versionado(rom_base, tmp_path):
    """extrair_fonte (ROM base + GLIFOS_ACENTOS + rótulo do HUD) gera exatamente o PNG e o
    fonte.yaml versionados."""
    cfg = _cfg()
    extrair_fonte(rom_base, cfg, tmp_path)
    tiles = ler_png(tmp_path / ARQ_PNG.name)
    assert tiles == ler_png(RAIZ / ARQ_PNG)
    base = fonte_da_rom(rom_base)
    codigos = set(cfg["acentos"].values())
    hud = list(HUD_CODIGOS_CIMA) + list(HUD_CODIGOS_BAIXO)
    tiles_base = tiles_hud(base)
    for t in range(TILES):
        fatia = slice(32 * t, 32 * t + 32)
        if t in hud:   # rótulo MOEDAS do HUD: letras da própria fonte, subidas (fonte.py)
            i = hud.index(t)
            assert tiles[fatia] == tiles_base[32 * i:32 * i + 32], hex(t)
        elif t not in codigos:
            assert tiles[fatia] == base[fatia], hex(t)
    assert ((tmp_path / ARQ_META.name).read_text(encoding="utf-8")
            == (RAIZ / ARQ_META).read_text(encoding="utf-8"))
    meta = yaml.safe_load((tmp_path / ARQ_META.name).read_text(encoding="utf-8"))
    assert set(meta["glifos"]) == codigos
    assert all("projeto" in g["origem"] for g in meta["glifos"].values())


def test_glifos_acentos_desenhados():
    """Um glifo de 8 x 8 (traço e fundo) para cada acento da config; o acento fica nas
    linhas de cima (Ú: agudo nas 2 primeiras)."""
    assert set(GLIFOS_ACENTOS) == set(_cfg()["acentos"])
    for ch, linhas in GLIFOS_ACENTOS.items():
        assert len(linhas) == 8 and all(len(l) == 8 and set(l) <= set("#.") for l in linhas), ch
    linhas = GLIFOS_ACENTOS["Ú"]
    assert "#" in linhas[0] and "#" in linhas[1]


def test_png_versionado_confere(rom_base):
    """graficos/fonte/fonte.png = fonte da ROM base + os 24 glifos dos acentos + os 12
    tiles do rótulo MOEDAS do HUD."""
    tiles = ler_png(RAIZ / ARQ_PNG)
    base = fonte_da_rom(rom_base)
    codigos = set(_cfg()["acentos"].values())
    for t in range(TILES):
        fatia = slice(32 * t, 32 * t + 32)
        if t in codigos or t in HUD_CODIGOS_CIMA or t in HUD_CODIGOS_BAIXO:
            assert tiles[fatia] != base[fatia] and len(set(tiles[fatia])) > 1, hex(t)
        else:
            assert tiles[fatia] == base[fatia], hex(t)
    # nenhum acento ficou igual à letra sem acento
    tabela = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")
    for ch, cod in _cfg()["acentos"].items():
        base_ch = unicodedata.normalize("NFD", ch)[0]
        b = tabela.codificar(base_ch)[0]
        assert tiles[32 * cod:32 * cod + 32] != tiles[32 * b:32 * b + 32], ch
    meta = yaml.safe_load((RAIZ / ARQ_META).read_text(encoding="utf-8"))
    assert set(meta["glifos"]) == codigos


def test_extrair_gera_fonte_se_nao_existe(rom_base, tmp_path, capsys):
    for rel in ("config/rom.yaml", "config/texto.yaml", "traducao/tabela.tbl"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAIZ / rel, tmp_path / rel)
    arq_rom = tmp_path / "base.bin"
    arq_rom.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "extrair", "--rom", str(arq_rom)]) == 0
    # só com a ROM base: sem aviso, e a fonte gerada é a versionada (acentos e HUD)
    assert not [l for l in capsys.readouterr().out.splitlines() if l.startswith("AVISO")]
    png = tmp_path / ARQ_PNG
    assert png.is_file() and (tmp_path / ARQ_META).is_file()
    assert ler_png(png) == ler_png(RAIZ / ARQ_PNG)
    # já existe: não é sobrescrito (é o arquivo editado à mão)
    png.write_bytes(b"editado")
    assert main(["--raiz", str(tmp_path), "extrair", "--rom", str(arq_rom)]) == 0
    assert png.read_bytes() == b"editado"


# ----------------------------------------------------------------- glifos

def _ctx(tbl: str, tiles: bytes, pts: dict[str, str] | None = None) -> Contexto:
    from ferramentas.textos import Entrada

    textos = {"t": [Entrada(id=k, en="x", pt=v, status="traduzido") for k, v in (pts or {}).items()]}
    ctx = Contexto(tabela=Tabela.de_texto(tbl), textos=textos, glossario=[])
    ctx.extra["fonte"] = tiles
    return ctx


def _fonte_teste() -> bytearray:
    tiles = bytearray(_tile(1) * TILES)
    for t in (0x41, 0x42, 0x5C, 0x85, 0xA4):
        tiles[32 * t:32 * t + 32] = bytes([0x1F]) * 32  # glifo "desenhado"
    return tiles


def test_glifo_faltando_erro():
    achados = checar_glifos(_ctx("20= \n41=A\n42=B\n43=C\n", bytes(_fonte_teste())))
    assert [(a.nivel, a.checagem) for a in achados] == [("erro", "glifos")]
    assert "'C'" in achados[0].mensagem and "43" in achados[0].mensagem


def test_glifo_ok():
    assert checar_glifos(_ctx("20= \n41=A\n42=B\nA4=Á\n09=[linha]\n", bytes(_fonte_teste()))) == []


def test_glifo_em_tile_invisivel_erro():
    achados = checar_glifos(_ctx("41=A\n85=ã\n5C=\\\n", bytes(_fonte_teste())))
    msgs = " ".join(a.mensagem for a in achados)
    assert len(achados) == 2
    assert "0x85" in msgs and "0x235" in msgs   # slot 4 trocado pelo bloco 0x235
    assert "0x5C" in msgs and "zera" in msgs


def test_glifos_sem_png_nao_checa():
    ctx = _ctx("43=C\n", b"")
    del ctx.extra["fonte"]
    assert checar_glifos(ctx) == []


def test_glifos_projeto_real():
    """A tabela versionada só usa tiles desenhados e visíveis na fonte versionada."""
    ctx = _ctx((RAIZ / "traducao" / "tabela.tbl").read_text(encoding="utf-8"),
               ler_png(RAIZ / ARQ_PNG))
    assert checar_glifos(ctx) == []


def test_acentos_codificam():
    tabela = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")
    assert tabela.codificar("ação") == bytes([0x61, 0xBC, 0xB2, 0x6F])
    for ch, cod in _cfg()["acentos"].items():
        assert tabela.codificar(ch) == bytes([cod]), ch
        assert tabela.decodificar(bytes([cod])) == ch


def test_tabela_nao_usa_tiles_invisiveis():
    tabela = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")
    for ch in tabela.caracteres():
        for b in tabela.codificar(ch):
            assert not 0x80 <= b <= 0x9F, (ch, hex(b))
            assert b not in (0x5C, 0x5D, 0x5F), (ch, hex(b))


# ------------------------------------------------------------- build + emulador

PT_TESTE = "ÁÉÍÓÚ ãõç[linha]ÀÂÃÊÔÇ[linha]àáâéêíóôú[linha][cor][nome:00][/cor]"
LINHA_1 = "ÁÉÍÓÚãõç"


def _copiar_projeto(destino: Path, rom_base: bytes) -> Path:
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, destino / rel)
    (destino / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", destino / "dados" / "scripts")
    arq_rom = destino / "base.bin"
    arq_rom.write_bytes(rom_base)
    return arq_rom


def _padrao(tile: bytes) -> list[int]:
    """Linhas do tile como máscaras de 8 bits (1 = traço, índice 15)."""
    linhas = []
    for y in range(8):
        m = 0
        for x in range(8):
            b = tile[y * 4 + x // 2]
            m = (m << 1) | (((b >> 4) if x % 2 == 0 else b & 15) == 15)
        linhas.append(m)
    return linhas


def _achar(img: Image.Image, padrao: list[int]) -> list[tuple[int, int]]:
    cinza = img.convert("L")
    w, h = cinza.size
    px = cinza.load()
    claro = [[px[x, y] > 128 for x in range(w)] for y in range(h)]
    mascaras = []
    for y in range(h):
        linha = [0] * max(0, w - 7)
        for x in range(w - 7):
            m = 0
            for dx in range(8):
                m = (m << 1) | claro[y][x + dx]
            linha[x] = m
        mascaras.append(linha)
    return [(x, y) for y in range(h - 7) for x in range(w - 7)
            if all(mascaras[y + dy][x] == padrao[dy] for dy in range(8))]


def test_jogo_mostra_acento(rom_base, caminho_rom_base, tmp_path):
    from ferramentas.emulador.libretro import CORE_PADRAO
    from ferramentas.textos import carregar_textos, salvar_textos

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    arq_rom = _copiar_projeto(tmp_path, rom_base)
    arq = tmp_path / "traducao" / "textos" / "dialogos.yaml"
    entradas = carregar_textos(arq)
    (e,) = [x for x in entradas if x.id == "dialogo.000.t01"]  # 1.ª fala do NEW GAME
    e.pt, e.status = PT_TESTE, "traduzido"
    salvar_textos(arq, entradas)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq_rom)]) == 0
    nova = (tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()
    png = ler_png(tmp_path / ARQ_PNG)
    assert fonte_da_rom(nova) == png
    # o bloco 5 (acentos) foi recomprimido (árvore de até MAX_FOLHAS folhas)
    _, end5 = ler_entrada(nova, 5)
    assert nova[end5:end5 + 64] != rom_base[end5:end5 + 64]

    # o emulador da sessão está preso à ROM base (uma instância por processo):
    # a ROM nova roda num processo à parte
    capturas = RAIZ / "build" / "capturas" / "fonte_acentos"
    r = subprocess.run([sys.executable, "-m", "ferramentas.emulador",
                        str(RAIZ / "roteiros" / "dialogo.yaml"), "--rom", str(tmp_path / "build" /
                        "wbmw-ptbr.bin"), "--destino", str(capturas)],
                       cwd=str(RAIZ), capture_output=True, timeout=600)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    vram = (capturas / "dialogo.vram").read_bytes()
    # VRAM tile n = 32n bytes; os tiles dos acentos são os do PNG (decodificados pelo 68000)
    for cod in _cfg()["acentos"].values():
        assert vram[32 * cod:32 * cod + 32] == png[32 * cod:32 * cod + 32], hex(cod)
    assert vram[0xA0 * 32:0xC0 * 32] == png[0xA0 * 32:0xC0 * 32]
    # e aparecem na tela: cada glifo da 1.ª linha está na captura
    tabela = Tabela.carregar(tmp_path / "traducao" / "tabela.tbl")
    with Image.open(capturas / "dialogo.png") as img:
        img.load()
        posicoes = []
        for ch in LINHA_1:
            cod = tabela.codificar(ch)[0]
            achados = _achar(img, _padrao(png[32 * cod:32 * cod + 32]))
            assert achados, f"{ch} ({cod:#x}) não aparece na tela"
            posicoes.append(achados[0])
    # na mesma linha, da esquerda para a direita
    assert len({y for _, y in posicoes}) == 1
    assert [x for x, _ in posicoes] == sorted(x for x, _ in posicoes)
