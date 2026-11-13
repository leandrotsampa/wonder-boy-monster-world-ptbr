"""Espaço livre da ROM compartilhado pelas etapas do build (``regiao_destino``).

O texto realocado vai primeiro (``etapa_texto``, a partir de ``0xA4C80``); o que
mais precisar de espaço (blocos da fonte que não cabem no lugar) vai depois, na
ordem em que as etapas rodam. Um ``RegiaoLivre`` por build fica em
``Projeto.regiao`` (``cmd_construir`` zera antes das etapas).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .compensacao import area_compensacao, sobrepoe
from .config import ErroConfig, Projeto, carregar_cfg_texto


class ErroEspaco(Exception):
    """Não há espaço na região livre para o que a etapa precisa gravar."""


def regiao_destino(cfg: dict) -> tuple[int, int]:
    reg = cfg.get("regiao_destino")
    if (not isinstance(reg, list) or len(reg) != 2 or not all(isinstance(v, int) for v in reg)
            or not 0 <= reg[0] < reg[1]):
        raise ErroConfig(f"texto.yaml: regiao_destino inválida: {reg!r} (use [inicio, fim])")
    return reg[0], reg[1]


@dataclass
class RegiaoLivre:
    """Alocador sequencial em ``[inicio, limite)``; ``usos`` = (nome, início, tamanho)."""

    inicio: int
    limite: int
    usos: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def pos(self) -> int:
        """Primeiro byte livre."""
        if not self.usos:
            return self.inicio
        _, ini, tam = self.usos[-1]
        return ini + tam

    @property
    def usado(self) -> int:
        """Bytes ocupados desde ``inicio`` (inclui o padding de alinhamento)."""
        return self.pos - self.inicio

    def alinhar(self, alinhamento: int = 1) -> int:
        return self.pos + (-self.pos % alinhamento)

    def reservar(self, nome: str, tamanho: int, alinhamento: int = 1) -> int:
        ini = self.alinhar(alinhamento)
        if ini + tamanho > self.limite:
            raise ErroEspaco(
                f"{nome}: {tamanho} bytes não cabem na região livre {self.inicio:#x}-"
                f"{self.limite:#x} (já usados {self.usado} de {self.limite - self.inicio}; "
                f"faltam {ini + tamanho - self.limite})")
        self.usos.append((nome, ini, tamanho))
        return ini


def regiao_livre(projeto: Projeto, tamanho_rom: int) -> RegiaoLivre:
    """A região do build em curso (criada de ``config/texto.yaml`` na 1.ª chamada)."""
    if projeto.regiao is None:
        inicio, limite = regiao_destino(carregar_cfg_texto(projeto.raiz))
        if limite > tamanho_rom:
            raise ErroEspaco(f"regiao_destino termina em {limite:#x}, depois do fim da ROM "
                             f"({tamanho_rom:#x})")
        area = area_compensacao(projeto, tamanho_rom)
        if sobrepoe(inicio, limite, area):
            raise ErroEspaco(f"regiao_destino {inicio:#x}-{limite:#x} cobre a área de "
                             f"compensação do CRC32/checksum em {area:#x} (rom.yaml); "
                             f"termine a região em {area:#x}")
        projeto.regiao = RegiaoLivre(inicio, limite)
    return projeto.regiao
