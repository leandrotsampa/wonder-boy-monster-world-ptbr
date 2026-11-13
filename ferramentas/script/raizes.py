"""Raízes dos scripts: tabela de diálogos e tabela mestra dos bancos de strings.

Ver docs/tecnico/mapa-rom.md §3–§4. Os endereços das duas tabelas vêm da tabela
global de ponteiros do jogo (``0x1CC14`` → diálogos, ``0x1CC10`` → tabela mestra),
para que a leitura funcione também numa ROM com o texto realocado.

Nomes lógicos das raízes:

- ``dialogo.NNN`` (``NNN`` decimal, ``000``–``130``);
- ``bB.XXX`` (banco ``B`` = 0–3, ``XXX`` = índice do slot em hexadecimal maiúsculo);
- ``extra.<hex>`` (``raizes_extra`` de ``config/texto.yaml``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

PTR_TAB_MESTRA = 0x1CC10
PTR_TAB_DIALOGOS = 0x1CC14
N_BANCOS = 4
# Faixa dos scripts na ROM base (1º script de diálogo .. fim das strings do banco 0).
LIMITES = (0x1DF1D, 0x22460)


@dataclass
class TabelasTexto:
    tab_dialogos: int
    tab_mestra: int
    dialogos: list[tuple[str, int]]  # (nome, flag), na ordem da tabela
    bases: dict[int, int]  # banco -> endereço da tabela de offsets
    bancos: dict[int, list[str | None]]  # banco -> nome por slot (None = offset 0)
    raizes: dict[str, int] = field(default_factory=dict)  # nome -> endereço, em ordem

    def faixas_tabelas_bancos(self) -> list[tuple[int, int]]:
        """Faixas ``[ini, fim)`` das tabelas de offsets de cada banco (dado, não código)."""
        return [(self.bases[b], self.bases[b] + 2 * len(self.bancos[b])) for b in range(N_BANCOS)]


def _s16(rom: bytes, end: int) -> int:
    return struct.unpack_from(">h", rom, end)[0]


def _u32(rom: bytes, end: int) -> int:
    return struct.unpack_from(">I", rom, end)[0]


def _contar(offsets, passo: int, limite: int, oque: str) -> int:
    """Entradas = menor offset positivo // passo (a tabela termina onde o 1º alvo começa)."""
    menor = None
    i = 0
    while True:
        o = offsets(i)
        if o > 0 and (menor is None or o < menor):
            menor = o
        i += 1
        if menor is not None and i >= menor // passo:
            return menor // passo
        if i > limite:
            raise ValueError(f"{oque}: contagem de entradas não determinada")


def ler_tabelas(rom: bytes, raizes_extra=()) -> TabelasTexto:
    """Lê a tabela de diálogos, as tabelas dos 4 bancos e monta as raízes nomeadas."""
    tab_d = _u32(rom, PTR_TAB_DIALOGOS)
    tab_m = _u32(rom, PTR_TAB_MESTRA)
    raizes: dict[str, int] = {}

    n = _contar(lambda i: _s16(rom, tab_d + 3 * i + 1), 3, 0x400, "tabela de diálogos")
    dialogos = []
    for i in range(n):
        nome = f"dialogo.{i:03d}"
        dialogos.append((nome, rom[tab_d + 3 * i]))
        raizes[nome] = tab_d + _s16(rom, tab_d + 3 * i + 1)

    bases: dict[int, int] = {}
    bancos: dict[int, list[str | None]] = {}
    for b in range(N_BANCOS):
        base = bases[b] = _u32(rom, tab_m + 4 * b)
        n = _contar(lambda i: _s16(rom, base + 2 * i), 2, 0x100, f"banco {b}")
        slots: list[str | None] = []
        for i in range(n):
            o = _s16(rom, base + 2 * i)
            if o == 0:
                slots.append(None)
                continue
            nome = f"b{b}.{i:03X}"
            slots.append(nome)
            raizes[nome] = base + o
        bancos[b] = slots

    for end in raizes_extra:
        raizes[f"extra.{int(end):x}"] = int(end)
    return TabelasTexto(tab_d, tab_m, dialogos, bases, bancos, raizes)
