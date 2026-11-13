"""Configuração do projeto."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ErroConfig(Exception):
    pass


@dataclass
class Projeto:
    raiz: Path
    rom: dict
    #: espaço livre do build em curso (``ferramentas.espaco.RegiaoLivre``), compartilhado
    #: pelas etapas; ``None`` até a 1.ª etapa que grava em ``regiao_destino``.
    regiao: object = field(default=None, repr=False, compare=False)

    @property
    def caminho_rom(self) -> Path:
        return self.raiz / "rom" / str(self.rom.get("nome_arquivo", ""))


def carregar_projeto(raiz: Path) -> Projeto:
    raiz = Path(raiz)
    arq = raiz / "config" / "rom.yaml"
    if not arq.is_file():
        raise ErroConfig(f"configuração não encontrada: {arq}")
    try:
        dados = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ErroConfig(f"{arq.name}: YAML inválido: {e}") from None
    return Projeto(raiz=raiz, rom=dados)


def carregar_cfg_texto(raiz: Path) -> dict:
    """Lê ``config/texto.yaml`` (vazio = ``{}``); erros viram ``ErroConfig``."""
    arq = Path(raiz) / "config" / "texto.yaml"
    try:
        dados = yaml.safe_load(arq.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ErroConfig(f"{arq.name}: {e}") from None
    if dados is None:
        return {}
    if not isinstance(dados, dict):
        raise ErroConfig(f"{arq.name}: o arquivo deve ser um mapeamento (chave: valor)")
    return dados
