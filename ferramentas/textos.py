"""Modelo dos textos de tradução em YAML."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import yaml

STATUS = ("pendente", "traduzido", "revisado")
MARCA_MUDOU = "[original mudou]"
MARCA_ORFAO = "[órfão]"


class ErroTextos(Exception):
    pass


@dataclass
class Entrada:
    id: str
    en: str
    pt: str = ""
    status: str = "pendente"
    nota: str = ""


def _acrescentar_nota(nota: str, marca: str) -> str:
    if marca in nota:
        return nota
    return f"{nota} {marca}".strip()


def carregar_textos(caminho: Path) -> list[Entrada]:
    caminho = Path(caminho)
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ErroTextos(f"{caminho.name}: YAML inválido: {e}") from None
    if dados is None:
        return []
    if not isinstance(dados, list):
        raise ErroTextos(f"{caminho.name}: o arquivo deve ser uma lista de entradas")
    entradas: list[Entrada] = []
    vistos: set[str] = set()
    for n, item in enumerate(dados, 1):
        if not isinstance(item, dict):
            raise ErroTextos(f"{caminho.name}: item {n} não é um mapeamento")
        id_ = item.get("id")
        local = f"{caminho.name}: {id_ if id_ is not None else f'item {n}'}"
        if id_ is None or "en" not in item:
            raise ErroTextos(f"{local}: campos 'id' e 'en' são obrigatórios")
        id_ = str(id_)
        if id_ in vistos:
            raise ErroTextos(f"{local}: id duplicado")
        vistos.add(id_)
        e = Entrada(
            id=id_,
            en=str(item["en"]),
            pt=str(item.get("pt") or ""),
            status=str(item.get("status") or "pendente"),
            nota=str(item.get("nota") or ""),
        )
        if e.status not in STATUS:
            raise ErroTextos(f"{local}: status inválido {e.status!r} (use {', '.join(STATUS)})")
        if e.status != "pendente" and not e.pt:
            raise ErroTextos(f"{local}: status {e.status!r} exige 'pt' preenchido")
        entradas.append(e)
    return entradas


def salvar_textos(caminho: Path, entradas: list[Entrada]) -> None:
    lista = []
    for e in entradas:
        d = {"id": e.id, "en": e.en, "pt": e.pt, "status": e.status}
        if e.nota:
            d["nota"] = e.nota
        lista.append(d)
    texto = yaml.safe_dump(lista, allow_unicode=True, sort_keys=False, width=1000)
    Path(caminho).write_text(texto, encoding="utf-8", newline="\n")


def mesclar(existentes: list[Entrada], extraidas: list[Entrada]) -> list[Entrada]:
    por_id = {e.id: e for e in existentes}
    resultado: list[Entrada] = []
    ids_extraidos = set()
    for nova in extraidas:
        ids_extraidos.add(nova.id)
        antiga = por_id.get(nova.id)
        if antiga is None:
            resultado.append(Entrada(id=nova.id, en=nova.en))
            continue
        e = replace(antiga, en=nova.en)
        if antiga.en != nova.en and antiga.pt:
            e.status = "pendente"
            e.nota = _acrescentar_nota(e.nota, MARCA_MUDOU)
        resultado.append(e)
    for antiga in existentes:
        if antiga.id not in ids_extraidos:
            resultado.append(replace(antiga, nota=_acrescentar_nota(antiga.nota, MARCA_ORFAO)))
    return resultado


def carregar_todos(pasta: Path) -> dict[str, list[Entrada]]:
    pasta = Path(pasta)
    if not pasta.is_dir():
        return {}
    todos: dict[str, list[Entrada]] = {}
    origem: dict[str, str] = {}
    for arq in sorted(pasta.glob("*.yaml")):
        entradas = carregar_textos(arq)
        for e in entradas:
            if e.id in origem:
                raise ErroTextos(f"id {e.id!r} duplicado em {origem[e.id]} e {arq.name}")
            origem[e.id] = arq.name
        todos[arq.stem] = entradas
    return todos
