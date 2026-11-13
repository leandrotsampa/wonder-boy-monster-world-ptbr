"""Segmentação dos scripts em esqueleto + trechos e codec de texto."""

from pathlib import Path

import yaml

from ferramentas.script.desmontador import desmontar
from ferramentas.script.raizes import LIMITES, ler_tabelas
from ferramentas.script.segmentos import exibir_en, ler_dicionario, segmentar
from ferramentas.tabela import Tabela

RAIZ = Path(__file__).resolve().parent.parent
TABELA = RAIZ / "traducao" / "tabela.tbl"


def _seg(rom: bytes, raizes: dict[str, int]):
    instrs = desmontar(rom, list(raizes.values()), (0, len(rom)))
    return segmentar(instrs, raizes)


def test_trecho_quebrado_por_rotulo():
    # 06 em 12, word em 13: alvo = 13 + (-7) = 6 ("W")
    rom = b"Hello World\x00" + b"\x06\xff\xf9"
    esq, trechos = _seg(rom, {"a": 0, "b": 12})
    assert [t.bruto for t in trechos] == [b"Hello ", b"World"]
    assert [t.id for t in trechos] == ["a.t00", "a.t01"]
    assert [t.end for t in trechos] == [0, 6]
    assert esq[1] == {"rotulo": "L_6", "trecho": "a.t01"}
    assert esq[3] == {"rotulo": "L_c", "op": 6, "sub": None, "args": [], "alvos": ["L_6"]}


def test_estrutural_separa():
    from ferramentas.script.opcodes import SUBOPS_0B
    assert SUBOPS_0B[0x19] == "B"
    rom = b"Hi\x0b\x19\x05Yo\x00"
    esq, trechos = _seg(rom, {"r": 0})
    assert [t.bruto for t in trechos] == [b"Hi", b"Yo"]
    assert esq == [
        {"rotulo": "L_0", "trecho": "r.t00"},
        {"rotulo": None, "op": 0x0B, "sub": 0x19, "args": [5], "alvos": []},
        {"rotulo": None, "trecho": "r.t01"},
        {"rotulo": None, "op": 0, "sub": None, "args": [], "alvos": []},
    ]


def test_codigos_de_texto_ficam_no_trecho():
    rom = b"A\x01\xa0B\x01\x80\x02\x03\x04\x04\x02\x05\x09\x0a\x01\x0c\x54\x0d\x01\xfe\xd6\x00"
    _, trechos = _seg(rom, {"r": 0})
    assert len(trechos) == 1 and trechos[0].bruto == rom[:-1]


def test_exibir_dicionario():
    tabela = Tabela.carregar(TABELA)
    dicionario = [f"w{i}" for i in range(0x54 - 0x3F)] + ["Monster"]
    assert exibir_en(b"\x0c\x54 was", tabela, dicionario) == "Monster was"
    assert exibir_en(b"\x0c\x05", tabela, dicionario) == "[s0:05]"


def test_exibir_argumento_de_controle_sempre_hex():
    # o argumento de 01/03/04/0A nunca vira tag nem caractere (seria um código "livre"
    # ou texto que o tradutor poderia mover/apagar); só 01 A0/01 80 têm tag ([cor]/[/cor])
    tabela = Tabela.carregar(TABELA)
    casos = {
        b"\x03\x06\x0a\x02\x04\x02Hi": "[$03][$06][$0A][$02][$04][$02]Hi",
        b"\x04\x20a": "[$04][$20]a",
        b"\x04\x09\x0a\x05\x03\x01\x02": "[$04][$09][$0A][$05][$03][$01][quebra2]",
        b"\x01\xa0x\x01\x80\x01\x54\x05\x09": "[cor]x[/cor][$01][$54][espera][linha]",
        b"\x0a\x04T\x0d\x01\xfe\xd6": "[$0A][$04]T[item:01]" + tabela.decodificar(b"\xfe\xd6"),
    }
    for bruto, esperado in casos.items():
        assert exibir_en(bruto, tabela, []) == esperado
        assert tabela.codificar(esperado) == bruto


def test_ids_estaveis():
    rom = b"Hello World\x00" + b"\x06\xff\xf9"
    a = _seg(rom, {"a": 0, "b": 12})
    b = _seg(rom, {"a": 0, "b": 12})
    assert a == b


def test_tabela_codigos():
    t = Tabela.carregar(TABELA)
    assert t.decodificar(b"\x01\xa0x\x01\x80\x02\x05\x09") == "[cor]x[/cor][quebra2][espera][linha]"
    assert t.decodificar(b"\x0c\xe7\x0d\x40\x0e\x2a\x0f\x08") == "[s0:E7][item:40][nome:2A][s3:08]"
    assert t.decodificar(b"\x03\x10") == "[$03][$10]"
    assert TABELA.read_bytes().count(b"\r") == 0


# --- ROM real ---------------------------------------------------------------

def _rom_segmentada(rom):
    cfg = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))
    tab = ler_tabelas(rom, cfg["raizes_extra"])
    instrs = desmontar(rom, list(tab.raizes.values()), LIMITES)
    return tab, segmentar(instrs, tab.raizes)


def test_tabela_ida_e_volta_rom(rom_base):
    tabela = Tabela.carregar(TABELA)
    _, (esq, trechos) = _rom_segmentada(rom_base)
    assert len(trechos) > 131
    for t in trechos:
        assert tabela.codificar(tabela.decodificar(t.bruto)) == t.bruto, t.id
    assert len({t.id for t in trechos}) == len(trechos)
    assert sum(1 for i in esq if "trecho" in i) == len(trechos)


def test_ids_estaveis_rom(rom_base):
    _, (_, a) = _rom_segmentada(rom_base)
    _, (_, b) = _rom_segmentada(rom_base)
    assert [(t.id, t.end, t.bruto) for t in a] == [(t.id, t.end, t.bruto) for t in b]


def test_dicionario_rom(rom_base):
    tabela = Tabela.carregar(TABELA)
    tab, (_, trechos) = _rom_segmentada(rom_base)
    dicionario = ler_dicionario(rom_base, tab, tabela)
    assert len(dicionario) == 0xE8 - 0x3F
    assert dicionario[0] == "" and all(dicionario[1:])  # slot 0x3F não é usado
    textos = [exibir_en(t.bruto, tabela, dicionario) for t in trechos]
    # "Monster" e "World" vêm do dicionário (0C 54 20 0C ..)
    assert any(s.startswith("Monster World was[linha]once a peaceful") for s in textos)


def test_argumento_de_controle_hex_rom(rom_base):
    import re

    com_arg = ("[$01]", "[$03]", "[$04]", "[$0A]")
    tabela = Tabela.carregar(TABELA)
    tab, (_, trechos) = _rom_segmentada(rom_base)
    dicionario = ler_dicionario(rom_base, tab, tabela)
    for t in trechos:
        toks = re.findall(r"\[[^\[\]]+\]|.", exibir_en(t.bruto, tabela, dicionario), re.S)
        i = 0
        while i < len(toks):
            if toks[i] in com_arg:
                assert i + 1 < len(toks) and re.fullmatch(r"\[\$[0-9A-F]{2}\]", toks[i + 1]), t.id
                i += 1
            i += 1
