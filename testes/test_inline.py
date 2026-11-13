"""Strings inline de tamanho fixo."""

from pathlib import Path

import pytest
import yaml

from ferramentas.config import ErroConfig, Projeto, carregar_cfg_texto
from ferramentas.inline import aplicar_inline, checar_inline, etapa_inline, extrair_inline, itens_inline
from ferramentas.script.montador import ErroMontagem
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada
from ferramentas.verificacao import Contexto

RAIZ = Path(__file__).resolve().parent.parent
TABELA = Tabela.carregar(RAIZ / "traducao" / "tabela.tbl")


def _projeto(tmp_path, itens, textos):
    (tmp_path / "config").mkdir()
    (tmp_path / "traducao" / "textos").mkdir(parents=True)
    (tmp_path / "config" / "texto.yaml").write_text(
        yaml.safe_dump({"inline": itens}), encoding="utf-8")
    (tmp_path / "traducao" / "tabela.tbl").write_text(
        (RAIZ / "traducao" / "tabela.tbl").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "traducao" / "textos" / "inline.yaml").write_text(
        yaml.safe_dump(textos, allow_unicode=True), encoding="utf-8")
    return Projeto(raiz=tmp_path, rom={})


def _rom():
    rom = bytearray(b"\xAA" * 4 + b"Time's up.\x00" + b"\xBB" * 4)
    return rom


ITEM = {"id": "quiz.tempo", "end": 4, "tam": 10, "preencher": "espaco"}


def test_inline_cabe_preenche(tmp_path):
    p = _projeto(tmp_path, [ITEM], [{"id": "quiz.tempo", "en": "Time's up.", "pt": "Acabou!"}])
    rom = _rom()
    etapa_inline(rom, p)
    assert bytes(rom[4:14]) == b"Acabou!   "
    assert rom[14] == 0 and rom[:4] == b"\xAA" * 4 and rom[15:] == b"\xBB" * 4


def test_inline_preencher_nulo(tmp_path):
    item = dict(ITEM, preencher="nulo")
    p = _projeto(tmp_path, [item], [{"id": "quiz.tempo", "en": "x", "pt": "Fim"}])
    rom = _rom()
    etapa_inline(rom, p)
    assert bytes(rom[4:14]) == b"Fim" + b"\x00" * 7


def test_inline_estoura(tmp_path):
    p = _projeto(tmp_path, [ITEM], [{"id": "quiz.tempo", "en": "x", "pt": "Tempo esgotado!"}])
    with pytest.raises(ErroMontagem, match="quiz.tempo"):
        etapa_inline(_rom(), p)


def test_inline_pt_vazio_mantem(tmp_path):
    p = _projeto(tmp_path, [ITEM], [{"id": "quiz.tempo", "en": "Time's up.", "pt": ""}])
    rom = _rom()
    original = bytes(rom)
    etapa_inline(rom, p)
    assert bytes(rom) == original


def test_inline_sem_config_e_noop(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "texto.yaml").write_text("inline: []\n", encoding="utf-8")
    rom = _rom()
    original = bytes(rom)
    etapa_inline(rom, Projeto(raiz=tmp_path, rom={}))
    assert bytes(rom) == original


def test_checar_inline_acha_estouro():
    ctx = Contexto(tabela=TABELA, glossario=[], textos={
        "inline": [Entrada("quiz.tempo", "x", pt="Tempo esgotado!")]},
        extra={"inline": [ITEM]})
    achados = checar_inline(ctx)
    assert len(achados) == 1 and achados[0].nivel == "erro" and "quiz.tempo" in achados[0].mensagem
    ctx.textos["inline"][0].pt = "Acabou!"
    assert checar_inline(ctx) == []


def test_extrair_inline_sintetico():
    es = extrair_inline(bytes(_rom()), [ITEM], TABELA)
    assert es == [Entrada("quiz.tempo", "Time's up.")]


