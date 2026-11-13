"""Fonte editável: blocos 0–7 da tabela ``0x41000`` <-> ``graficos/fonte/fonte.png``.

A fonte são os blocos 0–7 (tipo 02, Huffman + LZ; ver ``compressao.py``), 32 tiles
cada: código de caractere = índice do tile (``0x00–0xFF``). O PNG tem 16 × 16 tiles
(128 × 128 pixels, indexado): o bloco ``n`` são as linhas de tiles ``2n`` e ``2n+1``.

Atenção ao editar (docs/tecnico/vram.md):

- tiles ``0x80–0x9F`` (bloco 4) **não aparecem no jogo**: em toda cena com texto o
  slot 4 recebe o bloco ``0x235`` (HUD/efeitos). Ficam no PNG só como contexto;
- tiles ``0x5C``, ``0x5D`` e ``0x5F`` são zerados pelo jogo logo depois da carga;
- ``0xBE``/``0xBF`` são o tile de cima do prefixo ``FE``/``FF``;
- ``0xC0–0xC5``, ``0xD0``, ``0xFE`` e ``0xFF`` não são glifos: são gráficos de sprite
  (``TILES_EFEITO``; ``0xC0–0xC5``/``0xD0`` são as bolhas d'água) e têm de ficar como na
  base;
- ``0xC6–0xCB`` e ``0xD3–0xD8`` não são caracteres: são o rótulo "MOEDAS" do HUD em duas
  linhas de tiles (``HUD_*``, abaixo), impresso pela rotina do patch ``hud.moedas_rotina``
  (``config/patches.yaml``). Mudar os códigos exige mudar o patch.

``etapa_fonte`` só reinsere os blocos cujo conteúdo mudou: com o PNG igual à ROM, a
área da fonte fica byte a byte igual. Bloco recomprimido que cabe no lugar original
(≤ bytes que o original consome) é gravado no lugar; senão vai para a região livre
compartilhada (depois do texto) e a entrada da tabela é reapontada.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .compressao import (TABELA_GRAFICOS, TAMANHO_BLOCO, TIPO_HUFFMAN, ErroCompressao,
                         comprimir, descomprimir, escrever_entrada, ler_entrada)
from .config import Projeto
from .espaco import ErroEspaco, regiao_livre
from .tiles import ErroTiles, png_para_tiles, tiles_para_png

ARQ_PNG = Path("graficos") / "fonte" / "fonte.png"
ARQ_META = Path("graficos") / "fonte" / "fonte.yaml"
BLOCOS = tuple(range(8))
TILES = 32 * len(BLOCOS)            # 256
LARGURA_TILES = 16
BYTES_TILE = 32
#: tiles do bloco 4: no jogo o slot 4 recebe o bloco 0x235 (não são fonte)
TILES_INVISIVEIS = range(0x80, 0xA0)
#: tiles zerados pelo jogo depois da carga (¥ ] _ na fonte original)
TILES_ZERADOS = (0x5C, 0x5D, 0x5F)
#: tiles da faixa 0xA0-0xFF que não são glifos na fonte base (fundo transparente em vez do
#: fundo 1): gráficos de sprite carregados junto com a fonte. 0xC0-0xC5 e 0xD0 são as
#: bolhas d'água (sala 0x69: sprites com os tiles 0xC4, 0xC5 e 0xD0). A fonte do projeto
#: não pode alterá-los (testes/test_bolha.py).
TILES_EFEITO = (0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xD0, 0xFE, 0xFF)
#: paleta só para exibir/editar o PNG (o jogo usa a CRAM dele): 0 = magenta (vazio),
#: 1 = azul-escuro (fundo do glifo), 15 = branco (traço), 2–14 = tons de cinza.
PALETA_EXIBICAO = ([(255, 0, 255), (0, 0, 96)] + [(17 * i, 17 * i, 17 * i) for i in range(2, 15)]
                   + [(255, 255, 255)])


#: Glifos das letras acentuadas, desenhados pelo projeto no estilo da fonte original:
#: caractere -> 8 linhas de 8 pixels (``#`` = traço, 15; ``.`` = fundo, 1). O código de
#: cada um (o tile) vem de ``acentos`` em ``config/texto.yaml``.
GLIFOS_ACENTOS: dict[str, tuple[str, ...]] = {
    "À": ("..#.....", "...#....", "..####..", ".##..##.",
          ".#...##.", "###.###.", ".######.", "##...##."),
    "Ã": ("...#.#..", "..#.#...", "..####..", ".##..##.",
          ".#...##.", "###.###.", ".######.", "##...##."),
    "Â": ("...##...", "..#..#..", "..####..", ".##..##.",
          ".#...##.", "###.###.", ".######.", "##...##."),
    "Á": (".....#..", "....#...", "..####..", ".##..##.",
          ".#...##.", "###.###.", ".######.", "##...##."),
    "É": ("...#....", "..#.....", "######..", "##..##..",
          "##......", "####....", "##...#..", "#######."),
    "Ê": ("..##....", ".#..#...", "######..", "##..##..",
          "##......", "####....", "##...#..", "#######."),
    "Í": ("....#...", "...#....", ".####...", "..###...",
          "..##....", "..##....", ".###....", ".####..."),
    "Ó": ("....#...", "...#....", "..###...", ".##.##..",
          "##.#.##.", "##.#.##.", ".##.##..", "..###..."),
    "Õ": ("..##..#.", ".#..##..", ".#####..", "##...##.",
          "##.#.##.", "##.#.##.", "##...##.", ".#####.."),
    "Ô": ("..###...", ".#...#..", "..###...", ".##.##..",
          "##.#.##.", "##.#.##.", ".##.##..", "..###..."),
    "Ú": ("....#...", "...#....", ".##...#.", "###..##.",
          "##....#.", "##....#.", "###..##.", ".#####.."),
    "Ç": (".#####..", "###..##.", "##......", "##......",
          "###..##.", ".#####..", "...##...", "..##...."),
    "à": ("..#.....", "...#....", "..####..", ".....##.",
          "..#####.", ".###.##.", ".##..##.", "..#####."),
    "ã": ("...#.#..", "..#.#...", "..####..", ".....##.",
          "..#####.", ".###.##.", ".##..##.", "..#####."),
    "â": ("...##...", "..#..#..", "..####..", ".....##.",
          "..#####.", ".###.##.", ".##..##.", "..#####."),
    "á": (".....#..", "....#...", "..####..", ".....##.",
          "..#####.", ".###.##.", ".##..##.", "..#####."),
    "é": ("....#...", "...#....", "..####..", ".##..##.",
          ".######.", ".##..#..", ".###....", "..####.."),
    "ê": ("...##...", "..#..#..", "..####..", ".##..##.",
          ".######.", ".##..#..", ".###....", "..####.."),
    "í": (".....#..", "....#...", "........", "....#...",
          "...##...", "...##...", "...##...", "...##..."),
    "ó": (".....#..", "....#...", "..####..", ".##..##.",
          ".#.#..#.", ".#.#..#.", ".##..##.", "..####.."),
    "õ": ("...#.#..", "..#.#...", "..####..", ".##..##.",
          ".#.#..#.", ".#.#..#.", ".##..##.", "..####.."),
    "ô": ("...##...", "..#..#..", "..####..", ".##..##.",
          ".#.#..#.", ".#.#..#.", ".##..##.", "..####.."),
    "ú": (".....#..", "....#...", ".##...#.", ".##..##.",
          ".##..##.", ".##..##.", ".##..##.", "..####.."),
    "ç": ("........", "..####..", ".##..##.", ".#..##..",
          ".##.....", ".######.", "...##...", ".###...."),
}
#: Notas de desenho de alguns glifos (os outros: "desenho do projeto").
NOTAS_GLIFOS: dict[str, str] = {
    "Õ": "desenho do projeto: O da fonte original em 6 linhas + til ondulado de 2 linhas",
    "Ú": "desenho do projeto: U da fonte original em 6 linhas + agudo do Ó",
    "Ç": "desenho do projeto: C da fonte original em 6 linhas + cedilha separada",
}


#: Rótulo do quadro do ouro no HUD (docs/tecnico/mapa-rom.md §8, "HUD"). As letras são
#: os tiles da própria fonte, subidas ``HUD_SUBIDA`` pixels para não encostar no valor
#: (que fica na linha de tiles de baixo): ficam divididas entre a linha 4 da janela
#: (``HUD_CODIGOS_CIMA``, as ``HUD_SUBIDA`` linhas de cima de cada letra, embaixo do tile) e a
#: linha 5 (``HUD_CODIGOS_BAIXO``, o resto, com ``HUD_SUBIDA`` linhas livres embaixo).
HUD_TEXTO = "MOEDAS"
HUD_SUBIDA = 3
#: Os códigos são kana do slot 6 (sempre carregado, vram.md §3.1) que nenhum texto da ROM
#: usa e que não são TILES_EFEITO: 0xC0-0xC5 e 0xD0 são as bolhas d'água, e as strings
#: japonesas que sobraram no inglês usam 0xCF, 0xD1, 0xD2 e 0xDD (vram.md §3.2).
HUD_CODIGOS_CIMA = tuple(range(0xC6, 0xC6 + len(HUD_TEXTO)))     # 0xC6-0xCB
HUD_CODIGOS_BAIXO = tuple(range(0xD3, 0xD3 + len(HUD_TEXTO)))    # 0xD3-0xD8
#: patch de config/patches.yaml que imprime o rótulo (com ele, ``verificar`` exige os tiles)
PATCH_HUD = "hud.moedas_rotina"


def faixas_hud() -> str:
    """Os códigos do rótulo do HUD em texto ("0xC6-0xCB e 0xD3-0xD8")."""
    return " e ".join(f"0x{c[0]:02X}-0x{c[-1]:02X}" for c in (HUD_CODIGOS_CIMA, HUD_CODIGOS_BAIXO))


def tiles_hud(fonte: bytes) -> bytes:
    """Os tiles do rótulo do HUD (cima, depois baixo) a partir dos glifos de ``fonte``."""
    n = len(HUD_TEXTO)
    px = [[1] * (8 * n) for _ in range(16)]
    for i, ch in enumerate(HUD_TEXTO):
        tile = fonte[BYTES_TILE * ord(ch):BYTES_TILE * (ord(ch) + 1)]
        for y in range(8):
            for x in range(8):
                b = tile[4 * y + x // 2]
                px[8 - HUD_SUBIDA + y][8 * i + x] = b >> 4 if x % 2 == 0 else b & 15
    saida = bytearray()
    for lin in range(2):
        for c in range(n):
            for y in range(8):
                linha = px[8 * lin + y]
                saida += bytes((linha[8 * c + x] << 4) | linha[8 * c + x + 1]
                               for x in range(0, 8, 2))
    return bytes(saida)


def _tile_de_linhas(linhas: tuple[str, ...]) -> bytes:
    saida = bytearray()
    for linha in linhas:
        px = [15 if c == "#" else 1 for c in linha]
        saida += bytes((px[x] << 4) | px[x + 1] for x in range(0, 8, 2))
    return bytes(saida)


class ErroFonte(Exception):
    pass


def _bloco_da_rom(rom: bytes, bloco: int) -> tuple[bytes, int, int]:
    """(1 KB descomprimido, endereço do blob, bytes consumidos) do bloco da fonte."""
    tipo, end = ler_entrada(rom, bloco)
    if tipo != TIPO_HUFFMAN:
        raise ErroFonte(f"bloco {bloco} da fonte não é tipo 02 (tipo {tipo:#x}); "
                        "a ROM não é a esperada")
    try:
        dados, consumidos = descomprimir(rom, end)
    except ErroCompressao as e:
        raise ErroFonte(f"bloco {bloco} da fonte: {e}") from None
    return dados, end, consumidos


def fonte_da_rom(rom: bytes) -> bytes:
    """Os 256 tiles (8 KB) da fonte descomprimidos."""
    return b"".join(_bloco_da_rom(rom, b)[0] for b in BLOCOS)


def ler_png(caminho: Path) -> bytes:
    caminho = Path(caminho)
    w, h = LARGURA_TILES * 8, TILES // LARGURA_TILES * 8
    try:
        from PIL import Image

        with Image.open(caminho) as img:
            tamanho = img.size
        if tamanho != (w, h):
            raise ErroFonte(f"{caminho.name}: o PNG da fonte deve ter {w}x{h} pixels "
                            f"({LARGURA_TILES}x{TILES // LARGURA_TILES} tiles), não "
                            f"{tamanho[0]}x{tamanho[1]}")
        return png_para_tiles(caminho, TILES)
    except ErroTiles as e:
        raise ErroFonte(str(e)) from None
    except OSError as e:
        raise ErroFonte(f"{caminho.name}: {e}") from None


def tile_vazio(tiles: bytes, codigo: int) -> bool:
    """Tile de uma cor só (sem traço)."""
    tile = tiles[BYTES_TILE * codigo:BYTES_TILE * (codigo + 1)]
    return len({b >> 4 for b in tile} | {b & 15 for b in tile}) <= 1


# ------------------------------------------------------------------ extração

def _hex(v: int, digitos: int = 0) -> str:
    return f"0x{v:0{digitos}X}"


def extrair_fonte(rom: bytes, cfg: dict, destino: Path, desenhos: bool = True) -> None:
    """Grava ``fonte.png`` e ``fonte.yaml`` em ``destino`` a partir da ROM base.

    Com ``desenhos`` (o padrão), aplica os desenhos do projeto: os glifos de
    ``GLIFOS_ACENTOS`` nos códigos de ``cfg["acentos"]`` e o rótulo "MOEDAS" do HUD nos
    tiles ``HUD_CODIGOS_*`` (``tiles_hud``). Sem ``desenhos``: a fonte da base, sem mudança.
    """
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    tiles = bytearray(fonte_da_rom(rom))
    glifos: list[tuple[int, str, str]] = []
    acentos = (cfg.get("acentos") or {}) if desenhos else {}
    for ch, cod in sorted(acentos.items(), key=lambda kv: kv[1]):
        if ch not in GLIFOS_ACENTOS:
            raise ErroFonte(f"sem glifo desenhado para {ch!r} ({_hex(cod, 2)}) "
                            "em GLIFOS_ACENTOS")
        tiles[BYTES_TILE * cod:BYTES_TILE * (cod + 1)] = _tile_de_linhas(GLIFOS_ACENTOS[ch])
        glifos.append((cod, ch, NOTAS_GLIFOS.get(ch, "desenho do projeto")))
    if desenhos:   # rótulo MOEDAS do HUD (HUD_*), com as letras da própria fonte
        novos = tiles_hud(bytes(tiles))
        for i, cod in enumerate(HUD_CODIGOS_CIMA + HUD_CODIGOS_BAIXO):
            tiles[BYTES_TILE * cod:BYTES_TILE * (cod + 1)] = \
                novos[BYTES_TILE * i:BYTES_TILE * (i + 1)]
    tiles_para_png(bytes(tiles), LARGURA_TILES, PALETA_EXIBICAO, destino / ARQ_PNG.name)
    (destino / ARQ_META.name).write_text(_meta(rom, glifos, desenhos),
                                         encoding="utf-8", newline="\n")


def _meta(rom: bytes, glifos: list[tuple[int, str, str]], hud: bool = False) -> str:
    linhas = [
        "# Fonte editável (ferramentas/fonte.py). Gerado por 'python -m ferramentas extrair'",
        "# quando graficos/fonte/fonte.png não existe; edite o PNG, não este arquivo (os",
        "# metadados descrevem a ROM base e a origem dos glifos novos).",
        "#",
        "# PNG indexado de 16x16 tiles (128x128): tile n = código de caractere n; o bloco b",
        "# são as linhas de tiles 2b e 2b+1. Use só os índices 0-15 (fundo 1, traço 15).",
        "# - tiles 0x80-0x9F (bloco 4) NÃO aparecem no jogo: o slot 4 recebe o bloco 0x235",
        "#   (HUD/efeitos) em toda cena com texto. Estão aqui só como contexto;",
        "# - tiles 0x5C, 0x5D e 0x5F são zerados pelo jogo depois da carga;",
        "# - 0xBE/0xBF são o tile de cima do prefixo FE/FF;",
        "# - " + ", ".join(_hex(t, 2) for t in TILES_EFEITO) + " não são glifos: são gráficos",
        "#   de sprite (bolhas d'água em 0xC0-0xC5 e 0xD0); deixe-os como estão;",
        f"# - {faixas_hud()} (se 'hud' abaixo) são o rótulo MOEDAS do HUD, não caracteres.",
        "# Ver docs/tecnico/vram.md e docs/tecnico/mapa-rom.md §8.",
        "origem:",
        f"  rom_sha1: {hashlib.sha1(rom).hexdigest()}",
        f"  tabela: {_hex(TABELA_GRAFICOS)}",
    ]
    linhas += [
        f"png: {ARQ_PNG.name}",
        f"largura_tiles: {LARGURA_TILES}",
        f"tiles: {TILES}",
        "blocos:",
    ]
    for b in BLOCOS:
        _, end, consumidos = _bloco_da_rom(rom, b)
        linhas.append(f"  - {{bloco: {b}, ponteiro: {_hex(TABELA_GRAFICOS + 4 * b)}, "
                      f"blob: {_hex(end)}, bytes: {consumidos}, "
                      f"tiles: \"{_hex(32 * b, 2)}-{_hex(32 * b + 31, 2)}\"}}")
    linhas.append("tiles_invisiveis: \"0x80-0x9F\"")
    linhas.append("tiles_zerados: [" + ", ".join(_hex(t, 2) for t in TILES_ZERADOS) + "]")
    linhas.append("tiles_efeito: [" + ", ".join(_hex(t, 2) for t in TILES_EFEITO) + "]")
    linhas.append("paleta_exibicao: [" + ", ".join(
        f"\"#{r:02X}{g:02X}{b:02X}\"" for r, g, b in PALETA_EXIBICAO) + "]")
    if glifos:
        linhas.append("glifos:")
        for cod, ch, origem in glifos:
            linhas.append(f"  {_hex(cod, 2)}: {{caractere: \"{ch}\", origem: \"{origem}\"}}")
    else:
        linhas.append("glifos: {}")
    if hud:
        linhas += [
            "hud:",
            f"  texto: \"{HUD_TEXTO}\"",
            f"  subida: {HUD_SUBIDA}",
            "  cima: [" + ", ".join(_hex(c, 2) for c in HUD_CODIGOS_CIMA) + "]",
            "  baixo: [" + ", ".join(_hex(c, 2) for c in HUD_CODIGOS_BAIXO) + "]",
            "  janela: \"linhas 4 (cima) e 5 (baixo), colunas 23-28 (patch hud.moedas_rotina)\"",
            "  origem: \"desenho do projeto: as letras da própria fonte, subidas "
            f"{HUD_SUBIDA} pixels e divididas entre duas linhas de tiles para não "
            "encostarem no valor\"",
        ]
    return "\n".join(linhas) + "\n"


# --------------------------------------------------------------------- build

@dataclass
class Alteracao:
    bloco: int
    comprimido: bytes
    end_original: int
    tam_original: int

    @property
    def no_lugar(self) -> bool:
        return len(self.comprimido) <= self.tam_original


def planejar(rom: bytes, tiles: bytes) -> list[Alteracao]:
    """Blocos cujo conteúdo difere da ROM, já recomprimidos."""
    if len(tiles) != TILES * BYTES_TILE:
        raise ErroFonte(f"a fonte deve ter {TILES} tiles, não {len(tiles) // BYTES_TILE}")
    alteracoes = []
    for b in BLOCOS:
        original, end, consumidos = _bloco_da_rom(rom, b)
        novo = tiles[b * TAMANHO_BLOCO:(b + 1) * TAMANHO_BLOCO]
        if novo != original:
            alteracoes.append(Alteracao(b, comprimir(novo), end, consumidos))
    return alteracoes


def bytes_realocados(alteracoes: list[Alteracao]) -> int:
    """Bytes que a fonte vai ocupar na região livre (tipo 02: sem alinhamento)."""
    return sum(len(a.comprimido) for a in alteracoes if not a.no_lugar)


def etapa_fonte(rom: bytearray, projeto: Projeto) -> None:
    """Etapa do build: reinsere os blocos da fonte que mudaram no PNG (sem PNG: nada)."""
    arq = projeto.raiz / ARQ_PNG
    if not arq.is_file():
        return
    alteracoes = planejar(bytes(rom), ler_png(arq))
    if not alteracoes:
        return
    regiao = regiao_livre(projeto, len(rom))
    # reserva tudo antes de gravar: sem espaço, a ROM não fica pela metade
    destinos, antes = {}, len(regiao.usos)
    for a in alteracoes:
        if not a.no_lugar:
            try:
                destinos[a.bloco] = regiao.reservar(f"fonte bloco {a.bloco}", len(a.comprimido))
            except ErroEspaco as e:
                del regiao.usos[antes:]
                raise ErroEspaco(f"{e} (o PNG da fonte não cabe: reduza as mudanças)") from None
    for a in alteracoes:
        if a.no_lugar:
            rom[a.end_original:a.end_original + len(a.comprimido)] = a.comprimido
        else:
            end = destinos[a.bloco]
            rom[end:end + len(a.comprimido)] = a.comprimido
            escrever_entrada(rom, a.bloco, TIPO_HUFFMAN, end)
