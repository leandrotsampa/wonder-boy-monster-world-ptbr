"""Nomes de itens curtos nos menus (``nomes_menu`` em config/texto.yaml,
``ferramentas/nomes_menu.py``): a lista de equipamentos e a de itens do menu do START
passam a ler uma segunda tabela de nomes (curtos); diálogos, loja e baú continuam com o
banco 1 (nome completo). Mapa: docs/tecnico/mapa-rom.md §6, "Nomes de itens nos menus"."""

import shutil
from pathlib import Path

import pytest
import yaml

from ferramentas.config import ErroConfig, Projeto, carregar_cfg_texto
from ferramentas.nomes_menu import (ARQUIVO, bytes_nomes_menu, checar_nomes_menu,
                                    config_nomes_menu, etapa_nomes_menu, extrair_nomes_menu,
                                    id_menu, planejar_nomes_menu)
from ferramentas.patches import aplicar_patches, carregar_patches
from ferramentas.script.montador import ErroMontagem
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada, carregar_textos
from ferramentas.verificacao import Contexto

RAIZ = Path(__file__).resolve().parent.parent
TABELA = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")

# ROM sintética: a rotina que copia o nome em 0x200 (o prólogo real de 0x1E6A), duas
# chamadas (jsr $200.w) em 0x300 e 0x310, livre em 0x400.
ROTINA, CHAMADA_1, CHAMADA_2 = 0x200, 0x300, 0x310
PROLOGO = "42788D1042788CDE47F88CE0760D61000056"
LIVRE = (0x400, 0x600)
# Lista das telas de equipamento: base 14 colunas a partir da 15 (seta do cursor na 14);
# no build, 17 a partir da 14 e a seta na 13 (patches lista_equip.*): o fundo preto
# inteiro entre as molduras (colunas 12 e 31).
COLUNA_BASE, LARGURA_BASE = 15, 14
COLUNA_EQUIP, LARGURA_EQUIP = 14, 17
SETA = (0x87B5, 0x8FB5)


def _rom() -> bytearray:
    rom = bytearray(b"\x4E\x71" * 0x200 + b"\xFF" * 0x200)
    rom[ROTINA:ROTINA + 18] = bytes.fromhex(PROLOGO)
    rom[CHAMADA_1:CHAMADA_1 + 6] = bytes.fromhex("D0414EB80200")
    rom[CHAMADA_2:CHAMADA_2 + 8] = bytes.fromhex("004000304EB80200")
    return rom


def _nm(**kw):
    nm = {"arquivo": ARQUIVO,
          "rotina": {"end": ROTINA, "original": PROLOGO, "preparo": 12},
          "chamadas": [
              {"tela": "equipamento", "end": CHAMADA_1 + 2, "ini": CHAMADA_1,
               "fim": CHAMADA_1 + 6, "original": "D0414EB80200"},
              {"tela": "item", "end": CHAMADA_2 + 4, "ini": CHAMADA_2, "fim": CHAMADA_2 + 8,
               "original": "004000304EB80200"}],
          "telas": {"equipamento": {"itens": [0x00, 0x1F], "largura": 14},
                    "item": {"itens": [0x31, 0x3B], "largura": 9}}}
    nm.update(kw)
    return nm


def _cfg(**kw):
    return {"nomes_menu": _nm(**kw)}


def _reservar():
    pos = [LIVRE[0]]
    usos = []

    def reservar(nome, tamanho, alinhamento=1):
        ini = pos[0] + (-pos[0] % alinhamento)
        pos[0] = ini + tamanho
        usos.append((nome, ini, tamanho))
        return ini
    return reservar, usos


def _plano(pts, rom=None, **kw):
    rom = _rom() if rom is None else rom
    reservar, usos = _reservar()
    plano = planejar_nomes_menu(rom, config_nomes_menu(_cfg(**kw)), pts, TABELA, reservar)
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

def test_config_ausente_e_valida():
    assert config_nomes_menu({}) is None
    nm = config_nomes_menu(_cfg())
    assert [c["tela"] for c in nm["chamadas"]] == ["equipamento", "item"]
    assert id_menu(0x0E) == "b1m.00E"


@pytest.mark.parametrize("ruim, msg", [
    ({"arquivo": ""}, "arquivo"),
    ({"rotina": {"end": ROTINA, "original": PROLOGO, "preparo": 13}}, "preparo"),
    ({"rotina": {"end": ROTINA, "original": "4278", "preparo": 12}}, "preparo"),
    ({"chamadas": []}, "chamadas"),
    ({"chamadas": [{"tela": "nada", "end": CHAMADA_1 + 2, "ini": CHAMADA_1,
                    "fim": CHAMADA_1 + 6, "original": "D0414EB80200"}]}, "tela"),
    ({"chamadas": [{"tela": "item", "end": CHAMADA_1 + 2, "ini": CHAMADA_1,
                    "fim": CHAMADA_1 + 4, "original": "D041"}]}, "fim"),
    ({"chamadas": [{"tela": "item", "end": CHAMADA_1 + 2, "ini": CHAMADA_1,
                    "fim": CHAMADA_1 + 6, "original": "D041"}]}, "original"),
    ({"telas": {"equipamento": {"itens": [0x10, 0x01], "largura": 14},
                "item": {"itens": [0x31, 0x3B], "largura": 9}}}, "itens"),
    ({"telas": {"equipamento": {"itens": [0x00, 0x1F], "largura": 0},
                "item": {"itens": [0x31, 0x3B], "largura": 9}}}, "largura"),
    ({"telas": {"equipamento": {"itens": [0x00, 0x1F], "largura": 14},
                "item": {"itens": [0x1F, 0x3B], "largura": 9}}}, "duas telas"),
])
def test_config_invalida(ruim, msg):
    with pytest.raises(ErroConfig, match=msg):
        config_nomes_menu(_cfg(**ruim))


