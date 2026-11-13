import string

from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada
from ferramentas.verificacao import (CHECAGENS_PADRAO, Contexto, checar_caracteres,
                                     checar_controles, checar_glossario, formatar,
                                     rodar, tem_erros)


def _tabela(extra=""):
    chars = string.ascii_letters + " ã" + extra
    linhas = [f"{0x20 + i:02X}={c}" for i, c in enumerate(chars)]
    linhas += ["F0=[linha]", "F1=[nome]", "FF=[fim]"]
    return Tabela.de_texto("\n".join(linhas))


def _ctx(entradas, glossario=None, extra=""):
    return Contexto(tabela=_tabela(extra), textos={"arq": entradas}, glossario=glossario or [])


def test_caractere_fora_da_tabela():
    ctx = _ctx([Entrada(id="e1", en="Hi", pt="Olá", status="traduzido")])
    achados = checar_caracteres(ctx)
    assert len(achados) == 1 and achados[0].nivel == "erro" and "e1" in achados[0].local


def test_controle_faltando():
    ctx = _ctx([Entrada(id="e2", en="Hi [nome]", pt="Oi", status="traduzido")])
    achados = checar_controles(ctx)
    assert len(achados) == 1 and achados[0].nivel == "erro"


def test_controle_ordem_trocada():
    ctx = _ctx([Entrada(id="e3", en="[nome] a [fim]", pt="[fim] a [nome]", status="traduzido")])
    assert len(checar_controles(ctx)) == 1


def test_quebra_livre():
    ctx = _ctx([Entrada(id="e4", en="Hi there", pt="Oi[linha]você", status="traduzido")],
               extra="ê")
    assert rodar(ctx, CHECAGENS_PADRAO) == []


def test_argumento_de_controle_movido_e_erro():
    # 0A/04 seguidos do argumento 02: se o argumento aparecesse como [quebra2] (livre),
    # mover os [quebra2] passaria na verificação e geraria 03 06 0A 04 44 ... (lixo)
    from pathlib import Path

    from ferramentas.script.segmentos import exibir_en

    tabela = Tabela.carregar(Path(__file__).resolve().parent.parent / "traducao" / "tabela.tbl")
    en = exibir_en(b"\x03\x06\x0a\x02\x04\x02Having difficulties", tabela, [])
    pt = "[$03][$06][$0A][$04]Dificuldades?[quebra2][quebra2]"
    ctx = Contexto(tabela=tabela, glossario=[],
                   textos={"dialogos": [Entrada("d.t00", en, pt=pt, status="traduzido")]})
    achados = checar_controles(ctx)
    assert len(achados) == 1 and achados[0].nivel == "erro"
    ok = Entrada("d.t00", en, pt="[$03][$06][$0A][$02][$04][$02]Dificuldades?",
                 status="traduzido")
    assert checar_controles(Contexto(tabela=tabela, glossario=[], textos={"d": [ok]})) == []
    assert tabela.codificar(ok.pt)[:6] == b"\x03\x06\x0a\x02\x04\x02"


def test_glossario_inconsistente():
    glos = [{"en": "Dragon Castle", "pt": "Castelo do Dragão"}]
    ctx = _ctx([Entrada(id="e5", en="Go to Dragon Castle", pt="Va ao Castelo", status="traduzido")],
               glossario=glos)
    achados = checar_glossario(ctx)
    assert len(achados) == 1 and achados[0].nivel == "aviso"
    assert not tem_erros(achados)


def test_glossario_case_insensitive():
    glos = [{"en": "Dragon Castle", "pt": "Castelo do Dragão"}]
    ctx = _ctx([Entrada(id="e6", en="dragon castle!", pt="castelo do dragão!", status="traduzido")],
               glossario=glos)
    assert checar_glossario(ctx) == []


def test_glossario_termo_partido_por_quebra_de_linha():
    glos = [{"en": "Purapril Castle", "pt": "Castelo de Purapril"}]
    for quebra in ("[linha]", "[quebra2]", "[espera][linha]"):
        ctx = _ctx([Entrada(id="e7", en="the Bell Tower at[linha]Purapril Castle",
                            pt=f"vá ao Castelo de{quebra}Purapril", status="traduzido")],
                   glossario=glos)
        assert checar_glossario(ctx) == []


def test_pendente_ignorado():
    ctx = _ctx([Entrada(id="e7", en="Hi [nome] ç")])
    assert rodar(ctx, CHECAGENS_PADRAO) == []


def test_formatar_resumo():
    glos = [{"en": "Dragon Castle", "pt": "Castelo do Dragão"}]
    ctx = _ctx([Entrada(id="e8", en="Dragon Castle", pt="Olá", status="traduzido")], glossario=glos)
    achados = rodar(ctx, CHECAGENS_PADRAO)
    texto = formatar(achados)
    assert texto.rstrip().endswith("1 erro(s), 1 aviso(s)")
    assert "ERRO [caracteres]" in texto


def test_avanco_da_diaria_pode_mudar():
    """b0.005.t00 é só o avanço antes da diária da estalagem ([s0:05], usado só em
    b3.001.t00): o número de colunas de [$04] pode mudar; o código, não."""
    from ferramentas.verificacao import AVANCO_LIVRE

    assert AVANCO_LIVRE == {"b0.005.t00"}
    ok = Entrada("b0.005.t00", "[$04][$03]", pt="[$04][$01]", status="traduzido")
    assert checar_controles(_ctx([ok])) == []
    sem_avanco = Entrada("b0.005.t00", "[$04][$03]", pt="[$03][$01]", status="traduzido")
    assert len(checar_controles(_ctx([sem_avanco]))) == 1
    outro = Entrada("b0.003.t00", "[$04][$01]", pt="[$04][$03]", status="traduzido")
    assert len(checar_controles(_ctx([outro]))) == 1
