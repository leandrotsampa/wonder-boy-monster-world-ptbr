"""Relatório de revisão por lote: ``python -m ferramentas revisao --lote ID``.

Grava ``build/revisao/<ID>.html`` com, para cada entrada do lote (``traducao/lotes.yaml``),
onde aparece, quem fala, o original, a tradução e as páginas do ``pt`` desenhadas com a
fonte do jogo (``verificacao.paginas``: as mesmas regras de ``checar_largura`` e
``checar_linhas``). Com ``--capturas``, a ROM traduzida roda no emulador cada diálogo do
lote (a entrada 0 da tabela de diálogos trocada pela dele, só na ROM de teste) e as telas
em que o texto para entram no relatório. ``--lote todos`` gera ``todos.html``, um índice
com o progresso por arquivo e por status e os lotes.

Formato de ``traducao/lotes.yaml``::

    - id: piloto
      titulo: "Piloto: abertura, senhora, placa e loja"
      entradas:
        - {id: dialogo.000.t01, onde: "Abertura do NEW GAME", quem: Narrador, nota: ""}
        - {id: dialogo.002, onde: "Casa da senhora em Alsedo", quem: Senhora}
        - {id: b3.000, onde: Lojas, quem: Vendedor}

O ``id`` de uma entrada do lote é uma entrada (``dialogo.002.t01``), um diálogo inteiro
(``dialogo.002`` = todos os ``.tNN``) ou um script do banco 3 (``b3.000``).
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import yaml

from .tabela import Tabela
from .textos import STATUS, Entrada
from .verificacao import Contexto, Pagina, paginas

ARQ_LOTES = Path("traducao") / "lotes.yaml"
PASTA_SAIDA = Path("build") / "revisao"
LOTE_TODOS = "todos"
_ID_LOTE = re.compile(r"[A-Za-z0-9_.-]+")
_GRUPO = re.compile(r"(dialogo\.\d+|b3\.[0-9A-F]+)")
_TRECHO = re.compile(r"(.+)\.t\d+")       # dialogo.002.t01 -> dialogo.002

# janela desenhada: tiles de 8×8; cada linha de texto ocupa 16 px (tile de cima =
# prefixo/acento, tile de baixo = letra), como no jogo
_FUNDO_FONTE = {0, 1}                  # índices do PNG que não são traço
_COR_TEXTO = (238, 238, 238)
_COR_AMARELO = (238, 238, 0)
_COR_VARIAVEL, _FUNDO_VARIAVEL = (120, 220, 255), (0, 48, 96)
_COR_ERRO = (200, 40, 40)
_FUNDO_JANELA, _FUNDO_ROLA, _MOLDURA = (0, 0, 0), (72, 0, 0), (200, 200, 200)

# capturas: tabela de diálogos (entrada 0 = 1.º diálogo do NEW GAME) e o plano A, onde
# o jogo desenha a janela (64 × 32 células; moldura com os tiles 0x14/0x15/0x16)
PONTEIRO_DIALOGOS = 0x1CC14
PLANO_A, PLANO_COLUNAS, PLANO_LINHAS = 0xC000, 64, 32
TILE_CANTO, TILE_TOPO, TILE_LADO = 0x014, 0x015, 0x016
MAX_TELAS = 80
ARQ_TELAS = "telas.json"


class ErroRevisao(Exception):
    pass


# ------------------------------------------------------------------ lotes

def carregar_lotes(raiz: Path) -> list[dict]:
    """Lotes de ``traducao/lotes.yaml`` (``[]`` se o arquivo não existe)."""
    arq = Path(raiz) / ARQ_LOTES
    if not arq.is_file():
        return []
    try:
        dados = yaml.safe_load(arq.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as e:
        raise ErroRevisao(f"{ARQ_LOTES.as_posix()}: YAML inválido: {e}") from None
    if not isinstance(dados, list):
        raise ErroRevisao(f"{ARQ_LOTES.as_posix()}: o arquivo deve ser uma lista de lotes")
    vistos = set()
    for n, lote in enumerate(dados, 1):
        if not isinstance(lote, dict) or not isinstance(lote.get("entradas"), list):
            raise ErroRevisao(f"{ARQ_LOTES.as_posix()}: lote {n} precisa de 'id' e 'entradas'")
        id_ = str(lote.get("id", ""))
        if not _ID_LOTE.fullmatch(id_) or id_ == LOTE_TODOS or id_ in vistos:
            raise ErroRevisao(f"{ARQ_LOTES.as_posix()}: id de lote inválido ou repetido: "
                              f"{id_!r}")
        vistos.add(id_)
        for item in lote["entradas"]:
            if not isinstance(item, dict) or not item.get("id"):
                raise ErroRevisao(f"{ARQ_LOTES.as_posix()}: lote {id_}: entrada sem 'id': "
                                  f"{item!r}")
    return dados


def expandir_lote(lote: dict, textos: dict[str, list[Entrada]]
                  ) -> list[tuple[dict, str, Entrada]]:
    """(item do lote, arquivo, entrada) na ordem do lote; ``dialogo.NNN``/``b3.NNN``
    viram todas as entradas ``.tNN`` deles, na ordem do arquivo."""
    todas = [(a, e) for a, es in textos.items() for e in es]
    res = []
    for item in lote["entradas"]:
        alvo = str(item["id"])
        achadas = [(a, e) for a, e in todas if e.id == alvo or _pai(e.id) == alvo]
        if not achadas:
            raise ErroRevisao(f"lote {lote['id']}: entrada {alvo} não existe nos textos")
        res += [(item, a, e) for a, e in achadas]
    return res


def _pai(id_: str) -> str | None:
    m = _TRECHO.fullmatch(id_)
    return m.group(1) if m else None


def _grupo(id_: str) -> str:
    """Diálogo ou script do banco 3 da entrada (``dialogo.002``, ``b3.000``), a string
    dela (``b0.003``) ou o próprio id (``inline``)."""
    m = _GRUPO.match(id_)
    return m.group(1) if m else _pai(id_) or id_


# ------------------------------------------------------------------ desenho

@lru_cache(maxsize=4)
def _fonte(caminho: str):
    from PIL import Image

    with Image.open(caminho) as img:
        if img.mode != "P":
            raise ErroRevisao(f"{caminho}: a fonte deve ser um PNG indexado")
        return img.copy().load()


def desenhar(pagina: Pagina, fonte_png: Path):
    """A janela da página com a fonte do jogo (``graficos/fonte/fonte.png``: tile n =
    código n; índices 0 e 1 são fundo). Texto de ``[cor]`` em amarelo; valores em tempo de
    execução em caixa azul com o nome; linhas que rolam antes de o jogador ler com fundo
    vermelho; ``▼`` embaixo quando a página termina num ``[espera]``."""
    from PIL import Image, ImageDraw

    src = _fonte(str(fonte_png))
    celulas = pagina.celulas or [[] for _ in pagina.linhas]
    colunas = max([pagina.largura] + [c.col + max(c.largura, len(c.codigos))
                                      for linha in celulas for c in linha])
    linhas = max(len(celulas), pagina.altura, 1)
    img = Image.new("RGB", (8 * colunas + 16, 16 * linhas + 20), _FUNDO_JANELA)
    pinta = ImageDraw.Draw(img)
    pinta.rectangle((2, 2, img.width - 3, img.height - 3), outline=_MOLDURA, width=2)
    rola = max(len(celulas) - pagina.altura, 0) if pagina.altura else 0
    px = img.load()

    def glifo(cod: int, col: int, lin: int, cor) -> None:
        tx, ty = (cod % 16) * 8, (cod // 16) * 8
        x0, y0 = 8 + 8 * col, 8 + 16 * lin + 8
        for y in range(8):
            for x in range(8):
                if src[tx + x, ty + y] not in _FUNDO_FONTE:
                    px[x0 + x, y0 + y] = cor

    for lin, linha in enumerate(celulas):
        y0 = 8 + 16 * lin
        if lin < rola:
            pinta.rectangle((8, y0, 8 + 8 * colunas - 1, y0 + 15), fill=_FUNDO_ROLA)
        for c in linha:
            x0 = 8 + 8 * c.col
            if c.variavel:
                n = max(c.largura, 1)
                pinta.rectangle((x0, y0 + 2, x0 + 8 * n - 1, y0 + 15), fill=_FUNDO_VARIAVEL)
                for i, cod in enumerate(c.codigos[:n]):
                    glifo(cod, c.col + i, lin, _COR_VARIAVEL)
            elif not c.codigos:
                pinta.rectangle((x0, y0 + 8, x0 + 7, y0 + 15), outline=_COR_ERRO)
            else:
                for i, cod in enumerate(c.codigos):
                    glifo(cod, c.col + i, lin, _COR_AMARELO if c.cor else _COR_TEXTO)
    if pagina.espera:
        meio, base = img.width // 2, img.height - 3
        pinta.polygon([(meio - 4, base - 5), (meio + 4, base - 5), (meio, base - 1)],
                      fill=_COR_TEXTO)
    return img


def _png_base64(img, escala: int = 2) -> str:
    from PIL import Image

    if escala != 1:
        img = img.resize((img.width * escala, img.height * escala), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ------------------------------------------------------------------ capturas

def _trocar_dialogo_0(rom: bytes, origem: int) -> bytes:
    """Entrada 0 da tabela de diálogos (flag + offset) = a do diálogo ``origem``."""
    rom = bytearray(rom)
    tab = int.from_bytes(rom[PONTEIRO_DIALOGOS:PONTEIRO_DIALOGOS + 4], "big")
    rom[tab:tab + 3] = rom[tab + 3 * origem:tab + 3 * origem + 3]
    return bytes(rom)


def _dialogo_do_grupo(grupo: str, textos: dict[str, list[Entrada]]) -> int | None:
    """Número do diálogo que roda o grupo: o próprio ``dialogo.NNN`` ou, para
    ``b3.NNN``, o primeiro diálogo que chama o script (``[s3:NN]``)."""
    if grupo.startswith("dialogo."):
        return int(grupo.split(".")[1])
    if grupo.startswith("b3."):
        ref = f"[s3:{int(grupo[3:], 16):02X}]"
        for e in textos.get("dialogos", []):
            if ref in e.en:
                return int(e.id.split(".")[1])
    return None


def ler_janela(vram: bytes, tabela: Tabela) -> list[str] | None:
    """Linhas de texto da janela de diálogo no plano A (``None`` sem janela): a moldura
    começa no tile 0x14 (canto) com 0x15 à direita e 0x16 embaixo; cada linha de texto
    ocupa duas células (a letra na de baixo)."""
    def cel(lin: int, col: int) -> int:
        i = PLANO_A + 2 * (PLANO_COLUNAS * (lin % PLANO_LINHAS) + col % PLANO_COLUNAS)
        return int.from_bytes(vram[i:i + 2], "big")

    for lin in range(PLANO_LINHAS):
        for col in range(PLANO_COLUNAS):
            if (cel(lin, col) & 0x1FFF != TILE_CANTO or cel(lin, col + 1) & 0x7FF != TILE_TOPO
                    or cel(lin + 1, col) & 0x7FF != TILE_LADO):
                continue
            largura = 0
            while largura < PLANO_COLUNAS and cel(lin, col + 1 + largura) & 0x7FF == TILE_TOPO:
                largura += 1
            altura = 0
            while altura < PLANO_LINHAS and cel(lin + 1 + altura, col) & 0x7FF == TILE_LADO:
                altura += 1
            return [tabela.decodificar(bytes(cel(lin + 2 + 2 * k, col + 1 + c) & 0xFF
                                             for c in range(largura))).rstrip()
                    for k in range(altura // 2)]
    return None


def _parado(leituras: list[list[str]]) -> bool:
    """O texto parou de imprimir: as últimas 5 leituras (10 quadros entre elas) são
    iguais ou alternam entre dois valores (o cursor do menu SIM/NÃO pisca no tilemap);
    texto ainda imprimindo só cresce e nunca volta a uma leitura anterior."""
    if len(leituras) < 5:
        return False
    if len({tuple(l) for l in leituras}) == 1:
        return True
    return any(leituras[i] == leituras[k] != leituras[j]
               for i in range(5) for j in range(i + 1, 5) for k in range(j + 1, 5))


def _main_captura(argv: list[str]) -> int:
    """Processo à parte (uma instância do emulador por processo): NEW GAME com a ROM
    ``argv[0]`` (lida com a tabela ``argv[2]``) e, a cada parada do texto
    (``_parado``), grava a tela e as linhas em ``argv[1]`` e aperta C. Segue só o primeiro caminho (C escolhe a opção
    marcada) e para quando a janela some por 600 quadros."""
    from .emulador.libretro import CORE_PADRAO, Emulador

    rom, destino, tabela = Path(argv[0]), Path(argv[1]), Tabela.carregar(Path(argv[2]))
    destino.mkdir(parents=True, exist_ok=True)
    emu = Emulador(CORE_PADRAO, rom)
    try:
        emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
        for _ in range(2):
            emu.avancar(2, {"start"}); emu.avancar(120)
        emu.avancar(2, {"start"})
        telas: list[dict] = []
        leituras: list[list[str]] = []
        sem_janela = 0
        for _ in range(6000):
            emu.avancar(10)
            linhas = ler_janela(emu.vram(), tabela)
            if not linhas or not any(linhas):
                sem_janela += 1
                if (telas and sem_janela >= 60) or sem_janela >= 300:
                    break
                leituras = []
                continue
            sem_janela = 0
            leituras = (leituras + [linhas])[-5:]
            if not _parado(leituras):
                continue
            if not telas or telas[-1]["linhas"] != linhas:
                png = f"tela_{len(telas):02d}.png"
                emu.quadro_png(destino / png)
                telas.append({"png": png, "linhas": linhas})
                if len(telas) >= MAX_TELAS:
                    break
            emu.avancar(2, {"c"})
            leituras = []
    finally:
        emu.fechar()
    (destino / ARQ_TELAS).write_text(json.dumps({"telas": telas}, ensure_ascii=False,
                                                indent=1) + "\n",
                                     encoding="utf-8", newline="\n")
    return 0


def capturar(rom: bytes, dialogo: int, destino: Path, tabela_tbl: Path) -> list[dict]:
    """Roda o diálogo ``dialogo`` no emulador (num processo à parte) e devolve as telas
    (``ler_capturas``)."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    for velho in destino.glob("tela_*.png"):
        velho.unlink()
    arq = destino / "teste.bin"
    arq.write_bytes(_trocar_dialogo_0(rom, dialogo))
    raiz_ferramentas = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; from ferramentas.revisao import _main_captura; "
         "sys.exit(_main_captura(sys.argv[1:]))", str(arq), str(destino), str(tabela_tbl)],
        cwd=str(raiz_ferramentas), capture_output=True, timeout=1800)
    arq.unlink()
    if r.returncode != 0:
        raise ErroRevisao("captura do diálogo {}: {}".format(
            dialogo, r.stderr.decode("utf-8", "replace")[-2000:]))
    return ler_capturas(destino)


