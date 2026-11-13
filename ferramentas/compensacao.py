"""CRC32 do arquivo e checksum do cabeçalho iguais aos da ROM original.

Última etapa do build (``cmd_construir``, depois de ``corrigir_cabecalho``). A área de
compensação são os ``TAMANHO`` (8) bytes do fim da ROM (``compensacao`` em
``config/rom.yaml``, ``0xBFFF8``): ``FF`` na base, fora de ``regiao_destino`` e de
qualquer patch, e nunca lidos pelo jogo (mapa-rom.md §7). Layout::

    inicio+0  word V  \\ livres: procurados até a soma do cabeçalho bater
    inicio+2  word W  /
    inicio+4  4 bytes F: forjados para o CRC32 do arquivo dar o original

O checksum do cabeçalho (``0x18E``) recebe o valor da original; a soma das words de
``0x200`` ao fim tem de dar esse valor. Como F muda a soma e V/W mudam o CRC, os dois
são resolvidos juntos: para cada (V, W) em ordem crescente, F é forjado (O(1)) e a soma
conferida; a 1.ª combinação que fecha a soma é a usada (determinístico). Cada (V, W)
acerta a soma com chance ~1/65536, então a busca termina em ~65 mil tentativas.

Se a ROM já tem o CRC32 e o checksum da original (ex.: build sem mudanças), nada é
gravado e a área continua ``FF``.
"""

from __future__ import annotations

import zlib

from .config import Projeto
from .rom import INICIO_SOMA, OFFSET_CHECKSUM

TAMANHO = 8

_POLI = 0xEDB88320


def _tabela() -> list[int]:
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ _POLI if c & 1 else c >> 1
        tab.append(c)
    return tab


_TAB = _tabela()
#: índice da tabela pelo byte alto da entrada (único em todo o CRC32)
_INV = {v >> 24: i for i, v in enumerate(_TAB)}


class ErroCompensacao(Exception):
    pass


def forjar_crc32(estado: int, alvo: int) -> bytes:
    """4 bytes ``F`` tais que ``zlib.crc32(F, estado) == alvo``.

    O registrador interno é o CRC com os bits invertidos. Andando para trás a partir
    do registrador final, o byte alto de cada passo identifica o índice da tabela
    usado (os bytes altos das 256 entradas são distintos); com os 4 índices, o
    passo para frente a partir do estado dá os bytes.
    """
    reg = alvo ^ 0xFFFFFFFF
    indices = []
    for _ in range(4):
        i = _INV[reg >> 24]
        indices.append(i)
        reg = ((reg ^ _TAB[i]) << 8) & 0xFFFFFFFF
    reg = estado ^ 0xFFFFFFFF
    saida = bytearray()
    for i in reversed(indices):
        saida.append((reg ^ i) & 0xFF)
        reg = (reg >> 8) ^ _TAB[i]
    return bytes(saida)


def area_compensacao(projeto: Projeto, tamanho_rom: int) -> int | None:
    """Início da área (``compensacao`` em ``config/rom.yaml``); ``None`` = sem compensação."""
    inicio = projeto.rom.get("compensacao")
    if inicio is None:
        return None
    if (not isinstance(inicio, int) or isinstance(inicio, bool) or inicio % 2
            or inicio < INICIO_SOMA or inicio + TAMANHO != tamanho_rom):
        raise ErroCompensacao(
            f"rom.yaml: compensacao inválida: {inicio!r} (use o endereço par dos últimos "
            f"{TAMANHO} bytes da ROM, {tamanho_rom - TAMANHO:#x})")
    return inicio


def sobrepoe(inicio: int, fim: int, area: int | None) -> bool:
    """``[inicio, fim)`` toca a área de compensação ``[area, area + TAMANHO)``?"""
    return area is not None and inicio < area + TAMANHO and area < fim


def _soma(dados: bytes) -> int:
    return sum(int.from_bytes(dados[i:i + 2], "big") for i in range(0, len(dados), 2))


def compensar(rom: bytearray, original: bytes, inicio: int) -> bool:
    """Grava a área para ``rom`` ter o CRC32 e o checksum de ``original``.

    Retorna ``False`` (sem gravar nada) se já estão iguais. A área tem de estar no fim,
    em endereço par e com os mesmos bytes da original (nenhuma etapa pode tê-la usado).
    """
    if (len(rom) != len(original) or inicio % 2 or inicio < INICIO_SOMA
            or inicio + TAMANHO != len(rom)):
        raise ErroCompensacao(
            f"área de compensação em {inicio:#x} inválida: tem de ser par e ocupar os "
            f"últimos {TAMANHO} bytes da ROM ({len(rom):#x} bytes, igual à original)")
    if rom[inicio:] != original[inicio:]:
        raise ErroCompensacao(
            f"a área de compensação {inicio:#x}-{len(rom):#x} foi alterada por outra etapa "
            "do build (reservada para o CRC32/checksum)")
    alvo_crc = zlib.crc32(original) & 0xFFFFFFFF
    campo = bytes(original[OFFSET_CHECKSUM:OFFSET_CHECKSUM + 2])
    alvo_soma = int.from_bytes(campo, "big")
    rom[OFFSET_CHECKSUM:OFFSET_CHECKSUM + 2] = campo
    if zlib.crc32(rom) & 0xFFFFFFFF == alvo_crc and _soma(rom[INICIO_SOMA:]) & 0xFFFF == alvo_soma:
        return False
    falta = (alvo_soma - _soma(rom[INICIO_SOMA:inicio])) & 0xFFFF
    estado = zlib.crc32(rom[:inicio])
    crc32 = zlib.crc32
    for v in range(0x10000):
        bv = v.to_bytes(2, "big")
        estado_v = crc32(bv, estado)
        resto = (falta - v) & 0xFFFF
        for w in range(0x10000):
            bw = w.to_bytes(2, "big")
            f = forjar_crc32(crc32(bw, estado_v), alvo_crc)
            if (w + (f[0] << 8 | f[1]) + (f[2] << 8 | f[3])) & 0xFFFF == resto:
                rom[inicio:] = bv + bw + f
                return True
    raise ErroCompensacao("nenhuma combinação fecha o CRC32 e o checksum")  # pragma: no cover
