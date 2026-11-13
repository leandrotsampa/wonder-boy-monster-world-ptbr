"""Strings inline de tamanho fixo (fora das tabelas de texto; ver mapa-rom.md §6).

Cada item de ``config/texto.yaml`` (``inline:``) é ``{id, end, tam, preencher, nota}``:
``tam`` é o comprimento original do texto editável (sem o terminador ``00`` nem bytes de
controle vizinhos, que não são tocados). ``preencher`` é ``espaco`` (``0x20``) ou ``nulo``
(``0x00``) e completa o que sobra quando o ``pt`` é menor que ``tam``.

Item com ``sequencia: <nome>`` faz parte de um bloco lido em sequência (``sequencias_inline``
em ``config/texto.yaml``: ``{ini, fim, largura}``): o código acha cada string pelo ``00`` da
anterior e mede o tamanho na hora, então o ``pt`` pode ser maior ou menor que ``tam``. O bloco
inteiro é remontado no lugar (strings traduzidas + bytes originais entre elas) e completado com
``00`` até ``fim``; o limite é o tamanho do bloco e, por string, ``largura``.
"""

from __future__ import annotations

from ferramentas.config import ErroConfig, Projeto, carregar_cfg_texto
from ferramentas.script.montador import ErroMontagem
from ferramentas.tabela import ErroTabela, Tabela
from ferramentas.textos import Entrada, carregar_todos

ARQUIVO = "inline"
PREENCHIMENTO = {"espaco": 0x20, "nulo": 0x00}


def itens_inline(cfg: dict) -> list[dict]:
    """Itens validados da config (``ErroConfig`` se faltar campo ou for inconsistente)."""
    itens = cfg.get("inline") or []
    vistos: set[str] = set()
    for it in itens:
        for campo in ("id", "end", "tam", "preencher"):
            if campo not in it:
                raise ErroConfig(f"texto.yaml: item inline {it!r} sem o campo {campo!r}")
        for campo in ("end", "tam"):
            v = it[campo]
            if isinstance(v, bool) or not isinstance(v, int):
                raise ErroConfig(
                    f"texto.yaml: inline {it['id']}: {campo} deve ser inteiro (veio {v!r})")
        if it["end"] < 0:
            raise ErroConfig(f"texto.yaml: inline {it['id']}: end negativo")
        if it["tam"] < 1:
            raise ErroConfig(f"texto.yaml: inline {it['id']}: tam deve ser >= 1")
        if it["preencher"] not in PREENCHIMENTO:
            raise ErroConfig(f"texto.yaml: inline {it['id']}: preencher deve ser espaco ou nulo")
        if it["id"] in vistos:
            raise ErroConfig(f"texto.yaml: id inline duplicado {it['id']!r}")
        vistos.add(it["id"])
    seqs = cfg.get("sequencias_inline") or {}
    for nome, sq in seqs.items():
        for campo in ("ini", "fim", "largura"):
            v = sq.get(campo) if isinstance(sq, dict) else None
            if isinstance(v, bool) or not isinstance(v, int):
                raise ErroConfig(f"texto.yaml: sequencias_inline.{nome}: {campo} deve ser inteiro")
        if sq["fim"] <= sq["ini"]:
            raise ErroConfig(f"texto.yaml: sequencias_inline.{nome}: fim <= ini")
    itens = [dict(it) for it in itens]
    for it in itens:
        nome = it.get("sequencia")
        if nome is None:
            continue
        if nome not in seqs:
            raise ErroConfig(f"texto.yaml: inline {it['id']}: sequência {nome!r} não declarada")
        sq = seqs[nome]
        if not (sq["ini"] <= it["end"] and it["end"] + it["tam"] <= sq["fim"]):
            raise ErroConfig(f"texto.yaml: inline {it['id']}: fora da sequência {nome!r}")
        it["seq"] = {"nome": nome, **sq}
    ordem = sorted(itens, key=lambda i: i["end"])
    for a, b in zip(ordem, ordem[1:]):
        if a["end"] + a["tam"] > b["end"]:
            raise ErroConfig(
                f"texto.yaml: inline {a['id']} ({a['end']:#x}+{a['tam']}) sobrepõe {b['id']} "
                f"({b['end']:#x})")
    return itens


def extrair_inline(rom: bytes, itens: list[dict], tabela: Tabela) -> list[Entrada]:
    return [Entrada(it["id"], tabela.decodificar(bytes(rom[it["end"]:it["end"] + it["tam"]])))
            for it in itens]


def bytes_inline(item: dict, pt: str, tabela: Tabela) -> bytes:
    """``pt`` codificado e completado até ``tam``; ``ErroMontagem`` se não couber."""
    try:
        dados = tabela.codificar(pt, item["id"])
    except ErroTabela as e:
        raise ErroMontagem(str(e)) from None
    if len(dados) > item["tam"]:
        raise ErroMontagem(
            f"{item['id']}: o texto ocupa {len(dados)} bytes e o espaço inline é de "
            f"{item['tam']} (em {item['end']:#x})")
    return dados + bytes([PREENCHIMENTO[item["preencher"]]]) * (item["tam"] - len(dados))


def _codificar(item: dict, pt: str, tabela: Tabela) -> bytes:
    try:
        return tabela.codificar(pt, item["id"])
    except ErroTabela as e:
        raise ErroMontagem(str(e)) from None


