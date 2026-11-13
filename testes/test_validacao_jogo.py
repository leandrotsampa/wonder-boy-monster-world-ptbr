"""Validação no jogo das regras de largura/linhas (Plano 3, Tarefa 6).

Cada caso monta uma ROM com um ``pt`` de teste (numa cópia temporária do projeto,
nunca no repositório), roda ``roteiros/validacao.yaml`` num processo à parte (o
emulador da sessão está preso à ROM base) e confere, pelos pixels da janela de
diálogo, em que colunas de cada linha aparece texto. As capturas ficam em
``build/capturas/validacao/<caso>/`` e são a referência citada em
docs/tecnico/mapa-rom.md ("Largura de linha").

O texto de teste vai no 1.º diálogo do NEW GAME (``dialogo.000``, janela 0: 23×3).
Para outras janelas e para a loja/estalagem, a entrada 0 da tabela de diálogos da ROM
montada é trocada pela de outro diálogo (ou só o flag da janela muda): o jogo roda o
script real daquele diálogo logo no NEW GAME.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest
import yaml
from PIL import Image

from ferramentas import cli
from ferramentas.cli import main
from ferramentas.emulador.roteiro import carregar_roteiro
from ferramentas.emulador.vram_cenas import (ALOCADOS_RAM, MAX_ALOCADOS, SLOTS_RAM,
                                             checar_invariante_fonte)
from ferramentas.textos import Entrada, carregar_textos, salvar_textos
from ferramentas.tabela import Tabela
from ferramentas.verificacao import Contexto, checar_controles, checar_largura, checar_linhas

RAIZ = Path(__file__).resolve().parent.parent
ROTEIRO = RAIZ / "roteiros" / "validacao.yaml"
CAPTURAS = RAIZ / "build" / "capturas" / "validacao"
PONTEIRO_DIALOGOS = 0x1CC14
ESTRUTURA_FIM = "[cor][nome:00][/cor]"  # dialogo.000.t01 tem de manter o [nome:00]

# Páginas do caso "largura" (janela 0: 23 colunas × 3 linhas; dialogo.000.t00 deixa
# recuo 2 e avança 2 antes do 1.º caractere). Uma página termina em [espera].
PT_LARGURA = (
    "ABCDEFGHIJKLMNOPQRSTU[quebra2]abcdefghijklmnopqrstuvw[espera]"     # p0
    "[linha]0123456789012345678901[espera]"                             # p1
    "[linha]ABCDE[$04][$03]FGH[espera]"                                 # p2
    "[linha]ABCDEFGHIJKLMNOPQRSTU[$04][$02]XY[espera]"                  # p3
    "[linha]AB[espera]"                                                 # p4
    "CD[espera]"                                                        # p5
    "[linha]A[linha]BB[linha]CCC[linha]DDDD[espera]"                    # p6
    "[quebra2]Z" + ESTRUTURA_FIM                                        # p7 ([espera] do t02)
)
PT_JANELAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789[espera]" + ESTRUTURA_FIM
# loja (b3.000) e menu SIM/NÃO (b0.000) em PT; o nome do item e o preço são variáveis
PT_LOJA = {
    "b3.000.t00": "[s0:06]Você tem bom[linha]olho para coisas.[linha][espera][linha]Isso é"
                  "[linha][s0:02].[linha][espera]Custa[s0:03].[espera][linha]Quer comprar?"
                  "[s0:00]",
    "b0.000.t00": "[$03][$00][quebra2][$04][$04]SIM  NÃO",
}
# menu de magias (bloco repontável menu.magias) e de status (inline de tamanho fixo)
PT_INLINE = {"status.ap": "AT", "status.dp": "DF", "status.sp": "VL", "magia.fogo": "FOGO",
             "magia.terremoto": "TREM", "magia.trovao": "RAIO", "magia.poder": "FORÇA",
             "magia.escudo": "ESCUDO", "magia.retorno": "VOLTA"}

# janelas (tabela 0x1DD74): x, y, largura, altura (em tiles / caracteres)
JANELAS = yaml.safe_load((RAIZ / "config" / "texto.yaml").read_text(encoding="utf-8"))["janelas"]


def _cfg_teste(destino: Path) -> None:
    """Desliga largura/linhas na cópia: o pt de teste estoura de propósito."""
    arq = destino / "config" / "texto.yaml"
    cfg = yaml.safe_load(arq.read_text(encoding="utf-8"))
    cfg["largura_linha"] = 99
    cfg["linhas_por_caixa"] = 99
    cfg["janelas"] = [dict(j, largura=99, altura=99) for j in cfg["janelas"]]
    arq.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _montar(rom_base: bytes, destino: Path, pts: dict[str, str]) -> bytearray:
    for rel in ("config", "traducao", "graficos"):
        shutil.copytree(RAIZ / rel, destino / rel)
    (destino / "dados" / "scripts").mkdir(parents=True)
    shutil.copy(RAIZ / "dados" / "scripts" / "esqueleto.json", destino / "dados" / "scripts")
    _cfg_teste(destino)
    restantes = dict(pts)
    for arq in sorted((destino / "traducao" / "textos").glob("*.yaml")):
        entradas = carregar_textos(arq)
        mudou = False
        for e in entradas:
            if e.id in restantes:
                e.pt, e.status = restantes.pop(e.id), "traduzido"
                mudou = True
        if mudou:
            salvar_textos(arq, entradas)
    assert not restantes, f"ids inexistentes: {sorted(restantes)}"
    arq_rom = destino / "base.bin"
    arq_rom.write_bytes(rom_base)
    # o pt de teste usa [$04] fora do lugar do original: só checar_controles reclamaria
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli, "CHECAGENS_PADRAO",
                   [c for c in cli.CHECAGENS_PADRAO if c is not checar_controles])
        assert main(["--raiz", str(destino), "construir", "--rom", str(arq_rom)]) == 0
    return bytearray((destino / "build" / "wbmw-ptbr.bin").read_bytes())


def _trocar_dialogo_0(rom: bytearray, origem: int, flag: int | None = None) -> None:
    """A entrada 0 da tabela de diálogos (flag + offset) passa a ser a ``origem``."""
    tab = int.from_bytes(rom[PONTEIRO_DIALOGOS:PONTEIRO_DIALOGOS + 4], "big")
    rom[tab:tab + 3] = rom[tab + 3 * origem:tab + 3 * origem + 3]
    if flag is not None:
        rom[tab] = flag


CASOS = {
    # caso: (pts, diálogo cujo script roda no NEW GAME, flag da janela)
    "largura": ({"dialogo.000.t01": PT_LARGURA} | PT_INLINE, None, None),
    "janela4": ({"dialogo.000.t01": PT_JANELAS}, None, 4),
    "janela7": ({"dialogo.000.t01": PT_JANELAS}, None, 7),
    "loja": (PT_LOJA, 10, None),          # dialogo.010: 0B 0A 01 (item 1) + [s3:00]
    "estalagem": ({}, 46, None),          # dialogo.046: [s3:01]
}


@lru_cache(maxsize=None)
def _rodar(caso: str, rom_base: bytes, tmp: str) -> Path:
    from ferramentas.emulador.libretro import CORE_PADRAO

    if not CORE_PADRAO.is_file():
        pytest.skip("core libretro ausente")
    pts, origem, flag = CASOS[caso]
    shutil.rmtree(Path(tmp) / caso, ignore_errors=True)
    rom = _montar(rom_base, Path(tmp) / caso, pts)
    if origem is not None or flag is not None:
        _trocar_dialogo_0(rom, 0 if origem is None else origem, flag)
    arq = Path(tmp) / caso / "teste.bin"
    arq.write_bytes(rom)
    destino = CAPTURAS / caso
    shutil.rmtree(destino, ignore_errors=True)
    r = subprocess.run([sys.executable, "-m", "ferramentas.emulador", str(ROTEIRO), "--rom",
                        str(arq), "--destino", str(destino)],
                       cwd=str(RAIZ), capture_output=True, timeout=900)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    return destino


@pytest.fixture(scope="module")
def capturas(rom_base, tmp_path_factory):
    tmp = str(tmp_path_factory.mktemp("validacao"))
    return lambda caso: _rodar(caso, rom_base, tmp)


# ------------------------------------------------------------------ leitura da tela

def _origem(flag: int) -> tuple[int, int]:
    """Canto do texto na tela: a moldura fica no tile (x, y) da janela e o texto começa
    um tile para dentro; a área de jogo começa 64 px abaixo do topo (HUD)."""
    j = JANELAS[flag]
    return (j["x"] + 1) * 8, 64 + (j["y"] + 1) * 8


def _colunas(png: Path, flag: int, linha: int, cor=None) -> set[int]:
    """Colunas da ``linha`` (0 = topo) da janela com algum pixel claro (ou da ``cor``).

    Cada caractere ocupa 8×16 px (tile de cima = acento, tile de baixo = letra)."""
    x0, y0 = _origem(flag)
    largura = JANELAS[flag]["largura"]
    with Image.open(png) as img:
        px = img.convert("RGB").load()
        cols = set()
        for c in range(largura):
            for y in range(y0 + 16 * linha, y0 + 16 * linha + 16):
                for x in range(x0 + 8 * c, x0 + 8 * c + 8):
                    r, g, b = px[x, y]
                    claro = (r + g + b) / 3 > 128 if cor is None else cor(r, g, b)
                    if claro:
                        cols.add(c)
                        break
                if c in cols:
                    break
    return cols


def _faixa(a: int, b: int) -> set[int]:
    return set(range(a, b + 1))


def _amarelo(r, g, b):
    return r > 180 and g > 180 and b < 100


# ------------------------------------------------------------------ (a)(c)(d) largura

def test_largura_fisica_23_colunas(capturas):
    """(a) janela 0 = 23 colunas: 21 letras a partir da coluna 2 enchem até a coluna 22 e
    [quebra2] volta à coluna 0, onde cabem 23."""
    d = capturas("largura")
    assert _colunas(d / "pagina_0.png", 0, 0) == _faixa(2, 22)
    assert _colunas(d / "pagina_0.png", 0, 1) == _faixa(0, 22)
    assert _colunas(d / "pagina_0.png", 0, 2) == set()


def test_estouro_quebra_no_meio_da_palavra(capturas):
    """(d) o 22.º caractere depois de [linha] (recuo 2) não cabe: o motor quebra a linha
    sozinho (coluna 0 da linha seguinte), cortando a palavra; a janela rola."""
    d = capturas("largura")
    assert _colunas(d / "pagina_1.png", 0, 0) == _faixa(0, 22)   # linha de cima rolou
    assert _colunas(d / "pagina_1.png", 0, 1) == _faixa(2, 22)
    assert _colunas(d / "pagina_1.png", 0, 2) == {0}


def test_04_avanca_colunas_sem_quebrar(capturas):
    """(e1) [$04][$03] depois de texto só avança 3 colunas."""
    d = capturas("largura")
    assert _colunas(d / "pagina_2.png", 0, 2) == _faixa(2, 6) | _faixa(10, 12)


def test_04_na_borda_quebra(capturas):
    """(e1) [$04] que leva o cursor à borda (coluna >= 23): o próximo caractere vai para a
    coluna 0 da linha seguinte (o avanço se perde)."""
    d = capturas("largura")
    assert _colunas(d / "pagina_3.png", 0, 1) == _faixa(2, 22)
    assert _colunas(d / "pagina_3.png", 0, 2) == {0, 1}


def test_espera_continua_na_mesma_linha(capturas):
    """(c) [espera] não limpa a janela nem quebra a linha: o texto seguinte continua no
    mesmo lugar."""
    d = capturas("largura")
    assert _colunas(d / "pagina_4.png", 0, 2) == {2, 3}
    assert _colunas(d / "pagina_5.png", 0, 2) == _faixa(2, 5)
    assert _colunas(d / "pagina_5.png", 0, 1) == _colunas(d / "pagina_4.png", 0, 1)


def test_janela_rola_e_mostra_3_linhas(capturas):
    """(b) 4 linhas entre duas esperas: a janela (3 linhas) rola e a 1.ª ("A") some antes
    de o jogador ler."""
    d = capturas("largura")
    assert [_colunas(d / "pagina_6.png", 0, n) for n in range(3)] == [
        _faixa(2, 3), _faixa(2, 4), _faixa(2, 5)]


def test_quebra2_coluna_0_e_linha_no_recuo(capturas):
    """(c) [quebra2] (02) = nova linha na coluna 0; [linha] (09) = nova linha no recuo
    (2, definido por [$0A][$02]). Nenhum dos dois abre caixa nova."""
    d = capturas("largura")
    assert _colunas(d / "pagina_7.png", 0, 2) == _faixa(0, 5)          # "Z" + "Shion"
    assert _colunas(d / "pagina_7.png", 0, 2, _amarelo) == _faixa(1, 5)
    assert _colunas(d / "pagina_7.png", 0, 1) == _faixa(2, 5)          # DDDD (recuo)


@pytest.mark.parametrize("caso,flag", [("janela4", 4), ("janela7", 7)])
def test_largura_e_altura_vem_da_janela(capturas, caso, flag):
    """(a)(b) a largura e o número de linhas são os da janela do flag do diálogo
    (tabela 0x1DD74): 36 caracteres a partir da coluna 2 quebram na largura dela, e só as
    últimas ``altura`` linhas ficam na tela."""
    d = capturas(caso)
    larg, alt = JANELAS[flag]["largura"], JANELAS[flag]["altura"]
    linhas, col, resto = [], 2, 36
    while resto:
        n = min(resto, larg - col)
        linhas.append(_faixa(col, col + n - 1))
        resto -= n
        col = 0
    esperado = linhas[-alt:] + [set()] * (alt - len(linhas[-alt:]))
    assert [_colunas(d / "pagina_0.png", flag, n) for n in range(alt)] == esperado


# ------------------------------------------------------------------ (f) loja e estalagem

def test_loja_nome_preco_e_sim_nao(capturas):
    """(f) loja (b3.000) em PT: [s0:02] insere o nome do item em amarelo, [s0:03] o preço
    (número sem preenchimento, depois de [$04][$01]) e [s0:00] o menu SIM/NÃO."""
    d = capturas("loja")
    # "Isso é" / "Excalibur." (amarelo, coluna 2) / linha vazia
    assert _colunas(d / "pagina_1.png", 0, 1, _amarelo) == _faixa(2, 10)
    # "Custa" (2-6), avanço de 1 (7), "2500" (8-11), " MOEDAS" (13-18), "." (19)
    assert _colunas(d / "pagina_2.png", 0, 2) == _faixa(2, 6) | _faixa(8, 11) | _faixa(13, 19)
    # "Quer comprar?" e o menu: [quebra2] + [$04][$04] -> SIM em 4-6, NÃO em 9-11
    menu = _colunas(d / "pagina_3.png", 0, 2)
    assert _faixa(4, 6) | _faixa(9, 11) <= menu <= _faixa(3, 11) - {7, 8}
    assert _colunas(d / "pagina_3.png", 0, 1) == _faixa(2, 14) - {6}


def test_estalagem_preco_numerico(capturas):
    """(f) estalagem (b3.001): "custa[s0:05]." na mesma linha -> "custa" (recuo 2) +
    [$04][$01] (b0.005.t00 traduzido; no original [$04][$03], com o preço no começo da
    linha) + preço (15) + " MOEDAS." (b0.001 traduzido)."""
    d = capturas("estalagem")
    assert _colunas(d / "pagina_1.png", 0, 2) == _faixa(2, 6) | _faixa(8, 9) | _faixa(11, 17)


# ------------------------------------------------------------------ (g) inline

def test_menu_de_magias_sem_lixo_depois_do_texto(capturas):
    """(g) FIRE STORM -> FOGO: nada de lixo depois do texto (bloco repontável, sem os
    espaços do slot antigo) e o Ç aparece (glifo 0xAC)."""
    d = capturas("largura")
    with Image.open(d / "menu_magia.png") as img:
        px = img.convert("L").load()

        def colunas(x0, y, n):
            return {c for c in range(n) if any(px[x0 + 8 * c + dx, y + dy] > 128
                                                for dx in range(8) for dy in range(8))}
        # FOGO na 1.ª linha (texto em x=24, y=48), 10 posições do item
        assert colunas(24, 48, 10) == _faixa(0, 3)
        # FORÇA na 2.ª coluna do menu, 2.ª linha (x=144, y=72)
        assert colunas(144, 72, 6) == _faixa(0, 4)


# ------------------------------------------------------------------ (h) invariante

def test_invariante_fonte_em_todas_as_cenas(capturas):
    """(h) em cada cena do roteiro (passos checar_fonte), $A144 <= 40 e os slots 5–7 têm
    os blocos 5–7 (docs/tecnico/vram.md §3.1). O roteiro falha se não; aqui só confere
    que os despejos de RAM existem e passam de novo."""
    for caso in CASOS:
        d = capturas(caso)
        rams = sorted(d.glob("*.ram"))
        assert len(rams) >= 10, caso
        for arq in rams:
            assert checar_invariante_fonte(arq.read_bytes()) == [], f"{caso}/{arq.name}"


def test_checar_invariante_fonte_unitario():
    ram = bytearray(0x10000)
    for slot in range(8):
        ram[SLOTS_RAM + 2 * slot:SLOTS_RAM + 2 * slot + 2] = slot.to_bytes(2, "big")
    ram[ALOCADOS_RAM:ALOCADOS_RAM + 2] = MAX_ALOCADOS.to_bytes(2, "big")
    assert checar_invariante_fonte(bytes(ram)) == []
    ram[ALOCADOS_RAM + 1] += 1
    assert any("A144" in p for p in checar_invariante_fonte(bytes(ram)))
    ram[ALOCADOS_RAM:ALOCADOS_RAM + 2] = b"\x00\x05"
    ram[SLOTS_RAM + 10:SLOTS_RAM + 12] = b"\x02\x35"
    assert any("slot 5" in p for p in checar_invariante_fonte(bytes(ram)))


def test_limite_do_alocador_protege_os_slots_da_fonte():
    """0x125C4 grava os slots 0x30 - $A144 ... 0x2F: com $A144 = MAX_ALOCADOS o slot mais
    baixo é o 8. O slot 6 (0xC0-0xDF) tem o rótulo MOEDAS do HUD (0xC6-0xCB e 0xD3-0xD8), visível em
    todo o jogo, e o slot 7 (0xE0-0xFF) tem letras: $A144 = 41 já alcança o slot 7."""
    assert MAX_ALOCADOS == 40
    assert 0x30 - MAX_ALOCADOS == 8
    ram = bytearray(0x10000)
    for slot in range(8):
        ram[SLOTS_RAM + 2 * slot:SLOTS_RAM + 2 * slot + 2] = slot.to_bytes(2, "big")
    ram[ALOCADOS_RAM:ALOCADOS_RAM + 2] = (MAX_ALOCADOS + 1).to_bytes(2, "big")
    problemas = checar_invariante_fonte(bytes(ram))
    assert len(problemas) == 1 and "slot 7" in problemas[0]


def test_roteiro_validacao_valido_e_checa_toda_captura():
    passos = carregar_roteiro(ROTEIRO)
    capt = [p["capturar"] for p in passos if "capturar" in p]
    chec = [p["checar_fonte"] for p in passos if "checar_fonte" in p]
    assert capt and capt == chec


# ------------------------------------------------------------------ regras = jogo

def _ctx(textos: dict, esqueleto: bool = True) -> Contexto:
    from ferramentas.config import carregar_cfg_texto
    from ferramentas.script.montador import carregar_esqueleto

    cfg = carregar_cfg_texto(RAIZ)
    extra = {"largura_linha": cfg["largura_linha"], "linhas_por_caixa": cfg["linhas_por_caixa"],
             "janelas": cfg["janelas"]}
    if esqueleto:
        extra["esqueleto"] = carregar_esqueleto(RAIZ)
    return Contexto(tabela=Tabela.carregar(RAIZ / "traducao" / "tabela.tbl"), glossario=[],
                    textos=textos, extra=extra)


def _textos_reais() -> dict[str, list[Entrada]]:
    from ferramentas.textos import carregar_todos

    return carregar_todos(RAIZ / "traducao" / "textos")


def _com_pt(textos, pts):
    return {a: [Entrada(e.id, e.en, pt=pts.get(e.id, ""), status=e.status) for e in es]
            for a, es in textos.items()}


def test_regras_rejeitam_o_que_o_jogo_corta():
    """O que quebrou/rolou na captura é erro nas checagens com a config real; o que coube
    passa. p1 (22 caracteres depois do recuo) e p6 (4 linhas numa página)."""
    textos = _textos_reais()
    ok = ("ABCDEFGHIJKLMNOPQRSTU[quebra2]abcdefghijklmnopqrstuvw[espera][quebra2]"
          + ESTRUTURA_FIM)
    ctx = _ctx(_com_pt(textos, {"dialogo.000.t01": ok}))
    assert checar_largura(ctx) == [] and checar_linhas(ctx) == []
    largo = "[linha]0123456789012345678901[espera][quebra2]" + ESTRUTURA_FIM
    ach = checar_largura(_ctx(_com_pt(textos, {"dialogo.000.t01": largo})))
    assert len(ach) == 1 and "24" in ach[0].mensagem and "23" in ach[0].mensagem
    alto = "[linha]A[linha]BB[linha]CCC[linha]DDDD[espera]" + ESTRUTURA_FIM
    ach = checar_linhas(_ctx(_com_pt(textos, {"dialogo.000.t01": alto})))
    assert len(ach) == 1 and "4" in ach[0].mensagem and "3" in ach[0].mensagem
    # na borda pelo [$04] (p3) não é erro: o próprio jogo quebra ali
    borda = "[linha]ABCDEFGHIJKLMNOPQRSTU[$04][$02]XY[espera]" + ESTRUTURA_FIM
    assert checar_largura(_ctx(_com_pt(textos, {"dialogo.000.t01": borda}))) == []


def test_loja_pt_de_teste_passa_nas_regras():
    """A loja em PT do caso "loja" coube na tela (capturas): passa nas checagens."""
    ctx = _ctx(_com_pt(_textos_reais(), PT_LOJA))
    assert checar_largura(ctx) == [] and checar_linhas(ctx) == []