def test_aplicar_inline_id_ausente_ignora():
    rom = _rom()
    aplicar_inline(rom, [ITEM], {}, TABELA)
    assert bytes(rom) == bytes(_rom())


def test_inline_rom(rom_base):
    cfg = carregar_cfg_texto(RAIZ)
    itens = cfg["inline"]
    es = extrair_inline(rom_base, itens, TABELA)
    en = {e.id: e.en for e in es}
    assert len(es) == len(itens) == len(en)
    assert [en[k] for k in ("quiz.tempo", "quiz.errou", "quiz.acertou")] == \
        ["Time's up.", "Incorrect.", "Correct."]
    # mensagens do baú: repontáveis (testes/test_repontavel.py); status.ouro saiu (sem leitor)
    assert [en[k] for k in ("status.ap", "status.dp", "status.sp")] == ["AP", "DP", "SP"]
    # magias: bloco repontável menu.magias (testes/test_menus.py)
    assert not any(k.startswith("magia.") for k in en)
    assert en["creditos.programador_chefe"] == "CHIEF PROGRAMMER"
    assert en["ocarina.5.melodia"] == "The melody isn't quite right."
    assert not any("[$" in e.en for e in es)
    # cada slot é seguido do terminador 00 (ou de byte de controle), e tam == len(en)
    for it in itens:
        assert it["tam"] == len(en[it["id"]])
    # tamanhos máximos: nenhum item sobrepõe outro
    faixas = sorted((it["end"], it["end"] + it["tam"]) for it in itens)
    assert all(a[1] <= b[0] for a, b in zip(faixas, faixas[1:]))


def _it(**kw):
    return dict(ITEM, **kw)


def test_itens_sobreposicao():
    with pytest.raises(ErroConfig, match="sobrepõe"):
        itens_inline({"inline": [_it(id="a", end=4, tam=10), _it(id="b", end=10, tam=3)]})
    # adjacentes são válidos
    itens_inline({"inline": [_it(id="a", end=4, tam=10), _it(id="b", end=14, tam=3)]})


@pytest.mark.parametrize("tam", [0, -3])
def test_itens_tam_invalido(tam):
    with pytest.raises(ErroConfig, match="tam"):
        itens_inline({"inline": [_it(tam=tam)]})


@pytest.mark.parametrize("campo,valor", [("end", "0x1d72"), ("tam", "10"), ("tam", 2.5),
                                         ("end", True)])
def test_itens_tipo_invalido(campo, valor):
    with pytest.raises(ErroConfig, match=campo):
        itens_inline({"inline": [_it(**{campo: valor})]})


def test_checar_inline_id_desconhecido_avisa():
    ctx = Contexto(tabela=TABELA, glossario=[], textos={
        "inline": [Entrada("quiz.tmpo", "x", pt="Acabou!")]}, extra={"inline": [ITEM]})
    achados = checar_inline(ctx)
    assert len(achados) == 1 and achados[0].nivel == "aviso" and "quiz.tmpo" in achados[0].local


def test_ocarina_frase_numa_linha(rom_base):
    """Patches ``ocarina.*.linha``: o 02 (nova linha) entre "Shion plays" e "the " vira 07
    (liga a flag de janela, que o 07 do início do mini-script já ligou: não imprime nada).
    Com os slots traduzidos, "Shion toca sua Ocarina." sai numa linha de 23 colunas
    (conferido no emulador)."""
    from ferramentas.patches import aplicar_patches, carregar_patches
    from ferramentas.textos import carregar_textos

    # 0B 0A 28 insere o nome do item 0x28 (b1.028, a Ocarina) depois do slot "the "
    nome = {e.id: e.pt or e.en for e in carregar_textos(RAIZ / "traducao" / "textos" / "banco1_itens.yaml")}["b1.028.t00"]
    projeto = Projeto(raiz=RAIZ, rom={})
    rom = bytearray(rom_base)
    etapa_inline(rom, projeto)
    aplicar_patches(rom, carregar_patches(projeto))
    for ini, linha in ((0x2B56, 0x2B64), (0x2B8F, 0x2B9D)):
        assert rom_base[ini:ini + 3] == b"\x07\x03\x06" and rom_base[linha] == 0x02
        assert rom[linha] == 0x07
        frase = rom[ini + 3:rom.index(b"\x0b\x0a\x28", ini)].replace(b"\x07", b"").decode("ascii")
        assert frase == "Shion toca sua "
        assert len(frase) + len(nome) + len(".") <= 23


