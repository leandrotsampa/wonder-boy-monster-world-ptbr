"""Extração do texto da ROM: esqueleto (estrutura) + entradas traduzíveis por arquivo."""

from __future__ import annotations

from pathlib import Path

from ferramentas.script.desmontador import desmontar
from ferramentas.script.raizes import LIMITES, ler_tabelas
from ferramentas.script.segmentos import DICIONARIO_INI, exibir_en, ler_dicionario, rotulo, segmentar
from ferramentas.tabela import Tabela
from ferramentas.textos import Entrada

TABELA_PADRAO = Path(__file__).resolve().parent.parent.parent / "traducao" / "tabela.tbl"
ARQUIVOS_BANCO = {0: "banco0_sistema", 1: "banco1_itens", 2: "banco2_nomes", 3: "banco3_lojas"}


def _arquivo_da_raiz(raiz: str) -> str | None:
    """Arquivo YAML do texto de uma raiz; ``None`` para o dicionário (não traduzível)."""
    if raiz.startswith("dialogo."):
        return "dialogos"
    if raiz.startswith("extra."):
        return "extras"
    banco, _, indice = raiz.partition(".")
    b = int(banco[1:])
    if b == 0 and int(indice, 16) >= DICIONARIO_INI:
        return None
    return ARQUIVOS_BANCO[b]


def extrair_texto(rom: bytes, cfg: dict, tabela: Tabela | None = None,
                  limites: tuple[int, int] = LIMITES) -> tuple[dict, dict[str, list[Entrada]]]:
    """Devolve ``(esqueleto, entradas_por_arquivo)``.

    O esqueleto traz ``raizes``, ``instrucoes``, ``trechos`` (hex bruto) e ``tabelas``
    (diálogos e slots dos bancos, para o build refazer as tabelas de ponteiros).
    ``limites`` é a faixa ``[inicio, fim)`` dos scripts (outra que a da ROM base só
    para reler uma ROM com o texto realocado).
    """
    if tabela is None:
        tabela = Tabela.carregar(TABELA_PADRAO)
    tabelas = ler_tabelas(rom, cfg.get("raizes_extra") or [])
    instrs = desmontar(rom, list(tabelas.raizes.values()), limites)
    itens, trechos = segmentar(instrs, tabelas.raizes)
    dicionario = ler_dicionario(rom, tabelas, tabela)

    esqueleto = {
        "raizes": {nome: rotulo(end) for nome, end in tabelas.raizes.items()},
        "instrucoes": itens,
        "trechos": {t.id: t.bruto.hex() for t in trechos},
        "tabelas": {
            "dialogos": [{"raiz": nome, "flag": flag} for nome, flag in tabelas.dialogos],
            "bancos": {str(b): list(slots) for b, slots in sorted(tabelas.bancos.items())},
        },
    }

    grupos: dict[str, list[Entrada]] = {}
    for t in trechos:
        arquivo = _arquivo_da_raiz(t.id.rsplit(".t", 1)[0])
        if arquivo is None:
            continue
        grupos.setdefault(arquivo, []).append(Entrada(t.id, exibir_en(t.bruto, tabela, dicionario)))
    return esqueleto, grupos
