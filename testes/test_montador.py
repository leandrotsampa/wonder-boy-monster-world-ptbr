"""Montador de scripts, realocação do texto e etapa de build."""

import json
import re
import shutil
import struct
from pathlib import Path

import pytest
import yaml

from ferramentas import cli
from ferramentas.cli import main
from ferramentas.script.extracao import extrair_texto
from ferramentas.script.montador import (
    ErroMontagem,
    aplicar_layout,
    etapa_texto,
    montar_bloco,
    montar_no_lugar,
    montar_texto,
)
from ferramentas.script.raizes import ler_tabelas
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada, carregar_todos
from ferramentas.verificacao import Contexto, checar_espaco

RAIZ = Path(__file__).resolve().parent.parent
REGIAO = (0xA4C80, 0xC0000)


def _s16(dados, pos):
    return struct.unpack_from(">h", dados, pos)[0]


def _u32(dados, pos):
    return struct.unpack_from(">I", dados, pos)[0]


def _instr(op, sub=None, args=(), alvos=(), rotulo=None):
    return {"rotulo": rotulo, "op": op, "sub": sub, "args": list(args), "alvos": list(alvos)}


# --------------------------------------------------------------- sintéticos


def test_rotulos_resolvidos():
    trechos = {"t0": bytes.fromhex("414243444546")}  # era 2 bytes, agora 6
    instrs = [
        _instr(0x06, alvos=["L_x"], rotulo="L_a"),             # base+0, 3 bytes
        {"rotulo": None, "trecho": "t0"},                       # base+3, 6 bytes
        _instr(0x0B, 0x1A, args=[7], alvos=["L_a", "L_x"]),    # base+9: 0B 1A B R R (7 bytes)
        _instr(0x00, rotulo="L_x"),                             # base+16
        _instr(0x06, alvos=["L_a"]),                            # base+17
        _instr(0x0B, 0x02, args=[1, 2], alvos=["L_x"]),        # base+20: 0B 02 B B R
    ]
    base = 0x1000
    bloco, rotulos = montar_bloco(instrs, trechos.__getitem__, base)
    assert rotulos == {"L_a": 0x1000, "L_x": 0x1010}
    assert len(bloco) == 3 + 6 + 7 + 1 + 3 + 6
    assert bloco[0] == 0x06 and 0x1001 + _s16(bloco, 1) == 0x1010
    assert bloco[3:9] == trechos["t0"]
    assert bloco[9:12] == bytes([0x0B, 0x1A, 7])
    assert 0x100C + _s16(bloco, 12) == 0x1000
    assert 0x100E + _s16(bloco, 14) == 0x1010
    assert bloco[16] == 0x00
    assert bloco[17] == 0x06 and 0x1012 + _s16(bloco, 18) == 0x1000
    assert bloco[20:24] == bytes([0x0B, 0x02, 1, 2])
    assert 0x1018 + _s16(bloco, 24) == 0x1010


def test_salto_fora_de_alcance():
    instrs = [_instr(0x06, alvos=["L_x"]), {"rotulo": None, "trecho": "t"}, _instr(0x00, rotulo="L_x")]
    with pytest.raises(ErroMontagem, match="L_x"):
        montar_bloco(instrs, lambda _: b"\x41" * 0x9000, 0)


def test_rotulo_desconhecido():
    with pytest.raises(ErroMontagem, match="L_nada"):
        montar_bloco([_instr(0x06, alvos=["L_nada"])], lambda _: b"", 0)


def _esqueleto_sintetico():
    return {
        "raizes": {"dialogo.000": "L_d0", "dialogo.001": "L_d0", "b0.000": "L_s0",
                   "b1.000": "L_s1", "b1.002": "L_s1", "b2.000": "L_s2", "b3.001": "L_s3"},
        "instrucoes": [
            {"rotulo": "L_d0", "trecho": "dialogo.000.t00"},
            _instr(0x0B, 0x11, args=[0x1E], alvos=["L_s3"]),
            _instr(0x00),
            {"rotulo": "L_s0", "trecho": "b0.000.t00"}, _instr(0x00),
            {"rotulo": "L_s1", "trecho": "b1.000.t00"}, _instr(0x00),
            {"rotulo": "L_s2", "trecho": "b2.000.t00"}, _instr(0x00),
            {"rotulo": "L_s3", "trecho": "b3.001.t00"}, _instr(0x00),
        ],
        "trechos": {"dialogo.000.t00": "4142", "b0.000.t00": "41", "b1.000.t00": "4243",
                    "b2.000.t00": "44", "b3.001.t00": "45"},
        "tabelas": {
            "dialogos": [{"raiz": "dialogo.000", "flag": 3}, {"raiz": "dialogo.001", "flag": 5}],
            "bancos": {"0": ["b0.000"], "1": ["b1.000", None, "b1.002"], "2": ["b2.000"],
                       "3": [None, "b3.001"]},
        },
    }


