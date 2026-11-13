"""Menus do START e magias: blocos repontáveis (cabeçalhos, opções, magias), trampolins,
checagem de largura e capturas no jogo (mapa-rom.md §6, "Menus e magias")."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ferramentas.config import ErroConfig, Projeto, carregar_cfg_texto
from ferramentas.repontavel import (blocos_repontaveis, bytes_blocos, bytes_repontaveis,
                                    checar_repontaveis, etapa_repontavel, extrair_blocos,
                                    itens_repontaveis, planejar_repontaveis)
from ferramentas.script.montador import ErroMontagem
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada, carregar_textos
from ferramentas.verificacao import Contexto

RAIZ = Path(__file__).resolve().parent.parent
TABELA = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")

# ROM sintética: um menu de 2 entradas (coluna, linha, texto, 00) em 0x200 com a tabela
# de deslocamentos em 0x1FC; leitura em sequência em 0x100 (moveq #0,d4 + lea) e pela
# tabela em 0x110 (lea + adda.w); coordenada de cabeçalho em 0x120; livre em 0x400.
SEQ, TAB_REF, TROCA = 0x100, 0x110, 0x120
TABELA_END, MENU = 0x1FC, 0x200
LIVRE = (0x400, 0x500)


def _rom() -> bytearray:
    rom = bytearray(b"\x4E\x71" * 0x100 + b"\xFF" * 0x400)
    rom[SEQ:SEQ + 6] = bytes.fromhex("780043FA") + (MENU - (SEQ + 4)).to_bytes(2, "big")
    rom[TAB_REF:TAB_REF + 8] = (bytes.fromhex("43FA") + (TABELA_END - (TAB_REF + 2)).to_bytes(2, "big")
                                + bytes.fromhex("D2F10000"))
    rom[TROCA:TROCA + 2] = bytes.fromhex("1004")
    rom[TABELA_END:TABELA_END + 4] = bytes.fromhex("00040009")
    rom[MENU:MENU + 10] = b"\x03\x06AB\x00\x12\x06CDE\x00"
    return rom


def _seq_ref():
    return {"end": SEQ + 2, "tipo": "trampolim", "ini": SEQ, "fim": SEQ + 6,
            "original": "780043FA" + f"{MENU - (SEQ + 4):04X}"}


def _tab_ref():
    return {"end": TAB_REF, "tipo": "trampolim", "ini": TAB_REF, "fim": TAB_REF + 8,
            "original": f"43FA{TABELA_END - (TAB_REF + 2):04X}D2F10000"}


def _bloco(**kw):
    b = {"id": "menu.teste", "end": MENU, "prefixo": 2,
         "entradas": [{"id": "t.a", "largura": 5}, {"id": "t.b", "largura": 6}],
         "refs": [_seq_ref()],
         "tabela": {"end": TABELA_END, "refs": [_tab_ref()]},
         "trocas": [{"end": TROCA, "original": "1004", "novo": "0E04"}]}
    b.update(kw)
    return b


def _cfg(blocos, itens=()):
    return {"inline_repontavel": {"itens": list(itens), "ajustes": [], "blocos": blocos}}


def _reservar():
    pos = [LIVRE[0]]
    usos = []

    def reservar(nome, tamanho, alinhamento=1):
        ini = pos[0] + (-pos[0] % alinhamento)
        pos[0] = ini + tamanho
        usos.append((nome, ini, tamanho))
        return ini
    return reservar, usos


def _plano(pts, blocos=None, rom=None):
    rom = _rom() if rom is None else rom
    reservar, usos = _reservar()
    blocos = blocos_repontaveis(_cfg([_bloco()] if blocos is None else blocos))
    plano = planejar_repontaveis(rom, [], [], pts, TABELA, reservar, blocos)
    return rom, plano, usos


def _aplicado(plano, rom):
    rom = bytearray(rom)
    for end, dados in plano:
        rom[end:end + len(dados)] = dados
    return rom


def _desmontar(dados: bytes, end: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    return [(i.mnemonic, i.op_str.replace(" ", "")) for i in md.disasm(dados, end)]


# ------------------------------------------------------------- config

def test_config_blocos_vazia_e_valida():
    assert blocos_repontaveis({}) == []
    assert [b["id"] for b in blocos_repontaveis(_cfg([_bloco()]))] == ["menu.teste"]


@pytest.mark.parametrize("ruim, msg", [
    ({"prefixo": -1}, "prefixo"),
    ({"entradas": []}, "entradas"),
    ({"entradas": [{"id": "t.a"}, {"id": "t.a"}]}, "duplicado"),
    ({"entradas": [{"id": "t.a", "largura": 0}]}, "largura"),
    ({"refs": [], "tabela": None}, "refs"),
    ({"refs": [dict(_seq_ref(), ini=SEQ + 4)]}, "trampolim"),
    ({"refs": [dict(_seq_ref(), fim=SEQ + 4)]}, "trampolim"),
    ({"refs": [dict(_seq_ref(), original="7800")]}, "original"),
    ({"trocas": [{"end": TROCA, "original": "1004", "novo": "0E"}]}, "trocas"),
    ({"iguais": ["t.a", "nada"]}, "iguais"),
])
def test_config_bloco_invalido(ruim, msg):
    with pytest.raises(ErroConfig, match=msg):
        blocos_repontaveis(_cfg([_bloco(**ruim)]))


def test_config_bloco_conflitos():
    item = {"id": "t.a", "end": 0x300, "tam": 2, "refs": [{"end": 0x130, "tipo": "lea_pc"}]}
    with pytest.raises(ErroConfig, match="t.a"):
        blocos_repontaveis(_cfg([_bloco()], [item]))
    cfg = _cfg([_bloco()])
    cfg["inline"] = [{"id": "t.b", "end": 0x300, "tam": 2, "preencher": "espaco"}]
    with pytest.raises(ErroConfig, match="t.b"):
        blocos_repontaveis(cfg)
    # duas gravações no mesmo lugar
    outro = _bloco(id="menu.outro", entradas=[{"id": "u.a"}, {"id": "u.b"}], trocas=[],
                   tabela=None)
    with pytest.raises(ErroConfig, match="sobrep"):
        blocos_repontaveis(_cfg([_bloco(), outro]))


def test_trampolim_tambem_vale_para_itens():
    item = {"id": "x", "end": MENU + 2, "tam": 2, "refs": [_seq_ref()]}
    assert itens_repontaveis(_cfg([], [item]))[0]["refs"][0]["tipo"] == "trampolim"


# ------------------------------------------------------------- build sintético

def test_extrair_blocos():
    assert [(e.id, e.en) for e in extrair_blocos(_rom(), blocos_repontaveis(_cfg([_bloco()])),
                                                 TABELA)] == [("t.a", "AB"), ("t.b", "CDE")]


def test_bloco_sem_pt_nao_grava_nada():
    rom, plano, usos = _plano({})
    assert plano == [] and usos == []


def test_bloco_reponta_com_tabela_trampolins_e_trocas():
    rom, plano, usos = _plano({"t.b": "XYZW"})
    nova = _aplicado(plano, rom)
    nomes = [u[0] for u in usos]
    assert nomes[0] == "inline:menu.teste"
    base = usos[0][1]
    assert base % 2 == 0
    # tabela nova (deslocamentos a partir dela) + entradas com o prefixo original
    assert nova[base:base + 4] == bytes.fromhex("00040009")
    assert nova[base + 4:base + 16] == b"\x03\x06AB\x00\x12\x06XYZW\x00"
    # o original fica intacto; a troca de dados é aplicada
    assert nova[MENU:MENU + 10] == rom[MENU:MENU + 10]
    assert nova[TROCA:TROCA + 2] == bytes.fromhex("0E04")
    # leitura em sequência: jsr para o trampolim, que faz o moveq e o lea absoluto
    t_seq = next(u[1] for u in usos if u[0] == "trampolim:menu.teste@0x100")
    assert _desmontar(bytes(nova[SEQ:SEQ + 6]), SEQ) == [("jsr", f"${t_seq:x}.l")]
    assert _desmontar(bytes(nova[t_seq:t_seq + 10]), t_seq) == [
        ("moveq", "#$0,d4"), ("lea.l", f"${base + 4:x}.l,a1"), ("rts", "")]
    # leitura pela tabela: jsr + nop; o trampolim aponta a tabela nova e faz o adda
    t_tab = next(u[1] for u in usos if u[0] == "trampolim:menu.teste@0x110")
    assert t_seq % 2 == 0 and t_tab % 2 == 0
    assert _desmontar(bytes(nova[TAB_REF:TAB_REF + 8]), TAB_REF) == [
        ("jsr", f"${t_tab:x}.l"), ("nop", "")]
    assert _desmontar(bytes(nova[t_tab:t_tab + 12]), t_tab) == [
        ("lea.l", f"${base:x}.l,a1"), ("adda.w", "(a1,d0.w),a1"), ("rts", "")]


def test_espaco_contado_para_a_checagem():
    """A conta de espaço do verificar (sem ROM) bate com o que o build reserva."""
    _, _, usos = _plano({"t.b": "XYZW"})
    blocos = blocos_repontaveis(_cfg([_bloco()]))
    assert bytes_blocos(blocos, {"t.b": "XYZW"}, {"t.a": "AB", "t.b": "CDE"}, TABELA) ==         sum(u[2] for u in usos)
    assert bytes_blocos(blocos, {}, {}, TABELA) == 0
    item = {"id": "x", "end": MENU + 2, "tam": 2, "refs": [_seq_ref()]}
    assert bytes_repontaveis([item], {"x": "QQ"}, TABELA) == 3 + 10


def test_bloco_sem_tabela_e_sem_prefixo():
    rom = _rom()
    rom[0x300:0x306] = b"AB\x00CD\x00"
    rom[0x130:0x134] = bytes.fromhex("43FA") + (0x300 - 0x132).to_bytes(2, "big")
    bloco = {"id": "m", "end": 0x300, "prefixo": 0, "entradas": [{"id": "a"}, {"id": "b"}],
             "refs": [{"end": 0x130, "tipo": "lea_pc"}]}
    _, plano, usos = _plano({"a": "ÁRVORE"}, [bloco], rom)
    nova = _aplicado(plano, rom)
    novo = usos[0][1]
    assert nova[novo:novo + 10] == TABELA.codificar("ÁRVORE", "a") + b"\x00CD\x00"
    assert nova[0x130:0x134] == bytes.fromhex("43FA") + (novo - 0x132).to_bytes(2, "big")


@pytest.mark.parametrize("muda, msg", [
    (lambda r: r.__setitem__(slice(SEQ, SEQ + 2), b"\x70\x01"), "original"),
    (lambda r: r.__setitem__(slice(TABELA_END, TABELA_END + 2), b"\x00\x05"), "tabela"),
    (lambda r: r.__setitem__(slice(TROCA, TROCA + 2), b"\x10\x05"), "troca"),
    (lambda r: r.__setitem__(slice(MENU + 10, MENU + 11), b"\xFF"), "00"),
])
def test_bloco_confere_a_rom(muda, msg):
    """Tudo é conferido, com ou sem pt: trampolim, tabela, trocas e terminadores."""
    rom = _rom()
    muda(rom)
    with pytest.raises(ErroMontagem, match=msg):
        _plano({}, rom=rom)


def test_bloco_largura_estourada():
    with pytest.raises(ErroMontagem, match="t.a.*largura|largura.*t.a"):
        _plano({"t.a": "ABCDEF"})


def test_bloco_iguais():
    """Entradas que dividem a mesma linha (o jogo não limpa) têm de ter o mesmo tamanho."""
    blocos = [_bloco(iguais=["t.a", "t.b"])]
    with pytest.raises(ErroMontagem, match="mesmo tamanho"):
        _plano({}, blocos)
    _plano({"t.a": "ABC"}, blocos)   # AB -> ABC = CDE


def test_bloco_so_texto():
    with pytest.raises(ErroMontagem, match="só texto"):
        _plano({"t.a": "A[linha]"})


def _ctx(pts, blocos):
    return Contexto(tabela=TABELA, textos={"inline": [Entrada(k, "", pt=v) for k, v in pts.items()]},
                    glossario=[], extra={"repontavel": [], "repontavel_ajustes": [],
                                         "repontavel_blocos": blocos_repontaveis(_cfg(blocos))})


def test_verificar_acusa_largura_e_iguais():
    assert checar_repontaveis(_ctx({"t.a": "ABCDE"}, [_bloco()])) == []
    achados = checar_repontaveis(_ctx({"t.a": "ABCDEF"}, [_bloco()]))
    assert [a.nivel for a in achados] == ["erro"] and "largura" in achados[0].mensagem
    achados = checar_repontaveis(_ctx({"t.a": "ABCD", "t.b": "XY"},
                                      [_bloco(iguais=["t.a", "t.b"])]))
    assert [a.nivel for a in achados] == ["erro"] and "mesmo tamanho" in achados[0].mensagem


def test_etapa_com_projeto(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "traducao" / "textos").mkdir(parents=True)
    cfg = {"regiao_destino": list(LIVRE)} | _cfg([_bloco()])
    (tmp_path / "config" / "texto.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    shutil.copy(RAIZ / "traducao" / "tabela.tbl", tmp_path / "traducao" / "tabela.tbl")
    (tmp_path / "traducao" / "textos" / "inline.yaml").write_text(
        yaml.safe_dump([{"id": "t.a", "en": "AB", "pt": "QQ", "status": "traduzido"}]),
        encoding="utf-8")
    rom = _rom()
    etapa_repontavel(rom, Projeto(raiz=tmp_path, rom={}))
    assert rom[0x404:0x40F] == b"\x03\x06QQ\x00\x12\x06CDE\x00"


# ------------------------------------------------------------- ROM real

CABECALHOS = ["SELECT", "WEAPON", "ARMOR ", "SHIELD", "BOOTS ", "ITEM", "MAGIC"]
OPCOES = ["WEAPON", "ARMOR ", "SHIELD", "BOOTS ", "ITEM", "MAGIC"]
MAGIAS = ["FIRE STORM", "QUAKE", "THUNDER", "POWER", "SHIELD", "RETURN"]
#: decisões do autor (Plano 4): menus com ARMA no lugar de PODER; magias com TERREMOTO no
#: lugar de TREMOR DE TERRA; no HUD (10 colunas) a forma curta
PT_CABECALHOS = ["SELECIONAR", "   ARMA   ", " ARMADURA ", "  ESCUDO  ", "  BOTAS   ", "ITEM",
                 "MAGIA"]
PT_OPCOES = ["ARMA", "ARMADURA", "ESCUDO", "BOTAS", "ITEM", "MAGIA"]
PT_MAGIAS = ["BOLAS DE FOGO", "TERREMOTO", "TROVÕES", "SUPER FORÇA", "BLINDAGEM", "VOLTAR"]
PT_MAGIAS_HUD = ["FOGO", "TERREMOTO", "TROVÕES", "FORÇA", "BLINDAGEM", "VOLTAR"]
PT_STATUS = ["PA", "PD", "PE"]


def _blocos_reais() -> dict[str, dict]:
    return {b["id"]: b for b in blocos_repontaveis(carregar_cfg_texto(RAIZ))}


def test_blocos_reais_conferem_com_a_base(rom_base):
    blocos = _blocos_reais()
    assert set(blocos) == {"menu.cabecalhos", "menu.opcoes", "menu.magias", "menu.magias_hud"}
    en = {e.id: e.en for e in extrair_blocos(rom_base, list(blocos.values()), TABELA)}
    ids = {k: [e["id"] for e in b["entradas"]] for k, b in blocos.items()}
    assert [en[i] for i in ids["menu.cabecalhos"]] == CABECALHOS
    assert [en[i] for i in ids["menu.opcoes"]] == OPCOES
    assert [en[i] for i in ids["menu.magias"]] == MAGIAS
    assert [en[i] for i in ids["menu.magias_hud"]] == MAGIAS
    # tudo conferido sem pt (nada gravado)
    reservar, _ = _reservar()
    assert planejar_repontaveis(rom_base, [], [], {}, TABELA, reservar,
                                list(blocos.values())) == []


def test_auditoria_referencias_dos_menus(rom_base):
    """Toda instrução que aponta para as strings e tabelas dos menus está na config (as
    demais são dados que o varredor decodifica como instrução)."""
    from ferramentas.script.auditoria import referencias_a

    blocos = _blocos_reais()

    def refs(b):
        return sorted(r["end"] for r in b["refs"] + ((b.get("tabela") or {}).get("refs") or []))
    # magias: lea em sequência (0x7BB8), tabela 0x7BFE no menu (0x7C56) e no HUD (0x8784)
    assert referencias_a(rom_base, 0x7C0A, 0x7C44) == [0x7BB8, *DADOS_7C0A]
    assert referencias_a(rom_base, 0x7BFE, 0x7C0A) == [0x7C56, 0x8784]
    assert refs(blocos["menu.magias"]) == [0x7BB8, 0x7C56]
    assert refs(blocos["menu.magias_hud"]) == [0x8784]
    # cabeçalhos: tabela 0x82B6 (0x8278); opções: lea em sequência a partir de WEAPON
    assert referencias_a(rom_base, 0x82B6, 0x82C4) == [0x632E, 0x8278]   # 0x632E: dados
    assert referencias_a(rom_base, 0x82C4, 0x82F2) == [0x77D4]
    assert refs(blocos["menu.cabecalhos"]) == [0x8278]
    assert refs(blocos["menu.opcoes"]) == [0x77D4]
    # coordenadas trocadas junto com o texto: cabeçalho (0x82B2, lida em 0x828A) e
    # posições das opções/cursor (0x7D6E: 0x77D0, 0x77EC, 0x7D2E)
    assert referencias_a(rom_base, 0x82B2, 0x82B6) == [0x828A]
    assert referencias_a(rom_base, 0x7D6E, 0x7D7A) == [0x77D0, 0x77EC, 0x7D2E]


#: falsos positivos do varredor em 0x7C0A–0x7C44: tabelas de dados (0x8E4A…, 0x1B148…)
DADOS_7C0A = [0x8E50, 0x1B14E, 0x1B158, 0x1B1AC, 0x1B200]


def _alvos_de_desvio(rom: bytes) -> set[int]:
    """Alvos de bra/bsr/bcc (.b/.w), jmp/jsr (.w/.l/d16(pc)) e dbcc em todo endereço
    par."""
    alvos = set()

    def s16(v):
        return v - 0x10000 if v & 0x8000 else v
    for p in range(0x200, 0x1C600, 2):
        w = int.from_bytes(rom[p:p + 2], "big")
        if w >> 12 == 6:
            d = w & 0xFF
            if d == 0:
                alvos.add(p + 2 + s16(int.from_bytes(rom[p + 2:p + 4], "big")))
            elif d != 0xFF:
                alvos.add(p + 2 + (d - 256 if d & 0x80 else d))
        elif w & 0xF0F8 == 0x50C8:   # dbcc
            alvos.add(p + 2 + s16(int.from_bytes(rom[p + 2:p + 4], "big")))
        elif w in (0x4EB8, 0x4EF8):
            alvos.add(int.from_bytes(rom[p + 2:p + 4], "big"))
        elif w in (0x4EBA, 0x4EFA):   # jsr/jmp d16(pc)
            alvos.add(p + 2 + s16(int.from_bytes(rom[p + 2:p + 4], "big")))
        elif w in (0x4EB9, 0x4EF9):
            alvos.add(int.from_bytes(rom[p + 2:p + 6], "big"))
    return alvos


def test_trampolins_reais(rom_base):
    """Os bytes levados para o trampolim não usam o PC nem a pilha, e nenhum desvio cai
    no meio do trecho trocado (só no início)."""
    alvos = _alvos_de_desvio(rom_base)
    esperados = {
        0x7BB6: [("moveq", "#$0,d4"), ("lea.l", "$7c0a(pc),a1")],
        0x7C56: [("lea.l", "$7bfe(pc),a1"), ("adda.w", "(a1,d0.w),a1")],
        0x8784: [("lea.l", "$7bfe(pc),a1"), ("add.w", "d0,d0")],
        0x8278: [("lea.l", "$82b6(pc),a1"), ("adda.w", "(a1,d0.w),a1")],
        0x77D4: [("lea.l", "$82cb(pc),a1"), ("moveq", "#$5,d2")],
    }
    vistos = {}
    for b in _blocos_reais().values():
        for r in b["refs"] + ((b.get("tabela") or {}).get("refs") or []):
            assert r["tipo"] == "trampolim"
            vistos[r["ini"]] = r
            assert rom_base[r["ini"]:r["fim"]] == bytes.fromhex(r["original"])
            assert not {a for a in alvos if r["ini"] < a < r["fim"]}, hex(r["ini"])
    assert {k: _desmontar(rom_base[k:vistos[k]["fim"]], k) for k in vistos} == esperados


def test_textos_dos_menus_decididos():
    pts = {e.id: e.pt for e in carregar_textos(RAIZ / "traducao" / "textos" / "inline.yaml")}
    blocos = _blocos_reais()

    def de(bloco):
        return [pts[e["id"]] for e in blocos[bloco]["entradas"]]
    assert de("menu.cabecalhos") == PT_CABECALHOS
    assert de("menu.opcoes") == PT_OPCOES
    assert de("menu.magias") == PT_MAGIAS
    assert de("menu.magias_hud") == PT_MAGIAS_HUD
    assert [pts[k] for k in ("status.ap", "status.dp", "status.sp")] == PT_STATUS
    # origem registrada (projeto) nos blocos e nas trocas
    for nome in ("menu.cabecalhos", "menu.opcoes", "menu.magias", "menu.magias_hud"):
        assert "projeto" in blocos[nome]["origem"], nome
        assert all("projeto" in t["origem"] for t in blocos[nome].get("trocas") or [])
    # cabeçalhos das 5 primeiras telas: mesmo tamanho (a linha não é limpa) e centrados
    assert len({len(p) for p in PT_CABECALHOS[:5]}) == 1
    for p in PT_CABECALHOS[1:5]:
        assert len(p) - len(p.lstrip()) in ((10 - len(p.strip())) // 2,
                                            (11 - len(p.strip())) // 2)


def test_larguras_reais():
    """Largura máxima por entrada = espaço no painel (janela de 32 colunas; bordas nas
    colunas 12/31 no painel do menu e 0/31 nas telas de item e magia)."""
    b = _blocos_reais()
    larg = {e["id"]: e.get("largura") for bl in b.values() for e in bl["entradas"]}
    cab = [e["id"] for e in b["menu.cabecalhos"]["entradas"]]
    # cabeçalho na coluna 14 (troca em 0x82B2): enfeite(2) + espaço + texto + espaço +
    # enfeite(2) até a coluna 30; ITEM/MAGIA na coluna 11
    assert [larg[i] for i in cab] == [11] * 5 + [14] * 2
    assert b["menu.cabecalhos"]["iguais"] == cab[:5]
    # opções nas colunas 14 e 22 (troca em 0x7D6E): esquerda até a 20 (o cursor da direita
    # fica na 21), direita até a 29
    opc = [e["id"] for e in b["menu.opcoes"]["entradas"]]
    assert [larg[i] for i in opc] == [7, 8, 7, 8, 7, 8]
    # magias nas colunas 3 e 18: esquerda até a 16, direita até a 30; HUD: 10
    mag = [e["id"] for e in b["menu.magias"]["entradas"]]
    assert [larg[i] for i in mag] == [14, 13, 14, 13, 14, 13]
    assert {larg[e["id"]] for e in b["menu.magias_hud"]["entradas"]} == {10}


def test_build_real_reponta_menus(rom_base, tmp_path):
    from ferramentas.cli import main

    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    arq = tmp_path / "base.bin"
    arq.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq)]) == 0
    rom = (tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()
    regiao = carregar_cfg_texto(RAIZ)["regiao_destino"]

    def destino(ini):   # jsr do trampolim -> lea abs.l do trampolim
        ins = _desmontar(rom[ini:ini + 6], ini)
        assert ins[0][0] == "jsr", (hex(ini), ins)
        t = int(ins[0][1][1:-2], 16)
        assert regiao[0] <= t < regiao[1]
        lea = [i for i in _desmontar(rom[t:t + 16], t) if i[0] == "lea.l"][0]
        return int(lea[1].split(".")[0][1:], 16)

    def ler(end, n):
        res = []
        for _ in range(n):
            fim = rom.index(b"\x00", end)
            res.append(TABELA.decodificar(rom[end:fim]))
            end = fim + 1
        return res
    # opções em sequência; magias em sequência (coluna, linha, texto)
    assert ler(destino(0x77D4), 6) == PT_OPCOES
    mag = destino(0x7BB6)
    assert rom[mag:mag + 2] == bytes([3, 6])
    # tabelas: cabeçalhos, magias (menu) e magias (HUD)
    for ini, pt, prefixo in ((0x8278, PT_CABECALHOS, 0), (0x7C56, PT_MAGIAS, 2),
                             (0x8784, PT_MAGIAS_HUD, 2)):
        tab = destino(ini)
        offs = [int.from_bytes(rom[tab + 2 * i:tab + 2 * i + 2], "big") for i in range(len(pt))]
        assert [ler(tab + o + prefixo, 1)[0] for o in offs] == pt, hex(ini)
    assert [rom[destino(0x7C56) + o:][:2] for o in (0x0C,)] == [bytes([3, 6])]
    # coordenadas: cabeçalho na coluna 14; opções nas colunas 14 e 22
    assert rom[0x82B2:0x82B6] == bytes.fromhex("0E040B04")
    assert rom[0x7D6E:0x7D7A] == bytes.fromhex("0E0716070E0A160A0E0D160D")
    # originais intactos
    for a, b in ((0x7BFE, 0x7C44), (0x82B6, 0x82F2)):
        assert rom[a:b] == rom_base[a:b]


def test_menus_documentados():
    mapa = (RAIZ / "docs" / "tecnico" / "mapa-rom.md").read_text(encoding="utf-8")
    guia = (RAIZ / "docs" / "projeto" / "guia-traducao.md").read_text(encoding="utf-8")
    for trecho in ("Menus e magias", "0x82B6", "0x77D4", "0x7BFE", "0x8784", "trampolim",
                   "0x7D6E", "0x82B2"):
        assert trecho in mapa, trecho
    for trecho in ("SELECIONAR", "ARMA", "TERREMOTO", "BOLAS DE FOGO", "PA"):
        assert trecho in guia, trecho


# ------------------------------------------------------------- no jogo

# Truque para mostrar o nome da magia no HUD (aparece ao lançar a magia, 0x11402 ->
# 0x8778) sem jogar: só na ROM de teste, 0x400 (troca de tarefa) vira 'jmp' para um toco
# em espaço livre que, com $FF962C = 0x00ABCDEn, zera o ouro e chama 0x8778 com d0 = n
# (registradores salvos) e segue a troca de tarefa original.
GANCHO, TOCO = 0x400, 0x9F900
MAGICO = 0x00ABCDE0


def _toco() -> bytes:
    chamada = (bytes.fromhex("48E7FFFE7000103896 2F0240000F42B8962C4EB900008778 4CDF7FFF"
                             .replace(" ", "")))
    original = bytes.fromhex("3A788A4C205F4EF9") + (GANCHO + 6).to_bytes(4, "big")
    cmp1 = bytes.fromhex("0C7800AB962C")          # cmpi.w #$00AB,$962C.w
    cmp2 = bytes.fromhex("0C3800CD962E")          # cmpi.b #$CD,$962E.w
    cod = bytearray(cmp1) + bytes([0x66, 0])      # bne.b original (ajustado abaixo)
    cod += cmp2 + bytes([0x66, 0])
    p_orig = len(cod) + len(chamada)
    cod[7] = p_orig - 8
    cod[15] = p_orig - 16
    cod += chamada + original
    return bytes(cod)


def _com_gancho(rom: bytes) -> bytes:
    rom = bytearray(rom)
    toco = _toco()
    assert set(rom[TOCO:TOCO + len(toco)]) == {0xFF}
    assert rom[GANCHO:GANCHO + 6] == bytes.fromhex("3A788A4C205F")
    rom[TOCO:TOCO + len(toco)] = toco
    rom[GANCHO:GANCHO + 6] = bytes.fromhex("4EF9") + TOCO.to_bytes(4, "big")
    return bytes(rom)


def test_toco_desmonta():
    ins = _desmontar(_toco(), TOCO)
    p_orig = TOCO + 16 + 28
    assert ins[:4] == [("cmpi.w", "#$ab,$962c.w"), ("bne.b", f"${p_orig:x}"),
                       ("cmpi.b", "#$cd,$962e.w"), ("bne.b", f"${p_orig:x}")]
    assert ins[4:10] == [("movem.l", "d0-d7/a0-a6,-(a7)"), ("moveq", "#$0,d0"),
                         ("move.b", "$962f.w,d0"), ("andi.w", "#$f,d0"),
                         ("clr.l", "$962c.w"), ("jsr", "$8778.l")]
    assert ins[10:] == [("movem.l", "(a7)+,d0-d7/a0-a6"), ("movea.w", "$8a4c.w,a5"),
                        ("movea.l", "(a7)+,a0"), ("jmp", "$406.l")]


# Processo à parte (o emulador da sessão está preso à ROM base). NEW GAME, abertura, sai
# de casa; dá 2 de cada magia (contadores $95B8–$95BD, máximos $95BE–$95C3) e um escudo
# (o jogo começa sem: sem ele a categoria não abre; bit 6 de $95CC = possuídos da
# categoria, $95D0 = índice equipado, como os de arma/armadura/botas em $95CA–$95D1) e
# abre o menu: cada tela parte do estado salvo na tela de seleção. Depois, no campo, mostra o
# nome de cada magia no HUD pelo toco.
_SCRIPT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador

saida = Path(sys.argv[3])
saida.mkdir(parents=True, exist_ok=True)
emu = Emulador(CORE_PADRAO, Path(sys.argv[2]))
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
for _ in range(3):
    emu.avancar(2, {"start"}); emu.avancar(120)
for _ in range(144):
    emu.avancar(2, {"c"}); emu.avancar(18)
emu.avancar(20, {"baixo"}); emu.avancar(60)
emu.escrever_ram(0x95B8, bytes([2] * 6 + [3] * 6))
emu.escrever_ram(0x95CC, bytes([0x40]))
emu.escrever_ram(0x95D0, bytes([0x06]))
campo = emu.salvar_estado()

def gravar(nome):
    emu.quadro_png(saida / f"{nome}.png")
    (saida / f"{nome}.vram").write_bytes(emu.vram())

emu.avancar(3, {"start"}); emu.avancar(60)
selecao = emu.salvar_estado()
telas = {"selecao": [], "arma": ["c"], "armadura": ["dir", "c"], "escudo": ["baixo", "c"],
         "botas": ["baixo", "dir", "c"], "item": ["baixo", "baixo", "c"],
         "magia": ["baixo", "baixo", "dir", "c"]}
for nome, botoes in telas.items():
    emu.carregar_estado(selecao)
    for b in botoes:
        emu.avancar(3, {b}); emu.avancar(30)
    emu.avancar(30)
    gravar(nome)
# cursor na 2.ª coluna e de volta (o cursor apaga a posição antiga com espaço)
emu.carregar_estado(selecao)
for b in ("dir", "baixo", "esq", "baixo", "dir", "cima", "cima"):
    emu.avancar(3, {b}); emu.avancar(20)
gravar("cursor")
for n in range(6):
    emu.carregar_estado(campo)
    emu.escrever_ram(0x962C, (MAGICO + n).to_bytes(4, "big"))
    emu.avancar(10)
    gravar(f"hud_{n}")
emu.fechar()
'''.replace("MAGICO", str(MAGICO))


def _rodar(rom: Path, destino: Path) -> None:
    script = destino.parent / "menus.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_SCRIPT, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(RAIZ), str(rom), str(destino)],
                       cwd=str(RAIZ), capture_output=True, timeout=900)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]


def _linha(vram: bytes, lin: int) -> list[int]:
    return [int.from_bytes(vram[0xD800 + 2 * (32 * lin + c):][:2], "big") for c in range(32)]


def _texto(vram: bytes, col: int, lin: int, n: int) -> bytes:
    return bytes(w & 0xFF for w in _linha(vram, lin)[col:col + n])


def _cod(texto: str) -> bytes:
    return TABELA.codificar(texto, "teste")


def _cabecalho(vram: bytes, col: int, texto: bytes) -> None:
    lin = _linha(vram, 4)
    n = len(texto)
    assert lin[col:col + 3] == [0x87AE, 0x87AF, 0x8020]
    assert bytes(w & 0xFF for w in lin[col + 3:col + 3 + n]) == texto
    assert all(w >> 8 == 0xA0 for w in lin[col + 3:col + 3 + n])   # paleta 1, prioridade
    assert lin[col + 3 + n:col + 6 + n] == [0x8020, 0x8FAF, 0x8FAE]
    assert col + 5 + n <= 30


def test_menus_no_jogo(rom_base, tmp_path):
    from PIL import Image

    from ferramentas.cli import main
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, tmp_path / rel)
    (tmp_path / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", tmp_path / "dados" / "scripts")
    arq_base = tmp_path / "base.bin"
    arq_base.write_bytes(rom_base)
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq_base)]) == 0
    teste_base, teste_nova = tmp_path / "teste_base.bin", tmp_path / "teste_nova.bin"
    teste_base.write_bytes(_com_gancho(rom_base))
    teste_nova.write_bytes(_com_gancho((tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()))
    cap_base = RAIZ / "build" / "capturas" / "menus_base"
    cap_nova = RAIZ / "build" / "capturas" / "menus_ptbr"
    _rodar(teste_base, cap_base)
    _rodar(teste_nova, cap_nova)

    def vram(pasta, nome):
        return (pasta / f"{nome}.vram").read_bytes()

    # --- base: o que o jogo desenha (texto da fonte, não gráfico)
    v = vram(cap_base, "selecao")
    _cabecalho(v, 16, b"SELECT")
    for (c, l), t in zip([(15, 7), (24, 7), (15, 10), (24, 10), (15, 13), (24, 13)], OPCOES):
        assert _texto(v, c, l, len(t)) == t.encode()
    _cabecalho(vram(cap_base, "arma"), 16, b"WEAPON")
    _cabecalho(vram(cap_base, "armadura"), 16, b"ARMOR ")
    _cabecalho(vram(cap_base, "escudo"), 16, b"SHIELD")
    _cabecalho(vram(cap_base, "botas"), 16, b"BOOTS ")
    _cabecalho(vram(cap_base, "magia"), 11, b"MAGIC")
    _cabecalho(vram(cap_base, "item"), 11, b"ITEM")

    # --- PT: cabeçalhos, opções, magias, status e HUD
    v = vram(cap_nova, "selecao")
    _cabecalho(v, 14, _cod("SELECIONAR"))
    pos = [(14, 7), (22, 7), (14, 10), (22, 10), (14, 13), (22, 13)]
    for (c, l), t in zip(pos, PT_OPCOES):
        fim = 21 if c == 14 else 30   # até o cursor da coluna da direita / a moldura
        assert _texto(v, c, l, fim - c) == _cod(t) + b" " * (fim - c - len(t)), t
        assert _texto(v, c - 1, l, 1) in (b" ", b"\xB5")   # cursor (tile 0x87B5) ou nada
    # status: PA/PD/PE na coluna 2, linhas 9, 11 e 13 (paleta 1)
    for lin, t in zip((9, 11, 13), PT_STATUS):
        assert _linha(v, lin)[2:4] == [0xA000 | b for b in _cod(t)]
    for tela, pt in (("arma", PT_CABECALHOS[1]), ("armadura", PT_CABECALHOS[2]),
                     ("escudo", PT_CABECALHOS[3]), ("botas", PT_CABECALHOS[4])):
        _cabecalho(vram(cap_nova, tela), 14, _cod(pt))
    _cabecalho(vram(cap_nova, "item"), 11, _cod("ITEM"))
    v = vram(cap_nova, "magia")
    _cabecalho(v, 11, _cod("MAGIA"))
    for (c, l), t in zip([(3, 6), (18, 6), (3, 9), (18, 9), (3, 12), (18, 12)], PT_MAGIAS):
        assert _texto(v, c, l, len(_cod(t))) == _cod(t), t
        assert _linha(v, l)[c + len(_cod(t))] in (0x87A0, 0x8020), t   # nada depois
        # contadores da magia (2 de 3) na linha de baixo, mesma coluna, iguais aos da base
        assert _linha(v, l + 1)[c:c + 3] == _linha(vram(cap_base, "magia"), l + 1)[c:c + 3]
    # cursor: andou pelas 2 colunas (apaga a posição antiga com espaço); nenhuma letra
    # das opções foi apagada
    v = vram(cap_nova, "cursor")
    for (c, l), t in zip(pos, PT_OPCOES):
        assert _texto(v, c, l, len(t)) == _cod(t), t
    # HUD: nome centrado em 10 colunas a partir da 21 (linha 1), como o original
    for n in range(6):
        for pasta, nome in ((cap_base, MAGIAS[n]), (cap_nova, PT_MAGIAS_HUD[n])):
            t = _cod(nome) if pasta is cap_nova else nome.encode()
            esq = (10 - len(t) + 1) // 2
            assert _texto(vram(pasta, f"hud_{n}"), 21, 1, 10) == \
                b" " * esq + t + b" " * (10 - esq - len(t)), (pasta.name, n)

    # comparações lado a lado (base | PT) para conferência visual
    nomes = ["selecao", "arma", "armadura", "escudo", "botas", "item", "magia", "cursor", "hud_0"]
    for nome in nomes:
        with Image.open(cap_base / f"{nome}.png") as a, Image.open(cap_nova / f"{nome}.png") as b:
            par = Image.new("RGB", (a.width * 2 + 8, a.height))
            par.paste(a, (0, 0))
            par.paste(b, (a.width + 8, 0))
            par.save(RAIZ / "build" / "capturas" / f"menus_{nome}_comparacao.png")
