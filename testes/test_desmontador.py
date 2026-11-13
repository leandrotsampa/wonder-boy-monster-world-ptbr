"""Desmontador de script (linguagem do interpretador em 0x14F4)."""

from pathlib import Path

import pytest
import yaml

from ferramentas.script.desmontador import ErroScript, desmontar
from ferramentas.script.opcodes import OPS, SUBOPS_0B
from ferramentas.script.raizes import LIMITES, ler_tabelas

RAIZ = Path(__file__).resolve().parent.parent


def test_tabelas_completas():
    assert sorted(OPS) == list(range(0x10))
    assert sorted(SUBOPS_0B) == list(range(0x33))


def test_texto_simples():
    rom = b"Hi\x05\x00"
    instrs = desmontar(rom, [0], (0, len(rom)))
    assert sorted(instrs) == [0, 1, 2, 3]
    assert instrs[0].op == -1 and instrs[0].args == (ord("H"),)
    assert instrs[2].op == 0x05
    assert instrs[3].op == 0


def test_salto_incondicional():
    rom = bytes.fromhex("060004" "41" "00" "4200")
    instrs = desmontar(rom, [0], (0, len(rom)))
    assert instrs[0].alvos == (5,)
    assert instrs[0].tam == 3
    assert 3 not in instrs  # inalcançável
    assert sorted(instrs) == [0, 5, 6]


def test_salto_condicional_0b():
    assert SUBOPS_0B[0x11] == "BR"
    # 0B 11 05 [rel16 em 3: +4 -> 7] | 41 00 | 42 00
    rom = bytes.fromhex("0B11050004" "4100" "4200")
    instrs = desmontar(rom, [0], (0, len(rom)))
    assert instrs[0].op == 0x0B and instrs[0].sub == 0x11
    assert instrs[0].args == (5, 4)
    assert instrs[0].alvos == (7,)
    assert instrs[0].tam == 5
    assert sorted(instrs) == [0, 5, 6, 7, 8]


def test_char_2bytes():
    instrs = desmontar(b"\xFE\xD6\x00", [0], (0, 3))
    assert instrs[0].op == -1 and instrs[0].tam == 2
    assert instrs[0].args == (0xFE, 0xD6)
    assert sorted(instrs) == [0, 2]


def test_string_de_banco():
    instrs = desmontar(b"\x0C\x41\x00", [0], (0, 3))
    assert instrs[0].op == 0x0C and instrs[0].args == (0x41,) and instrs[0].alvos == ()


def test_sobreposicao():
    # o salto (rel em 3, +3 -> 6) cai no meio do caractere FE D6 (5-6)
    rom = bytes.fromhex("0B11050003" "FED6" "00")
    with pytest.raises(ErroScript, match="0x6"):
        desmontar(rom, [0], (0, len(rom)))


def test_fora_dos_limites():
    rom = bytes.fromhex("060010" "00")
    with pytest.raises(ErroScript, match="limites"):
        desmontar(rom, [0], (0, len(rom)))
    with pytest.raises(ErroScript):
        desmontar(b"AB", [0], (0, 2))  # cai do fim sem 00


def test_opcode_desconhecido():
    with pytest.raises(ErroScript, match="subop"):
        desmontar(b"\x0B\x7F\x00", [0], (0, 3))


# --- ROM real ---------------------------------------------------------------

def test_raizes_rom(rom_base):
    tab = ler_tabelas(rom_base, [0x1DF1D])
    assert tab.tab_dialogos == 0x1DD94 and tab.tab_mestra == 0x211CA
    assert tab.bases == {0: 0x211DA, 1: 0x21720, 2: 0x21A06, 3: 0x21FCA}
    assert len(tab.dialogos) == 131 and tab.dialogos[0][0] == "dialogo.000"
    assert tab.dialogos[-1][0] == "dialogo.130"
    assert all(0 <= flag <= 7 for _, flag in tab.dialogos)
    # banco 3: 9 slots usados + 7 slots com offset 0 até o 1º alvo positivo (0x20)
    assert [len(tab.bancos[b]) for b in range(4)] == [232, 65, 43, 16]
    assert tab.bancos[0][0x3F] is None and tab.bancos[0][0x40] == "b0.040"
    assert tab.bancos[3][8] == "b3.008" and tab.bancos[3][9:] == [None] * 7
    nomes = list(tab.raizes)
    assert nomes[0] == "dialogo.000" and nomes[131] == "b0.000"
    assert nomes[-1] == "extra.1df1d" and tab.raizes["dialogo.000"] == 0x1DF1D
    assert len(tab.raizes) == 468 + 1  # 131 diálogos + 337 slots não nulos + 1 extra
    nulos = sum(n is None for b in tab.bancos.values() for n in b)
    assert nulos == 232 + 65 + 43 + 16 - 337


def test_cobertura_rom(rom_base):
    cfg = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))
    tab = ler_tabelas(rom_base, cfg["raizes_extra"])
    tabelas = tab.faixas_tabelas_bancos()
    instrs = desmontar(rom_base, list(tab.raizes.values()), LIMITES)

    for ins in instrs.values():
        for alvo in ins.alvos:
            assert alvo in instrs, f"alvo {alvo:#x} de {ins.end:#x} não é início de instrução"

    coberto = bytearray(LIMITES[1])
    for ins in instrs.values():
        for e in range(ins.end, ins.end + ins.tam):
            assert not coberto[e], f"sobreposição em {e:#x}"
            coberto[e] = 1
    for ini, fim in tabelas:  # tabelas de offsets dos bancos são dado
        for e in range(ini, fim):
            coberto[e] = 1

    lacunas = cfg.get("lacunas_conhecidas") or []
    for lac in lacunas:
        assert str(lac["justificativa"]).strip(), f"sem justificativa: {lac}"
        for e in range(lac["inicio"], lac["fim"]):
            assert not coberto[e], f"lacuna obsoleta: {e:#x} já é coberto ({lac})"
            coberto[e] = 1

    faltando = []
    for ini, fim in [(0x1DF1D, 0x211CA), (0x213AA, 0x22460)]:
        e = ini
        while e < fim:
            if not coberto[e]:
                f = e
                while f < fim and not coberto[f]:
                    f += 1
                faltando.append(f"{e:#x}-{f:#x} {rom_base[e:min(f, e + 16)].hex()}")
                e = f
            else:
                e += 1
    assert not faltando, f"{len(faltando)} lacunas não cobertas: {faltando[:40]}"
