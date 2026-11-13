"""Itens gráficos (título, placas, final): blocos de ``0x41000`` <-> PNG em ``graficos/``.

Cada item de ``config/graficos.yaml`` é uma lista de blocos da tabela de
gráficos (32 tiles cada; ver ``compressao.py`` e docs/tecnico/mapa-rom.md §8), um PNG
editável e um YAML de metadados:

- ``importar-tiles --origem <ROM> --item <nome>`` lê os blocos da ROM de origem do item
  (``origem.sha1`` confere), aplica os retoques do projeto (``RETOQUES``) e grava o PNG e
  os metadados. Item sem ``origem`` (o título) não é importado: o PNG versionado é a
  arte do projeto, editada à mão;
- ``etapa_graficos`` (build) recomprime no formato do item só os blocos que diferem da
  ROM base; cabe no lugar original → grava no lugar; senão vai para a região livre
  compartilhada (``espaco.py``, depois do texto e da fonte) e a entrada é reapontada.

Disposição do PNG (``disposicao`` no item): ``sprite`` (padrão, o título, abaixo) ou
``fundo`` (cenário e final: cada bloco são 2 linhas de 16 tiles na ordem do bloco, os
blocos empilhados; ``bloco_para_folha``). Nos itens ``fundo`` a origem é a ROM base, e as
letras novas são os ``RETOQUES`` do projeto: "HOT" nas placas das estalagens, "SAÍDA" na
placa de saída, os tiles novos de "FIM"/"CONTINUA..." no final (o tilemap do final muda
pelos patches ``final.*``) e "FIM DE JOGO" no game over (bloco ``0xFF``, mesmo
tilemap). Ver docs/tecnico/mapa-rom.md §8, "Texto desenhado em tiles".

Os textos da tela de título são **sprites** de 2 tiles de altura com os tiles em ordem
de coluna (tile ``2c`` em cima, ``2c+1`` embaixo). Por isso o PNG tem 2 linhas de tiles
e uma coluna de tiles por coluna de sprite: o texto aparece legível, como na tela.

Item ``titulo`` (blocos ``0x166–0x168`` = slots 30–32 do título, tiles ``0x3C0–0x41F``).
Coluna ``c`` do PNG = tiles ``0x3C0 + 2c`` e ``0x3C0 + 2c + 1``. Tiles de cada texto, lidos
na tabela de sprites do VRAM (``SPRITES_TITULO``; ``test_tiles_de_cada_texto_do_titulo_no_jogo``):

- colunas 0–9 (tiles ``0x3C0–0x3D3``): "NOVO JOGO" no lugar de "NEW GAME" (sprites
  26–28 do menu, 80 pixels);
- colunas 10–19 (``0x3D4–0x3E7``): "CONTINUAR" (sprites 29–31 do menu, 80 pixels; só
  aparece com jogo salvo);
- colunas 20–31 (``0x3E8–0x3FF``), colunas 34–41 (``0x404–0x413``) e coluna 43
  (``0x416–0x417``): "APERTE START" no lugar de "PRESS START BUTTON" (sprites 26–31 do
  título, 168 pixels: 5 sprites de 4 colunas e o último de 1, na coluna 43);
- colunas 32–33 (``0x400–0x403``): a seta do menu (sprite 32 do menu), no meio dos
  tiles do APERTE START;
- colunas 42 (``0x414–0x415``) e 44–47 (``0x418–0x41F``): sem uso na tela.

O PNG do título é arte do projeto, editada à mão: letras condensadas (traço de 6 pixels,
passo de 8) com 1 pixel de contorno (índice 1). O "CONTINUAR" cabe inteiro nas colunas
10–19: o contorno do R não pode cair no pixel 160 (coluna 20, o 1.º tile do APERTE
START), senão vira um traço à esquerda do A na tela do título.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .compressao import (TABELA_GRAFICOS, TAMANHO_BLOCO, TIPO_00, TIPO_CRU, TIPO_HUFFMAN,
                         TIPO_VAZIO, ErroCompressao, comprimir, descomprimir, escrever_entrada,
                         ler_entrada)
from .config import ErroConfig, Projeto
from .espaco import ErroEspaco, regiao_livre
from .fonte import PALETA_EXIBICAO
from .tiles import ErroTiles, png_para_tiles, tiles_para_png

ARQ_CONFIG = Path("config") / "graficos.yaml"
BYTES_TILE = 32
TILES_BLOCO = TAMANHO_BLOCO // BYTES_TILE        # 32
ALTURA_TILES = 2                                 # sprites de 2 tiles de altura
FORMATOS = {"02": TIPO_HUFFMAN, "01": TIPO_CRU}
#: disposição do PNG: "sprite" (colunas de 2 tiles, ordem de sprite; título) ou "fundo"
#: (cada bloco = 2 linhas de 16 tiles em ordem de bloco, blocos empilhados; cenário)
DISPOSICOES = ("sprite", "fundo")
TILES_LINHA_FUNDO = 16


#: Tiles de cada texto do item ``titulo`` (faixas inclusivas), lidos na tabela de sprites
#: do VRAM no título, no menu e no menu com jogo salvo (ver a docstring do módulo).
SPRITES_TITULO: dict[str, tuple[tuple[int, int], ...]] = {
    "NOVO JOGO": ((0x3C0, 0x3D3),),
    "CONTINUAR": ((0x3D4, 0x3E7),),
    "APERTE START": ((0x3E8, 0x3FF), (0x404, 0x413), (0x416, 0x417)),
    "seta": ((0x400, 0x403),),
}


class ErroGraficos(Exception):
    pass


# ---------------------------------------------------------------- tiles <-> faixa

def tiles_para_faixa(tiles: bytes) -> list[list[int]]:
    """Tiles em ordem de sprite (coluna de 2) -> pixels (16 linhas)."""
    n = len(tiles) // BYTES_TILE
    colunas = n // ALTURA_TILES
    px = [[0] * (colunas * 8) for _ in range(ALTURA_TILES * 8)]
    for t in range(n):
        c, lin = divmod(t, ALTURA_TILES)
        for y in range(8):
            for x in range(8):
                b = tiles[t * BYTES_TILE + y * 4 + x // 2]
                px[lin * 8 + y][c * 8 + x] = b >> 4 if x % 2 == 0 else b & 15
    return px


def faixa_para_tiles(px: list[list[int]]) -> bytes:
    colunas = len(px[0]) // 8
    saida = bytearray()
    for t in range(colunas * ALTURA_TILES):
        c, lin = divmod(t, ALTURA_TILES)
        for y in range(8):
            linha = px[lin * 8 + y]
            for x in range(0, 8, 2):
                saida.append((linha[c * 8 + x] << 4) | linha[c * 8 + x + 1])
    return bytes(saida)


def _ordem_png(tiles: bytes) -> bytes:
    """Ordem de sprite -> ordem de linhas do PNG (linha 0 = tiles de cima)."""
    n = len(tiles) // BYTES_TILE
    ordem = [2 * c + lin for lin in range(ALTURA_TILES) for c in range(n // ALTURA_TILES)]
    return b"".join(tiles[t * BYTES_TILE:(t + 1) * BYTES_TILE] for t in ordem)


def _ordem_sprite(tiles_png: bytes) -> bytes:
    n = len(tiles_png) // BYTES_TILE
    colunas = n // ALTURA_TILES
    saida = bytearray()
    for t in range(n):
        c, lin = divmod(t, ALTURA_TILES)
        i = lin * colunas + c
        saida += tiles_png[i * BYTES_TILE:(i + 1) * BYTES_TILE]
    return bytes(saida)


# ---------------------------------------------------------------- cenário (disposição "fundo")

def bloco_para_folha(dados: bytes) -> list[list[int]]:
    """1 KB (32 tiles) -> pixels de 16 linhas × 128: tile ``t`` na coluna ``t % 16`` e na
    linha ``t // 16`` de tiles (a mesma folha do PNG)."""
    px = [[0] * (TILES_LINHA_FUNDO * 8) for _ in range(16)]
    for t in range(TILES_BLOCO):
        tx, ty = (t % TILES_LINHA_FUNDO) * 8, (t // TILES_LINHA_FUNDO) * 8
        for y in range(8):
            for x in range(8):
                b = dados[t * BYTES_TILE + y * 4 + x // 2]
                px[ty + y][tx + x] = b >> 4 if x % 2 == 0 else b & 15
    return px


def folha_para_bloco(px: list[list[int]]) -> bytes:
    saida = bytearray()
    for t in range(TILES_BLOCO):
        tx, ty = (t % TILES_LINHA_FUNDO) * 8, (t // TILES_LINHA_FUNDO) * 8
        for y in range(8):
            linha = px[ty + y]
            for x in range(0, 8, 2):
                saida.append((linha[tx + x] << 4) | linha[tx + x + 1])
    return bytes(saida)


@dataclass(frozen=True)
class Retoque:
    """Pixels desenhados na folha de um bloco (16 × 128, ``bloco_para_folha``): cada
    caractere de ``linhas`` é um pixel a partir de (``x``, ``y``); ``-`` mantém o pixel da
    origem e os outros caracteres viram o índice de cor dado em ``cores``."""

    descricao: str
    bloco: int
    x: int
    y: int
    linhas: tuple[str, ...]
    cores: tuple[tuple[str, int], ...]


def aplicar_retoque(r: Retoque, folha: list[list[int]]) -> None:
    cores = dict(r.cores)
    for dy, linha in enumerate(r.linhas):
        for dx, ch in enumerate(linha):
            if ch == "-":
                continue
            if ch not in cores:
                raise ErroGraficos(f"retoque {r.descricao!r}: caractere {ch!r} sem cor")
            x, y = r.x + dx, r.y + dy
            if not (0 <= y < len(folha) and 0 <= x < len(folha[0])):
                raise ErroGraficos(f"retoque {r.descricao!r}: pixel ({x}, {y}) fora do bloco")
            folha[y][x] = cores[ch]


#: Placa "HOT" (no lugar de "INN"), 12 × 4 pixels nas colunas 98–109 da folha (tiles
#: 12–13 / 28–29): H e T de 3 pixels, O de 4, 1 pixel entre as letras. ``#`` = letra,
#: ``s`` = sombra à direita da haste do T (como a do I de "INN"), ``.`` = fundo da placa.
HOT = ("#.#..##..###",
       "###.#..#..#s",
       "#.#.#..#..#s",
       "#.#..##...#s")


def _hot(bloco: int, y: int, letra: int, sombra: int, fundo: int) -> Retoque:
    return Retoque(f"HOT no lugar de INN (bloco 0x{bloco:X}, linhas {y}-{y + 3})", bloco, 98,
                   y, HOT, (("#", letra), ("s", sombra), (".", fundo)))


#: Placa "SAÍDA" (no lugar de "EXIT"), pixels 73–100 da folha do bloco 0xB8 (tiles 25–28,
#: embaixo): letras de 7 linhas (8–14), hastes de 2 pixels e traços de 1, com a sombra
#: (cor 9) logo abaixo de cada traço, como no "EXIT"; S e D de 5 pixels, A de 6, Í de 2,
#: 1 pixel entre as letras, nas mesmas colunas do "EXIT" (73–100). O acento fica nas
#: linhas 5–6 do tile de cima (tile 10, que só aparece acima da placa), com a linha 7
#: livre.
SAIDA = (
    "-------------##-------------",
    "------------##s-------------",
    "----------------------------",
    "#####..####..##.####...####.",
    "##sss.##ss##.##.##s##.##ss##",
    "##....##..##.##.##.##.##..##",
    "#####.######.##.##.##.######",
    "sss##.##ss##.##.##.##.##ss##",
    "...##.##..##.##.##.##.##..##",
    "#####.##..##.##.####s.##..##",
    "sssss.ss..ss.ss.ssss..ss..ss",
)

#: Final (bloco 0x2EE, tiles 16–31 = 0x450–0x45F no slot 34): letras de 16 × 16 pixels
#: montadas no tilemap com espelhamento. "FIM" e "CONTINUA..." reaproveitam T, I, C, O, N
#: e U do THE END / TO BE CONTINUED; o A é um alto novo (espelhado) sobre a base do H. Os
#: tiles que só o E, o B e o D usavam viram o alto do M e o do A (espelhados), o pé do F
#: e o ponto.
_TILE_M = (
    "........",
    ".###....",
    ".####...",
    ".#####..",
    ".######.",
    ".#######",
    ".####.##",
    ".####..#",
)
_TILE_A = (
    "........",
    "......##",
    ".....###",
    "....####",
    "...####.",
    "..####..",
    ".####...",
    ".####...",
)
_TILE_F_ESQ = (".#######",) + (".####...",) * 6 + ("........",)
_TILE_F_DIR = ("######..",) + ("........",) * 7
_TILE_PONTO = ("........",) * 4 + ("..###...",) * 3 + ("........",)
_BRANCO = ((".", 0), ("#", 15))


def _tile_final(tile: int, linhas: tuple[str, ...], nome: str) -> Retoque:
    t = tile - 0x440   # slot 34 = tiles 0x440–0x45F
    return Retoque(f"tile 0x{tile:X}: {nome}", 0x2EE, (t % TILES_LINHA_FUNDO) * 8,
                   (t // TILES_LINHA_FUNDO) * 8, linhas, _BRANCO)


#: Game over (bloco 0xFF no slot 9 = tiles 0x120–0x13F; tilemap de 16 × 2 tiles nas
#: colunas 8–23 das linhas 12–13, sem mudança): "FIM DE JOGO" no lugar de "GAME OVER".
#: Cada letra é a máscara do traço (12 × 14 pixels; o I tem 2 de largura) numa célula com
#: 1 pixel de contorno (índice 1, preto como o fundo) em volta: o contorno são os 8
#: vizinhos do traço, e a cor do traço depende só da linha (degradê vermelho, laranja,
#: amarelo e branco no meio, simétrico). G, M, E e O são as máscaras do original, pixel a
#: pixel; F (o E sem a barra de baixo), I (a haste), D (o lado esquerdo do E com a curva
#: do O) e J (a haste da direita com a curva do O embaixo, 10 pixels de largura) são do
#: projeto.
_LETRAS_GO: dict[str, tuple[str, ...]] = {
    "G": ("...######...", "..########..", ".###....###.", "###......###", "##........##",
          "##..........", "##..........", "##...#######", "##...#######", "##........##",
          "###......###", ".###....###.", "..########..", "...######..."),
    "M": ("#..........#", "##........##", "###......###", "####....####", "#####..#####",
          "##.######.##", "##..####..##", "##...##...##", "##........##", "##........##",
          "##........##", "##........##", "##........##", "##........##"),
    "E": ("############", "############", "##..........", "##..........", "##..........",
          "##..........", "##########..", "##########..", "##..........", "##..........",
          "##..........", "##..........", "############", "############"),
    "O": ("...######...", "..########..", ".###....###.", "###......###", "##........##",
          "##........##", "##........##", "##........##", "##........##", "##........##",
          "###......###", ".###....###.", "..########..", "...######..."),
    "F": ("############", "############", "##..........", "##..........", "##..........",
          "##..........", "##########..", "##########..", "##..........", "##..........",
          "##..........", "##..........", "##..........", "##.........."),
    "I": ("##",) * 14,
    "D": ("#########...", "##########..", "##......###.", "##.......###", "##........##",
          "##........##", "##........##", "##........##", "##........##", "##........##",
          "##.......###", "##......###.", "##########..", "#########..."),
    "J": ("........##", "........##", "........##", "........##", "........##",
          "........##", "........##", "........##", "##......##", "##......##",
          "###....###", ".###..###.", "..######..", "...####..."),
}
#: cor do traço por linha da folha (linhas 0 e 15 são só contorno)
_DEGRADE_GO = "-bbcc99ff99ccbb-"
#: "FIM DE JOGO" em 128 pixels com os espaços do original: células de 14 pixels (I: 4,
#: J: 12), 1 pixel entre letras e 4 entre palavras. Ocupa os pixels 0–127 (o original,
#: 3–124); a 1.ª e a última coluna são só contorno, preto como o fundo.
TEXTO_GO = "FIM DE JOGO"
ESPACO_LETRA_GO, ESPACO_PALAVRA_GO = 1, 4


def compor_game_over(texto: str = TEXTO_GO, x0: int = 0) -> tuple[str, ...]:
    """16 linhas × 128 caracteres da folha do bloco 0xFF: ``.`` fundo, ``o`` contorno e o
    índice de cor do traço (``b``, ``c``, ``9``, ``f``)."""
    traco = [[False] * 128 for _ in range(16)]
    x = x0
    for ch in texto:
        if ch == " ":
            x += ESPACO_PALAVRA_GO - ESPACO_LETRA_GO
            continue
        mascara = _LETRAS_GO[ch]
        largura = len(mascara[0]) + 2
        if x + largura > 128:
            raise ErroGraficos(f"{texto!r} não cabe em 128 pixels")
        for y, linha in enumerate(mascara):
            for dx, c in enumerate(linha):
                if c == "#":
                    traco[y + 1][x + 1 + dx] = True
        x += largura + ESPACO_LETRA_GO
    saida = []
    for y in range(16):
        linha = []
        for x in range(128):
            if traco[y][x]:
                linha.append(_DEGRADE_GO[y])
            elif any(0 <= y + dy < 16 and 0 <= x + dx < 128 and traco[y + dy][x + dx]
                     for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                linha.append("o")
            else:
                linha.append(".")
        saida.append("".join(linha))
    return tuple(saida)


_CORES_GO = ((".", 0), ("o", 1), ("b", 0xB), ("c", 0xC), ("9", 0x9), ("f", 0xF))


#: Retoques do projeto por item (disposição "fundo").
RETOQUES: dict[str, list[Retoque]] = {
    "placas_hot": [
        _hot(0x37, 6, 0x6, 0xC, 0x1),
        _hot(0x88, 9, 0x6, 0xC, 0x1),
        _hot(0xD3, 7, 0x6, 0xC, 0x1),
        _hot(0x10B, 9, 0x5, 0x3, 0x2),
        _hot(0x11C, 2, 0x9, 0xC, 0x1),
    ],
    "placa_saida": [
        Retoque("SAÍDA no lugar de EXIT (acento nas linhas 5-6, letras nas 8-15)", 0xB8, 73, 5,
                SAIDA, (("#", 0xA), ("s", 0x9), (".", 0x1))),
    ],
    "final": [
        _tile_final(0x453, _TILE_M, "alto do M (era um tile do E e do B)"),
        _tile_final(0x454, _TILE_F_ESQ, "pé do F, esquerda (era um tile do B)"),
        _tile_final(0x455, _TILE_F_DIR, "pé do F, direita (era um tile do B)"),
        _tile_final(0x45C, _TILE_PONTO, "ponto das reticências (era um tile do E)"),
        _tile_final(0x45D, _TILE_A, "alto do A (era um tile do D)"),
    ],
    "game_over": [
        Retoque("FIM DE JOGO no lugar de GAME OVER (bloco inteiro: G, M, E e O do original; "
                "F, I, D e J do projeto)", 0xFF, 0, 0, compor_game_over(), _CORES_GO),
    ],
}


# ---------------------------------------------------------------- configuração

@dataclass
class Item:
    nome: str
    blocos: list[int]
    formato: str
    png: Path
    meta: Path
    origem: dict = field(default_factory=dict)
    disposicao: str = "sprite"

    @property
    def tiles(self) -> int:
        return TILES_BLOCO * len(self.blocos)


def carregar_itens(raiz: Path) -> list[Item]:
    """Itens de ``config/graficos.yaml`` (sem o arquivo: nenhum)."""
    arq = Path(raiz) / ARQ_CONFIG
    if not arq.is_file():
        return []
    try:
        dados = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ErroConfig(f"{arq.name}: YAML inválido: {e}") from None
    itens_cfg = dados.get("itens") if isinstance(dados, dict) else None
    if not isinstance(itens_cfg, dict):
        raise ErroConfig(f"{arq.name}: falta o mapeamento 'itens'")
    itens = []
    for nome, cfg in itens_cfg.items():
        if not isinstance(cfg, dict):
            raise ErroConfig(f"{arq.name}: item {nome!r} inválido")
        blocos = cfg.get("blocos")
        if (not isinstance(blocos, list) or not blocos
                or not all(isinstance(b, int) and 0 <= b < 768 for b in blocos)):
            raise ErroConfig(f"{arq.name}: {nome}: 'blocos' deve ser uma lista de blocos 0–767")
        formato = str(cfg.get("formato", "02"))
        if formato not in FORMATOS:
            raise ErroConfig(f"{arq.name}: {nome}: formato {formato!r} (use 02 ou 01)")
        for chave in ("png", "meta"):
            if not isinstance(cfg.get(chave), str):
                raise ErroConfig(f"{arq.name}: {nome}: falta '{chave}'")
        disposicao = str(cfg.get("disposicao", "sprite"))
        if disposicao not in DISPOSICOES:
            raise ErroConfig(f"{arq.name}: {nome}: disposicao {disposicao!r} "
                             f"(use {' ou '.join(DISPOSICOES)})")
        itens.append(Item(str(nome), blocos, formato, Path(cfg["png"]), Path(cfg["meta"]),
                          cfg.get("origem") or {}, disposicao))
    return itens


def item_por_nome(raiz: Path, nome: str) -> Item:
    for item in carregar_itens(raiz):
        if item.nome == nome:
            return item
    raise ErroConfig(f"{ARQ_CONFIG.as_posix()}: item {nome!r} não existe")


# ---------------------------------------------------------------- leitura de blocos

def ler_bloco(rom: bytes, bloco: int) -> tuple[bytes, int, int, int]:
    """(1 KB, tipo, endereço, bytes ocupados na ROM) do bloco, como ``0x6BC4`` o expande."""
    tipo, end = ler_entrada(rom, bloco)
    if tipo == TIPO_VAZIO:
        return bytes(TAMANHO_BLOCO), tipo, end, 0
    if tipo == TIPO_CRU:
        if end + TAMANHO_BLOCO > len(rom):
            raise ErroGraficos(f"bloco {bloco:#x}: cru em {end:#x} passa do fim da ROM")
        return bytes(rom[end:end + TAMANHO_BLOCO]), tipo, end, TAMANHO_BLOCO
    if tipo == TIPO_00:
        raise ErroGraficos(f"bloco {bloco:#x}: tipo 00 (rotina 0x6BFC) não implementado")
    try:
        dados, consumidos = descomprimir(rom, end)
    except ErroCompressao as e:
        raise ErroGraficos(f"bloco {bloco:#x}: {e}") from None
    return dados, tipo, end, consumidos


def tiles_da_rom(rom: bytes, item: Item) -> bytes:
    return b"".join(ler_bloco(rom, b)[0] for b in item.blocos)


def _tamanho_png(item: Item) -> tuple[int, int]:
    if item.disposicao == "fundo":
        return TILES_LINHA_FUNDO * 8, len(item.blocos) * (TILES_BLOCO // TILES_LINHA_FUNDO) * 8
    return item.tiles // ALTURA_TILES * 8, ALTURA_TILES * 8


def ler_png(caminho: Path, item: Item) -> bytes:
    """Tiles do PNG do item na ordem dos blocos na ROM (sprite: desfaz as colunas)."""
    caminho = Path(caminho)
    w, h = _tamanho_png(item)
    try:
        from PIL import Image

        with Image.open(caminho) as img:
            tamanho = img.size
        if tamanho != (w, h):
            raise ErroGraficos(f"{caminho.name}: o PNG do item {item.nome} deve ter {w}x{h} "
                               f"pixels, não {tamanho[0]}x{tamanho[1]}")
        tiles = png_para_tiles(caminho, item.tiles)
        return tiles if item.disposicao == "fundo" else _ordem_sprite(tiles)
    except ErroTiles as e:
        raise ErroGraficos(str(e)) from None
    except OSError as e:
        raise ErroGraficos(f"{caminho.name}: {e}") from None


# ---------------------------------------------------------------- importação

def _hex(v: int) -> str:
    return f"0x{v:X}"


def importar_tiles(origem: bytes, base: bytes, item: Item, raiz: Path) -> list[str]:
    """Grava o PNG e os metadados do item a partir da ROM de origem; devolve avisos."""
    if not item.origem:
        raise ErroGraficos(f"item {item.nome!r} sem 'origem' em {ARQ_CONFIG.as_posix()}: o "
                           "PNG é arte do projeto, editada à mão (não se importa)")
    sha = hashlib.sha1(origem).hexdigest()
    esperado = str(item.origem.get("sha1", "")).lower()
    if esperado and sha != esperado:
        raise ErroGraficos(f"ROM de origem com sha1 {sha}, esperado {esperado} "
                           f"({item.origem.get('arquivo', '?')})")
    if item.disposicao == "fundo":
        return _importar_fundo(origem, base, item, raiz)
    tiles = tiles_da_rom(origem, item)
    png = Path(raiz) / item.png
    png.parent.mkdir(parents=True, exist_ok=True)
    tiles_para_png(_ordem_png(tiles), item.tiles // ALTURA_TILES, PALETA_EXIBICAO, png)
    meta = Path(raiz) / item.meta
    meta.write_text(_meta(origem, base, item), encoding="utf-8", newline="\n")
    return []


def _importar_fundo(origem: bytes, base: bytes, item: Item, raiz: Path) -> list[str]:
    retoques = RETOQUES.get(item.nome, [])
    soltos = [r.descricao for r in retoques if r.bloco not in item.blocos]
    if soltos:
        raise ErroGraficos(f"{item.nome}: retoque em bloco fora do item: {soltos[0]}")
    tiles = bytearray()
    for b in item.blocos:
        folha = bloco_para_folha(ler_bloco(origem, b)[0])
        for r in retoques:
            if r.bloco == b:
                aplicar_retoque(r, folha)
        tiles += folha_para_bloco(folha)
    png = Path(raiz) / item.png
    png.parent.mkdir(parents=True, exist_ok=True)
    tiles_para_png(bytes(tiles), TILES_LINHA_FUNDO, PALETA_EXIBICAO, png)
    (Path(raiz) / item.meta).write_text(_meta_fundo(origem, base, item, retoques),
                                        encoding="utf-8", newline="\n")
    return []


def _meta_fundo(origem: bytes, base: bytes, item: Item, retoques: list[Retoque]) -> str:
    descricao = item.origem.get("descricao", "")
    linhas_bloco = TILES_BLOCO // TILES_LINHA_FUNDO
    linhas = [
        f"# Item gráfico '{item.nome}' (ferramentas/graficos.py). Gerado por",
        f"# 'python -m ferramentas importar-tiles --origem <ROM> --item {item.nome}'; edite o",
        "# PNG, não este arquivo.",
        "#",
        f"# PNG indexado de {TILES_LINHA_FUNDO}x{linhas_bloco * len(item.blocos)} tiles: cada "
        f"bloco são {linhas_bloco} linhas de {TILES_LINHA_FUNDO} tiles",
        "# em ordem de bloco (tile t na coluna t % 16), blocos empilhados na ordem abaixo.",
        "# Índices de cor da paleta da cena. Ver docs/tecnico/mapa-rom.md §8.",
        "origem:",
        f"  descricao: \"{descricao}\"",
        f"  arquivo: \"{item.origem.get('arquivo', '')}\"",
        f"  rom_sha1: {hashlib.sha1(origem).hexdigest()}",
        f"  base_sha1: {hashlib.sha1(base).hexdigest()}",
        f"  tabela: {_hex(TABELA_GRAFICOS)}",
        f"png: {item.png.name}",
        f"formato: \"{item.formato}\"",
        "disposicao: fundo",
        f"tiles: {item.tiles}",
        "blocos:",
    ]
    for i, b in enumerate(item.blocos):
        _, t_b, end_b, tam_b = ler_bloco(base, b)
        linhas.append(
            f"  - {{bloco: {_hex(b)}, ponteiro: {_hex(TABELA_GRAFICOS + 4 * b)}, "
            f"base: {{tipo: \"{t_b:02X}\", endereco: {_hex(end_b)}, bytes: {tam_b}}}, "
            f"linhas_png: \"{i * linhas_bloco}-{(i + 1) * linhas_bloco - 1}\"}}")
    linhas.append("partes:")
    for r in retoques:
        i = item.blocos.index(r.bloco)
        largura = max(len(l) for l in r.linhas)
        y0 = i * linhas_bloco * 8 + r.y
        linhas += [f"  - retoque: \"{r.descricao}\"",
                   f"    bloco: {_hex(r.bloco)}",
                   f"    pixels_png: \"x {r.x}-{r.x + largura - 1}, "
                   f"y {y0}-{y0 + len(r.linhas) - 1}\"",
                   "    origem: \"desenho do projeto\""]
    linhas += ["  - texto: \"restante (fora dos retoques acima)\"",
               f"    origem: \"{descricao}\""]
    return "\n".join(linhas) + "\n"


def _meta(origem: bytes, base: bytes, item: Item) -> str:
    descricao = item.origem.get("descricao", "")
    linhas = [
        f"# Item gráfico '{item.nome}' (ferramentas/graficos.py). Gerado por",
        f"# 'python -m ferramentas importar-tiles --origem <ROM> --item {item.nome}'; edite o",
        "# PNG, não este arquivo.",
        "#",
        f"# PNG indexado de {item.tiles // ALTURA_TILES}x{ALTURA_TILES} tiles: cada coluna de "
        "tiles é uma coluna de sprite",
        "# (tile 2c em cima, 2c+1 embaixo, em ordem de bloco). Índices 0 = transparente,",
        "# 1 = contorno, 15 = traço. Ver docs/tecnico/mapa-rom.md §8.",
        "origem:",
        f"  descricao: \"{descricao}\"",
        f"  arquivo: \"{item.origem.get('arquivo', '')}\"",
        f"  rom_sha1: {hashlib.sha1(origem).hexdigest()}",
        f"  base_sha1: {hashlib.sha1(base).hexdigest()}",
        f"  tabela: {_hex(TABELA_GRAFICOS)}",
        f"png: {item.png.name}",
        f"formato: \"{item.formato}\"",
        f"tiles: {item.tiles}",
        "blocos:",
    ]
    for i, b in enumerate(item.blocos):
        _, t_o, end_o, _ = ler_bloco(origem, b)
        _, t_b, end_b, tam_b = ler_bloco(base, b)
        primeiro = TILES_BLOCO * i
        linhas.append(
            f"  - {{bloco: {_hex(b)}, ponteiro: {_hex(TABELA_GRAFICOS + 4 * b)}, "
            f"origem: {{tipo: \"{t_o:02X}\", endereco: {_hex(end_o)}}}, "
            f"base: {{tipo: \"{t_b:02X}\", endereco: {_hex(end_b)}, bytes: {tam_b}}}, "
            f"colunas_png: \"{primeiro // 2}-{(primeiro + TILES_BLOCO) // 2 - 1}\"}}")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------- build

@dataclass
class Alteracao:
    item: str
    bloco: int
    dados: bytes          # comprimido (02) ou cru (01)
    tipo: int
    end_original: int
    tam_original: int

    @property
    def no_lugar(self) -> bool:
        # cru só fica no lugar se o original já era cru (endereço par, 1 KB)
        return len(self.dados) <= self.tam_original and (
            self.tipo != TIPO_CRU or self.end_original % 2 == 0)


def planejar(rom: bytes, raiz: Path) -> list[Alteracao]:
    """Blocos de todos os itens cujo PNG difere da ROM, já no formato do item."""
    alteracoes = []
    for item in carregar_itens(raiz):
        arq = Path(raiz) / item.png
        if not arq.is_file():
            continue
        tiles = ler_png(arq, item)
        for i, b in enumerate(item.blocos):
            original, tipo, end, ocupados = ler_bloco(rom, b)
            novo = tiles[i * TAMANHO_BLOCO:(i + 1) * TAMANHO_BLOCO]
            if novo == original:
                continue
            fmt = FORMATOS[item.formato]
            dados = comprimir(novo) if fmt == TIPO_HUFFMAN else novo
            alteracoes.append(Alteracao(item.nome, b, dados, fmt, end,
                                        ocupados if tipo in (TIPO_HUFFMAN, TIPO_CRU) else 0))
    return alteracoes


def bytes_realocados(alteracoes: list[Alteracao]) -> int:
    """Bytes na região livre (sem o padding de alinhamento dos crus)."""
    return sum(len(a.dados) for a in alteracoes if not a.no_lugar)


def etapa_graficos(rom: bytearray, projeto: Projeto) -> None:
    """Etapa do build: reinsere os blocos dos itens de ``config/graficos.yaml`` que mudaram."""
    alteracoes = planejar(bytes(rom), projeto.raiz)
    if not alteracoes:
        return
    destinos: dict[int, int] = {}
    if any(not a.no_lugar for a in alteracoes):
        regiao = regiao_livre(projeto, len(rom))
        antes = len(regiao.usos)
        try:
            for a in alteracoes:
                if not a.no_lugar:
                    destinos[a.bloco] = regiao.reservar(
                        f"{a.item} bloco {a.bloco:#x}", len(a.dados),
                        2 if a.tipo == TIPO_CRU else 1)
        except ErroEspaco as e:
            del regiao.usos[antes:]
            raise ErroEspaco(f"{e} (os gráficos não cabem: reduza as mudanças)") from None
    for a in alteracoes:
        if a.no_lugar:
            rom[a.end_original:a.end_original + len(a.dados)] = a.dados
            escrever_entrada(rom, a.bloco, a.tipo, a.end_original)
        else:
            end = destinos[a.bloco]
            rom[end:end + len(a.dados)] = a.dados
            escrever_entrada(rom, a.bloco, a.tipo, end)