# ------------------------------------------------------------- build sintético

def test_sem_nome_curto_nao_grava_nada():
    _, plano, usos = _plano({})
    assert plano == [] and usos == []
    _, plano, usos = _plano({id_menu(0x0E): ""})
    assert plano == [] and usos == []


@pytest.mark.parametrize("muda, msg", [
    (lambda r: r.__setitem__(slice(ROTINA, ROTINA + 2), b"\x70\x01"), "rotina"),
    (lambda r: r.__setitem__(slice(CHAMADA_1, CHAMADA_1 + 2), b"\xD0\x42"), "original"),
])
def test_confere_a_rom_mesmo_sem_nomes(muda, msg):
    rom = _rom()
    muda(rom)
    with pytest.raises(ErroMontagem, match=msg):
        _plano({}, rom=rom)


def test_chamada_tem_de_ir_para_a_rotina():
    rom = _rom()
    rom[CHAMADA_1:CHAMADA_1 + 6] = bytes.fromhex("D0414EB80202")
    with pytest.raises(ErroMontagem, match="chama"):
        _plano({}, rom=rom, chamadas=[{"tela": "equipamento", "end": CHAMADA_1 + 2,
                                       "ini": CHAMADA_1, "fim": CHAMADA_1 + 6,
                                       "original": "D0414EB80202"}])


def test_tabela_rotina_e_trampolins():
    pts = {id_menu(0x0E): "Couro", id_menu(0x33): "Chave Sol"}
    rom, plano, usos = _plano(pts)
    nova = _aplicado(plano, rom)
    nomes = {u[0]: u for u in usos}
    _, rot, tam_rot = nomes["nomes_menu:rotina"]
    _, tab, tam_tab = nomes["nomes_menu:tabela"]
    assert rot % 2 == 0 and tab % 2 == 0
    # tabela: 0x3C words (até o maior item das telas); 0 = sem nome curto (banco 1)
    offs = [int.from_bytes(nova[tab + 2 * i:tab + 2 * i + 2], "big") for i in range(0x3C)]
    assert [i for i, o in enumerate(offs) if o] == [0x0E, 0x33]

    def texto(i):
        ini = tab + offs[i]
        return bytes(nova[ini:nova.index(0, ini)])
    assert texto(0x0E) == TABELA.codificar("Couro") and texto(0x33) == TABELA.codificar(
        "Chave Sol")
    assert tam_tab == 2 * 0x3C + len("Couro") + 1 + len("Chave Sol") + 1
    # rotina: índice fora da tabela ou sem nome curto -> rotina original; senão o mesmo
    # preparo da original e segue o laço de cópia dela (rotina + 18)
    ins = _desmontar(bytes(nova[rot:rot + tam_rot]), rot)
    fb = rot + tam_rot - 6
    assert ins == [
        ("move.w", "d0,d3"), ("andi.w", "#$ff,d3"), ("cmpi.w", "#$3c,d3"),
        ("bcc.b", f"${fb:x}"), ("add.w", "d3,d3"), ("lea.l", f"${tab:x}.l,a2"),
        ("move.w", "(a2,d3.w),d3"), ("beq.b", f"${fb:x}"), ("adda.w", "d3,a2"),
        ("clr.w", "$8d10.w"), ("clr.w", "$8cde.w"), ("lea.l", "$8ce0.w,a3"),
        ("jmp", f"${ROTINA + 18:x}.l"), ("jmp", f"${ROTINA:x}.l")]
    # chamadas: o trecho vira jsr para o trampolim (+ nop), que refaz o trecho chamando a
    # rotina nova
    for ini, fim, antes in ((CHAMADA_1, CHAMADA_1 + 6, [("add.w", "d1,d0")]),
                            (CHAMADA_2, CHAMADA_2 + 8, [("ori.w", "#$30,d0")])):
        _, t, n = nomes[f"nomes_menu:trampolim@{ini:#x}"]
        assert t % 2 == 0
        ins = _desmontar(bytes(nova[ini:fim]), ini)
        assert ins[0] == ("jsr", f"${t:x}.l") and all(i == ("nop", "") for i in ins[1:])
        assert _desmontar(bytes(nova[t:t + n]), t) == antes + [("jsr", f"${rot:x}.l"),
                                                                ("rts", "")]
    # a rotina original e o banco 1 ficam intactos
    assert nova[ROTINA:ROTINA + 18] == rom[ROTINA:ROTINA + 18]


def test_preparo_segue_os_patches_do_prologo():
    """Os patches (config/patches.yaml) são gravados depois desta etapa: o preparo que a
    rotina nova refaz é o do prólogo já com os patches que o tocam (ex.: o buffer do nome
    em outro lugar), e a ROM continua conferida com o original."""
    from ferramentas.patches import Patch

    lea = Patch("buffer", ROTINA + 8, bytes.fromhex("47F88CE0"), bytes.fromhex("47F8AB00"),
                "x", "y")
    fora = Patch("outro", 0x100, bytes.fromhex("4E71"), bytes.fromhex("4E75"), "x", "y")
    rom = _rom()
    reservar, usos = _reservar()
    plano = planejar_nomes_menu(rom, config_nomes_menu(_cfg()), {id_menu(0x0E): "Couro"},
                                TABELA, reservar, patches=[lea, fora])
    nova = _aplicado(plano, rom)
    _, rot, tam = {u[0]: u for u in usos}["nomes_menu:rotina"]
    ins = _desmontar(bytes(nova[rot:rot + tam]), rot)
    assert ("lea.l", "$ab00.w,a3") in ins and ("lea.l", "$8ce0.w,a3") not in ins
    assert nova[ROTINA:ROTINA + 18] == rom[ROTINA:ROTINA + 18]   # o build grava o patch depois


