"""Checagens de largura de linha (checar_largura) e linhas por página (checar_linhas).

Regras confirmadas no jogo em testes/test_validacao_jogo.py (Plano 3, Tarefa 6).
"""

from pathlib import Path

import pytest

from ferramentas.config import carregar_cfg_texto
from ferramentas.script.extracao import extrair_texto
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada
from ferramentas.verificacao import (CHECAGENS_PADRAO, DIGITOS_NUMERO, Contexto, checar_largura,
                                     checar_linhas)

RAIZ = Path(__file__).resolve().parent.parent
TABELA = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")


def _ctx(textos, n=10, alt=None, **extra):
    return Contexto(tabela=TABELA, glossario=[], textos=textos,
                    extra={"largura_linha": n, "linhas_por_caixa": alt} | extra)


def test_linha_longa_erro():
    # [linha] volta ao recuo (2): a 2.ª linha tem 2 + 11 = 13 colunas
    e = Entrada("dialogo.000.t00", "x", pt="aaaaa[linha]bbbbbbbbbbb[linha]cc")
    achados = checar_largura(_ctx({"dialogos": [e]}))
    assert len(achados) == 1
    assert achados[0].nivel == "erro" and achados[0].checagem == "largura"
    assert "dialogos:dialogo.000.t00" in achados[0].local
    assert "linha 2 tem 13 colunas e o limite é 10" in achados[0].mensagem


def test_linha_no_limite_passa_e_quebra2_volta_a_coluna_0():
    e = Entrada("dialogo.000.t00", "x", pt="aaaaaaaaaa[quebra2]bbbbbbbbbb[espera][linha]cccccccc")
    assert checar_largura(_ctx({"dialogos": [e]})) == []


def test_pt_vazio_e_arquivo_de_nomes_ignorados():
    textos = {"dialogos": [Entrada("d.t00", "a" * 40, pt="")],
              "banco1_itens": [Entrada("b1.000.t00", "x", pt="a" * 40)]}
    assert checar_largura(_ctx(textos)) == []
    assert checar_linhas(_ctx(textos, alt=1)) == []


def test_controles_sem_largura_e_avanco():
    # [cor]/[/cor]/[espera]/[$03][$06] não ocupam coluna; [$04][$03] avança 3 colunas
    ok = Entrada("d.t00", "x", pt="[$03][$06][cor]aaaaaaa[/cor][espera]")
    longo = Entrada("d.t01", "x", pt="[$04][$03]aaaaaaaa")
    achados = checar_largura(_ctx({"dialogos": [ok, longo]}))
    assert [a.local for a in achados] == ["dialogos:d.t01"]


def test_variavel_conta_maior_nome():
    itens = [Entrada("b1.000.t00", "Sword"), Entrada("b1.001.t00", "Excalibur!!")]  # 11
    # [item:FF] não existe no banco -> maior nome (11); 11 + 1 = 12 > 10
    e = Entrada("d.t00", "x", pt="[item:FF]a")
    achados = checar_largura(_ctx({"dialogos": [e], "banco1_itens": itens}))
    assert len(achados) == 1 and "12" in achados[0].mensagem
    # entrada conhecida conta o próprio tamanho (5 + 1 = 6): passa
    e2 = Entrada("d.t01", "x", pt="[item:00]a")
    assert checar_largura(_ctx({"dialogos": [e2], "banco1_itens": itens})) == []
    # s0 com valor em tempo de execução (dois trechos) soma o maior nome do banco 1
    s0 = [Entrada("b0.002.t00", "[cor]"), Entrada("b0.002.t01", "[/cor]")]
    e3 = Entrada("d.t02", "x", pt="[s0:02]")
    achados = checar_largura(_ctx({"dialogos": [e3], "banco0_sistema": s0, "banco1_itens": itens}))
    assert len(achados) == 1 and "11" in achados[0].mensagem


