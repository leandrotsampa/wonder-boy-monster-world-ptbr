"""Relatório de revisão por lote (``python -m ferramentas revisao``,
``ferramentas/revisao.py``): páginas simuladas do ``pt`` (``verificacao.paginas``), a
janela desenhada com a fonte do jogo e o HTML do lote.

Os lotes vêm de ``traducao/lotes.yaml``; aqui o lote ``piloto`` é escrito numa cópia
temporária do projeto (nunca no repositório).
"""

from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

import pytest
import yaml

from ferramentas.cli import _contexto, main
from ferramentas.config import carregar_projeto
from ferramentas.textos import Entrada
from ferramentas.verificacao import Pagina, paginas

RAIZ = Path(__file__).resolve().parent.parent
FONTE = RAIZ / "graficos" / "fonte" / "fonte.png"

# Abertura aprovada (dialogo.000.t01), janela 0 (23×3): o t00 deixa o recuo em 2 e
# avança 2 colunas; uma página por [espera] e a última fecha no [espera] do t02.
ABERTURA = [
    ["  Houve um tempo em que", "  Monster World vivia", "  em paz."],
    ["  Mas essa paz foi", "  destruída por um", "  exército de monstros."],
    ["  Um jovem chamado", "  Shion jurou", "  derrotá-los e trazer"],
    ["  a paz novamente", "  à sua terra."],
]

LOTE_PILOTO = [{
    "id": "piloto",
    "titulo": "Piloto: abertura, senhora de Alsedo, placa e loja",
    "entradas": [
        {"id": "dialogo.000.t01", "onde": "Abertura do NEW GAME", "quem": "Narrador",
         "nota": ""},
        {"id": "dialogo.002", "onde": "Casa da senhora em Alsedo", "quem": "Senhora",
         "nota": "dá o Elixir e a magia"},
        {"id": "dialogo.003.t00", "onde": "Placa na entrada de Alsedo", "quem": "Placa"},
        {"id": "b3.000", "onde": "Lojas", "quem": "Vendedor"},
    ],
}]


def _ctx(pts: dict[str, str] | None = None):
    ctx = _contexto(carregar_projeto(RAIZ))
    for entradas in ctx.textos.values():
        for e in entradas:
            if pts and e.id in pts:
                e.pt = pts[e.id]
    return ctx


def test_paginas_do_piloto():
    pags = paginas(_ctx(), "dialogo.000.t01")
    assert [p.linhas for p in pags] == ABERTURA
    assert all(isinstance(p, Pagina) for p in pags)
    assert [(p.largura, p.altura) for p in pags] == [(23, 3)] * 4
    assert [p.espera for p in pags] == [True, True, True, False]


def test_paginas_janela_estreita():
    """Janela 4 (Esfinge, dialogo.091: 17×5): o motor quebra no meio da palavra quando o
    caractere cai na coluna 17, como na captura do caso janela4 de
    test_validacao_jogo.py."""
    pags = paginas(_ctx({"dialogo.091.t01": "ABCDEFGHIJKLMNOPQRSTUVWXYZ[espera]"}),
                   "dialogo.091.t01")
    assert len(pags) == 1
    assert pags[0].linhas == ["ABCDEFGHIJKLMNOPQ", "RSTUVWXYZ"]
    assert (pags[0].largura, pags[0].altura, pags[0].espera) == (17, 5, True)


def test_variaveis_legiveis():
    pags = paginas(_ctx(), "b3.000.t00")
    linhas = [l for p in pags for l in p.linhas]
    assert "  ‹item›?" in linhas
    assert "  Custa ‹preço› MOEDAS." in linhas
    assert not any("[" in l for l in linhas)


def test_sem_pt_nao_tem_paginas():
    assert paginas(_ctx(), "dialogo.002.t00") == []
    assert paginas(_ctx(), "nao.existe") == []


def test_desenhar_cor_amarela():
    from ferramentas.revisao import desenhar

    pag = paginas(_ctx(), "dialogo.000.t01")[2]
    img = desenhar(pag, FONTE).convert("RGB")
    assert img.width >= 8 * 23 and img.height >= 16 * 3
    cores = {img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)}
    assert any(r > 180 and g > 180 and b < 100 for r, g, b in cores)    # Shion
    assert any(r > 180 and g > 180 and b > 180 for r, g, b in cores)    # texto branco


# ------------------------------------------------------------------ HTML