def test_nome_curto_so_texto_e_largura_da_tela():
    with pytest.raises(ErroMontagem, match="só texto"):
        _plano({id_menu(0x0E): "Couro[linha]"})
    with pytest.raises(ErroMontagem, match="b1m.033.*10 colunas.*9"):
        _plano({id_menu(0x33): "Chave Solx"})
    with pytest.raises(ErroMontagem, match="b1m.00E.*15 colunas.*14"):
        _plano({id_menu(0x0E): "A" * 15})


def test_nome_curto_fora_das_telas_e_erro():
    with pytest.raises(ErroMontagem, match="b1m.020"):
        _plano({"b1m.020": "Fogo"})


def test_espaco_contado_para_a_checagem():
    pts = {id_menu(0x0E): "Couro", id_menu(0x33): "Chave Sol"}
    _, _, usos = _plano(pts)
    nm = config_nomes_menu(_cfg())
    assert bytes_nomes_menu(nm, pts, TABELA) == sum(u[2] for u in usos)
    assert bytes_nomes_menu(nm, {}, TABELA) == 0
    assert bytes_nomes_menu(None, pts, TABELA) == 0


def test_extrair_lista_um_por_item_das_telas():
    banco1 = [Entrada(f"b1.{i:03X}.t00", f"N{i:02X}") for i in range(0x41)]
    ents = extrair_nomes_menu(config_nomes_menu(_cfg()), banco1)
    assert [e.id for e in ents] == ([id_menu(i) for i in range(0x20)]
                                    + [id_menu(i) for i in range(0x31, 0x3C)])
    assert ents[0x0E].en == "N0E" and ents[0x0E].pt == ""


def test_etapa_com_projeto(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "traducao" / "textos").mkdir(parents=True)
    cfg = {"regiao_destino": list(LIVRE)} | _cfg()
    (tmp_path / "config" / "texto.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    shutil.copy(RAIZ / "traducao" / "tabela.tbl", tmp_path / "traducao" / "tabela.tbl")
    rom = _rom()
    etapa_nomes_menu(rom, Projeto(raiz=tmp_path, rom={}))
    assert rom == _rom()   # sem o arquivo de nomes curtos: nada muda
    (tmp_path / "traducao" / "textos" / f"{ARQUIVO}.yaml").write_text(
        yaml.safe_dump([{"id": "b1m.00E", "en": "Leather Armor", "pt": "Couro",
                         "status": "traduzido"}]), encoding="utf-8")
    etapa_nomes_menu(rom, Projeto(raiz=tmp_path, rom={}))
    assert rom[CHAMADA_1:CHAMADA_1 + 2] == bytes.fromhex("4EB9")
    assert TABELA.codificar("Couro") + b"\x00" in bytes(rom[LIVRE[0]:LIVRE[1]])


# ------------------------------------------------------------- verificar

def _ctx(curtos: dict[str, str], completos: dict[int, str], nm=None):
    banco1 = [Entrada(f"b1.{i:03X}.t00", f"N{i:02X}", pt=completos.get(i, ""))
              for i in range(0x41)]
    menu = [Entrada(k, "x", pt=v) for k, v in curtos.items()]
    return Contexto(tabela=TABELA, textos={"banco1_itens": banco1, ARQUIVO: menu},
                    glossario=[], extra={"nomes_menu": config_nomes_menu(_cfg())
                                         if nm is None else nm})


def test_verificar_sem_config_nao_checa():
    assert checar_nomes_menu(_ctx({}, {0x0E: "A" * 16}, nm=False)) == []


def test_verificar_largura_por_tela():
    assert checar_nomes_menu(_ctx({}, {})) == []
    # completo sem nome curto: vale a largura da tela em que aparece
    ach = checar_nomes_menu(_ctx({}, {0x0E: "Couraça de Couro"}))
    assert [(a.nivel, a.local) for a in ach] == [("erro", "banco1_itens:b1.00E.t00")]
    assert "14" in ach[0].mensagem and "equipamento" in ach[0].mensagem
    # com o nome curto, o completo pode passar da tela (até o limite do buffer, 16)
    assert checar_nomes_menu(_ctx({id_menu(0x0E): "Couro"}, {0x0E: "Couraça de Couro"})) == []
    ach = checar_nomes_menu(_ctx({id_menu(0x33): "Chave do Sol"}, {}))
    assert [(a.nivel, a.local) for a in ach] == [("erro", f"{ARQUIVO}:b1m.033")]
    assert "9" in ach[0].mensagem and "item" in ach[0].mensagem
    # itens que não aparecem nas telas (magias, consumíveis) não têm limite de menu
    assert checar_nomes_menu(_ctx({}, {0x20: "Bolas de Fogo"})) == []


def test_verificar_nome_curto_invalido():
    ach = checar_nomes_menu(_ctx({id_menu(0x0E): "Couro[linha]"}, {}))
    assert [a.nivel for a in ach] == ["erro"] and "só texto" in ach[0].mensagem
    ach = checar_nomes_menu(_ctx({"b1m.020": "Fogo"}, {}))
    assert [a.nivel for a in ach] == ["erro"] and "tela" in ach[0].mensagem


def test_en_original_passa():
    """O texto original (sem tradução) cabe em todas as telas."""
    textos = {"banco1_itens": carregar_textos(RAIZ / "traducao" / "textos" / "banco1_itens.yaml")}
    textos["banco1_itens"] = [Entrada(e.id, e.en) for e in textos["banco1_itens"]]
    ctx = Contexto(tabela=TABELA, textos=textos, glossario=[],
                   extra={"nomes_menu": config_nomes_menu(carregar_cfg_texto(RAIZ))})
    assert checar_nomes_menu(ctx) == []


def test_etapa_recusa_sobreposicao(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "traducao" / "textos").mkdir(parents=True)
    cfg = {"regiao_destino": list(LIVRE)} | _cfg()
    (tmp_path / "config" / "texto.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (tmp_path / "config" / "patches.yaml").write_text(yaml.safe_dump({"patches": [
        {"id": "p", "end": CHAMADA_2 + 4, "original": "4EB8", "novo": "4E71"}]}),
        encoding="utf-8")
    shutil.copy(RAIZ / "traducao" / "tabela.tbl", tmp_path / "traducao" / "tabela.tbl")
    with pytest.raises(ErroConfig, match="sobrepõe o patch p"):
        etapa_nomes_menu(_rom(), Projeto(raiz=tmp_path, rom={}))


