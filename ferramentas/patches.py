"""Patches de código: troca de bytes conferida (config/patches.yaml).

Cada item diz o endereço, os bytes que a ROM base tem ali (``original``) e os que o
build grava (``novo``), do mesmo tamanho. O build confere todos os ``original`` antes
de gravar qualquer um; se algum não bater, nada é gravado.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .compensacao import area_compensacao, sobrepoe
from .config import ErroConfig, Projeto

ARQ_PATCHES = Path("config") / "patches.yaml"


class ErroPatch(Exception):
    pass


@dataclass(frozen=True)
class Patch:
    id: str
    end: int
    original: bytes
    novo: bytes
    descricao: str
    origem: str


def _hex(valor, id_, campo) -> bytes:
    if not isinstance(valor, str):
        raise ErroConfig(f"patches.yaml: {id_}: '{campo}' deve ser texto hex")
    try:
        dados = bytes.fromhex(valor.replace(" ", ""))
    except ValueError:
        raise ErroConfig(f"patches.yaml: {id_}: '{campo}' não é hex válido: {valor!r}") from None
    if not dados:
        raise ErroConfig(f"patches.yaml: {id_}: '{campo}' vazio")
    return dados


def carregar_patches(projeto: Projeto) -> list[Patch]:
    """Lê ``config/patches.yaml`` (ausente = nenhum patch); erros viram ``ErroConfig``."""
    arq = projeto.raiz / ARQ_PATCHES
    if not arq.is_file():
        return []
    try:
        dados = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ErroConfig(f"patches.yaml: YAML inválido: {e}") from None
    itens = dados.get("patches") if isinstance(dados, dict) else None
    if itens is None:
        return []
    if not isinstance(itens, list):
        raise ErroConfig("patches.yaml: 'patches' deve ser uma lista")
    patches: list[Patch] = []
    for n, it in enumerate(itens, 1):
        if not isinstance(it, dict) or not isinstance(it.get("id"), str):
            raise ErroConfig(f"patches.yaml: item {n} sem 'id'")
        id_ = it["id"]
        end = it.get("end")
        if not isinstance(end, int) or isinstance(end, bool) or end < 0:
            raise ErroConfig(f"patches.yaml: {id_}: 'end' deve ser inteiro >= 0")
        original = _hex(it.get("original"), id_, "original")
        novo = _hex(it.get("novo"), id_, "novo")
        if len(original) != len(novo):
            raise ErroConfig(f"patches.yaml: {id_}: 'original' e 'novo' com tamanho diferente")
        patches.append(Patch(id_, end, original, novo, str(it.get("descricao", "")),
                             str(it.get("origem", ""))))
    ids = [p.id for p in patches]
    for id_ in ids:
        if ids.count(id_) > 1:
            raise ErroConfig(f"patches.yaml: id duplicado: {id_}")
    ordem = sorted(patches, key=lambda p: p.end)
    for a, b in zip(ordem, ordem[1:]):
        if a.end + len(a.original) > b.end:
            raise ErroConfig(f"patches.yaml: {a.id} sobrepõe {b.id}")
    return patches


def aplicar_patches(rom: bytearray, patches: list[Patch]) -> None:
    """Confere todos os ``original`` e só então grava os ``novo``."""
    for p in patches:
        atual = bytes(rom[p.end:p.end + len(p.original)])
        if atual != p.original:
            raise ErroPatch(f"patch {p.id}: em {p.end:#x} a ROM tem {atual.hex().upper()}, "
                            f"esperado {p.original.hex().upper()}")
    for p in patches:
        rom[p.end:p.end + len(p.novo)] = p.novo


def etapa_patches(rom: bytearray, projeto: Projeto) -> None:
    patches = carregar_patches(projeto)
    area = area_compensacao(projeto, len(rom))
    for p in patches:
        if sobrepoe(p.end, p.end + len(p.novo), area):
            raise ErroPatch(f"patch {p.id}: {p.end:#x}-{p.end + len(p.novo):#x} toca a área de "
                            f"compensação do CRC32/checksum em {area:#x} (rom.yaml)")
    aplicar_patches(rom, patches)
