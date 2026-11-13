"""Desmontador de script por descida recursiva (ver ``opcodes.py``)."""

from __future__ import annotations

from dataclasses import dataclass

from ferramentas.script.opcodes import (
    CHAR_MIN,
    FIM,
    OPS,
    PREFIXOS_CHAR,
    SALTO_INCONDICIONAL,
    SUBOPS_0B,
    SUBOPS_FIM,
)


class ErroScript(Exception):
    """Script inválido: fora dos limites, sobreposição ou opcode desconhecido."""


@dataclass(frozen=True)
class Instr:
    end: int
    op: int  # -1 = caractere
    sub: int | None
    args: tuple[int, ...]
    alvos: tuple[int, ...]
    tam: int


def _decodificar(rom: bytes, end: int, limites: tuple[int, int]) -> tuple[Instr, bool]:
    """Decodifica a instrução em ``end``; retorna (instr, o fluxo continua?)."""
    ini, fim = limites

    def byte(pos: int) -> int:
        if not ini <= pos < fim:
            raise ErroScript(f"leitura em {pos:#x} fora dos limites {ini:#x}-{fim:#x}")
        return rom[pos]

    b = byte(end)
    if b >= CHAR_MIN:
        if b in PREFIXOS_CHAR:
            return Instr(end, -1, None, (b, byte(end + 1)), (), 2), True
        return Instr(end, -1, None, (b,), (), 1), True

    op = b
    pos = end + 1
    sub = None
    tipos = OPS[op]
    if op == 0x0B:
        sub = byte(pos)
        pos += 1
        if sub not in SUBOPS_0B:
            raise ErroScript(f"subop 0B {sub:#04x} desconhecido em {end:#x}")
        tipos = SUBOPS_0B[sub]

    args: list[int] = []
    alvos: list[int] = []
    for t in tipos:
        if t in "BS":
            args.append(byte(pos))
            pos += 1
        elif t in "RW":
            w = (byte(pos) << 8) | byte(pos + 1)
            if t == "R":
                w -= (w & 0x8000) << 1
                alvos.append(pos + w)
            args.append(w)
            pos += 2
        else:  # pragma: no cover - erro de tabela
            raise ErroScript(f"tipo de argumento inválido {t!r}")

    continua = not (op in FIM or op in SALTO_INCONDICIONAL or (sub is not None and sub in SUBOPS_FIM))
    return Instr(end, op, sub, tuple(args), tuple(alvos), pos - end), continua


def desmontar(rom: bytes, raizes: list[int], limites: tuple[int, int]) -> dict[int, Instr]:
    """Desmonta todo o código alcançável a partir das ``raizes``.

    Segue o fluxo contínuo e os alvos de salto. Lança ``ErroScript`` se uma
    instrução cair fora dos ``limites`` (``[inicio, fim)``), se duas instruções se
    sobrepuserem ou se aparecer um opcode/subop desconhecido.
    """
    ini, fim = limites
    instrs: dict[int, Instr] = {}
    dono: dict[int, int] = {}  # byte -> início da instrução que o contém
    origem: dict[int, int | None] = {}  # instrução -> predecessora (None = raiz)

    def cadeia(end: int | None) -> str:
        passos = []
        while end is not None and len(passos) < 12:
            passos.append(f"{end:#x}")
            end = origem.get(end)
        if end is not None:
            passos.append("...")
        return " <- ".join(passos)

    pilha: list[tuple[int, int | None]] = [(r, None) for r in reversed(raizes)]
    while pilha:
        end, de = pilha.pop()
        if end in instrs:
            continue
        if end in dono:
            raise ErroScript(
                f"o fluxo chega a {end:#x}, no meio da instrução em {dono[end]:#x} "
                f"(cadeia: {cadeia(de)})"
            )
        if not ini <= end < fim:
            raise ErroScript(f"instrução em {end:#x} fora dos limites {ini:#x}-{fim:#x} (cadeia: {cadeia(de)})")
        origem[end] = de
        try:
            ins, continua = _decodificar(rom, end, limites)
        except ErroScript as e:
            raise ErroScript(f"{e} (cadeia: {cadeia(end)})") from None
        for e in range(end, end + ins.tam):
            if e in dono:
                raise ErroScript(
                    f"instrução em {end:#x} sobrepõe a instrução em {dono[e]:#x} "
                    f"(cadeia: {cadeia(end)})"
                )
        for e in range(end, end + ins.tam):
            dono[e] = end
        instrs[end] = ins
        for alvo in reversed(ins.alvos):
            pilha.append((alvo, end))
        if continua:
            pilha.append((end + ins.tam, end))
    return instrs