# ------------------------------------------------------------- ROM real

def _nm_real() -> dict:
    return config_nomes_menu(carregar_cfg_texto(RAIZ))


def test_config_real_confere_com_a_base(rom_base):
    nm = _nm_real()
    assert {c["tela"]: c["end"] for c in nm["chamadas"]} == {"equipamento": 0x8428,
                                                            "item": 0x7AD6}
    reservar, usos = _reservar()
    assert planejar_nomes_menu(rom_base, nm, {}, TABELA, reservar) == [] and usos == []
    conferir = __import__("ferramentas.nomes_menu", fromlist=["x"]).conferir_conflitos
    conferir(Projeto(raiz=RAIZ, rom={}), carregar_cfg_texto(RAIZ), nm)


def test_chamadas_da_rotina_na_base(rom_base):
    """Quem chama 0x1E6A (busca em todo endereço par do código): o baú (0x1EEC, fica com
    o nome completo) e as duas listas do menu (na config)."""
    chamadas = []
    for p in range(0x200, 0x80000, 2):
        w = int.from_bytes(rom_base[p:p + 2], "big")
        alvo = None
        if w == 0x4EB8 or w == 0x4EF8:
            alvo = int.from_bytes(rom_base[p + 2:p + 4], "big")
        elif w in (0x4EB9, 0x4EF9):
            alvo = int.from_bytes(rom_base[p + 2:p + 6], "big")
        elif w in (0x6100, 0x6000):
            d = int.from_bytes(rom_base[p + 2:p + 4], "big")
            alvo = p + 2 + (d - 0x10000 if d & 0x8000 else d)
        elif w >> 8 in (0x60, 0x61) and w & 0xFF not in (0, 0xFF):
            d = w & 0xFF
            alvo = p + 2 + (d - 256 if d & 0x80 else d)
        if alvo == 0x1E6A:
            chamadas.append(p)
    assert chamadas == [0x1EEC, 0x7AD6, 0x8428]
    assert sorted(c["end"] for c in _nm_real()["chamadas"]) == [0x7AD6, 0x8428]


def test_trampolins_reais(rom_base):
    """O que vai para o trampolim não usa o PC nem a pilha e nenhum desvio cai no meio
    do trecho trocado."""
    from test_menus import _alvos_de_desvio

    alvos = _alvos_de_desvio(rom_base)
    esperados = {0x8426: [("add.w", "d1,d0"), ("jsr", "$1e6a.w")],
                 0x7AD2: [("ori.w", "#$30,d0"), ("jsr", "$1e6a.w")]}
    nm = _nm_real()
    for c in nm["chamadas"]:
        assert rom_base[c["ini"]:c["fim"]] == bytes.fromhex(c["original"])
        assert not {a for a in alvos if c["ini"] < a < c["fim"]}, hex(c["ini"])
    assert {c["ini"]: _desmontar(rom_base[c["ini"]:c["fim"]], c["ini"])
            for c in nm["chamadas"]} == esperados
    # o prólogo da rotina: o preparo (12 bytes) não depende de a2/d3; o resto busca no
    # banco 1 e é refeito pela rotina nova com a tabela dos nomes curtos
    rot = nm["rotina"]
    assert _desmontar(rom_base[rot["end"]:rot["end"] + 18], rot["end"]) == [
        ("clr.w", "$8d10.w"), ("clr.w", "$8cde.w"), ("lea.l", "$8ce0.w,a3"),
        ("moveq", "#$d,d3"), ("bsr.w", "$1ed0")]