TABELA = Tabela({b"\x41": "A", b"\x42": "B", b"\x43": "C", b"\x4F": "O", b"\x69": "i"})


def _rom_sintetica_texto():
    rom = bytearray(0x22000)
    rom[0x1CC10:0x1CC14] = (0x211CA).to_bytes(4, "big")
    return rom


@pytest.mark.parametrize("modo", ["original", "traducao"])
def test_montar_texto_sintetico(modo):
    esq = _esqueleto_sintetico()
    textos = {"dialogos": [Entrada("dialogo.000.t00", "AB", pt="OiOiOi")]}
    layout = montar_texto(esq, textos, TABELA, 0x1000, 0x2000, modo)
    rom = _rom_sintetica_texto()
    aplicar_layout(rom, layout)

    assert _u32(rom, 0x1CC14) == 0x1000
    t = ler_tabelas(bytes(rom))
    assert t.tab_dialogos == 0x1000
    assert [f for _, f in t.dialogos] == [3, 5]
    assert all(t.bases[b] % 2 == 0 for b in range(4))
    # aliases apontam para o mesmo endereço; slots nulos ficam com offset 0
    assert t.raizes["dialogo.000"] == t.raizes["dialogo.001"] == 0x1000 + 6
    assert t.bancos[1] == ["b1.000", None, "b1.002"]
    assert t.raizes["b1.000"] == t.raizes["b1.002"]
    assert _s16(rom, t.bases[1] + 2) == 0 and _s16(rom, t.bases[3]) == 0
    assert t.bancos[3] == [None, "b3.001"]
    # cada tabela imediatamente antes das suas strings
    for b, nome in ((0, "b0.000"), (1, "b1.000"), (2, "b2.000"), (3, "b3.001")):
        assert t.raizes[nome] == t.bases[b] + 2 * len(t.bancos[b])
    # o salto do diálogo (para o banco 3) foi resolvido pelo mapa global
    pt = b"\x4F\x69" * 3 if modo == "traducao" else b"\x41\x42"
    ini = t.raizes["dialogo.000"]
    assert rom[ini:ini + len(pt)] == pt
    salto = ini + len(pt) + 3
    assert rom[ini + len(pt):salto] == bytes([0x0B, 0x11, 0x1E])
    assert salto + _s16(rom, salto) == t.raizes["b3.001"]
    assert rom[t.raizes["b3.001"]:t.raizes["b3.001"] + 2] == b"\x45\x00"


def test_estouro_regiao():
    esq = _esqueleto_sintetico()
    with pytest.raises(ErroMontagem, match="excede") as exc:
        montar_texto(esq, {}, TABELA, 0x1000, 0x1010, "original")
    total = sum(len(b) for _, b in montar_texto(esq, {}, TABELA, 0x1000, 0x2000, "original").blocos)
    assert str(total) in str(exc.value)


def test_fall_through_entre_blocos_recusado():
    esq = _esqueleto_sintetico()
    del esq["instrucoes"][2]  # o diálogo agora cai direto nas strings do banco 0
    with pytest.raises(ErroMontagem, match="continua"):
        montar_texto(esq, {}, TABELA, 0x1000, 0x2000, "original")


def test_checar_espaco():
    ctx = Contexto(tabela=TABELA, textos={}, glossario=[])
    assert checar_espaco(ctx) == []
    ctx.extra["montagem"] = {"usado": 10, "destino": 0x1000, "limite": 0x2000}
    assert checar_espaco(ctx) == []
    ctx.extra["montagem"] = {"erro": "o texto excede a região"}
    achados = checar_espaco(ctx)
    assert len(achados) == 1 and achados[0].nivel == "erro" and "excede" in achados[0].mensagem


# ------------------------------------------------------------- CLI sem ROM real