def test_sem_largura_configurada_nao_checa():
    e = Entrada("d.t00", "x", pt="a" * 99)
    assert checar_largura(Contexto(tabela=TABELA, glossario=[], textos={"dialogos": [e]})) == []
    assert checar_linhas(Contexto(tabela=TABELA, glossario=[], textos={"dialogos": [e]})) == []


def _ctx_original(rom_base):
    cfg = carregar_cfg_texto(RAIZ)
    esqueleto, grupos = extrair_texto(rom_base, cfg, TABELA)
    textos = {a: [Entrada(e.id, e.en, pt=e.en) for e in es] for a, es in grupos.items()}
    return Contexto(tabela=TABELA, glossario=[], textos=textos,
                    extra={"largura_linha": cfg["largura_linha"],
                           "linhas_por_caixa": cfg["linhas_por_caixa"],
                           "janelas": cfg["janelas"], "esqueleto": esqueleto})


def test_en_original_passa(rom_base):
    ctx = _ctx_original(rom_base)
    assert checar_largura(ctx) == []
    assert checar_linhas(ctx) == []


def test_janelas_conferem_com_a_rom(rom_base):
    cfg = carregar_cfg_texto(RAIZ)
    ptr = int.from_bytes(rom_base[0x1CC18:0x1CC1C], "big")
    assert ptr == 0x1DD74
    tabela = [tuple(rom_base[ptr + 4 * i:ptr + 4 * i + 4]) for i in range(8)]
    assert [(j["x"], j["y"], j["largura"], j["altura"]) for j in cfg["janelas"]] == tabela
    # a janela 0 é o padrão para texto sem janela conhecida
    assert (cfg["largura_linha"], cfg["linhas_por_caixa"]) == (23, 3)


def test_checar_linhas_esta_nas_checagens_padrao():
    assert checar_linhas in CHECAGENS_PADRAO


# ---- uma regra por teste (comportamento do motor, ver mapa-rom.md "Largura de linha")

def _linhas(texto, textos=None, largura=None):
    from ferramentas.verificacao import _Larguras
    return _Larguras(textos or {}).linhas(texto, largura)


def test_linha_usa_recuo_e_quebra2_coluna_0():
    assert _linhas("a[linha]b") == [1, 3]           # recuo padrão 2
    assert _linhas("a[quebra2]b") == [1, 1]
    assert _linhas("[$0A][$04]a[linha]b") == [1, 5]  # [$0A] define o recuo, não avança


def test_04_avanca_e_so_quebra_na_borda():
    # no meio da linha só avança (estouro é erro)
    assert _linhas("Hello[$04][$02]" + "a" * 24) == [31]
    ach = checar_largura(_ctx({"dialogos": [Entrada("d.t00", "x", pt="Hello[$04][$02]"
                                                    + "a" * 24)]}, 25))
    assert len(ach) == 1 and "31" in ach[0].mensagem
    # se o avanço chega à borda (>= largura), o motor quebra: o resto vai para a coluna 0
    assert _linhas("a" * 23 + "[$04][$02]" + "b" * 5, largura=23) == [23, 5]
    assert _linhas("a" * 20 + "[$04][$05]" + "b" * 5, largura=23) == [20, 5]
    assert _linhas("a" * 20 + "[$04][$02]" + "b" * 5, largura=23) == [27]


def test_argumento_de_04_e_hex_e_nao_quebra():
    # [$04][$02] é 04 02 (avança 2); o argumento 02/09 não é uma nova linha
    assert _linhas("[$04][$02]" + "a" * 24) == [26]
    assert _linhas("[$04][$09]a") == [10]  # 04 09
    assert _linhas("[$04][$20]a") == [33]  # argumento imprimível (0x20) também é número