def _copiar_projeto(destino: Path, lotes=LOTE_PILOTO) -> Path:
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, destino / rel)
    (destino / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", destino / "dados" / "scripts")
    if lotes is not None:
        (destino / "traducao" / "lotes.yaml").write_text(
            yaml.safe_dump(lotes, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return destino


def _linhas_html(doc: str) -> dict[str, str]:
    return dict(re.findall(r"<tr class='entrada[^']*' id='([^']+)'>(.*?)</tr>", doc, re.S))


def test_html_do_lote(tmp_path):
    raiz = _copiar_projeto(tmp_path)
    assert main(["--raiz", str(raiz), "revisao", "--lote", "piloto"]) == 0
    doc = (raiz / "build" / "revisao" / "piloto.html").read_text(encoding="utf-8")
    ctx = _ctx()
    todas = {e.id: e for es in ctx.textos.values() for e in es}
    esperadas = (["dialogo.000.t01"] + sorted(i for i in todas if i.startswith("dialogo.002."))
                 + ["dialogo.003.t00"] + sorted(i for i in todas if i.startswith("b3.000.")))
    linhas = _linhas_html(doc)
    assert list(linhas) == esperadas
    for id_, linha in linhas.items():
        e = todas[id_]
        assert html.escape(e.en, quote=False) in linha, id_
        if e.pt:
            assert html.escape(e.pt, quote=False) in linha, id_
            assert linha.count("<img class='pagina'") == len(paginas(ctx, id_)) > 0, id_
        else:
            assert "pendente" in linha and "<img class='pagina'" not in linha, id_
    assert "Casa da senhora em Alsedo" in linhas["dialogo.002.t01"]
    assert "Vendedor" in linhas["b3.000.t02"]
    assert "Piloto: abertura" in doc


def test_lote_inexistente_e_sem_lotes(tmp_path, capsys):
    raiz = _copiar_projeto(tmp_path / "a")
    assert main(["--raiz", str(raiz), "revisao", "--lote", "nada"]) == 1
    assert "nada" in capsys.readouterr().err
    raiz = _copiar_projeto(tmp_path / "b", lotes=None)
    assert main(["--raiz", str(raiz), "revisao", "--lote", "piloto"]) == 1
    assert "lotes.yaml" in capsys.readouterr().err


def test_lote_com_entrada_inexistente(tmp_path, capsys):
    lotes = [{"id": "x", "titulo": "X", "entradas": [{"id": "dialogo.999"}]}]
    raiz = _copiar_projeto(tmp_path, lotes)
    assert main(["--raiz", str(raiz), "revisao", "--lote", "x"]) == 1
    assert "dialogo.999" in capsys.readouterr().err


def test_indice_todos(tmp_path):
    raiz = _copiar_projeto(tmp_path)
    assert main(["--raiz", str(raiz), "revisao", "--lote", "todos"]) == 0
    doc = (raiz / "build" / "revisao" / "todos.html").read_text(encoding="utf-8")
    assert "dialogos" in doc and "banco3_lojas" in doc
    assert "pendente" in doc and "traduzido" in doc and "revisado" in doc
    assert "piloto.html" in doc
    assert (raiz / "build" / "revisao" / "piloto.html").is_file()


# ------------------------------------------------------------------ no jogo

def test_paginas_do_piloto_no_jogo(rom_base, tmp_path):
    """``revisao --capturas``: a ROM montada roda a abertura no emulador e as linhas da
    janela (tilemap) em cada parada batem com as páginas simuladas."""
    from ferramentas.emulador.libretro import CORE_PADRAO
    from ferramentas.revisao import ler_capturas

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    lotes = [{"id": "abertura", "titulo": "Abertura",
              "entradas": [{"id": "dialogo.000.t01"}]}]
    raiz = _copiar_projeto(tmp_path / "proj", lotes)
    arq = tmp_path / "base.bin"
    arq.write_bytes(rom_base)
    assert main(["--raiz", str(raiz), "revisao", "--lote", "abertura", "--capturas",
                 "--rom", str(arq)]) == 0
    telas = ler_capturas(raiz / "build" / "revisao" / "capturas" / "abertura" / "dialogo.000")
    assert len(telas) >= len(ABERTURA)
    for pagina, tela in zip(ABERTURA, telas):
        assert tela["linhas"][-len(pagina):] == pagina
    doc = (raiz / "build" / "revisao" / "abertura.html").read_text(encoding="utf-8")
    assert doc.count("<img class='captura'") == len(telas)


# ------------------------------------------------------------------ progresso

@pytest.mark.parametrize("en, esperado", [
    ("[s0:06]", True),
    ("[espera][linha]", True),
    ("[$03][$06]", True),
    ("[$10] ", True),
    ("[$04][$02]A", False),
    (".", False),
    ("...", False),
    ("[cor]Alsedo[/cor]", False),
])
def test_so_codigo(en, esperado):
    from ferramentas.revisao import so_codigo

    assert so_codigo(en) is esperado


def test_progresso_sem_as_entradas_so_codigo():
    from ferramentas.revisao import _contagem, _resumo

    entradas = [Entrada("x.000.t00", "[s0:06]"),
                Entrada("x.000.t01", "Hello", pt="Olá", status="traduzido")]
    cont = _contagem(entradas)
    assert cont["pendente"] == 0 and cont["traduzido"] == 1
    assert _resumo(cont).endswith("(100%)")