@pytest.fixture
def projeto_sintetico(tmp_path, rom_sintetica):
    from ferramentas.rom import hashes
    (tmp_path / "rom").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "traducao").mkdir()
    (tmp_path / "rom" / "base.bin").write_bytes(rom_sintetica)
    cfg = {"nome_arquivo": "base.bin", "sha1": hashes(bytes(rom_sintetica))["sha1"]}
    (tmp_path / "config" / "rom.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "traducao" / "tabela.tbl").write_text("41=A\n", encoding="utf-8")
    return tmp_path


def test_construir_sem_esqueleto(projeto_sintetico, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ETAPAS", [etapa_texto])
    assert main(["--raiz", str(projeto_sintetico), "construir"]) == 1
    err = capsys.readouterr().err
    assert "extrair" in err and "Traceback" not in err
    assert not (projeto_sintetico / "build").exists()


def test_extrair_texto_yaml_nao_mapeamento(projeto_sintetico, capsys):
    (projeto_sintetico / "config" / "texto.yaml").write_text("- 1\n- 2\n", encoding="utf-8")
    assert main(["--raiz", str(projeto_sintetico), "extrair"]) == 1
    err = capsys.readouterr().err
    assert "texto.yaml" in err and "Traceback" not in err


def test_extrair_value_error_sem_traceback(projeto_sintetico, monkeypatch, capsys):
    (projeto_sintetico / "config" / "texto.yaml").write_text("raizes_extra: []\n", encoding="utf-8")

    def falha(*_a, **_k):
        raise ValueError("tabela de diálogos: contagem de entradas não determinada")

    monkeypatch.setattr(cli, "extrair_texto", falha)
    assert main(["--raiz", str(projeto_sintetico), "extrair"]) == 1
    err = capsys.readouterr().err
    assert "contagem de entradas não determinada" in err and "Traceback" not in err
    assert not (projeto_sintetico / "dados").exists()


# ------------------------------------------------------------------ ROM real


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tabela():
    return Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")


def test_identidade_no_lugar(rom_base, cfg, tabela):
    esq, _ = extrair_texto(rom_base, cfg, tabela)
    assert montar_no_lugar(rom_base, esq, cfg) == rom_base[0x1DD94:0x22460]


# Correções feitas à mão no esqueleto versionado (o resto é igual à ROM base). Na troca de
# Pedras Encantadas (dialogo.080), as duas perguntas SIM/NÃO (`0B 02 col_sim col_nao`) punham a
# seta do NÃO na coluna 7, colada no "SIM" ("YES▶ NO" já no original); a estalagem e as outras
# perguntas usam 8. Endereço do byte na ROM base: (antes, depois).
CORRECOES_ESQUELETO = {0x1F8CA + 3: (0x07, 0x08), 0x1F9CB + 3: (0x07, 0x08)}


def test_esqueleto_versionado_atual(rom_base, cfg, tabela):
    esq, _ = extrair_texto(rom_base, cfg, tabela)
    versionado = json.loads((RAIZ / "dados" / "scripts" / "esqueleto.json").read_text(encoding="utf-8"))
    montado = montar_no_lugar(rom_base, versionado, cfg)
    base = rom_base[0x1DD94:0x22460]
    assert len(montado) == len(base)
    diferencas = {0x1DD94 + i: (a, b) for i, (a, b) in enumerate(zip(base, montado)) if a != b}
    assert diferencas == CORRECOES_ESQUELETO
    assert versionado["tabelas"] == esq["tabelas"]


def _canonico(esq):
    """Esqueleto com os rótulos trocados pelo índice da instrução rotulada."""
    instrs = esq["instrucoes"]
    idx = {it["rotulo"]: i for i, it in enumerate(instrs) if it["rotulo"]}
    itens = []
    for it in instrs:
        if "trecho" in it:
            itens.append((it["rotulo"] is not None, it["trecho"]))
        else:
            itens.append((it["rotulo"] is not None, it["op"], it["sub"], tuple(it["args"]),
                          tuple(idx[a] for a in it["alvos"])))
    raizes = {nome: idx[r] for nome, r in esq["raizes"].items()}
    return itens, raizes, esq["tabelas"], esq["trechos"]


def test_realocado_equivalente(rom_base, cfg, tabela):
    esq, _ = extrair_texto(rom_base, cfg, tabela)
    layout = montar_texto(esq, {}, tabela, *REGIAO, modo="original")
    rom = bytearray(rom_base)
    aplicar_layout(rom, layout)
    assert _u32(rom, 0x1CC14) == REGIAO[0]
    # a região antiga fica intacta
    assert rom[0x1DD94:0x211CA] == rom_base[0x1DD94:0x211CA]
    assert rom[0x211DA:0x22460] == rom_base[0x211DA:0x22460]
    novo, _ = extrair_texto(bytes(rom), cfg, tabela, limites=REGIAO)
    assert all(a >= REGIAO[0] for a in ler_tabelas(bytes(rom)).raizes.values())
    assert _canonico(novo) == _canonico(esq)


def _registros_ips(patch):
    i, regs = 5, []
    while patch[i:i + 3] != b"EOF":
        off = int.from_bytes(patch[i:i + 3], "big")
        tam = int.from_bytes(patch[i + 3:i + 5], "big")
        i += 5
        if tam == 0:
            tam = int.from_bytes(patch[i:i + 2], "big")
            i += 3
        else:
            i += tam
        regs.append((off, off + tam))
    return regs


def test_build_cli_com_texto(tmp_path, rom_base):
    for rel in ("config/rom.yaml", "config/texto.yaml", "traducao/tabela.tbl",
                "dados/scripts/esqueleto.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAIZ / rel, tmp_path / rel)
    arq_rom = tmp_path / "base.bin"
    arq_rom.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq_rom)]) == 0
    relatorio = (tmp_path / "build" / "relatorio.txt").read_text(encoding="utf-8")
    assert re.search(r"^Espaço: \d+ bytes usados de \d+ em 0xA4C80–0xBFFF8$", relatorio, re.M)
    nova = (tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()
    assert _u32(nova, 0x1CC14) == REGIAO[0]
    assert _u32(nova, 0x211CA) > REGIAO[0]
    permitidos = [(0x18E, 0x190), (0x1A4, 0x1A8), (0x1CC14, 0x1CC18), (0x211CA, 0x211DA), REGIAO]
    regs = _registros_ips((tmp_path / "build" / "wbmw-ptbr.ips").read_bytes())
    assert regs
    for ini, fim in regs:
        assert any(a <= ini and fim <= b for a, b in permitidos), f"IPS toca {ini:#x}-{fim:#x}"


def test_build_cli_traducao_realocada(tmp_path, rom_base):
    """Modo tradução com a ROM real: um pt 3× maior desloca todo o texto seguinte
    (saltos e ponteiros entre blocos); a ROM gerada relê com o pt e o resto intacto."""
    from ferramentas.ips import aplicar_ips
    from ferramentas.textos import carregar_textos, salvar_textos

    shutil.copytree(RAIZ / "config", tmp_path / "config")
    shutil.copytree(RAIZ / "traducao" / "textos", tmp_path / "traducao" / "textos")
    shutil.copy(RAIZ / "traducao" / "tabela.tbl", tmp_path / "traducao" / "tabela.tbl")
    # o patch do HUD (config/patches.yaml) exige a fonte com o rótulo MOEDAS
    shutil.copytree(RAIZ / "graficos" / "fonte", tmp_path / "graficos" / "fonte")
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    arq_rom = tmp_path / "base.bin"
    arq_rom.write_bytes(rom_base)

    alvo = "dialogo.000.t01"  # termina com [cor][nome:00][/cor] ... e fica no 1º bloco
    arq = tmp_path / "traducao" / "textos" / "dialogos.yaml"
    entradas = carregar_textos(arq)
    (e,) = [x for x in entradas if x.id == alvo]
    assert "[nome:00]" in e.en
    pt = "[linha]".join(["Era uma vez um mundo"] * 40) + "[linha][cor][nome:00][/cor] venceu."
    assert len(pt) >= 3 * len(e.en)
    e.pt, e.status = pt, "traduzido"
    salvar_textos(arq, entradas)

    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq_rom)]) == 0
    nova = (tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()
    ips = (tmp_path / "build" / "wbmw-ptbr.ips").read_bytes()
    assert aplicar_ips(rom_base, ips) == nova

    cfg = yaml.safe_load((tmp_path / "config" / "texto.yaml").read_text(encoding="utf-8"))
    tabela = Tabela.carregar(tmp_path / "traducao" / "tabela.tbl")
    _, antes = extrair_texto(rom_base, cfg, tabela)
    esq, depois = extrair_texto(nova, cfg, tabela, limites=REGIAO)
    assert all(a >= REGIAO[0] for a in ler_tabelas(nova).raizes.values())
    en_antes = {x.id: x.en for es in antes.values() for x in es}
    en_depois = {x.id: x.en for es in depois.values() for x in es}
    assert en_depois.keys() == en_antes.keys()
    assert en_depois[alvo] == pt
    # o resto relê como foi pedido: o pt versionado quando existe, senão o original
    pts = {x.id: x.pt for es in carregar_todos(tmp_path / "traducao" / "textos").values()
           for x in es}
    esperado = {k: (pts.get(k) or v) for k, v in en_antes.items()}
    mudados = [k for k in en_antes if k != alvo and esperado[k] != en_depois[k]]
    assert mudados == []