def test_banco3_so_primeiro_trecho_e_recomeca_no_recuo():
    b3 = {"banco3_lojas": [Entrada("b3.006.t00", "Buy"), Entrada("b3.006.t01", "x" * 23)]}
    assert _linhas("[s3:06]yyyyyyyyyyyy", b3) == [3, 14]
    # script de 1 trecho: não recomeça a linha
    b3 = {"banco3_lojas": [Entrada("b3.007.t00", "Buy")]}
    assert _linhas("[s3:07]yy", b3) == [5]


def test_banco3_que_limpa_a_janela_recomeca_na_coluna_0():
    from ferramentas.verificacao import _Larguras
    b3 = {"banco3_lojas": [Entrada("b3.006.t00", "Buy"), Entrada("b3.006.t01", "x" * 23)]}
    medidor = _Larguras(b3)
    medidor.b3_limpa_no_fim = {"b3.006"}
    assert medidor.linhas("[s3:06]yyyyyyyyyyyy") == [3, 12]


def test_lacuna_numerica_no_banco0_conta_6_digitos():
    assert DIGITOS_NUMERO == 6
    b0 = {"banco0_sistema": [Entrada("b0.005.t00", "ab"), Entrada("b0.005.t01", "cd")]}
    assert _linhas("[s0:05]", b0) == [2 + 6 + 2]


def test_digitos_numero_cobre_as_tabelas_de_preco(rom_base):
    """Maior número impresso pelo subop 0B 05: preços (0x1DAE, índices válidos 0x00–0x2E;
    0x2F em diante é código) e diárias da estalagem (0x1906, 16 valores)."""
    precos = [int.from_bytes(rom_base[0x1DAE + 4 * i:0x1DB2 + 4 * i], "big") for i in range(0x2F)]
    diarias = [int.from_bytes(rom_base[0x1906 + 4 * i:0x190A + 4 * i], "big") for i in range(16)]
    assert max(len(str(v)) for v in precos + diarias) == DIGITOS_NUMERO


def test_referencia_circular_nao_recursa():
    b0 = {"banco0_sistema": [Entrada("b0.001.t00", "[s0:02]a"), Entrada("b0.002.t00", "[s0:01]b")]}
    assert _linhas("[s0:01]", b0) == [2]


def test_espera_nao_reinicia_a_linha():
    e = Entrada("d.t00", "x", pt="aaaaaaaaaa[espera]bbbbbbbbbbbbbbb")
    ach = checar_largura(_ctx({"dialogos": [e]}, 10))
    assert len(ach) == 1 and "25" in ach[0].mensagem


# ---- linhas por página

def test_pagina_maior_que_a_janela_erro():
    e = Entrada("d.t00", "x", pt="a[linha]b[linha]c[espera][linha]d[linha]e[linha]f[linha]g[espera]")
    ach = checar_linhas(_ctx({"dialogos": [e]}, alt=3))
    assert len(ach) == 1 and ach[0].checagem == "linhas" and ach[0].nivel == "erro"
    assert "página 2 tem 4 linhas" in ach[0].mensagem and "mostra 3" in ach[0].mensagem


def test_linhas_em_branco_antes_do_texto_nao_contam_e_no_fim_contam():
    # [espera][linha][linha]texto: as linhas vazias antes do texto rolam sem perder nada
    ok = Entrada("d.t00", "x", pt="a[espera][linha][linha]b[linha]c[linha]d[espera]")
    assert checar_linhas(_ctx({"dialogos": [ok]}, alt=3)) == []
    # texto + [linha] antes da espera: o cursor desce e a 1.ª linha rola
    ruim = Entrada("d.t01", "x", pt="a[linha]b[linha]c[linha][espera]")
    assert len(checar_linhas(_ctx({"dialogos": [ruim]}, alt=3))) == 1


def test_menu_sim_nao_ocupa_uma_linha():
    b0 = [Entrada("b0.000.t00", "[$03][$00][quebra2][$04][$04]YES  NO")]
    ok = Entrada("d.t00", "x", pt="a[linha]b[s0:00]")
    ruim = Entrada("d.t01", "x", pt="a[linha]b[linha]c[s0:00]")
    ach = checar_linhas(_ctx({"dialogos": [ok, ruim], "banco0_sistema": b0}, alt=3))
    assert [a.local for a in ach] == ["dialogos:d.t01"]


