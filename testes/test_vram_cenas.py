"""Mapa de VRAM por cena (ferramentas/emulador/vram_cenas.py), passo ``repetir`` dos
roteiros e códigos dos acentos (config/texto.yaml; ver docs/tecnico/vram.md)."""

from pathlib import Path

import pytest
import yaml

from ferramentas.emulador.roteiro import carregar_roteiro, executar_roteiro
from ferramentas.emulador.vram_cenas import _faixas, analisar, fonte_da_rom

RAIZ = Path(__file__).resolve().parent.parent

ACENTOS_OBRIGATORIOS = "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ"


class _EmuFalso:
    def __init__(self):
        self.chamadas = []

    def avancar(self, quadros, botoes=frozenset()):
        self.chamadas.append((quadros, frozenset(botoes)))


def test_roteiro_repetir(tmp_path):
    r = tmp_path / "r.yaml"
    r.write_text("- esperar: 1\n- repetir: 3\n  passos:\n    - apertar: [c]\n      quadros: 2\n"
                 "    - repetir: 2\n      passos:\n        - esperar: 5\n", encoding="utf-8")
    emu = _EmuFalso()
    executar_roteiro(r, tmp_path / "saida", emulador=emu)
    c = (2, frozenset({"c"}))
    e = (5, frozenset())
    assert emu.chamadas == [(1, frozenset())] + [c, e, e] * 3


@pytest.mark.parametrize("texto", [
    "- repetir: 2\n",                                   # sem passos
    "- repetir: -1\n  passos: []\n",                    # N negativo
    "- repetir: 2\n  passos:\n    - pular: 1\n",        # passo interno inválido
    "- esperar: 1\n  passos: []\n",                     # passos fora de repetir
    "- repetir: 2\n  passos: []\n  quadros: 1\n",       # chave extra
    "- repetir: x\n  passos: []\n",                     # N não inteiro
    "- repetir: true\n  passos: []\n",                  # bool não é contagem
    "- repetir: 10001\n  passos: []\n",                 # acima de MAX_REPETIR
    "- repetir: 2\n  passos: {esperar: 1}\n",           # passos não é lista
])
def test_roteiro_repetir_invalido(tmp_path, texto):
    r = tmp_path / "r.yaml"
    r.write_text(texto, encoding="utf-8")
    with pytest.raises(ValueError):
        carregar_roteiro(r)


def test_roteiro_repetir_zero(tmp_path):
    r = tmp_path / "r.yaml"
    r.write_text("- repetir: 0\n  passos:\n    - esperar: 5\n- esperar: 1\n", encoding="utf-8")
    emu = _EmuFalso()
    executar_roteiro(r, tmp_path / "saida", emulador=emu)
    assert emu.chamadas == [(1, frozenset())]


def test_roteiro_cenas_valido():
    assert carregar_roteiro(RAIZ / "roteiros" / "cenas.yaml")


def test_faixas():
    assert _faixas([]) == "-"
    assert _faixas([0x80, 0x81, 0x82, 0x90, 0xA0, 0xA1]) == "80-82 90 A0-A1"


def _acentos() -> dict[str, int]:
    cfg = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))
    return cfg["acentos"]


def test_acentos_config():
    acentos = _acentos()
    assert set(ACENTOS_OBRIGATORIOS) <= set(acentos)
    codigos = list(acentos.values())
    assert len(set(codigos)) == len(codigos), "código repetido"
    for ch, cod in acentos.items():
        assert len(ch) == 1
        # 0x80–0x9F: no jogo o slot 4 recebe o bloco 0x235 (HUD/efeitos);
        # 0xBE/0xBF: tiles de cima do prefixo FE/FF; FE/FF: prefixos.
        assert 0xA0 <= cod <= 0xFD and cod not in (0xBE, 0xBF), f"{ch}: {cod:#x}"


