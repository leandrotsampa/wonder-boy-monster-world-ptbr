"""Auditoria de referências absolutas de 32 bits a uma faixa da ROM.

Varre linearmente as regiões de código com o capstone (68000) e lista cada
operando absoluto longo (``$xxxx.l``) ou imediato de 32 bits (``#$xxxx``) cujo
valor cai em ``[inicio, fim)``. Requer ``capstone`` (requirements-dev.txt).
"""

from __future__ import annotations

REGIOES_CODIGO = [(0x200, 0x1C600)]


def referencias_absolutas(
    rom: bytes,
    inicio: int,
    fim: int,
    regioes: list[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Retorna [(endereço do operando, valor)] ordenado por endereço."""
    from capstone import CS_ARCH_M68K, CS_MODE_M68K_000, Cs
    from capstone.m68k import (
        M68K_AM_ABSOLUTE_DATA_LONG,
        M68K_OP_IMM,
        M68K_OP_MEM,
    )

    md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)
    md.detail = True
    achadas: list[tuple[int, int]] = []
    for ini, fm in regioes or REGIOES_CODIGO:
        pos = ini
        while pos < fm:
            decodificou = False
            for ins in md.disasm(bytes(rom[pos:fm]), pos):
                decodificou = True
                pos = ins.address + ins.size
                if ins.id == 0:  # dado (skipdata)
                    continue
                for op in ins.operands:
                    absoluto = op.type == M68K_OP_MEM and op.address_mode == M68K_AM_ABSOLUTE_DATA_LONG
                    if not (absoluto or op.type == M68K_OP_IMM):
                        continue
                    valor = op.imm & 0xFFFFFFFF
                    if not inicio <= valor < fim:
                        continue
                    alvo = valor.to_bytes(4, "big")
                    # o operando é a última ocorrência dos 4 bytes (alinhada a word)
                    for off in range(ins.size - 4, 1, -2):
                        if bytes(ins.bytes[off:off + 4]) == alvo:
                            achadas.append((ins.address + off, valor))
                            break
            if not decodificou:
                pos += 2  # byte(s) indecodificável(is): dado no meio do código
            elif pos < fm:
                pos += 2  # o disasm parou numa instrução inválida
    return sorted(set(achadas))


def referencias_a(
    rom: bytes,
    inicio: int,
    fim: int,
    regioes: list[tuple[int, int]] | None = None,
) -> list[int]:
    """Endereços das instruções que apontam para ``[inicio, fim)``.

    Força bruta: decodifica uma instrução em **cada** endereço par das regiões (não depende
    de uma varredura linear sincronizada) e aceita operando PC-relativo (``d16(pc)`` e
    ``d8(pc,Xn)``), absoluto (``.w``/``.l``) ou imediato. Pode trazer falso positivo em
    dados no meio do código; nunca perde uma referência direta.
    """
    from capstone import CS_ARCH_M68K, CS_MODE_M68K_000, Cs
    from capstone.m68k import (
        M68K_AM_ABSOLUTE_DATA_LONG,
        M68K_AM_ABSOLUTE_DATA_SHORT,
        M68K_AM_PCI_DISP,
        M68K_AM_PCI_INDEX_8_BIT_DISP,
        M68K_OP_IMM,
        M68K_OP_MEM,
    )

    md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)
    md.detail = True
    achadas: list[int] = []
    for ini, fm in regioes or REGIOES_CODIGO:
        for pos in range(ini, fm, 2):
            for ins in md.disasm(bytes(rom[pos:min(pos + 10, fm)]), pos, 1):
                if ins.id == 0:
                    continue
                for op in ins.operands:
                    valor = None
                    if op.type == M68K_OP_MEM:
                        if op.address_mode in (M68K_AM_PCI_DISP, M68K_AM_PCI_INDEX_8_BIT_DISP):
                            valor = (pos + 2 + op.mem.disp) & 0xFFFFFF
                        elif op.address_mode in (M68K_AM_ABSOLUTE_DATA_LONG,
                                                 M68K_AM_ABSOLUTE_DATA_SHORT):
                            valor = op.imm & 0xFFFFFFFF
                    elif op.type == M68K_OP_IMM:
                        valor = op.imm & 0xFFFFFFFF
                    if valor is not None and inicio <= valor < fim:
                        achadas.append(pos)
                        break
    return sorted(set(achadas))


def referencias_ram(
    rom: bytes,
    inicio: int,
    fim: int,
    regioes: list[tuple[int, int]] | None = None,
) -> list[int]:
    """Endereços das instruções que apontam para a RAM em ``$FF0000 + [inicio, fim)``.

    Força bruta como ``referencias_a`` (uma instrução em cada endereço par), mas só aceita
    o que endereça a RAM: absoluto ``.w`` de ``$8000`` a ``$FFFF`` (estendido com sinal
    para ``$FF8000-$FFFFFF``), absoluto ``.l`` em ``$E00000-$FFFFFF`` (a RAM e os
    espelhos dela) e imediato carregado num registrador de endereço (``movea``/``adda``/
    ``suba``/``cmpa``). PC-relativo e imediato em registrador de dado ficam de fora (ROM
    ou valores). Acessos por base + deslocamento (``d16(An)``) não entram: a base vem de
    uma destas referências ou de cálculo, e a varredura no emulador cobre o resto.
    """
    from capstone import CS_ARCH_M68K, CS_MODE_M68K_000, Cs
    from capstone.m68k import (
        M68K_AM_ABSOLUTE_DATA_LONG,
        M68K_AM_ABSOLUTE_DATA_SHORT,
        M68K_OP_IMM,
        M68K_OP_MEM,
    )

    md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)
    md.detail = True
    achadas: list[int] = []
    for ini, fm in regioes or REGIOES_CODIGO:
        for pos in range(ini, fm, 2):
            for ins in md.disasm(bytes(rom[pos:min(pos + 10, fm)]), pos, 1):
                if ins.id == 0:
                    continue
                curto = ins.mnemonic.endswith(".w")
                for op in ins.operands:
                    valor = None
                    if op.type == M68K_OP_MEM and op.address_mode == M68K_AM_ABSOLUTE_DATA_SHORT:
                        v = op.imm & 0xFFFF
                        valor = v if v & 0x8000 else None
                    elif op.type == M68K_OP_MEM and op.address_mode == M68K_AM_ABSOLUTE_DATA_LONG:
                        v = op.imm & 0xFFFFFF
                        valor = v & 0xFFFF if v >= 0xE00000 else None
                    elif op.type == M68K_OP_IMM and ins.mnemonic.startswith(
                            ("movea", "adda", "suba", "cmpa")):
                        if curto:
                            v = op.imm & 0xFFFF
                            valor = v if v & 0x8000 else None
                        else:
                            v = op.imm & 0xFFFFFF
                            valor = v & 0xFFFF if v >= 0xE00000 else None
                    if valor is not None and inicio <= valor < fim:
                        achadas.append(pos)
                        break
    return sorted(set(achadas))
