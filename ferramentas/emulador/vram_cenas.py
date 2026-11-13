"""Análise do VRAM por cena: quais tiles da área da fonte (0x00–0xFF) estão em uso.

Lê save states do GPGX (``estado_salvar`` dos roteiros) e, para cada um, mostra:

- os blocos de gráficos carregados nos slots 0–7 (``$FF8E08``, 1 slot = 32 tiles
  em VRAM ``slot × 0x400``; ver docs/tecnico/mapa-rom.md §8);
- quais tiles ``0x00–0xFF`` aparecem nas tabelas de nomes (planos A, B, janela)
  e na tabela de sprites;
- se o conteúdo de cada tile ``0x80–0xFF`` ainda é o da fonte (blocos 0–7
  descomprimidos), zero ou outra coisa.

Uso::

    python -m ferramentas.emulador.vram_cenas build/capturas/cenas/*.estado
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..compressao import TAMANHO_BLOCO, descomprimir, ler_entrada, TIPO_CRU, TIPO_HUFFMAN
from ..config import carregar_projeto
from .libretro import (RAIZ, TAM_RAM, TAM_VRAM, _OFFSET_VRAM_ESTADO, _REL_REGS_VRAM,
                       _desembaralhar, _vram_do_estado)

BYTES_TILE = 32
SLOTS_RAM = 0x8E08          # $FF8E08: 64 words, bloco carregado em cada slot de 1 KB
# $FFA144 (word): total de slots alocados por 0x125C4, que ocupa os slots
# 0x30 - $A144 ... 0x2F. Com 41 ele chegaria ao slot 7 (letras), com 42 ao slot 6 (rótulo
# MOEDAS do HUD, 0xC6-0xCB e 0xD3-0xD8, visível em todo o jogo) e com 43 ao slot 5 (acentos). O limite
# 40 deixa o slot 8 como o mais baixo alocado. Ver vram.md §3.1.
ALOCADOS_RAM = 0xA144
SLOT_TOPO_ALOCADOR = 0x30
MAX_ALOCADOS = SLOT_TOPO_ALOCADOR - 8   # 40
SLOTS_FONTE_FIXOS = (5, 6, 7)  # slot n = bloco n em toda cena com texto (0xA0-0xFF)
_OFFSET_RAM_ESTADO = 16     # work_ram logo depois da string de versão


def regs_do_estado(estado: bytes) -> bytes:
    o = _OFFSET_VRAM_ESTADO + _REL_REGS_VRAM
    return bytes(estado[o:o + 0x20])


def ram_do_estado(estado: bytes) -> bytes:
    return _desembaralhar(estado[_OFFSET_RAM_ESTADO:_OFFSET_RAM_ESTADO + TAM_RAM])


def fonte_da_rom(rom: bytes, blocos: range = range(8)) -> bytes:
    """Tiles 0x00–0xFF como a ROM os carrega (blocos 0–7 em sequência)."""
    dados = bytearray()
    for b in blocos:
        tipo, end = ler_entrada(rom, b)
        if tipo == TIPO_HUFFMAN:
            dados += descomprimir(rom, end)[0]
        elif tipo == TIPO_CRU:
            dados += rom[end:end + TAMANHO_BLOCO]
        else:
            dados += bytes(TAMANHO_BLOCO)
    return bytes(dados)


def checar_invariante_fonte(ram: bytes) -> list[str]:
    """Problemas da invariante da fonte (vram.md §3.1) na RAM do 68000; [] = ok.

    ``$A144`` (word) <= ``MAX_ALOCADOS`` (o alocador não desce abaixo do slot 8) e os
    slots 5–7 com os blocos 5–7.
    """
    problemas = []
    alocados = int.from_bytes(ram[ALOCADOS_RAM:ALOCADOS_RAM + 2], "big")
    if alocados > MAX_ALOCADOS:
        slot = max(SLOT_TOPO_ALOCADOR - alocados, 0)
        problemas.append(f"$A144 = {alocados} (> {MAX_ALOCADOS}): o alocador 0x125C4 "
                         f"alcança o slot {slot} (slots 5-7: acentos, rótulo do HUD e letras)")
    for slot in SLOTS_FONTE_FIXOS:
        bloco = int.from_bytes(ram[SLOTS_RAM + 2 * slot:SLOTS_RAM + 2 * slot + 2], "big")
        if bloco != slot:
            problemas.append(f"slot {slot} tem o bloco {bloco:#05x} (esperado {slot})")
    return problemas


def _tamanho_plano(codigo: int) -> int:
    return {0: 32, 1: 64, 3: 128}.get(codigo & 3, 32)


@dataclass
class Cena:
    nome: str
    slots: list[int]
    #: tile -> conjunto de origens ("A", "B", "J", "S")
    uso: dict[int, set[str]] = field(default_factory=dict)
    #: tile 0x00–0xFF -> "fonte" | "zero" | "outro"
    conteudo: dict[int, str] = field(default_factory=dict)


def analisar(nome: str, estado: bytes, fonte: bytes) -> Cena:
    vram = _desembaralhar(_vram_do_estado(estado))
    regs = regs_do_estado(estado)
    ram = ram_do_estado(estado)
    slots = [int.from_bytes(ram[SLOTS_RAM + 2 * i:SLOTS_RAM + 2 * i + 2], "big") for i in range(8)]
    cena = Cena(nome, slots)

    h40 = bool(regs[12] & 0x01)
    larg, alt = _tamanho_plano(regs[16]), _tamanho_plano(regs[16] >> 4)
    planos = {
        "A": ((regs[2] & 0x38) << 10, larg * alt),
        "B": ((regs[4] & 0x07) << 13, larg * alt),
        "J": ((regs[3] & (0x3C if h40 else 0x3E)) << 10, (64 if h40 else 32) * 32),
    }
    for origem, (base, n) in planos.items():
        for i in range(n):
            end = (base + 2 * i) % TAM_VRAM
            tile = int.from_bytes(vram[end:end + 2], "big") & 0x7FF
            cena.uso.setdefault(tile, set()).add(origem)

    end_sat = (regs[5] & (0x7E if h40 else 0x7F)) << 9
    maximo = 80 if h40 else 64
    i, vistos = 0, set()
    while i not in vistos and i < maximo:
        vistos.add(i)
        e = end_sat + 8 * i
        y = int.from_bytes(vram[e:e + 2], "big") & 0x3FF
        tam, link = vram[e + 2], vram[e + 3] & 0x7F
        attr = int.from_bytes(vram[e + 4:e + 6], "big")
        x = int.from_bytes(vram[e + 6:e + 8], "big") & 0x1FF
        if x and y:   # x = 0 mascara; y = 0 fica fora da tela
            n = (((tam >> 2) & 3) + 1) * ((tam & 3) + 1)
            for t in range(n):
                cena.uso.setdefault(((attr & 0x7FF) + t) & 0x7FF, set()).add("S")
        if link == 0:
            break
        i = link

    for t in range(0x100):
        atual = vram[t * BYTES_TILE:(t + 1) * BYTES_TILE]
        if atual == fonte[t * BYTES_TILE:(t + 1) * BYTES_TILE]:
            cena.conteudo[t] = "fonte"
        elif not any(atual):
            cena.conteudo[t] = "zero"
        else:
            cena.conteudo[t] = "outro"
    return cena


def _faixas(tiles: list[int]) -> str:
    if not tiles:
        return "-"
    partes, ini, ant = [], tiles[0], tiles[0]
    for t in tiles[1:] + [None]:
        if t is not None and t == ant + 1:
            ant = t
            continue
        partes.append(f"{ini:02X}" if ini == ant else f"{ini:02X}-{ant:02X}")
        if t is not None:
            ini = ant = t
    return " ".join(partes)


def relatorio(cena: Cena, inicio: int = 0x80, fim: int = 0x100) -> str:
    faixa = range(inicio, fim)
    linhas = [f"== {cena.nome}",
              "slots 0-7: " + " ".join(f"{s:03X}" for s in cena.slots)]
    for origem, rotulo in (("A", "plano A"), ("B", "plano B"), ("J", "janela"), ("S", "sprites")):
        usados = sorted(t for t in faixa if origem in cena.uso.get(t, ()))
        linhas.append(f"{rotulo:8} usa {inicio:02X}-{fim - 1:02X}: {_faixas(usados)}")
    for tipo in ("fonte", "zero", "outro"):
        linhas.append(f"conteúdo {tipo:5}: {_faixas([t for t in faixa if cena.conteudo[t] == tipo])}")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ferramentas.emulador.vram_cenas",
                                description="Uso dos tiles 0x80–0xFF por cena (save states).")
    p.add_argument("estados", nargs="+", type=Path)
    p.add_argument("--rom", type=Path, help="ROM de referência da fonte (padrão: ROM base)")
    p.add_argument("--inicio", type=lambda s: int(s, 0), default=0x80)
    p.add_argument("--fim", type=lambda s: int(s, 0), default=0x100)
    args = p.parse_args(argv)
    rom = (args.rom or carregar_projeto(RAIZ).caminho_rom).read_bytes()
    fonte = fonte_da_rom(rom)
    for caminho in args.estados:
        cena = analisar(caminho.stem, caminho.read_bytes(), fonte)
        print(relatorio(cena, args.inicio, args.fim))
    return 0


if __name__ == "__main__":
    sys.exit(main())
