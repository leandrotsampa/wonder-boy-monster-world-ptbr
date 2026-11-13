"""Comando extrair: esqueleto + YAML a partir da ROM real."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from ferramentas.cli import main
from ferramentas.script.extracao import extrair_texto
from ferramentas.textos import carregar_textos

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def projeto(tmp_path, rom_base):
    for rel in ("config/rom.yaml", "config/texto.yaml", "traducao/tabela.tbl"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(RAIZ / rel, tmp_path / rel)
    rom = tmp_path / "rom.bin"
    rom.write_bytes(rom_base)
    return tmp_path, str(rom)


def _extrair(raiz, rom):
    assert main(["--raiz", str(raiz), "extrair", "--rom", rom]) == 0


def test_extrair_contagens(rom_base, cfg):
    _, grupos = extrair_texto(rom_base, cfg)
    assert len(grupos["dialogos"]) >= 131
    assert all(e.id.startswith("dialogo.") for e in grupos["dialogos"])
    # 65 slots no banco 1; 6 deles repetem o endereço de outro slot (aliases),
    # então há 59 strings distintas e cada uma vira uma entrada
    esq, _ = extrair_texto(rom_base, cfg)
    slots = esq["tabelas"]["bancos"]["1"]
    assert len(slots) == 65 and None not in slots
    rotulos = {esq["raizes"][n] for n in slots}
    assert len(rotulos) == 59
    b1 = {e.id for e in grupos["banco1_itens"]}
    assert {e.id.split(".t")[0] for e in grupos["banco1_itens"]} <= set(slots)
    assert len(b1) == 59
    assert all(e.id.startswith("b1.") for e in grupos["banco1_itens"])
    # o dicionário (b0.03F em diante) não é traduzível
    assert not any(int(e.id.split(".")[1], 16) >= 0x3F
                   for e in grupos["banco0_sistema"])
    assert set(grupos) <= {"dialogos", "banco0_sistema", "banco1_itens", "banco2_nomes",
                           "banco3_lojas", "extras"}


def test_esqueleto_tem_tabelas(rom_base, cfg):
    esq, _ = extrair_texto(rom_base, cfg)
    t = esq["tabelas"]
    assert len(t["dialogos"]) == 131 and t["dialogos"][0]["raiz"] == "dialogo.000"
    assert len(t["bancos"]["3"]) == 16 and t["bancos"]["3"].count(None) == 7
    assert len(t["bancos"]["0"]) == 232
    # os trechos do dicionário continuam no esqueleto
    assert any(k.startswith("b0.040.") for k in esq["trechos"])


def test_en_legivel(rom_base, cfg):
    _, grupos = extrair_texto(rom_base, cfg)
    assert any("once a peaceful" in e.en for e in grupos["dialogos"])


def test_reextrair_preserva_pt(projeto):
    raiz, rom = projeto
    _extrair(raiz, rom)
    arq = raiz / "traducao" / "textos" / "dialogos.yaml"
    entradas = carregar_textos(arq)
    entradas[0].pt = "Olá"
    entradas[0].status = "traduzido"
    from ferramentas.textos import salvar_textos
    salvar_textos(arq, entradas)
    _extrair(raiz, rom)
    de_novo = carregar_textos(arq)
    assert de_novo[0].pt == "Olá" and de_novo[0].status == "traduzido"
    assert de_novo[0].nota == ""


def test_esqueleto_deterministico(projeto):
    raiz, rom = projeto
    arq = raiz / "dados" / "scripts" / "esqueleto.json"
    _extrair(raiz, rom)
    a = arq.read_bytes()
    _extrair(raiz, rom)
    assert arq.read_bytes() == a
    assert b"\r" not in a
    assert json.loads(a)["tabelas"]["dialogos"]