def bytes_sequencia(rom: bytes, itens: list[dict], pts: dict[str, str], tabela: Tabela) -> bytes:
    """Bloco de uma sequência remontado (mesmo tamanho; ``ErroMontagem`` se não couber).

    ``itens`` são todos os itens da mesma sequência; ``rom`` é a ROM base (os bytes entre as
    strings vêm dela). Item sem ``pt`` fica com o texto original.
    """
    sq = itens[0]["seq"]
    pos, partes = sq["ini"], []
    for it in sorted(itens, key=lambda i: i["end"]):
        partes.append(bytes(rom[pos:it["end"]]))
        pt = pts.get(it["id"], "")
        dados = _codificar(it, pt, tabela) if pt else bytes(rom[it["end"]:it["end"] + it["tam"]])
        if len(dados) > sq["largura"]:
            raise ErroMontagem(
                f"{it['id']}: o texto ocupa {len(dados)} colunas e a linha da sequência "
                f"{sq['nome']!r} tem {sq['largura']}")
        partes.append(dados)
        pos = it["end"] + it["tam"]
    partes.append(bytes(rom[pos:sq["fim"]]))
    bloco = b"".join(partes)
    tam = sq["fim"] - sq["ini"]
    if len(bloco) > tam:
        raise ErroMontagem(
            f"sequência {sq['nome']!r}: o bloco remontado ocupa {len(bloco)} bytes e o espaço "
            f"é de {tam} (em {sq['ini']:#x}); sobram {len(bloco) - tam} a mais")
    return bloco + b"\x00" * (tam - len(bloco))


def aplicar_inline(rom: bytearray, itens: list[dict], pts: dict[str, str], tabela: Tabela) -> None:
    seqs: dict[str, list[dict]] = {}
    for it in itens:
        if "seq" in it:
            seqs.setdefault(it["seq"]["nome"], []).append(it)
            continue
        pt = pts.get(it["id"], "")
        if not pt:
            continue
        dados = bytes_inline(it, pt, tabela)
        rom[it["end"]:it["end"] + it["tam"]] = dados
    for grupo in seqs.values():
        sq = grupo[0]["seq"]
        rom[sq["ini"]:sq["fim"]] = bytes_sequencia(bytes(rom), grupo, pts, tabela)


def _pts(textos: dict[str, list[Entrada]]) -> dict[str, str]:
    return {e.id: e.pt for e in textos.get(ARQUIVO, [])}


def etapa_inline(rom: bytearray, projeto: Projeto) -> None:
    if not (projeto.raiz / "config" / "texto.yaml").is_file():
        return
    itens = itens_inline(carregar_cfg_texto(projeto.raiz))
    if not itens:
        return
    trad = projeto.raiz / "traducao"
    arq_tbl = trad / "tabela.tbl"
    if not arq_tbl.is_file():
        raise ErroMontagem(f"{arq_tbl} não encontrada")
    aplicar_inline(rom, itens, _pts(carregar_todos(trad / "textos")), Tabela.carregar(arq_tbl))


def checar_inline(ctx):
    """Erro se algum ``pt`` inline não codifica ou excede o ``tam`` (antes do build)."""
    from ferramentas.verificacao import Achado

    achados = []
    pts = _pts(ctx.textos)
    conhecidos = {it["id"] for it in ctx.extra.get("inline", []) + ctx.extra.get("repontavel", [])}
    conhecidos |= {e["id"] for b in ctx.extra.get("repontavel_blocos", []) for e in b["entradas"]}
    for id_ in sorted(set(pts) - conhecidos):
        achados.append(Achado("aviso", "inline", f"{ARQUIVO}:{id_}",
                              "id ausente de config/texto.yaml (inline); será ignorado"))
    seqs: dict[str, list[dict]] = {}
    for it in ctx.extra.get("inline", []):
        if "seq" in it:
            seqs.setdefault(it["seq"]["nome"], []).append(it)
            continue
        pt = pts.get(it["id"], "")
        if not pt:
            continue
        try:
            bytes_inline(it, pt, ctx.tabela)
        except ErroMontagem as e:
            achados.append(Achado("erro", "inline", f"{ARQUIVO}:{it['id']}", str(e)))
    for nome, grupo in seqs.items():
        achados += _checar_sequencia(nome, grupo, pts, ctx.tabela)
    return achados


def _checar_sequencia(nome, grupo, pts, tabela):
    """Sem a ROM: cada string cabe na linha e a soma dos ``pt`` não passa da dos ``tam``."""
    from ferramentas.verificacao import Achado

    achados, soma = [], 0
    for it in grupo:
        pt = pts.get(it["id"], "")
        try:
            n = len(_codificar(it, pt, tabela)) if pt else it["tam"]
        except ErroMontagem as e:
            achados.append(Achado("erro", "inline", f"{ARQUIVO}:{it['id']}", str(e)))
            continue
        if n > it["seq"]["largura"]:
            achados.append(Achado("erro", "inline", f"{ARQUIVO}:{it['id']}",
                                  f"o texto ocupa {n} colunas e a linha tem {it['seq']['largura']}"))
        soma += n - it["tam"]
    if soma > 0:
        achados.append(Achado("erro", "inline", f"sequencia:{nome}",
                              f"os textos somam {soma} bytes a mais que os originais"))
    return achados