def ler_capturas(pasta: Path) -> list[dict]:
    """Telas gravadas por ``capturar``: ``[{"linhas": [...], "png": Path}]``."""
    pasta = Path(pasta)
    arq = pasta / ARQ_TELAS
    if not arq.is_file():
        return []
    telas = json.loads(arq.read_text(encoding="utf-8"))["telas"]
    return [{"linhas": t["linhas"], "png": pasta / t["png"]} for t in telas]


# ------------------------------------------------------------------ HTML

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--bd:#ddd;--hd:#f3f3f3;--pend:#b45309;--ok:#15803d}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#e8e8e8;--mut:#9a9a9a;--bd:#333;
--hd:#1e1e1e;--pend:#f59e0b;--ok:#4ade80}}
body{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,Segoe UI,sans-serif;
margin:0 auto;max-width:1400px;padding:16px}
h1{font-size:24px}.desc{color:var(--mut)}
table{border-collapse:collapse;width:100%;margin:12px 0}
th,td{border:1px solid var(--bd);padding:6px 8px;vertical-align:top;text-align:left}
thead th{background:var(--hd);position:sticky;top:0}
tr.grupo th{background:var(--hd);font-family:ui-monospace,Consolas,monospace}
.bruto{font-family:ui-monospace,Consolas,monospace;font-size:13px;white-space:pre-wrap;
word-break:break-word}
.status{font-size:12px;color:var(--mut)}.pendente{color:var(--pend);font-weight:600}
.revisado .status{color:var(--ok)}
img{image-rendering:pixelated;max-width:100%}img.pagina{display:block;margin:0 0 6px}
figure{display:inline-block;margin:6px 10px 6px 0;vertical-align:top}
figcaption{color:var(--mut);font-size:12px;font-family:ui-monospace,Consolas,monospace;
white-space:pre}
.num{text-align:right}
"""


def _documento(titulo: str, corpo: str) -> str:
    return ("<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(titulo)}</title><style>{_CSS}</style></head><body>"
            f"{corpo}</body></html>\n")


_CODIGO = re.compile(r"\[[^\]]*\]")


def so_codigo(en: str) -> bool:
    """Entrada sem caractere literal fora dos ``[...]`` (``[s0:06]``, ``[espera]``,
    ``[$03][$06]``; glifos em ``[$XX]``, como as notas ``[$10]``–``[$12]`` das lojas, contam
    como código): fica com ``pt`` vazio e ``pendente`` (o montador mantém o original) e não
    entra no progresso."""
    return not _CODIGO.sub("", en).strip()


def _contagem(entradas) -> dict[str, int]:
    """Entradas por status, sem as só-código (``so_codigo``)."""
    entradas = [e for e in entradas if not so_codigo(e.en)]
    return {s: sum(e.status == s for e in entradas) for s in STATUS}


def _resumo(cont: dict[str, int]) -> str:
    n = sum(cont.values())
    feitos = cont["traduzido"] + cont["revisado"]
    pct = round(100 * feitos / n) if n else 0
    return (f"{n} entradas: {cont['pendente']} pendente, {cont['traduzido']} traduzido, "
            f"{cont['revisado']} revisado ({pct}%)")


def _celula_entrada(item: dict, e: Entrada, ctx: Contexto, fonte_png: Path) -> str:
    esc = lambda t: html.escape(str(t or ""), quote=False)   # noqa: E731
    onde = "".join(f"<div>{esc(item.get(k))}</div>" for k in ("onde", "quem")
                   if item.get(k))
    notas = [n for n in (item.get("nota"), e.nota) if n]
    onde += "".join(f"<div class='status'>{esc(n)}</div>" for n in notas)
    if e.pt:
        pt = f"<div class='bruto'>{esc(e.pt)}</div>"
        imgs = "".join(
            f"<img class='pagina' alt='página {i}' src='{_png_base64(desenhar(p, fonte_png))}'>"
            for i, p in enumerate(paginas(ctx, e.id), 1)) if fonte_png.is_file() else ""
    else:
        pt, imgs = "<span class='pendente'>pendente</span>", ""
    return (f"<tr class='entrada {e.status}' id='{html.escape(e.id)}'>"
            f"<td><code>{esc(e.id)}</code><div class='status'>{esc(e.status)}</div></td>"
            f"<td>{onde}</td><td><div class='bruto'>{esc(e.en)}</div></td>"
            f"<td>{pt}</td><td>{imgs}</td></tr>")


def html_lote(lote: dict, ctx: Contexto, fonte_png: Path,
              capturas: dict[str, list[dict]] | None = None) -> str:
    itens = expandir_lote(lote, ctx.textos)
    linhas = []
    grupo_atual = None
    grupos_vistos: list[str] = []
    for item, _, e in itens:
        grupo = _grupo(e.id)
        if grupo != grupo_atual:
            if grupo_atual is not None:
                linhas.append(_linha_capturas(grupo_atual, capturas, grupos_vistos))
            grupo_atual = grupo
            linhas.append(f"<tr class='grupo'><th colspan='5'>{html.escape(grupo)}</th></tr>")
        linhas.append(_celula_entrada(item, e, ctx, fonte_png))
    if grupo_atual is not None:
        linhas.append(_linha_capturas(grupo_atual, capturas, grupos_vistos))
    titulo = str(lote.get("titulo") or lote["id"])
    corpo = (f"<h1>{html.escape(titulo)}</h1>"
             f"<p class='desc'>Lote <code>{html.escape(str(lote['id']))}</code> — "
             f"{_resumo(_contagem([e for _, _, e in itens]))}. As páginas mostram o "
             "<code>pt</code> como a janela do jogo o exibe, com a fonte do jogo, a partir do "
             "pior estado de entrada (o mesmo de <code>verificar</code>): ▼ = espera o botão; "
             "fundo vermelho = linhas que rolam antes de o jogador ler; caixa azul = valor "
             "em tempo de execução.</p>"
             "<table><thead><tr><th>Entrada</th><th>Onde / quem</th><th>Original</th>"
             "<th>Tradução</th><th>Páginas</th></tr></thead><tbody>"
             + "".join(linhas) + "</tbody></table>")
    return _documento(titulo, corpo)


def _linha_capturas(grupo: str, capturas, vistos: list[str]) -> str:
    """Telas do emulador do grupo (uma vez por grupo)."""
    if not capturas or grupo not in capturas or grupo in vistos:
        return ""
    vistos.append(grupo)
    from PIL import Image

    figs = []
    for i, t in enumerate(capturas[grupo]):
        with Image.open(t["png"]) as img:
            src = _png_base64(img.convert("RGB"), 1)
        leg = html.escape("\n".join(t["linhas"]))
        figs.append(f"<figure><img class='captura' alt='tela {i}' src='{src}'>"
                    f"<figcaption>{leg}</figcaption></figure>")
    if not figs:
        figs.append("<span class='desc'>nenhuma tela capturada</span>")
    return (f"<tr class='capturas'><td colspan='5'><div class='status'>No jogo "
            f"({html.escape(grupo)}, primeiro caminho):</div>{''.join(figs)}</td></tr>")


def html_indice(lotes: list[dict], ctx: Contexto) -> str:
    linhas = []
    total = {s: 0 for s in STATUS}
    for arquivo, entradas in sorted(ctx.textos.items()):
        cont = _contagem(entradas)
        for s in STATUS:
            total[s] += cont[s]
        linhas.append(_linha_progresso(html.escape(arquivo), cont))
    linhas.append(_linha_progresso("<b>TOTAL</b>", total))
    cab = ("<tr>" + "".join(f"<th>{c}</th>" for c in ("", *STATUS, "total", "%")) + "</tr>")
    corpo = ("<h1>Revisão da tradução</h1><h2>Progresso por arquivo</h2>"
             f"<table><thead>{cab}</thead><tbody>{''.join(linhas)}</tbody></table>"
             "<p class='desc'>Entradas só com códigos (sem texto visível, como "
             "<code>[s0:06]</code> ou <code>[espera]</code>) ficam vazias e não entram na "
             "contagem.</p><h2>Lotes</h2>")
    if not lotes:
        corpo += (f"<p class='desc'>Nenhum lote definido em "
                  f"<code>{ARQ_LOTES.as_posix()}</code>.</p>")
    else:
        lin = []
        for lote in lotes:
            cont = _contagem([e for _, _, e in expandir_lote(lote, ctx.textos)])
            id_ = html.escape(str(lote["id"]))
            lin.append(_linha_progresso(
                f"<a href='{id_}.html'>{id_}</a> — "
                f"{html.escape(str(lote.get('titulo') or ''))}", cont))
        corpo += f"<table><thead>{cab}</thead><tbody>{''.join(lin)}</tbody></table>"
    return _documento("Revisão da tradução", corpo)


def _linha_progresso(nome: str, cont: dict[str, int]) -> str:
    n = sum(cont.values())
    pct = round(100 * (cont["traduzido"] + cont["revisado"]) / n) if n else 0
    nums = "".join(f"<td class='num'>{cont[s]}</td>" for s in STATUS)
    return f"<tr><td>{nome}</td>{nums}<td class='num'>{n}</td><td class='num'>{pct}%</td></tr>"


# ------------------------------------------------------------------ comando

def gerar(raiz: Path, ctx: Contexto, lote_id: str, rom: bytes | None = None) -> list[Path]:
    """Grava o HTML do lote (ou o índice e todos os lotes, com ``todos``) em
    ``build/revisao/``; com ``rom`` (a ROM traduzida), captura os diálogos no emulador.
    Devolve os arquivos gravados."""
    raiz = Path(raiz)
    lotes = carregar_lotes(raiz)
    saida = raiz / PASTA_SAIDA
    saida.mkdir(parents=True, exist_ok=True)
    fonte_png = raiz / "graficos" / "fonte" / "fonte.png"
    gravados = []
    if lote_id == LOTE_TODOS:
        escolhidos = lotes
        arq = saida / f"{LOTE_TODOS}.html"
        arq.write_text(html_indice(lotes, ctx), encoding="utf-8", newline="\n")
        gravados.append(arq)
    else:
        if not lotes:
            raise ErroRevisao(f"{ARQ_LOTES.as_posix()} não existe ou está vazio: defina o "
                              f"lote {lote_id} lá")
        escolhidos = [l for l in lotes if str(l["id"]) == lote_id]
        if not escolhidos:
            raise ErroRevisao(f"lote {lote_id} não existe em {ARQ_LOTES.as_posix()} "
                              f"(lotes: {', '.join(str(l['id']) for l in lotes)})")
    for lote in escolhidos:
        capturas = None
        if rom is not None:
            capturas = {}
            for grupo in dict.fromkeys(_grupo(e.id) for _, _, e in
                                       expandir_lote(lote, ctx.textos)):
                dialogo = _dialogo_do_grupo(grupo, ctx.textos)
                if dialogo is None:
                    continue
                print(f"  capturando {grupo} (diálogo {dialogo})...")
                capturas[grupo] = capturar(rom, dialogo,
                                           saida / "capturas" / str(lote["id"]) / grupo,
                                           raiz / "traducao" / "tabela.tbl")
        arq = saida / f"{lote['id']}.html"
        arq.write_text(html_lote(lote, ctx, fonte_png, capturas), encoding="utf-8",
                       newline="\n")
        gravados.append(arq)
    return gravados
