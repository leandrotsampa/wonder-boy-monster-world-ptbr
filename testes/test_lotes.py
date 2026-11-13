"""Mapa de cenas (``traducao/lotes.yaml``) e glossário de lugares.

Cada entrada traduzível dos textos está em exatamente um lote, com o lugar (``onde``) e
quem fala (``quem``); as strings japonesas que sobraram do original ficam no lote
``sem_traducao``, com o motivo, e nunca recebem ``pt``. Os nomes de lugar do banco 2 têm
a decisão registrada em ``traducao/glossario.yaml``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import yaml

from ferramentas.revisao import carregar_lotes, expandir_lote, so_codigo
from ferramentas.textos import carregar_todos

RAIZ = Path(__file__).resolve().parent.parent
TEXTOS = RAIZ / "traducao" / "textos"
GLOSSARIO = RAIZ / "traducao" / "glossario.yaml"

# um lote por tarefa de tradução (Tasks 3–9 do plano), nesta ordem, e o das sobras
# Na ordem do jogo informada pelo autor (traducao/lotes.yaml).
LOTES = ["alsedo", "purapril", "lilypad", "mar_deserto", "begonia", "childam", "final",
         "geral", "sem_traducao"]
SEM_TRADUCAO = "sem_traducao"
ARQUIVOS = ("dialogos", "banco0_sistema", "banco2_nomes", "banco3_lojas", "inline")

# as strings com kana do original (testes/test_vram_cenas.py, CHARS_ALTOS_ESPERADOS)
JAPONESAS = {"b0.004.t00", "b1.026.t00", "b1.030.t00", "b2.006.t00"}

# banco 2: nomes de lugar (e o título que contém um lugar); os demais são pessoas e
# monstros, que ficam como no inglês, salvo os casos cinzentos abaixo
LUGARES_B2 = {"b2.001.t00", "b2.002.t00", "b2.003.t00", "b2.004.t00", "b2.005.t00",
              "b2.007.t00", "b2.008.t00", "b2.009.t00", "b2.028.t00"}
CINZENTOS_B2 = {"b2.022.t00", "b2.026.t00"}   # "Monster" e "Sphinx": palavras comuns

_TAG = re.compile(r"\[[^\]]*\]")
_TOKEN = re.compile(r"\[\$([0-9A-F]{2})\]|\[[^\]]*\]|(.)", re.S)
_COM_ARGUMENTO = {0x01, 0x03, 0x04, 0x0A, 0x0C, 0x0D, 0x0E, 0x0F}


def _traduzivel(en: str) -> bool:
    """Tem letra fora dos códigos de controle."""
    return bool(re.search(r"[A-Za-z]", _TAG.sub("", en)))


def _japonesa(en: str) -> bool:
    """Usa caractere fora do ASCII: byte >= 0x80 como caractere (``[$XX]`` que não é
    argumento de código) ou letra acentuada (os kana que caem nos códigos dos acentos)."""
    argumento = False
    for m in _TOKEN.finditer(en):
        if m.group(1):
            b = int(m.group(1), 16)
            if argumento:
                argumento = False
            elif b in _COM_ARGUMENTO:
                argumento = True
            elif b >= 0x80:
                return True
        else:
            argumento = False
            if m.group(2) and ord(m.group(2)) >= 0x80:
                return True
    return False


def _sem_cor(texto: str) -> str:
    return texto.replace("[cor]", "").replace("[/cor]", "")


def _textos():
    return carregar_todos(TEXTOS)


def test_lotes_conhecidos():
    assert [lote["id"] for lote in carregar_lotes(RAIZ)] == LOTES


def test_toda_entrada_em_um_lote():
    textos = _textos()
    lotes = carregar_lotes(RAIZ)
    onde_esta = defaultdict(list)
    for lote in lotes:
        for item, _arq, e in expandir_lote(lote, textos):
            onde_esta[e.id].append(lote["id"])
            if lote["id"] == SEM_TRADUCAO:
                assert str(item.get("nota") or "").strip(), f"{item['id']}: sem motivo"
            else:
                for campo in ("onde", "quem"):
                    assert str(item.get(campo) or "").strip(), f"{item['id']}: sem {campo}"

    repetidas = {i: ls for i, ls in onde_esta.items() if len(ls) > 1}
    assert repetidas == {}

    japonesas = {e.id for es in textos.values() for e in es if _japonesa(e.en)}
    assert japonesas == JAPONESAS
    sobras = {i for i, ls in onde_esta.items() if ls == [SEM_TRADUCAO]}
    assert sobras == JAPONESAS
    por_id = {e.id: e for es in textos.values() for e in es}
    assert all(por_id[i].pt == "" for i in sobras), "string japonesa com pt"

    faltando = [e.id for arq in ARQUIVOS for e in textos[arq]
                if _traduzivel(e.en) and e.id not in JAPONESAS and e.id not in onde_esta]
    assert faltando == []


def test_glossario_de_lugares():
    glossario = yaml.safe_load(GLOSSARIO.read_text(encoding="utf-8")) or []
    for termo in glossario:
        for campo in ("en", "pt", "nota"):
            assert str(termo.get(campo) or "").strip(), f"glossário: {termo!r} sem {campo}"
    por_en = {str(t["en"]): str(t["pt"]) for t in glossario}

    nomes = {e.id: e for e in _textos()["banco2_nomes"]}
    for id_, e in nomes.items():
        if id_ in JAPONESAS:
            assert e.pt == ""
            continue
        assert e.status in ("traduzido", "revisado"), id_
        if id_ in LUGARES_B2:
            assert _sem_cor(e.en) in por_en, f"{id_}: {e.en!r} fora do glossário"
            assert _sem_cor(e.pt) == por_en[_sem_cor(e.en)], id_
            assert e.pt.startswith("[cor]") == e.en.startswith("[cor]"), id_
        elif id_ in CINZENTOS_B2:
            assert e.pt != e.en and (_sem_cor(e.en) in por_en or e.nota), id_
        else:
            assert e.pt == e.en, f"{id_}: nome de pessoa ou monstro fica como no inglês"


def test_tudo_traduzido():
    """Toda entrada dos lotes (fora de ``sem_traducao``) e todo nome de item do banco 1
    tem ``pt`` e status ``traduzido`` ou ``revisado``; só as entradas só-código
    (``so_codigo``) ficam vazias. ``banco1_menu`` fica de fora: vazio lá é usar o nome
    completo."""
    textos = _textos()
    pendentes = []
    vistos = set()
    for lote in carregar_lotes(RAIZ):
        if lote["id"] == SEM_TRADUCAO:
            continue
        for _item, _arq, e in expandir_lote(lote, textos):
            vistos.add(e.id)
            if so_codigo(e.en):
                continue
            if not e.pt.strip() or e.status not in ("traduzido", "revisado"):
                pendentes.append(f"{lote['id']}: {e.id} ({e.status})")
    for e in textos["banco1_itens"]:
        if e.id in JAPONESAS or so_codigo(e.en):
            continue
        if not e.pt.strip() or e.status not in ("traduzido", "revisado"):
            pendentes.append(f"banco1_itens: {e.id} ({e.status})")
    assert pendentes == []
    assert vistos, "nenhuma entrada nos lotes"