# Sequência: strings lidas em fluxo (cada uma acha a próxima pelo 00), tamanho livre por item.
SEQ_ROM = bytearray(b"\xAA" * 2 + b"STAFF\x00\x9aCHIEF\x00NOME\x00\x99\x00" + b"\xBB" * 2)
SEQ_CFG = {
    "sequencias_inline": {"cred": {"ini": 2, "fim": 21, "largura": 20}},
    "inline": [
        {"id": "c.a", "end": 2, "tam": 5, "preencher": "espaco", "sequencia": "cred"},
        {"id": "c.b", "end": 9, "tam": 5, "preencher": "espaco", "sequencia": "cred"},
    ],
}


def test_sequencia_remonta_com_tamanhos_livres():
    rom = bytearray(SEQ_ROM)
    aplicar_inline(rom, itens_inline(SEQ_CFG), {"c.a": "EQUIPE", "c.b": "CHEF"}, TABELA)
    assert bytes(rom) == b"\xAA" * 2 + b"EQUIPE\x00\x9aCHEF\x00NOME\x00\x99\x00" + b"\xBB" * 2


def test_sequencia_sem_pt_mantem_original():
    rom = bytearray(SEQ_ROM)
    aplicar_inline(rom, itens_inline(SEQ_CFG), {}, TABELA)
    assert rom == SEQ_ROM


def test_sequencia_que_nao_cabe_falha():
    with pytest.raises(ErroMontagem, match="sequência 'cred'"):
        aplicar_inline(bytearray(SEQ_ROM), itens_inline(SEQ_CFG), {"c.a": "EQUIPES", "c.b": "CHEFE"},
                       TABELA)


def test_checar_sequencia_soma_e_largura():
    itens = itens_inline(SEQ_CFG)
    def ctx(pts):
        return Contexto(tabela=TABELA, glossario=[], extra={"inline": itens},
                        textos={"inline": [Entrada(i, "x", p, "traduzido") for i, p in pts.items()]})
    assert checar_inline(ctx({"c.a": "EQUIPE", "c.b": "CHEF"})) == []
    assert any("a mais" in a.mensagem for a in checar_inline(ctx({"c.a": "EQUIPES", "c.b": "CHEFE"})))
    largo = {"c.a": "A" * 21, "c.b": "B"}
    assert any("colunas" in a.mensagem for a in checar_inline(ctx(largo)))


def test_sequencia_nao_declarada_ou_fora_do_bloco():
    cfg = {"inline": [dict(SEQ_CFG["inline"][0], sequencia="outra")]}
    with pytest.raises(ErroConfig, match="não declarada"):
        itens_inline(cfg)
    cfg = dict(SEQ_CFG, inline=[dict(SEQ_CFG["inline"][0], end=19)])
    with pytest.raises(ErroConfig, match="fora da sequência"):
        itens_inline(cfg)


def test_creditos_reais_sem_traducao_reproduzem_a_base(rom_base):
    """O bloco dos créditos remontado só com os textos originais é idêntico ao da base."""
    itens = itens_inline(carregar_cfg_texto(RAIZ))
    cred = [it for it in itens if it.get("sequencia") == "creditos"]
    assert len(cred) == 8 and rom_base[0x1AD60] == 0x99
    rom = bytearray(rom_base)
    aplicar_inline(rom, cred, {}, TABELA)
    assert rom == rom_base
