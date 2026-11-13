"""Segmentação do script desmontado em esqueleto (estrutura) + trechos (texto).

Um **trecho** é uma sequência máxima de instruções de texto contíguas: caracteres,
``01 xx``, ``02``, ``03 xx``, ``04 xx``, ``05``, ``09``, ``0A xx`` e ``0C–0F xx``.
Ele termina antes de qualquer outra instrução e antes de qualquer endereço que
seja raiz ou alvo de salto (um rótulo nunca cai no meio de um trecho).

O esqueleto é uma lista, na ordem de endereço, com um item por instrução
estrutural (``{"rotulo", "op", "sub", "args", "alvos"}``) ou por trecho
(``{"rotulo", "trecho"}``). ``rotulo`` é ``L_<hex>`` quando o endereço é raiz ou
alvo e ``None`` nos demais. ``args`` traz só os argumentos ``B``/``S``/``W``, na
ordem; os saltos (``R``) ficam em ``alvos``, como rótulos, porque o montador os
recalcula.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ferramentas.script.desmontador import Instr
from ferramentas.script.opcodes import CHAR_MIN, FIM, OPS, PREFIXOS_CHAR, SALTO_INCONDICIONAL, SUBOPS_0B, SUBOPS_FIM
from ferramentas.script.raizes import TabelasTexto
from ferramentas.tabela import Tabela

OPS_TEXTO = {0x01, 0x02, 0x03, 0x04, 0x05, 0x09, 0x0A, 0x0C, 0x0D, 0x0E, 0x0F}
_OPS_COM_ARG = {0x01, 0x03, 0x04, 0x0A, 0x0C, 0x0D, 0x0E, 0x0F}
_OPS_ARG_TABELA = {0x01, 0x0C, 0x0D, 0x0E, 0x0F}  # o par op+arg pode ter tag na tabela
_COR = {b"\x01\xa0", b"\x01\x80"}
DICIONARIO_INI = 0x3F
_S0 = re.compile(r"\[s0:([0-9A-F]{2})\]")


@dataclass
class Trecho:
    id: str
    end: int
    bruto: bytes


def rotulo(end: int) -> str:
    return f"L_{end:x}"


def _e_texto(ins: Instr) -> bool:
    return ins.op == -1 or ins.op in OPS_TEXTO


def _bytes(ins: Instr) -> bytes:
    """Bytes de uma instrução de texto (só tem argumentos de 1 byte)."""
    if ins.op == -1:
        return bytes(ins.args)
    return bytes((ins.op, *ins.args))


def _continua(ins: Instr) -> bool:
    if ins.op == -1:
        return True
    return not (ins.op in FIM or ins.op in SALTO_INCONDICIONAL
                or (ins.sub is not None and ins.sub in SUBOPS_FIM))


def _args_sem_salto(ins: Instr) -> list[int]:
    tipos = SUBOPS_0B[ins.sub] if ins.op == 0x0B else OPS[ins.op]
    return [a for t, a in zip(tipos, ins.args) if t != "R"]


def segmentar(instrs: dict[int, Instr], raizes: dict[str, int]) -> tuple[list[dict], list[Trecho]]:
    """Divide as instruções em esqueleto + trechos (ver docstring do módulo).

    O id de um trecho é ``<raiz>.t<NN>``: a raiz é a primeira (na ordem de endereço
    das raízes; empate pela ordem de ``raizes``) cujo fluxo alcança o trecho, e
    ``NN`` numera, a partir de 00, os trechos dessa raiz na ordem de endereço.
    """
    for nome, end in raizes.items():
        if end not in instrs:
            raise ValueError(f"raiz {nome} ({end:#x}) não é início de instrução")
    rotulados = set(raizes.values())
    for ins in instrs.values():
        rotulados.update(ins.alvos)

    # 1) agrupa em itens, na ordem de endereço
    itens: list[tuple[int, Instr | list[Instr]]] = []
    atual: list[Instr] | None = None
    fim_atual = -1
    for end in sorted(instrs):
        ins = instrs[end]
        if _e_texto(ins):
            if atual is not None and end == fim_atual and end not in rotulados:
                atual.append(ins)
            else:
                atual = [ins]
                itens.append((end, atual))
            fim_atual = end + ins.tam
        else:
            atual = None
            itens.append((end, ins))

    # 2) dono de cada trecho: primeira raiz que o alcança
    trecho_de: dict[int, int] = {}  # endereço da instrução -> índice do item-trecho
    for k, (_, item) in enumerate(itens):
        if isinstance(item, list):
            for ins in item:
                trecho_de[ins.end] = k
    dono: dict[int, str] = {}
    visitado: set[int] = set()
    ordem = sorted(enumerate(raizes.items()), key=lambda x: (x[1][1], x[0]))
    for _, (nome, raiz) in ordem:
        pilha = [raiz]
        while pilha:
            end = pilha.pop()
            if end in visitado:
                continue
            visitado.add(end)
            k = trecho_de.get(end)
            if k is not None:
                dono.setdefault(k, nome)
            ins = instrs[end]
            pilha.extend(ins.alvos)
            if _continua(ins):
                pilha.append(end + ins.tam)

    # 3) ids e saída
    contagem: dict[str, int] = {}
    esqueleto: list[dict] = []
    trechos: list[Trecho] = []
    for k, (end, item) in enumerate(itens):
        rot = rotulo(end) if end in rotulados else None
        if isinstance(item, list):
            nome = dono[k]
            n = contagem.get(nome, 0)
            contagem[nome] = n + 1
            t = Trecho(f"{nome}.t{n:02d}", end, b"".join(_bytes(i) for i in item))
            trechos.append(t)
            esqueleto.append({"rotulo": rot, "trecho": t.id})
        else:
            esqueleto.append({
                "rotulo": rot,
                "op": item.op,
                "sub": item.sub,
                "args": _args_sem_salto(item),
                "alvos": [rotulo(a) for a in item.alvos],
            })
    return esqueleto, trechos


def _hex(b: int) -> str:
    return f"[${b:02X}]"


def exibir_en(bruto: bytes, tabela: Tabela, dicionario: list[str]) -> str:
    """Texto exibido de um trecho; expande ``[s0:XX]`` (XX ≥ 0x3F) pela palavra do dicionário.

    Decodifica instrução por instrução. O argumento de ``01``, ``03``, ``04`` e ``0A``
    sai SEMPRE como ``[$XX]`` (nunca tag nem caractere), para ser um código obrigatório
    em ``checar_controles``; só ``01 A0``/``01 80`` usam a tabela (``[cor]``/``[/cor]``).
    ``0C–0F xx`` usa a tabela; sem entrada, sai ``[$0C][$XX]``. Os demais bytes (caracteres,
    ``FE``/``FF`` + caractere, ``02``, ``05``, ``09``) são decodificados pela tabela.
    """
    partes: list[str] = []
    corrida = bytearray()  # bytes sem argumento, decodificados juntos pela tabela

    def descarregar() -> None:
        if corrida:
            partes.append(tabela.decodificar(bytes(corrida)))
            corrida.clear()

    i = 0
    while i < len(bruto):
        b = bruto[i]
        if b >= CHAR_MIN:
            n = 2 if b in PREFIXOS_CHAR else 1
            corrida += bruto[i:i + n]
            i += n
            continue
        if b not in _OPS_COM_ARG or i + 1 >= len(bruto):
            corrida.append(b)
            i += 1
            continue
        descarregar()
        par = bruto[i:i + 2]
        texto = tabela.decodificar(par) if b in _OPS_ARG_TABELA else ""
        if b == 0x01 and par not in _COR:
            texto = ""
        if not texto or texto.startswith("[$"):
            texto = _hex(b) + _hex(par[1])
        partes.append(texto)
        i += 2
    descarregar()

    def palavra(m: re.Match) -> str:
        k = int(m.group(1), 16) - DICIONARIO_INI
        if 0 <= k < len(dicionario) and dicionario[k]:
            return dicionario[k]
        return m.group(0)

    return _S0.sub(palavra, "".join(partes))


def ler_dicionario(rom: bytes, tabelas: TabelasTexto, tabela: Tabela) -> list[str]:
    """Palavras do dicionário (banco 0, slots 0x3F em diante), sem o terminador ``00``.

    Slots não usados (offset 0) viram ``""``.
    """
    palavras = []
    for nome in tabelas.bancos[0][DICIONARIO_INI:]:
        if nome is None:
            palavras.append("")
            continue
        ini = tabelas.raizes[nome]
        palavras.append(tabela.decodificar(rom[ini:rom.index(b"\x00", ini)]))
    return palavras