def test_pagina_tolera_o_que_o_original_ja_faz():
    # o en já rola (4 linhas): o pt pode ter até 4, não 5
    en = "a[linha]b[linha]c[linha]d[espera]"
    igual = Entrada("d.t00", en, pt="w[linha]x[linha]y[linha]z[espera]")
    pior = Entrada("d.t01", en, pt="v[linha]w[linha]x[linha]y[linha]z[espera]")
    ach = checar_linhas(_ctx({"dialogos": [igual, pior]}, alt=3))
    assert [a.local for a in ach] == ["dialogos:d.t01"]


# ---- fluxo do script (esqueleto): janela pelo flag e coluna carregada entre trechos

def _esqueleto(instrucoes, flag=0, raizes=None):
    return {"raizes": raizes or {"dialogo.000": "L0"}, "instrucoes": instrucoes, "trechos": {},
            "tabelas": {"dialogos": [{"raiz": "dialogo.000", "flag": flag}], "bancos": {}}}


JANELAS = [{"x": 4, "y": 1, "largura": 23, "altura": 3},
           {"x": 0, "y": 0, "largura": 17, "altura": 5}]


def test_fluxo_usa_a_janela_do_flag():
    instr = [{"rotulo": "L0", "trecho": "dialogo.000.t00"}, {"op": 0, "rotulo": None}]
    e = Entrada("dialogo.000.t00", "x", pt="a" * 20)
    for flag, erros in ((0, 0), (1, 1)):
        ctx = _ctx({"dialogos": [e]}, 99, 99, janelas=JANELAS,
                   esqueleto=_esqueleto(instr, flag))
        ach = checar_largura(ctx)
        assert len(ach) == erros
        if erros:
            assert "limite é 17" in ach[0].mensagem


