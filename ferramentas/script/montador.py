"""Montador de scripts: esqueleto + trechos → bytes, com os saltos recalculados.

Duas passadas: (1) o tamanho de cada item dá o endereço de cada rótulo; (2) os
bytes são emitidos, e cada operando ``R`` vira o word com sinal ``alvo − endereço
do 1º byte do word`` (semântica do op ``06``, ver ``opcodes.py``).

Instruções estruturais são refeitas pela cadeia de tipos do opcode/subop: ``B``/``S``
saem de ``args`` (1 byte), ``W`` também de ``args`` (2 bytes) e cada ``R`` do
próximo rótulo de ``alvos``, na ordem da cadeia (``"BR"``, ``"BRR"``, ``"BBR"``...).

Layout realocado (``montar_texto``), a partir de ``destino``, em 5 blocos::

    [tabela de diálogos + scripts de diálogo] [tabela do banco 0 + strings]
    [banco 1] [banco 2] [banco 3]

A ordem original das instruções é mantida; o bloco do grupo ``g`` começa na 1ª
instrução rotulada com uma raiz desse grupo. Assim o fim do banco 2 inclui o que
vinha antes das primeiras strings do banco 3, e o bloco do banco 3 inclui o
dicionário (strings do banco 0 que, na ROM, ficam depois da tabela do banco 3).
Os rótulos são resolvidos num único mapa global, então saltos e aliases entre
blocos continuam certos. Inserir uma tabela entre dois itens só é permitido se o
item anterior não continuar no seguinte (fall-through), o que vale na ROM base
porque cada fronteira de bloco coincide com uma lacuna (tabela/padding).
As tabelas dos bancos (lidas com ``move.w``) ficam em endereço par.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ferramentas.config import Projeto
from ferramentas.espaco import ErroEspaco, regiao_destino, regiao_livre  # noqa: F401 (reexporta)
from ferramentas.script.opcodes import FIM, OPS, SALTO_INCONDICIONAL, SUBOPS_0B, SUBOPS_FIM
from ferramentas.script.raizes import LIMITES, N_BANCOS, PTR_TAB_DIALOGOS, ler_tabelas
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada, carregar_todos

ARQ_ESQUELETO = Path("dados") / "scripts" / "esqueleto.json"
MODOS = ("original", "traducao")
TAB_MESTRA = 0x211CA  # tabela mestra dos bancos, apontada por 0x1CC10 (que não muda)


class ErroMontagem(Exception):
    """Falha ao montar/realocar o texto (rótulo, salto, espaço, esqueleto)."""


@dataclass
class Layout:
    blocos: list[tuple[int, bytes]]
    ponteiros: list[tuple[int, int]]  # (endereço, valor u32)

    @property
    def tamanho(self) -> int:
        return sum(len(b) for _, b in self.blocos)


# ------------------------------------------------------------------ instruções


def _tipos(item: dict) -> str:
    op, sub = item["op"], item.get("sub")
    if op not in OPS:
        raise ErroMontagem(f"opcode desconhecido {op!r} (rótulo {item.get('rotulo')})")
    if op == 0x0B:
        if sub not in SUBOPS_0B:
            raise ErroMontagem(f"subop 0B desconhecido {sub!r} (rótulo {item.get('rotulo')})")
        return SUBOPS_0B[sub]
    return OPS[op]


def _tamanho(item: dict, bytes_trecho: Callable[[str], bytes]) -> int:
    if "trecho" in item:
        return len(bytes_trecho(item["trecho"]))
    tipos = _tipos(item)
    return 1 + (item["op"] == 0x0B) + sum(1 if t in "BS" else 2 for t in tipos)


def _continua(item: dict) -> bool:
    if "trecho" in item:
        return True
    op, sub = item["op"], item.get("sub")
    return not (op in FIM or op in SALTO_INCONDICIONAL or (op == 0x0B and sub in SUBOPS_FIM))


def _emitir(item: dict, pos: int, rotulos: dict[str, int],
            bytes_trecho: Callable[[str], bytes]) -> bytes:
    if "trecho" in item:
        return bytes_trecho(item["trecho"])
    tipos = _tipos(item)
    args, alvos = list(item.get("args") or []), list(item.get("alvos") or [])
    n_r = tipos.count("R")
    if len(args) != len(tipos) - n_r or len(alvos) != n_r:
        raise ErroMontagem(
            f"instrução {item['op']:#04x}/{item.get('sub')} (rótulo {item.get('rotulo')}): "
            f"esperados {len(tipos) - n_r} args e {n_r} alvos, há {len(args)} e {len(alvos)}")
    saida = bytearray([item["op"]])
    if item["op"] == 0x0B:
        saida.append(item["sub"])
    ia = ir = 0
    for t in tipos:
        if t in "BS":
            saida.append(args[ia] & 0xFF)
            ia += 1
        elif t == "W":
            saida += (args[ia] & 0xFFFF).to_bytes(2, "big")
            ia += 1
        else:  # R
            alvo = alvos[ir]
            ir += 1
            if alvo not in rotulos:
                raise ErroMontagem(f"rótulo {alvo} não definido (salto em {pos:#x})")
            rel = rotulos[alvo] - (pos + len(saida))
            if not -0x8000 <= rel <= 0x7FFF:
                raise ErroMontagem(f"salto em {pos:#x} para {alvo} ({rotulos[alvo]:#x}) "
                                   f"fora do alcance de ±0x8000 ({rel:+#x})")
            saida += struct.pack(">h", rel)
    return bytes(saida)


def _posicoes(instrucoes: list[dict], bytes_trecho, base: int,
              rotulos: dict[str, int]) -> tuple[list[int], int]:
    """1ª passada: endereço de cada item; registra os rótulos em ``rotulos``."""
    posicoes = []
    pos = base
    for item in instrucoes:
        rot = item.get("rotulo")
        if rot is not None:
            if rot in rotulos:
                raise ErroMontagem(f"rótulo {rot} definido duas vezes")
            rotulos[rot] = pos
        posicoes.append(pos)
        pos += _tamanho(item, bytes_trecho)
    return posicoes, pos


def montar_bloco(instrucoes: list[dict], bytes_trecho: Callable[[str], bytes], base: int,
                 rotulos: dict[str, int] | None = None) -> tuple[bytes, dict[str, int]]:
    """Monta ``instrucoes`` a partir de ``base``; devolve (bytes, rótulo → endereço).

    ``rotulos`` (opcional) é um mapa global já calculado, usado para resolver os
    saltos para fora do bloco; o mapa devolvido tem só os rótulos do bloco.
    """
    locais: dict[str, int] = {}
    posicoes, _ = _posicoes(instrucoes, bytes_trecho, base, locais)
    mapa = locais if rotulos is None else rotulos
    saida = bytearray()
    for item, pos in zip(instrucoes, posicoes):
        saida += _emitir(item, pos, mapa, bytes_trecho)
    return bytes(saida), locais


# --------------------------------------------------------------------- trechos


def _fonte_trechos(esqueleto: dict, textos: dict[str, list[Entrada]], tabela: Tabela,
                   modo: str) -> Callable[[str], bytes]:
    if modo not in MODOS:
        raise ErroMontagem(f"modo inválido {modo!r} (use {', '.join(MODOS)})")
    trechos = esqueleto.get("trechos") or {}
    pt = {}
    if modo == "traducao":
        pt = {e.id: e.pt for entradas in textos.values() for e in entradas if e.pt}
    cache: dict[str, bytes] = {}

    def bytes_trecho(tid: str) -> bytes:
        if tid not in cache:
            if tid in pt:
                cache[tid] = tabela.codificar(pt[tid], tid)
            elif tid in trechos:
                cache[tid] = bytes.fromhex(trechos[tid])
            else:
                raise ErroMontagem(f"trecho {tid} ausente do esqueleto")
        return cache[tid]

    return bytes_trecho


# ---------------------------------------------------------------------- tabelas


def _tabelas(esqueleto: dict) -> tuple[list[dict], list[list[str | None]]]:
    try:
        tabs = esqueleto["tabelas"]
        dialogos = list(tabs["dialogos"])
        bancos = [list(tabs["bancos"][str(b)]) for b in range(N_BANCOS)]
    except (KeyError, TypeError) as e:
        raise ErroMontagem(f"esqueleto sem as tabelas de ponteiros ({e}); rode 'extrair'") from None
    return dialogos, bancos


def _endereco_raiz(esqueleto: dict, nome: str, rotulos: dict[str, int]) -> int:
    rot = esqueleto["raizes"].get(nome)
    if rot not in rotulos:
        raise ErroMontagem(f"raiz {nome}: rótulo {rot} não definido")
    return rotulos[rot]


def _offset16(valor: int, oque: str) -> bytes:
    if not -0x8000 <= valor <= 0x7FFF:
        raise ErroMontagem(f"{oque}: offset {valor:+#x} não cabe em 16 bits com sinal")
    return struct.pack(">h", valor)


def _tabela_dialogos(esqueleto, dialogos, base, rotulos) -> bytes:
    saida = bytearray()
    for i, d in enumerate(dialogos):
        flag = int(d["flag"])
        if not 0 <= flag <= 0xFF:
            raise ErroMontagem(f"diálogo {i}: flag {flag} inválida")
        saida.append(flag)
        saida += _offset16(_endereco_raiz(esqueleto, d["raiz"], rotulos) - base, d["raiz"])
    return bytes(saida)


def _tabela_banco(esqueleto, slots, base, rotulos) -> bytes:
    saida = bytearray()
    for nome in slots:
        if nome is None:
            saida += b"\x00\x00"
            continue
        off = _endereco_raiz(esqueleto, nome, rotulos) - base
        if off == 0:
            raise ErroMontagem(f"{nome}: offset 0 seria lido como slot vazio")
        saida += _offset16(off, nome)
    return bytes(saida)


# ------------------------------------------------------------------- realocação


def _inicios_blocos(esqueleto: dict, dialogos, bancos) -> list[int]:
    """Índice da 1ª instrução de cada um dos 5 blocos (+ ``len`` no fim)."""
    instrs = esqueleto["instrucoes"]
    raizes = esqueleto["raizes"]

    def rot(nome: str) -> str:
        if nome not in raizes:
            raise ErroMontagem(f"raiz {nome} das tabelas não está em 'raizes' do esqueleto")
        return raizes[nome]

    grupos = [{rot(d["raiz"]) for d in dialogos}]
    grupos += [{rot(n) for n in slots if n is not None} for slots in bancos]
    primeiro = {}
    for i, item in enumerate(instrs):
        r = item.get("rotulo")
        if r is None:
            continue
        for g in range(1, len(grupos)):
            if g not in primeiro and r in grupos[g]:
                primeiro[g] = i
    inicios = [0] + [None] * (len(grupos) - 1) + [len(instrs)]
    for g in range(len(grupos) - 1, 0, -1):
        inicios[g] = primeiro.get(g, inicios[g + 1])
    for g in range(1, len(inicios)):
        if inicios[g] < inicios[g - 1]:
            raise ErroMontagem("as strings dos bancos não seguem a ordem dos blocos "
                               "(diálogos, banco 0, 1, 2, 3); layout não suportado")
    for s in set(inicios[1:-1]):
        if 0 < s < len(instrs) and _continua(instrs[s - 1]):
            raise ErroMontagem(
                f"a instrução antes de {instrs[s].get('rotulo')} continua nela (fall-through); "
                "não dá para inserir a tabela do banco entre as duas")
    return inicios


def montar_texto(esqueleto: dict, textos: dict[str, list[Entrada]], tabela: Tabela,
                 destino: int, limite: int, modo: str = "traducao") -> Layout:
    """Monta todo o texto realocado em ``[destino, limite)`` (ver docstring do módulo)."""
    bytes_trecho = _fonte_trechos(esqueleto, textos, tabela, modo)
    dialogos, bancos = _tabelas(esqueleto)
    extras = sorted(n for n in esqueleto.get("raizes", {}) if n.startswith("extra."))
    if extras:
        raise ErroMontagem(
            f"raizes_extra ({', '.join(extras)}) não suportadas: a config guarda o endereço do "
            "script, não o da referência no código que teria de ser atualizada")
    if destino % 2:
        raise ErroMontagem(f"destino {destino:#x} precisa ser par")
    instrs = esqueleto["instrucoes"]
    inicios = _inicios_blocos(esqueleto, dialogos, bancos)
    tam_tabelas = [3 * len(dialogos)] + [2 * len(s) for s in bancos]

    # 1ª passada: endereços das tabelas e dos rótulos (mapa global)
    rotulos: dict[str, int] = {}
    blocos_pos = []  # (início do bloco, endereço da tabela, posições, fim sem padding)
    pos = destino
    for g in range(len(tam_tabelas)):
        ini = pos
        fatia = instrs[inicios[g]:inicios[g + 1]]
        posicoes, fim = _posicoes(fatia, bytes_trecho, ini + tam_tabelas[g], rotulos)
        blocos_pos.append((ini, posicoes, fim))
        pos = fim + (fim % 2)  # a próxima tabela de banco fica em endereço par
    total = pos - destino
    if pos > limite:
        raise ErroMontagem(
            f"o texto montado ocupa {total} bytes e excede a região {destino:#x}-{limite:#x} "
            f"({limite - destino} bytes) em {pos - limite} bytes")

    # 2ª passada: bytes
    blocos = []
    for g, (ini, posicoes, fim) in enumerate(blocos_pos):
        if g == 0:
            saida = bytearray(_tabela_dialogos(esqueleto, dialogos, ini, rotulos))
        else:
            saida = bytearray(_tabela_banco(esqueleto, bancos[g - 1], ini, rotulos))
        fatia = instrs[inicios[g]:inicios[g + 1]]
        for item, p in zip(fatia, posicoes):
            saida += _emitir(item, p, rotulos, bytes_trecho)
        if fim % 2:
            saida.append(0x00)
        blocos.append((ini, bytes(saida)))

    ponteiros = [(PTR_TAB_DIALOGOS, blocos[0][0])]
    ponteiros += [(TAB_MESTRA + 4 * b, blocos[b + 1][0]) for b in range(N_BANCOS)]
    return Layout(blocos, ponteiros)


def aplicar_layout(rom: bytearray, layout: Layout) -> None:
    for ini, dados in layout.blocos:
        if ini + len(dados) > len(rom):
            raise ErroMontagem(f"bloco em {ini:#x} ({len(dados)} bytes) passa do fim da ROM")
        rom[ini:ini + len(dados)] = dados
    for end, valor in layout.ponteiros:
        rom[end:end + 4] = valor.to_bytes(4, "big")


# --------------------------------------------------------------------- no lugar


def montar_no_lugar(rom: bytes, esqueleto: dict, cfg: dict) -> bytes:
    """Remonta, nos endereços originais, a faixa ``[tabela de diálogos, LIMITES[1])``.

    Só para o teste de identidade (modo original). A faixa é montada do zero: as
    tabelas (diálogos, mestra, bancos) e as instruções, em sequência, pulando as
    lacunas (tabelas e ``lacunas_conhecidas``). Só os bytes de ``lacunas_conhecidas``
    (código morto e padding, que nenhuma raiz alcança) são copiados da ROM; qualquer
    outro byte não escrito lança ``ErroMontagem``.
    """
    bytes_trecho = _fonte_trechos(esqueleto, {}, Tabela({}), "original")
    dialogos, bancos = _tabelas(esqueleto)
    try:
        t = ler_tabelas(rom)
    except ValueError as e:
        raise ErroMontagem(str(e)) from None
    ini, fim = t.tab_dialogos, LIMITES[1]
    lacunas = [(int(l["inicio"]), int(l["fim"])) for l in cfg.get("lacunas_conhecidas") or []]
    buracos = sorted([(t.tab_dialogos, t.tab_dialogos + 3 * len(dialogos)),
                      (t.tab_mestra, t.tab_mestra + 4 * N_BANCOS)]
                     + [(t.bases[b], t.bases[b] + 2 * len(bancos[b])) for b in range(N_BANCOS)]
                     + lacunas)

    # 1ª passada: posições, pulando os buracos
    rotulos: dict[str, int] = {}
    posicoes = []
    pos = ini
    for item in esqueleto["instrucoes"]:
        for a, b in buracos:
            if a <= pos < b:
                pos = b
        rot = item.get("rotulo")
        if rot is not None:
            if rot in rotulos:
                raise ErroMontagem(f"rótulo {rot} definido duas vezes")
            rotulos[rot] = pos
        posicoes.append(pos)
        pos += _tamanho(item, bytes_trecho)

    buf = bytearray(fim - ini)
    escrito = bytearray(fim - ini)

    def escrever(end: int, dados: bytes) -> None:
        if not (ini <= end and end + len(dados) <= fim):
            raise ErroMontagem(f"escrita em {end:#x} fora da faixa {ini:#x}-{fim:#x}")
        for k in range(end - ini, end - ini + len(dados)):
            if escrito[k]:
                raise ErroMontagem(f"byte {ini + k:#x} escrito duas vezes")
            escrito[k] = 1
        buf[end - ini:end - ini + len(dados)] = dados

    escrever(t.tab_dialogos, _tabela_dialogos(esqueleto, dialogos, t.tab_dialogos, rotulos))
    escrever(t.tab_mestra, b"".join(t.bases[b].to_bytes(4, "big") for b in range(N_BANCOS)))
    for b in range(N_BANCOS):
        escrever(t.bases[b], _tabela_banco(esqueleto, bancos[b], t.bases[b], rotulos))
    for item, p in zip(esqueleto["instrucoes"], posicoes):
        escrever(p, _emitir(item, p, rotulos, bytes_trecho))

    for a, b in lacunas:
        for e in range(max(a, ini), min(b, fim)):
            if not escrito[e - ini]:
                buf[e - ini] = rom[e]
                escrito[e - ini] = 1
    if not all(escrito):
        e = ini + escrito.index(0)
        raise ErroMontagem(f"byte {e:#x} não coberto pela montagem nem pelas lacunas conhecidas")
    return bytes(buf)


# ------------------------------------------------------------------------ build


def carregar_esqueleto(raiz: Path) -> dict:
    arq = Path(raiz) / ARQ_ESQUELETO
    if not arq.is_file():
        raise ErroMontagem(f"{ARQ_ESQUELETO.as_posix()} não encontrado; rode "
                           "'python -m ferramentas extrair' antes de construir")
    try:
        esq = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ErroMontagem(f"{arq.name}: JSON inválido: {e}") from None
    if not isinstance(esq, dict) or not {"raizes", "instrucoes", "trechos", "tabelas"} <= set(esq):
        raise ErroMontagem(f"{arq.name}: formato inválido; rode 'extrair' de novo")
    return esq


def etapa_texto(rom: bytearray, projeto: Projeto) -> None:
    """Etapa do build: monta o texto traduzido e o grava realocado em ``regiao_destino``.

    O texto é a 1.ª coisa reservada na região livre compartilhada (``Projeto.regiao``):
    começa no endereço par seguinte ao que já estiver ocupado (no build, ``destino``).
    """
    esqueleto = carregar_esqueleto(projeto.raiz)
    try:
        regiao = regiao_livre(projeto, len(rom))
    except ErroEspaco as e:
        raise ErroMontagem(str(e)) from None
    trad = projeto.raiz / "traducao"
    arq_tbl = trad / "tabela.tbl"
    if not arq_tbl.is_file():
        raise ErroMontagem(f"{arq_tbl} não encontrada")
    tabela = Tabela.carregar(arq_tbl)
    destino = regiao.alinhar(2)
    layout = montar_texto(esqueleto, carregar_todos(trad / "textos"), tabela, destino,
                          regiao.limite)
    regiao.reservar("texto", layout.tamanho, alinhamento=2)
    aplicar_layout(rom, layout)