def test_largura_da_lista_de_equipamentos(rom_base):
    """0x8428 centraliza em 14 colunas (moveq #$E,d1; sub.w $8CDE,d1; lsr.w #1,d1) a
    partir da coluna 15 (move.w #$F06,d7 em 0x83D4); a lista de itens usa as posições de
    0x7B0A (colunas 2, 12 e 22)."""
    assert _desmontar(rom_base[0x842E:0x8436], 0x842E) == [
        ("moveq", "#$e,d1"), ("sub.w", "$8cde.w,d1"), ("lsr.w", "#$1,d1")]
    assert _desmontar(rom_base[0x83D4:0x83D8], 0x83D4) == [("move.w", "#$f06,d7")]
    pos = rom_base[0x7B0A:0x7B22]
    assert sorted({pos[i] for i in range(0, 24, 2)}) == [2, 12, 22]
    telas = _nm_real()["telas"]
    assert telas["equipamento"]["largura"] == LARGURA_EQUIP and telas["item"]["largura"] == 9


def test_lista_de_equipamentos_alargada(rom_base):
    """Os patches lista_equip.* põem a seta do cursor na coluna 13 (0x7848) e o nome em 17
    colunas a partir da 14 (o fundo preto entre as molduras das colunas 12 e 31); o pisca
    do item equipado (0x7E46, laço subq/bne de 0x8762) apaga as mesmas 17 colunas."""
    ps = {p.id: p for p in carregar_patches(Projeto(raiz=RAIZ, rom={}))}
    rom = bytearray(rom_base)
    aplicar_patches(rom, [p for i, p in ps.items() if i.startswith("lista_equip.")])
    assert _desmontar(rom_base[0x7848:0x784E], 0x7848) == [("move.w", "#$e07,$9624.w")]
    assert _desmontar(rom_base[0x7E46:0x7E4A], 0x7E46) == [("move.w", "#$f06,d7")]
    assert _desmontar(rom_base[0x7E76:0x7E78], 0x7E76) == [("moveq", "#$d,d5")]
    assert _desmontar(bytes(rom[0x7848:0x784E]), 0x7848) == [("move.w", "#$d07,$9624.w")]
    assert _desmontar(bytes(rom[0x83D4:0x83D8]), 0x83D4) == [("move.w", "#$e06,d7")]
    assert _desmontar(bytes(rom[0x842E:0x8430]), 0x842E) == [("moveq", "#$11,d1")]
    assert _desmontar(bytes(rom[0x7E46:0x7E4A]), 0x7E46) == [("move.w", "#$e06,d7")]
    assert _desmontar(bytes(rom[0x7E76:0x7E78]), 0x7E76) == [("moveq", "#$11,d5")]
    assert COLUNA_EQUIP + LARGURA_EQUIP == 31
    # ao voltar para a seleção, 0x7808 limpa 9 linhas a partir da coluna 13 (laço de
    # 0x8762): na base 17 tiles (13-29); com a lista indo até a coluna 30, 18 tiles
    assert _desmontar(rom_base[0x7808:0x7814], 0x7808) == [
        ("move.w", "#$d06,d7"), ("moveq", "#$8,d3"), ("bsr.w", "$83b0"), ("moveq", "#$11,d5")]
    assert _desmontar(bytes(rom[0x7812:0x7814]), 0x7812) == [("moveq", "#$12,d5")]
    assert 13 + 0x12 == COLUNA_EQUIP + LARGURA_EQUIP


# ------------------------------------------------------------- textos decididos

def _completos() -> dict[int, str]:
    return {int(e.id[3:6], 16): e.pt for e in
            carregar_textos(RAIZ / "traducao" / "textos" / "banco1_itens.yaml") if e.pt}


def _curtos() -> dict[int, str]:
    return {int(e.id[4:7], 16): e.pt for e in
            carregar_textos(RAIZ / "traducao" / "textos" / f"{ARQUIVO}.yaml") if e.pt}


def _no_menu(item: int) -> str:
    return _curtos().get(item) or _completos()[item]


def test_textos_decididos():
    """Decisões do autor: itens e magias traduzidos (nomes próprios ficam), magias como no
    menu (Task 3, TERREMOTO); nas telas de equipamento (17 colunas) o menu mostra o
    nome completo; Knight = Militar, Hard = Robusta."""
    comp, curto = _completos(), _curtos()
    assert comp[0x1D] == "Botas de Couro"
    assert not set(curto) & set(range(0x20))
    assert [comp[i] for i in range(0x20, 0x26)] == ["Bolas de Fogo", "Terremoto", "Trovões",
                                                    "Super Força", "Blindagem", "Voltar"]
    assert comp[0x01] == "Excalibur" and comp[0x2A] == "Elixir"
    # buffer do nome maior (testes/test_buffer_nome.py): os completos naturais voltam
    assert [comp[i] for i in (0x08, 0x0E, 0x16, 0x19, 0x1C, 0x04)] == [
        "Armadura Lendária", "Armadura de Couro", "Escudo de Madeira", "Botas de Cerâmica",
        "Botas de Escalada", "Lança de Batalha"]
    # Pygmy fica em inglês (termo da série), também no menu
    assert [comp[i] for i in (0x07, 0x0F, 0x17, 0x1F)] == [
        "Espada Pygmy", "Armadura Pygmy", "Escudo Pygmy", "Botas Pygmy"]
    assert [comp[i] for i in (0x02, 0x0A, 0x12, 0x0C, 0x14)] == [
        "Espada Militar", "Armadura Militar", "Escudo Militar", "Armadura Robusta",
        "Escudo Robusto"]
    assert [curto[i] for i in (0x33, 0x34)] == ["Chave Sol", "Chave Lua"]
    # todo nome usado no jogo traduzido (os slots 0x26 e 0x30 são lixo sem uso)
    ids = {int(e.id[3:6], 16) for e in
           carregar_textos(RAIZ / "traducao" / "textos" / "banco1_itens.yaml")}
    assert ids - set(comp) == {0x26, 0x30}
    # arquivo dos nomes curtos: um por item das telas, com a nota da tela e do completo
    ents = carregar_textos(RAIZ / "traducao" / "textos" / f"{ARQUIVO}.yaml")
    assert [e.id for e in ents] == [id_menu(i) for i in [*range(0x20), *range(0x31, 0x3C)]]
    for e in ents:
        assert "tela" in e.nota and comp[int(e.id[4:7], 16)] in e.nota, e.id