def test_acentos_nos_codigos_do_bloco_5():
    """Maiúsculas em 0xA1-0xAC e minúsculas em 0xB1-0xBC, na mesma ordem."""
    esperado = (dict(zip("ÀÃÂÁÉÊÍÓÕÔÚÇ", range(0xA1, 0xAD)))
                | dict(zip("àãâáéêíóõôúç", range(0xB1, 0xBD))))
    assert {ch: _acentos()[ch] for ch in esperado} == esperado


def test_dialogo_usa_fonte_em_a0_ff(_emulador_sessao, caminho_rom_base, tmp_path):
    """Com a janela de texto aberta, 0xA0–0xFF ainda é a fonte e nada mais usa 0x80–0xFF."""
    _emulador_sessao.reiniciar()
    executar_roteiro(RAIZ / "roteiros" / "dialogo.yaml", tmp_path, emulador=_emulador_sessao)
    fonte = fonte_da_rom(caminho_rom_base.read_bytes())
    cena = analisar("dialogo", _emulador_sessao.salvar_estado(), fonte)
    assert cena.slots == [0, 1, 2, 3, 0x235, 5, 6, 7]
    assert all(cena.conteudo[t] == "fonte" for t in range(0xA0, 0x100))
    assert not any(cena.uso.get(t) for t in range(0x80, 0x100))
    for cod in _acentos().values():
        assert cena.conteudo[cod] == "fonte"


#: Trechos e itens inline da ROM base com algum CARACTERE >= 0x80 (argumentos de
#: opcode não contam; FE/FF + char conta os dois bytes). São as strings japonesas
#: que sobraram no inglês (docs/tecnico/vram.md §6).
CHARS_ALTOS_ESPERADOS = {
    "b0.004.t00": [0x95, 0x97, 0x8C, 0x98, 0x9B, 0xBD],
    "b1.026.t00": [0xAF, 0xAE, 0x93, 0xA9, 0xB3, 0xA4],
    "b1.030.t00": [0xFB, 0xCF, 0xFE, 0xE4],
    "b2.006.t00": [0xFF, 0xEA, 0xD2, 0xD1, 0xFA, 0xDD],
}


def _chars_altos(bruto: bytes) -> list[int]:
    """Bytes >= 0x80 usados como caractere num trecho (ver segmentos.py)."""
    com_arg, sem_arg = {0x01, 0x03, 0x04, 0x0A, 0x0C, 0x0D, 0x0E, 0x0F}, {0x02, 0x05, 0x09}
    altos, i = [], 0
    while i < len(bruto):
        b = bruto[i]
        if b in com_arg:
            i += 2
        elif b in sem_arg:
            i += 1
        elif b in (0xFE, 0xFF):
            altos += [b, bruto[i + 1]]
            i += 2
        else:
            assert b >= 0x10, f"byte {b:#x} inesperado num trecho"
            if b >= 0x80:
                altos.append(b)
            i += 1
    return altos


def test_texto_ingles_nao_usa_kana(rom_base):
    from ferramentas.config import carregar_cfg_texto
    from ferramentas.inline import itens_inline
    from ferramentas.script.extracao import extrair_texto

    cfg = carregar_cfg_texto(RAIZ)
    esqueleto, _ = extrair_texto(rom_base, cfg)
    achados = {tid: a for tid, h in esqueleto["trechos"].items() if (a := _chars_altos(bytes.fromhex(h)))}
    for it in itens_inline(cfg):
        if a := [b for b in rom_base[it["end"]:it["end"] + it["tam"]] if b >= 0x80]:
            achados[f"inline:{it['id']}"] = a
    assert achados == CHARS_ALTOS_ESPERADOS
    # só b1.026 cruza com os códigos dos acentos
    codigos = set(_acentos().values())
    cruzam = {tid: sorted(set(a) & codigos) for tid, a in achados.items() if set(a) & codigos}
    assert cruzam == {"b1.026.t00": [0xA4, 0xA9, 0xB3]}