def test_fluxo_carrega_a_coluna_entre_trechos():
    # t00 imprime 15 colunas, o subop 0B 05 (número, 6 dígitos) continua a linha e t01
    # começa na coluna 21: 21 + 5 = 26 > 23
    instr = [{"rotulo": "L0", "trecho": "dialogo.000.t00"},
             {"op": 11, "sub": 5, "args": [], "alvos": [], "rotulo": None},
             {"rotulo": None, "trecho": "dialogo.000.t01"}, {"op": 0, "rotulo": None}]
    t00 = Entrada("dialogo.000.t00", "x", pt="a" * 15)
    t01 = Entrada("dialogo.000.t01", "x", pt="bbbbb")
    ctx = _ctx({"dialogos": [t00, t01]}, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    ach = checar_largura(ctx)
    assert [a.local for a in ach] == ["dialogos:dialogo.000.t01"]
    assert "26" in ach[0].mensagem and "começa na coluna 21" in ach[0].mensagem


def test_fluxo_caminhos_alternativos_nao_somam():
    # 0B 11 (flag de evento -> salto): t01 e t02 são alternativas a partir do fim de t00
    instr = [{"rotulo": "L0", "trecho": "dialogo.000.t00"},
             {"op": 11, "sub": 0x11, "args": [3], "alvos": ["L2"], "rotulo": None},
             {"rotulo": None, "trecho": "dialogo.000.t01"}, {"op": 0, "rotulo": None},
             {"rotulo": "L2", "trecho": "dialogo.000.t02"}, {"op": 0, "rotulo": None}]
    textos = {"dialogos": [Entrada("dialogo.000.t00", "x", pt="a" * 10),
                           Entrada("dialogo.000.t01", "x", pt="b" * 13),
                           Entrada("dialogo.000.t02", "x", pt="c" * 13)]}
    ctx = _ctx(textos, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    assert checar_largura(ctx) == []


def test_fluxo_limpa_janela_zera_coluna_e_pagina():
    instr = [{"rotulo": "L0", "trecho": "dialogo.000.t00"},
             {"op": 11, "sub": 0x20, "args": [], "alvos": [], "rotulo": None},
             {"rotulo": None, "trecho": "dialogo.000.t01"}, {"op": 0, "rotulo": None}]
    textos = {"dialogos": [Entrada("dialogo.000.t00", "x", pt="a[linha]b[linha]" + "c" * 20),
                           Entrada("dialogo.000.t01", "x", pt="d" * 23 + "[espera]")]}
    ctx = _ctx(textos, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    assert checar_largura(ctx) == [] and checar_linhas(ctx) == []


def test_fluxo_pagina_continua_no_trecho_seguinte():
    instr = [{"rotulo": "L0", "trecho": "dialogo.000.t00"},
             {"op": 7, "rotulo": None},
             {"rotulo": None, "trecho": "dialogo.000.t01"}, {"op": 0, "rotulo": None}]
    textos = {"dialogos": [Entrada("dialogo.000.t00", "x", pt="a[linha]b"),
                           Entrada("dialogo.000.t01", "x", pt="[linha]c[linha]d[espera]")]}
    ctx = _ctx(textos, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    ach = checar_linhas(ctx)
    assert [a.local for a in ach] == ["dialogos:dialogo.000.t01"]
    assert "4 linhas" in ach[0].mensagem


def test_fluxo_nome_do_item_definido_pelo_subop_0a():
    # 0B 0A 01 define o item; [s0:02] ([cor] + nome + [/cor]) conta o nome dele, não o maior
    instr = [{"rotulo": "L0", "op": 11, "sub": 0x0A, "args": [1], "alvos": []},
             {"rotulo": None, "trecho": "dialogo.000.t00"}, {"op": 0, "rotulo": None}]
    textos = {"dialogos": [Entrada("dialogo.000.t00", "x", pt="a" * 15 + "[s0:02]")],
              "banco0_sistema": [Entrada("b0.002.t00", "[cor]"), Entrada("b0.002.t01", "[/cor]")],
              "banco1_itens": [Entrada("b1.000.t00", "Grande Machado"),   # 14
                               Entrada("b1.001.t00", "Erva")]}             # 4
    ctx = _ctx(textos, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    assert checar_largura(ctx) == []
    sem_item = _esqueleto([{"rotulo": "L0", "trecho": "dialogo.000.t00"}, {"op": 0}])
    ach = checar_largura(_ctx(textos, 99, 99, janelas=JANELAS, esqueleto=sem_item))
    assert len(ach) == 1 and "29" in ach[0].mensagem   # 15 + 14


def test_fluxo_menu_fecha_a_pagina_do_trecho():
    # trecho seguido do menu (0B 02): a página termina ali e conta no próprio trecho
    instr = [{"rotulo": "L0", "trecho": "dialogo.000.t00"},
             {"op": 11, "sub": 2, "args": [3, 7], "alvos": ["L1"], "rotulo": None},
             {"rotulo": "L1", "op": 0}]
    textos = {"dialogos": [Entrada("dialogo.000.t00", "x",
                                   pt="a[linha]b[linha]c[linha]d")]}
    ctx = _ctx(textos, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    assert len(checar_linhas(ctx)) == 1


def test_fluxo_fecha_a_pagina_alcancada_por_salto():
    # trecho -> salto (06) -> fim (00): a página final do trecho também é checada
    instr = [{"rotulo": "L0", "trecho": "dialogo.000.t00"},
             {"op": 6, "args": [], "alvos": ["L1"], "rotulo": None},
             {"rotulo": None, "trecho": "dialogo.000.t01"},
             {"rotulo": "L1", "op": 0}]
    textos = {"dialogos": [Entrada("dialogo.000.t00", "x", pt="a[linha]b[linha]c[linha]d"),
                           Entrada("dialogo.000.t01", "x", pt="e[espera]")]}
    ctx = _ctx(textos, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    ach = checar_linhas(ctx)
    assert [a.local for a in ach] == ["dialogos:dialogo.000.t00"]
    assert "4 linhas" in ach[0].mensagem


def test_fluxo_fecha_a_pagina_depois_de_subop_sem_texto():
    # trecho -> 0B 18 (som, não imprime) -> 00: a página fecha no 00
    instr = [{"rotulo": "L0", "trecho": "dialogo.000.t00"},
             {"op": 11, "sub": 0x18, "args": [72], "alvos": [], "rotulo": None},
             {"rotulo": None, "op": 0}]
    textos = {"dialogos": [Entrada("dialogo.000.t00", "x", pt="a[linha]b[linha]c[linha]d")]}
    ctx = _ctx(textos, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    assert len(checar_linhas(ctx)) == 1


def test_fluxo_caminhos_convergentes_valem_pela_maior_coluna():
    # dois caminhos chegam a t02 (colunas 10 e 2); t02 -> salto -> 00. A largura e as
    # linhas da página final são checadas a partir do pior caso (coluna 10)
    instr = [{"rotulo": "L0", "op": 11, "sub": 0x11, "args": [3], "alvos": ["L2"]},
             {"rotulo": None, "trecho": "dialogo.000.t00"},
             {"op": 6, "args": [], "alvos": ["L3"], "rotulo": None},
             {"rotulo": "L2", "trecho": "dialogo.000.t01"},
             {"op": 6, "args": [], "alvos": ["L3"], "rotulo": None},
             {"rotulo": "L3", "trecho": "dialogo.000.t02"},
             {"op": 6, "args": [], "alvos": ["L4"], "rotulo": None},
             {"rotulo": "L4", "op": 0}]
    textos = {"dialogos": [Entrada("dialogo.000.t00", "x", pt="a" * 10),
                           Entrada("dialogo.000.t01", "x", pt="b" * 2),
                           Entrada("dialogo.000.t02", "x", pt="c" * 15 + "[linha]d[linha]e[linha]f")]}
    ctx = _ctx(textos, 99, 99, janelas=JANELAS, esqueleto=_esqueleto(instr))
    ach = checar_largura(ctx)
    assert [a.local for a in ach] == ["dialogos:dialogo.000.t02"]
    assert "25" in ach[0].mensagem and "começa na coluna 10" in ach[0].mensagem
    lin = checar_linhas(ctx)
    assert [a.local for a in lin] == ["dialogos:dialogo.000.t02"]
    assert "4 linhas" in lin[0].mensagem


def test_fluxo_esqueleto_real_fecha_as_paginas_finais(rom_base):
    # trechos cuja página só chega ao 00/espera/limpeza por saltos ou outros subops (ex.:
    # o final, dialogo.122-127, e a estalagem, b3.001.t07): a última página é checada.
    # No final o en já rola (janela 6, 23x3: dialogo.124 tem 4 linhas, ver mapa-rom.md):
    # ali o limite é o do en; dialogo.122 cabe em 3 linhas e b3.001.t07 em 2
    ctx = _ctx_original(rom_base)
    quatro, cinco = "a[linha]b[linha]c[linha]d", "a[linha]b[linha]c[linha]d[linha]e"
    pts = {"dialogo.122.t00": quatro, "dialogo.124.t00": cinco, "b3.001.t07": quatro,
           "dialogo.123.t00": quatro}   # 123: o en tem 4, então 4 passa
    textos = {a: [Entrada(e.id, e.en, pt=pts.get(e.id, e.pt)) for e in es]
              for a, es in ctx.textos.items()}
    ach = checar_linhas(Contexto(tabela=TABELA, glossario=[], textos=textos, extra=ctx.extra))
    assert sorted(a.local for a in ach) == ["banco3_lojas:b3.001.t07",
                                            "dialogos:dialogo.122.t00",
                                            "dialogos:dialogo.124.t00"]