def test_glossario_documentado():
    guia = (RAIZ / "docs" / "projeto" / "guia-traducao.md").read_text(encoding="utf-8")
    comp, curto = _completos(), _curtos()
    for i, c in comp.items():
        linha = next((l for l in guia.splitlines() if l.startswith("|") and f"| {c} |" in l),
                     None)
        assert linha, c
        assert f"| {curto.get(i, '—')} |" in linha, (c, linha)
    mapa = (RAIZ / "docs" / "tecnico" / "mapa-rom.md").read_text(encoding="utf-8")
    for trecho in ("Nomes de itens nos menus", "0x8426", "0x7AD2", "banco1_menu"):
        assert trecho in mapa, trecho


# ------------------------------------------------------------- build real

def _copiar_projeto(destino: Path, rom_base: bytes) -> Path:
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, destino / rel)
    (destino / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", destino / "dados" / "scripts")
    arq = destino / "base.bin"
    arq.write_bytes(rom_base)
    return arq


def _construir(destino: Path, rom_base: bytes) -> bytes:
    from ferramentas.cli import main

    arq = _copiar_projeto(destino, rom_base)
    assert main(["--raiz", str(destino), "construir", "--rom", str(arq)]) == 0
    return (destino / "build" / "wbmw-ptbr.bin").read_bytes()


def _nome_banco1(rom: bytes, item: int) -> str:
    bases = int.from_bytes(rom[0x1CC10:0x1CC14], "big")
    b1 = int.from_bytes(rom[bases + 4:bases + 8], "big")
    ini = b1 + int.from_bytes(rom[b1 + 2 * item:b1 + 2 * item + 2], "big")
    return TABELA.decodificar(rom[ini:rom.index(b"\x00", ini)])


def test_build_real_tabela_dos_menus(rom_base, tmp_path):
    rom = _construir(tmp_path, rom_base)
    regiao = carregar_cfg_texto(RAIZ)["regiao_destino"]

    def jsr_alvo(end):
        ins = _desmontar(rom[end:end + 6], end)
        assert ins[0][0] == "jsr", (hex(end), ins)
        alvo = int(ins[0][1][1:-2], 16)
        assert regiao[0] <= alvo < regiao[1]
        return alvo
    rotinas = set()
    for ini, antes in ((0x8426, ("add.w", "d1,d0")), (0x7AD2, ("ori.w", "#$30,d0"))):
        t = jsr_alvo(ini)
        ins = _desmontar(rom[t:t + 12], t)
        assert ins[0] == antes and ins[1][0] == "jsr" and ins[2] == ("rts", "")
        rotinas.add(int(ins[1][1][1:-2], 16))
    assert len(rotinas) == 1
    rot = rotinas.pop()
    lea = next(i for i in _desmontar(rom[rot:rot + 40], rot)
               if i[0] == "lea.l" and i[1].endswith(".l,a2"))
    tab = int(lea[1].split(".")[0][1:], 16)
    nm = _nm_real()
    curtos = _curtos()
    for item in range(0x3C):
        off = int.from_bytes(rom[tab + 2 * item:tab + 2 * item + 2], "big")
        if item in curtos:
            assert TABELA.decodificar(rom[tab + off:rom.index(b"\x00", tab + off)]) == \
                curtos[item], hex(item)
        else:
            assert off == 0, hex(item)
    assert set(curtos) <= {i for t in nm["telas"].values()
                           for i in range(t["itens"][0], t["itens"][1] + 1)}
    # o banco 1 (diálogos, loja, baú) continua com o nome completo
    for item, nome in _completos().items():
        assert _nome_banco1(rom, item) == nome, hex(item)
    # a rotina original e a chamada do baú só mudam pelos patches declarados (buffer_nome.*)
    from ferramentas.patches import aplicar_patches, carregar_patches

    com_patches = bytearray(rom_base)
    aplicar_patches(com_patches, carregar_patches(Projeto(raiz=RAIZ, rom={})))
    assert rom[0x1E6A:0x1EF0] == com_patches[0x1E6A:0x1EF0]
    assert com_patches[0x1E6A:0x1EF0] != rom_base[0x1E6A:0x1EF0]


def test_ida_e_volta_sem_nomes_curtos(rom_base, tmp_path):
    """Sem nomes curtos, as chamadas dos menus ficam como na base."""
    from ferramentas.cli import main
    from ferramentas.textos import salvar_textos

    arq = _copiar_projeto(tmp_path, rom_base)
    caminho = tmp_path / "traducao" / "textos" / f"{ARQUIVO}.yaml"
    salvar_textos(caminho, [Entrada(e.id, e.en, nota=e.nota) for e in carregar_textos(caminho)])
    # sem curto, o completo aparece no menu: os que passam da tela voltam ao original
    caminho = tmp_path / "traducao" / "textos" / "banco1_itens.yaml"
    salvar_textos(caminho, [Entrada(e.id, e.en) for e in carregar_textos(caminho)])
    assert main(["--raiz", str(tmp_path), "construir", "--rom", str(arq)]) == 0
    rom = (tmp_path / "build" / "wbmw-ptbr.bin").read_bytes()
    for c in _nm_real()["chamadas"]:
        assert rom[c["ini"]:c["fim"]] == rom_base[c["ini"]:c["fim"]]
    rel = (tmp_path / "build" / "relatorio.txt").read_text(encoding="utf-8")
    assert "nomes_menu" not in rel


# ------------------------------------------------------------- no jogo

# Processo à parte (o emulador da sessão está preso à ROM base). Menus: NEW GAME,
# abertura, sai de casa, dá equipamentos (bits de posse por categoria em $95CA–$95CD,
# equipado em $95CE–$95D1) e os 11 itens da tela ITEM ($958D–$9597) e abre cada tela.
# Diálogos: a entrada 0 da tabela de diálogos aponta para o diálogo a testar (só na ROM
# de teste) e cada página é gravada.
POSSE = {"arma": (0x95, 0), "armadura": (0x55, 4), "escudo": (0xC5, 6), "botas": (0x72, 5)}

_SCRIPT_MENU = r'''
import sys
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
emu.escrever_ram(0x95CA, bytes(POSSE))
emu.escrever_ram(0x958C, bytes([0] + [1] * 11))
emu.avancar(3, {"start"}); emu.avancar(60)
selecao = emu.salvar_estado()
(saida / "selecao.vram").write_bytes(emu.vram())
telas = {"arma": ["c"], "armadura": ["dir", "c"], "escudo": ["baixo", "c"],
         "botas": ["baixo", "dir", "c"], "item": ["baixo", "baixo", "c"]}
for nome, botoes in telas.items():
    emu.carregar_estado(selecao)
    for b in botoes:
        emu.avancar(3, {b}); emu.avancar(30)
    emu.avancar(30)
    emu.quadro_png(saida / f"{nome}.png")
    (saida / f"{nome}.vram").write_bytes(emu.vram())
    emu.avancar(3, {"b"}); emu.avancar(40)
    emu.quadro_png(saida / f"{nome}_volta.png")
    (saida / f"{nome}_volta.vram").write_bytes(emu.vram())
emu.fechar()
'''.replace("POSSE", repr([p for p, _ in POSSE.values()] + [e for _, e in POSSE.values()]))

_SCRIPT_DIALOGO = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ferramentas.emulador.libretro import CORE_PADRAO, Emulador

saida = Path(sys.argv[3])
saida.mkdir(parents=True, exist_ok=True)
emu = Emulador(CORE_PADRAO, Path(sys.argv[2]))
emu.avancar(300); emu.avancar(2, {"start"}); emu.avancar(240)
for _ in range(2):
    emu.avancar(2, {"start"}); emu.avancar(120)
emu.avancar(2, {"start"})
for n in range(36):
    emu.avancar(50)
    emu.quadro_png(saida / f"p{n:02d}.png")
    (saida / f"p{n:02d}.vram").write_bytes(emu.vram())
    emu.avancar(2, {"c"})
emu.fechar()
'''


def _rodar_script(script_txt: str, nome: str, rom: Path, destino: Path) -> None:
    import subprocess
    import sys

    script = destino.parent / f"{nome}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(script_txt, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(RAIZ), str(rom), str(destino)],
                       cwd=str(RAIZ), capture_output=True, timeout=900)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]


def _linha(vram: bytes, lin: int) -> list[int]:
    return [int.from_bytes(vram[0xD800 + 2 * (32 * lin + c):][:2], "big") for c in range(32)]


def _texto(vram: bytes, col: int, lin: int, n: int) -> bytes:
    return bytes(w & 0xFF for w in _linha(vram, lin)[col:col + n])


def _cod(texto: str) -> bytes:
    return TABELA.codificar(texto, "teste")


def _nomes_equipamento(vram: bytes, col: int, larg: int) -> list[bytes]:
    """Nomes da lista de equipamentos (``larg`` colunas a partir de ``col``, linhas 6-14
    entre as bordas), conferindo a centralização ((larg - n) / 2 espaços à esquerda), que
    nada passa da área e que as molduras (colunas 12 e 31) ficam intactas."""
    nomes = []
    for lin in range(6, 15):
        linha = _linha(vram, lin)
        assert all(0x87A1 <= linha[c] <= 0x87BF for c in (12, 31)), lin   # moldura
        # 0x87A0 = fundo do painel (preto, como o espaço 0x8020): fica na coluna 30 das
        # linhas que a lista não escreve. A seta do cursor (pisca) fica na coluna antes
        # dos nomes, nunca dentro deles.
        assert col - 1 >= 13 and all(w not in SETA for w in linha[col:col + larg]), lin
        cel = bytes(0x20 if w == 0x87A0 or w in SETA else w & 0xFF for w in linha[13:31])
        txt = cel[col - 13:col - 13 + larg].strip(b" ")
        assert cel[:col - 13].strip(b" ") == cel[col - 13 + larg:].strip(b" ") == b"", lin
        cel = cel[col - 13:col - 13 + larg]
        if not txt or set(txt) <= {0xBE, 0xBF}:
            continue
        assert cel.index(txt) == (larg - len(txt)) // 2, (lin, cel)
        nomes.append(txt)
    return nomes


def _tem_texto(vram: bytes, dados: bytes) -> bool:
    baixos = bytes(vram[i + 1] for i in range(0xC000, 0x10000, 2))
    return dados in baixos


def _trocar_dialogo_0(rom: bytes, origem: int, item: int | None = None) -> bytes:
    """Entrada 0 da tabela de diálogos = a do diálogo ``origem``; com ``item``, o
    primeiro ``0B 0A xx`` do script passa a definir esse item."""
    rom = bytearray(rom)
    tab = int.from_bytes(rom[0x1CC14:0x1CC18], "big")
    rom[tab:tab + 3] = rom[tab + 3 * origem:tab + 3 * origem + 3]
    if item is not None:
        d = int.from_bytes(rom[tab + 1:tab + 3], "big")
        ini = tab + (d - 0x10000 if d & 0x8000 else d)
        p = rom.index(b"\x0B\x0A", ini)
        assert p - ini < 16
        rom[p + 2] = item
    return bytes(rom)


def test_nomes_no_jogo(rom_base, tmp_path):
    from PIL import Image

    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    nova = _construir(tmp_path, rom_base)
    capturas = RAIZ / "build" / "capturas"
    for nome, dados in (("base", rom_base), ("ptbr", nova)):
        arq = tmp_path / f"{nome}.bin"
        arq.write_bytes(dados)
        _rodar_script(_SCRIPT_MENU, "nomes_menu", arq, capturas / f"nomes_menu_{nome}")
        for caso, origem, item in (("senhora", 2, None), ("loja", 10, 0x1C)):
            arq = tmp_path / f"{nome}_{caso}.bin"
            arq.write_bytes(_trocar_dialogo_0(dados, origem, item))
            _rodar_script(_SCRIPT_DIALOGO, "nomes_dialogo", arq,
                          capturas / f"nomes_{caso}_{nome}")
    ens = {int(e.id[3:6], 16): e.en for e in
           carregar_textos(RAIZ / "traducao" / "textos" / "banco1_itens.yaml")}
    comp = _completos()

    # --- menus: cada categoria mostra o nome do menu (curto, ou o completo sem curto)
    for nome, nome_de, area in (("base", lambda i: ens[i], (COLUNA_BASE, LARGURA_BASE)),
                                ("ptbr", _no_menu, (COLUNA_EQUIP, LARGURA_EQUIP))):
        pasta = capturas / f"nomes_menu_{nome}"
        for k, (cat, (posse, _)) in enumerate(POSSE.items()):
            vram = (pasta / f"{cat}.vram").read_bytes()
            esperados = sorted(_cod(nome_de(8 * k + b)) for b in range(8) if posse >> b & 1)
            assert sorted(_nomes_equipamento(vram, *area)) == esperados, (nome, cat)
        vram = (pasta / "item.vram").read_bytes()
        pos = rom_base[0x7B0A:0x7B22]
        for d2 in range(1, 12):
            col, lin = pos[2 * d2], pos[2 * d2 + 1] + 1
            t = _cod(nome_de(0x30 + d2))
            # depois do nome, o fundo do painel (0x87A0) ou a moldura: nada encostado
            assert _texto(vram, col, lin, len(t)) == t, (nome, hex(0x30 + d2))
            assert col + len(t) == 31 or _linha(vram, lin)[col + len(t)] == 0x87A0,                 (nome, hex(0x30 + d2))
    # de volta à seleção, o painel fica como antes: nada da lista sobra (0x87A0 e 0x8020
    # são o mesmo preto; a seta muda de lugar)
    for nome in ("base", "ptbr"):
        pasta = capturas / f"nomes_menu_{nome}"

        def painel(v):
            return [[0 if w in (0x87A0, 0x8020, *SETA) else w for w in _linha(v, lin)[13:31]]
                    for lin in range(6, 15)]
        sel = painel((pasta / "selecao.vram").read_bytes())
        for t in [*POSSE, "item"]:
            assert painel((pasta / f"{t}_volta.vram").read_bytes()) == sel, (nome, t)
    # o curto aparece no menu e o completo não (tela ITEM: Chave do Sol -> Chave Sol)
    v = (capturas / "nomes_menu_ptbr" / "item.vram").read_bytes()
    assert _tem_texto(v, _cod(_curtos()[0x33])) and not _tem_texto(v, _cod(comp[0x33]))

    # --- diálogos: a senhora dá Elixir e a magia Bolas de Fogo; a loja oferece as Botas
    # de Escalada (o item do script trocado para 0x1C só na ROM de teste): nome completo
    for caso, itens in (("senhora", (0x2A, 0x20)), ("loja", (0x1C,))):
        for nome, nome_de in (("base", lambda i: ens[i]), ("ptbr", lambda i: comp[i])):
            pasta = capturas / f"nomes_{caso}_{nome}"
            pags = [(p, p.with_suffix(".vram").read_bytes()) for p in sorted(pasta.glob("p*.png"))]
            for i in itens:
                achadas = [p for p, v in pags if _tem_texto(v, _cod(nome_de(i)))]
                assert achadas, (caso, nome, hex(i))
                if nome == "ptbr":
                    shutil.copy(achadas[0], capturas / f"nomes_{caso}_{i:02x}.png")

    # comparações lado a lado (base | PT) para conferência visual
    for t in [*POSSE, "item"]:
        with Image.open(capturas / "nomes_menu_base" / f"{t}.png") as a, \
                Image.open(capturas / "nomes_menu_ptbr" / f"{t}.png") as b:
            par = Image.new("RGB", (a.width * 2 + 8, a.height))
            par.paste(a, (0, 0))
            par.paste(b, (a.width + 8, 0))
            par.save(capturas / f"nomes_menu_{t}_comparacao.png")
