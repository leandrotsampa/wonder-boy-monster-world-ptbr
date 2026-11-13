"""Framework de verificação e checagens genéricas de texto."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Callable

from .tabela import ErroTabela, Tabela
from .textos import Entrada

_CODIGO = re.compile(r"\[[^\[\]]+\]")
CODIGOS_LIVRES = {"[quebra2]", "[linha]", "[espera]", "[cor]", "[/cor]"}
# Entradas em que só o número de colunas de [$04] (avanço) pode mudar. b0.005.t00 é o
# avanço antes da diária ([s0:05], que nos textos só a estalagem b3.001.t00 usa): no
# original, 3 colunas, porque o valor vinha no começo da linha; com o preço na mesma linha
# da frase, 1 coluna dá um espaço só ("custa 10 MOEDAS.").
AVANCO_LIVRE = {"b0.005.t00"}


@dataclass
class Achado:
    nivel: str  # "erro" | "aviso"
    checagem: str
    local: str
    mensagem: str


@dataclass
class Contexto:
    tabela: Tabela
    textos: dict[str, list[Entrada]]
    glossario: list[dict]
    extra: dict = field(default_factory=dict)


Checagem = Callable[[Contexto], list[Achado]]


def _traduzidas(ctx: Contexto):
    for arquivo, entradas in ctx.textos.items():
        for e in entradas:
            if e.pt:
                yield f"{arquivo}:{e.id}", e


def checar_caracteres(ctx: Contexto) -> list[Achado]:
    achados = []
    for local, e in _traduzidas(ctx):
        try:
            ctx.tabela.codificar(e.pt, e.id)
        except ErroTabela as exc:
            achados.append(Achado("erro", "caracteres", local, str(exc)))
    return achados


def _codigos(texto: str) -> list[str]:
    return [c for c in _CODIGO.findall(texto) if c not in CODIGOS_LIVRES]


def _sem_avanco(codigos: list[str]) -> list[str]:
    return [("[$04]" if i and codigos[i - 1] == "[$04]" else c) for i, c in enumerate(codigos)]


def checar_controles(ctx: Contexto) -> list[Achado]:
    achados = []
    for local, e in _traduzidas(ctx):
        esperado, obtido = _codigos(e.en), _codigos(e.pt)
        if e.id in AVANCO_LIVRE:
            esperado, obtido = _sem_avanco(esperado), _sem_avanco(obtido)
        if esperado != obtido:
            achados.append(Achado(
                "erro", "controles", local,
                f"códigos de controle diferem do original: esperado {esperado}, obtido {obtido}",
            ))
    return achados


_QUEBRAS = re.compile(r"(?:\[(?:linha|quebra2|espera)\])+")


def _sem_quebras(texto: str) -> str:
    """Troca quebras e esperas por espaço, para um termo partido entre linhas contar inteiro."""
    return _QUEBRAS.sub(" ", texto).lower()


def checar_glossario(ctx: Contexto) -> list[Achado]:
    achados = []
    for local, e in _traduzidas(ctx):
        pt_texto = _sem_quebras(e.pt)
        for termo in ctx.glossario:
            en, pt = str(termo.get("en", "")), str(termo.get("pt", ""))
            if en and pt and en.lower() in e.en.lower() and pt.lower() not in pt_texto:
                achados.append(Achado(
                    "aviso", "glossario", local,
                    f"original contém {en!r}, mas a tradução não usa {pt!r}",
                ))
    return achados


def checar_espaco(ctx: Contexto) -> list[Achado]:
    """Erro se a montagem do texto falhou ou se texto + fonte + gráficos excedem a região.

    ``ctx.extra["montagem"]`` é ``{"usado", "texto", "inline", "fonte", "graficos",
    "destino", "limite"}`` (``usado`` = texto + strings inline repontáveis + blocos da fonte e dos itens gráficos que não cabem no
    lugar) ou ``{"erro"}``; ausente quando não há esqueleto nem blocos a realocar.
    """
    m = ctx.extra.get("montagem")
    if not m:
        return []
    if "erro" in m:
        return [Achado("erro", "espaco", "texto", m["erro"])]
    disponivel = m["limite"] - m["destino"]
    if m["usado"] > disponivel:
        return [Achado("erro", "espaco", "regiao_destino",
                       f"texto ({m.get('texto', 0)} bytes) + inline repontável "
                       f"({m.get('inline', 0)} bytes) + fonte realocada "
                       f"({m.get('fonte', 0)} bytes) + gráficos realocados "
                       f"({m.get('graficos', 0)} bytes) = {m['usado']} bytes, "
                       f"excede {disponivel}")]
    return []


def checar_glifos(ctx: Contexto) -> list[Achado]:
    """Erro se algum caractere da tabela (exceto o espaço) usa tile vazio ou invisível.

    ``ctx.extra["fonte"]`` são os 256 tiles de ``graficos/fonte/fonte.png``; ausente =
    não checa. Invisíveis no jogo: ``0x80–0x9F`` (slot 4 recebe o bloco ``0x235``) e
    ``0x5C``/``0x5D``/``0x5F`` (zerados depois da carga); ver docs/tecnico/vram.md.
    """
    from .fonte import TILES_INVISIVEIS, TILES_ZERADOS, tile_vazio

    tiles = ctx.extra.get("fonte")
    if tiles is None:
        return []
    achados = []
    for ch in sorted(ctx.tabela.caracteres()):
        if ch == " ":
            continue
        for cod in ctx.tabela.codificar(ch):
            if cod in TILES_INVISIVEIS:
                motivo = ("não aparece no jogo: o slot 4 (0x80-0x9F) recebe o bloco 0x235 "
                          "(HUD) em toda cena com texto")
            elif cod in TILES_ZERADOS:
                motivo = "não aparece no jogo: o jogo zera esse tile depois da carga"
            elif tile_vazio(tiles, cod):
                motivo = "tile vazio na fonte (desenhe o glifo em graficos/fonte/fonte.png)"
            else:
                continue
            achados.append(Achado("erro", "glifos", "tabela.tbl",
                                  f"caractere {ch!r} (0x{cod:02X}): {motivo}"))
    return achados


def checar_hud(ctx: Contexto) -> list[Achado]:
    """Erro se um caractere usa os códigos do rótulo MOEDAS do HUD (``HUD_CODIGOS_*``) ou se,
    com o patch do HUD, a fonte não traz os tiles do rótulo.

    Olha os caracteres da tabela (todo byte da chave), ``ctx.extra["acentos"]`` (de
    ``config/texto.yaml``) e, se ``ctx.extra["hud"]`` (patch ``hud.moedas_rotina`` em
    ``config/patches.yaml``), compara esses tiles de ``ctx.extra["fonte"]`` com
    ``tiles_hud`` da própria fonte: PNG sem o rótulo (kana nesses tiles) ou ausente faria
    o HUD mostrar kana. Ver ferramentas/fonte.py e mapa-rom.md §8.
    """
    from .fonte import (ARQ_PNG, BYTES_TILE, HUD_CODIGOS_BAIXO, HUD_CODIGOS_CIMA, faixas_hud,
                        tiles_hud)

    codigos = HUD_CODIGOS_CIMA + HUD_CODIGOS_BAIXO
    faixa = faixas_hud()
    motivo = f"os códigos {faixa} são o rótulo MOEDAS do HUD, não caracteres"
    achados = []
    for chave, valor in sorted(ctx.tabela.entradas().items()):
        if valor.startswith("[") and valor.endswith("]"):
            continue
        for cod in chave:
            if cod in codigos:
                achados.append(Achado("erro", "hud", "tabela.tbl",
                                      f"caractere {valor!r} (0x{cod:02X}): {motivo}"))
    for ch, cod in sorted((ctx.extra.get("acentos") or {}).items(), key=lambda kv: kv[1]):
        if cod in codigos:
            achados.append(Achado("erro", "hud", "config/texto.yaml",
                                  f"acento {ch!r} (0x{cod:02X}): {motivo}"))
    if not ctx.extra.get("hud"):
        return achados
    tiles = ctx.extra.get("fonte")
    if tiles is None:
        achados.append(Achado("erro", "hud", ARQ_PNG.as_posix(),
                              f"o patch do HUD imprime os tiles {faixa}, mas não há fonte "
                              "editável: o HUD mostraria os kana da fonte original"))
        return achados
    esperado = tiles_hud(tiles)
    errados = [cod for i, cod in enumerate(codigos)
               if tiles[BYTES_TILE * cod:BYTES_TILE * (cod + 1)]
               != esperado[BYTES_TILE * i:BYTES_TILE * (i + 1)]]
    if errados:
        lista = ", ".join(f"0x{c:02X}" for c in errados)
        achados.append(Achado("erro", "hud", ARQ_PNG.as_posix(),
                              f"os tiles {lista} não são o rótulo MOEDAS do HUD (tiles_hud); "
                              "restaure o PNG versionado ou apague-o e rode 'extrair', "
                              "que gera o rótulo"))
    return achados


def checar_inline(ctx: Contexto) -> list[Achado]:
    from .inline import checar_inline as _checar
    from .repontavel import checar_repontaveis

    return _checar(ctx) + checar_repontaveis(ctx)


# largura de linha e linhas por página (regras confirmadas no jogo: Plano 3, Tarefa 6;
# capturas em build/capturas/validacao/, ver docs/tecnico/mapa-rom.md "Largura de linha")

# Arquivos checados: texto que aparece na janela de diálogo. Os nomes (banco1_itens,
# banco2_nomes), as strings fixas (inline) e o banco0_sistema não são checados; entram só
# como referências (expansão de [s0/item/nome:XX]).
ARQUIVOS_LARGURA = ("dialogos", "banco3_lojas")
_TOKEN = re.compile(r"\[[^\[\]]+\]|.", re.S)
_REF = re.compile(r"\[(s0|item|nome|s3):([0-9A-Fa-f]{2})\]")
_BANCO_DE = {"s0": 0, "item": 1, "nome": 2, "s3": 3}
# Controles seguidos de 1 argumento (03 NN, 04 NN, 0A NN, 01 NN); a extração sempre
# exibe o argumento como [$NN] (ver segmentos.exibir_en).
_COM_ARG = {"[$03]", "[$04]", "[$0A]", "[$01]"}
# Marcadores legíveis dos valores em tempo de execução nas páginas simuladas (paginas())
MARCA_ITEM, MARCA_NUMERO = "‹item›", "‹preço›"
MARCA_SCRIPT = "‹script›"   # resto de um script do banco 3 (só o 1.º trecho é medido)
# Maior número que o jogo imprime (subop 0B 05, decimal sem zeros à esquerda: 0x183E):
# preço da tabela 0x1DAE (maior 500000) ou diária da estalagem (tabela 0x1906, maior 300).
DIGITOS_NUMERO = 6
# Recuo de [linha] (09): $8CAB, definido por [$0A][$NN] e nunca zerado pelo código; o
# único valor usado é 2 (b0.006, b0.007 e 13 trechos), então vale 2 desde o 1.º diálogo.
RECUO_PADRAO = 2
# Subops de 0B que importam para a medição (no esqueleto, "sub" é decimal).
_SUB_LIMPA, _SUB_CURSOR, _SUB_ALTURA = 0x20, 0x1E, 0x32
_SUB_NUMERO, _SUB_ITEM, _SUB_STRING_BYTE, _SUB_DEF_ITEM = 0x05, 0x06, 0x01, 0x0A
_SUB_DEF_STRING, _SUB_STRING, _SUB_QUIZ = 0x1B, 0x1C, 0x1F
_SUB_PAUSA = {0x02, 0x21, 0x1A}       # menu SIM/NÃO, resposta do quiz, botões: o jogador lê
_SUB_FIM = {0x00, 0x25}               # encerram o fluxo
_SUB_SEMPRE_SALTA = {0x24, 0x27}      # tabelas de salto sem caminho direto
_FECHA_PAGINA = _SUB_PAUSA | _SUB_FIM | {_SUB_LIMPA}   # subops que encerram a página
_MAX_ESTADO = 255                     # teto da análise de fluxo (garante o ponto fixo)


def _valor_arg(tok: str) -> int:
    m = re.fullmatch(r"\[\$([0-9A-Fa-f]{2})\]", tok)
    return int(m.group(1), 16) if m else 0


@dataclass
class _Estado:
    """Cursor do motor de texto (0x14F4): coluna ($8C9A), recuo ($8CAB), linhas com texto
    na página atual (desde a última espera) e altura da janela ($8CA0).

    ``abertos``: trechos cuja última página ainda está aberta (o texto deles está na
    janela e nenhuma espera, pausa, limpeza ou fim veio depois); onde caminhos se
    encontram, vale a união (o pior caso: todos são checados ao fechar).
    """
    col: int = 0
    recuo: int = RECUO_PADRAO
    pag: int = 0
    altura: int = 0
    string_1c: tuple[int, int] | None = None   # banco/índice do subop 1B (lido pelo 1C)
    item: int | None = None                    # $8CAE (subop 0A): item do nome inserido
    abertos: frozenset[str] = frozenset()

    def copia(self) -> "_Estado":
        return replace(self)

    def juntar(self, outro: "_Estado") -> bool:
        """Funde ``outro`` no pior caso (maior coluna/recuo/página, menor altura)."""
        antigo = (self.col, self.recuo, self.pag, self.altura, self.string_1c, self.item,
                  self.abertos)
        self.col = min(max(self.col, outro.col), _MAX_ESTADO)
        self.recuo = min(max(self.recuo, outro.recuo), _MAX_ESTADO)
        self.pag = min(max(self.pag, outro.pag), _MAX_ESTADO)
        if outro.altura and (not self.altura or outro.altura < self.altura):
            self.altura = outro.altura
        if self.string_1c != outro.string_1c:
            self.string_1c = None
        if self.item != outro.item:
            self.item = None
        self.abertos = self.abertos | outro.abertos
        return (self.col, self.recuo, self.pag, self.altura, self.string_1c,
                self.item, self.abertos) != antigo


@dataclass
class _Celula:
    """O que o motor imprimiu numa coluna: um caractere ou, para um valor em tempo de
    execução, um marcador legível (``‹item›``) que ocupa ``largura`` colunas."""
    col: int
    texto: str
    largura: int = 1
    cor: bool = False          # entre [cor] e [/cor]: amarelo
    variavel: bool = False
    codigos: bytes = b""       # tiles da fonte (preenchido por paginas())


class _Tela:
    """Registra o que o motor de texto imprime, para ``paginas``.

    Com ``largura``, o caractere que cai na coluna >= largura vai para a coluna 0 da
    linha seguinte (o motor quebra sozinho no meio da palavra); a medição das checagens
    não quebra (lá é estouro). Uma página fechada deixa a linha atual na janela: se o
    texto seguinte continua nela (``[espera]`` sem ``[linha]``), a página nova a mostra.
    """

    def __init__(self, largura: int = 0):
        self.largura = largura
        self.cor = False
        self.linhas: list[list[_Celula]] = [[]]
        self.paginas: list[tuple[list[list[_Celula]], bool]] = []

    def escrever(self, col: int, texto: str, largura: int, variavel: bool) -> None:
        self.linhas[-1].append(_Celula(col, texto, largura, self.cor, variavel))

    def nova_linha(self, com_texto: bool) -> None:
        if com_texto:
            self.linhas.append([])
        else:              # antes do 1.º caractere da página: as linhas vazias rolam
            self.linhas = [[]]

    def fechar(self, espera: bool) -> None:
        self.paginas.append((self.linhas, espera))
        self.linhas = [list(self.linhas[-1])]


@dataclass
class _Relato:
    linhas: list[int] = field(default_factory=lambda: [0])          # maior coluna por linha
    paginas: list[tuple[int, int]] = field(default_factory=list)    # (linhas, altura)
    tela: _Tela | None = None                                       # só em paginas()


class _Larguras:
    """Mede o texto exibido (com tags) como o motor de texto o imprime.

    Regras (código em 0x14F4–0x172C; confirmadas nas capturas de
    testes/test_validacao_jogo.py):

    * caractere = 1 coluna. O motor quebra a linha sozinho quando um caractere cai na
      coluna >= largura da janela, no meio da palavra: aqui isso é estouro;
    * ``[quebra2]`` (02) = nova linha na coluna 0; ``[linha]`` (09) = nova linha na coluna
      do recuo (``[$0A][$NN]`` define; ``RECUO_PADRAO`` = 2); ``[espera]`` (05) só espera o
      botão: não limpa a janela nem quebra a linha, e fecha a página;
    * ``[$04][$NN]`` avança NN colunas; se o cursor chega à borda (>= largura), o próximo
      caractere vai para a coluna 0 da linha seguinte (o motor quebra; não é estouro);
    * ``[$03][$NN]``, ``[$01][$NN]``, ``[cor]``, ``[/cor]`` e demais ``[$XX]`` valem 0
      (``[$XX]`` >= 0x80 sem entrada na tabela vale 1);
    * ``[s0/item/nome/s3:XX]``: o texto da string do banco entra na linha. No banco 0 a
      lacuna entre dois trechos é um valor em tempo de execução: nome de item (``[cor]``
      antes dela) = o nome do item de $8CAE se o fluxo o define (subop 0A), senão o maior
      nome do banco 1; senão número de ``DIGITOS_NUMERO`` dígitos. No banco 3 (script) só o
      1º trecho entra e, havendo mais trechos, a linha seguinte recomeça com página nova, na
      coluna 0 se o script termina limpando a janela (0B 20: quiz, b3.006) ou no recuo
      (b3.007 termina em ``[espera][linha]``);
    * ``[item:XX]`` sem entrada no banco conta o maior nome do banco 1;
    * página = linhas com texto entre duas esperas (ou pausas de menu): a janela rola
      quando passa da altura e as primeiras linhas somem antes de o jogador ler.
    """

    def __init__(self, textos: dict[str, list[Entrada]]):
        self.entradas: dict[str, list[str]] = {}
        for entradas in textos.values():
            for e in entradas:
                chave, sep, _ = e.id.rpartition(".t")
                if sep and re.fullmatch(r"b[0-3]\.[0-9A-F]+", chave):
                    self.entradas.setdefault(chave, []).append(e.pt or e.en)
        self._em_curso: set[str] = set()
        self._maiores: dict[str, int] = {}
        # scripts do banco 3 que terminam limpando a janela (0B 20 antes do 00): depois
        # deles o texto recomeça na coluna 0; nos outros, no recuo (ver _medicoes)
        self.b3_limpa_no_fim: set[str] = set()

    # --- valores em tempo de execução
    def _maior(self, nome: str, chaves: list[str]) -> int:
        if nome not in self._maiores:
            self._maiores[nome] = 0  # protege contra referência circular
            maior = 0
            for chave in chaves:
                rel = _Relato()
                self._expandir(chave, _Estado(recuo=0), None, rel)
                maior = max(maior, max(rel.linhas))
            self._maiores[nome] = maior
        return self._maiores[nome]

    def maior_do_banco(self, banco: int) -> int:
        return self._maior(f"b{banco}", [c for c in self.entradas if c.startswith(f"b{banco}.")])

    def maior_nome(self) -> int:
        return self.maior_do_banco(1)

    def nome_item(self, est: _Estado) -> int:
        """Largura do nome inserido em tempo de execução: o item de $8CAE, se conhecido
        (subop 0A antes, no fluxo), senão o maior nome do banco 1."""
        if est.item is not None:
            item = est.item - 0x40 if 0x60 <= est.item < 0x66 else est.item   # 0x1864
            chave = f"b1.{item:03X}"
            if chave in self.entradas:
                rel = _Relato()
                self._expandir(chave, _Estado(recuo=0), None, rel)
                return max(rel.linhas)
        return self.maior_nome()

    # --- medição
    def avancar(self, est: _Estado, rel: _Relato, n: int = 1, texto: str = "") -> None:
        """Imprime ``n`` colunas visíveis: um caractere (``texto``) ou, com ``n`` > 1, um
        valor em tempo de execução (``texto`` = marcador legível, para ``paginas``)."""
        tela = rel.tela
        if tela is not None and tela.largura and est.col >= tela.largura:
            self._nova_linha(est, rel, 0)      # o motor quebra na borda
        if est.pag == 0:
            est.pag = 1
        if tela is not None:
            tela.escrever(est.col, texto or "?", n, texto.startswith("‹"))
        est.col = min(est.col + n, _MAX_ESTADO)
        rel.linhas[-1] = max(rel.linhas[-1], est.col)

    @staticmethod
    def _nova_linha(est: _Estado, rel: _Relato, col: int) -> None:
        if rel.tela is not None:
            rel.tela.nova_linha(bool(est.pag))
        if est.pag:
            est.pag = min(est.pag + 1, _MAX_ESTADO)
        est.col = col
        rel.linhas.append(0)

    @staticmethod
    def fim_pagina(est: _Estado, rel: _Relato, espera: bool = False) -> None:
        if est.pag:
            rel.paginas.append((est.pag, est.altura))
            if rel.tela is not None:
                rel.tela.fechar(espera)
        est.pag = 0

    def expandir(self, chave: str, est: _Estado, largura: int | None, rel: _Relato) -> None:
        self._expandir(chave, est, largura, rel)

    def _expandir(self, chave: str, est: _Estado, largura: int | None, rel: _Relato) -> None:
        if chave in self._em_curso or chave not in self.entradas:
            return
        self._em_curso.add(chave)
        try:
            trechos = self.entradas[chave]
            for i, trecho in enumerate(trechos):
                if i:
                    if not chave.startswith("b0."):
                        break
                    if trechos[i - 1].rstrip().endswith("[cor]"):
                        self.avancar(est, rel, self.nome_item(est), MARCA_ITEM)
                    else:
                        self.avancar(est, rel, DIGITOS_NUMERO, MARCA_NUMERO)
                self.medir(trecho, est, largura, rel)
            if chave.startswith("b3.") and len(trechos) > 1:
                if rel.tela is not None:
                    rel.tela.escrever(est.col, MARCA_SCRIPT, 0, True)
                    if est.pag:
                        rel.tela.fechar(False)
                self._nova_linha(est, rel, 0 if chave in self.b3_limpa_no_fim else est.recuo)
                est.pag = 0
                if rel.tela is not None:
                    rel.tela.linhas = [[]]   # o resto do script imprime outras páginas
        finally:
            self._em_curso.discard(chave)

    def _referencia(self, tipo: str, hexa: str, est: _Estado, largura: int | None,
                    rel: _Relato) -> None:
        chave = f"b{_BANCO_DE[tipo]}.{int(hexa, 16):03X}"
        if chave in self.entradas:
            self._expandir(chave, est, largura, rel)
        elif tipo == "item":
            self.avancar(est, rel, self.maior_nome(), MARCA_ITEM)

    def medir(self, texto: str, est: _Estado, largura: int | None, rel: _Relato) -> None:
        """Imprime ``texto`` a partir de ``est`` (que é alterado), anotando em ``rel``."""
        toks = _TOKEN.findall(texto)
        i = 0
        while i < len(toks):
            tok = toks[i]
            i += 1
            if tok == "[linha]":
                self._nova_linha(est, rel, est.recuo)
            elif tok == "[quebra2]":
                self._nova_linha(est, rel, 0)
            elif tok == "[espera]":
                self.fim_pagina(est, rel, espera=True)
            elif tok in _COM_ARG:
                arg = _valor_arg(toks[i]) if i < len(toks) else 0
                i += 1
                if tok == "[$04]":
                    est.col = min(est.col + arg, _MAX_ESTADO)
                    if largura and est.col >= largura:
                        self._nova_linha(est, rel, 0)   # o motor quebra na borda
                elif tok == "[$0A]":
                    est.recuo = arg
            elif tok in ("[cor]", "[/cor]"):
                if rel.tela is not None:
                    rel.tela.cor = tok == "[cor]"
            elif tok.startswith("["):
                m = _REF.fullmatch(tok)
                if m:
                    self._referencia(m.group(1), m.group(2), est, largura, rel)
                elif re.fullmatch(r"\[\$[89A-Fa-f][0-9A-Fa-f]\]", tok):
                    self.avancar(est, rel, 1, tok)
            else:
                self.avancar(est, rel, 1, tok)

    def linhas(self, texto: str, largura: int | None = None) -> list[int]:
        """Larguras das linhas de ``texto`` medido sozinho (coluna 0, recuo padrão)."""
        rel = _Relato()
        self.medir(texto, _Estado(), largura, rel)
        return rel.linhas


@dataclass(frozen=True)
class _Janela:
    largura: int
    altura: int


def _janelas(ctx: Contexto) -> tuple[list[_Janela], _Janela]:
    padrao = _Janela(int(ctx.extra.get("largura_linha") or 0),
                     int(ctx.extra.get("linhas_por_caixa") or 0))
    janelas = [_Janela(int(j["largura"]), int(j["altura"]))
               for j in ctx.extra.get("janelas") or []]
    return janelas, padrao


def _flag_dialogos(esq: dict | None) -> dict[str, int]:
    if not esq:
        return {}
    return {d["raiz"]: int(d["flag"]) for d in esq.get("tabelas", {}).get("dialogos", [])}


def _janela_de(raiz: str, flags: dict[str, int], janelas: list[_Janela],
               chamadores: dict[str, _Janela], padrao: _Janela) -> _Janela:
    flag = flags.get(raiz)
    if flag is not None and flag < len(janelas):
        return janelas[flag]
    return chamadores.get(raiz, padrao)


def _chamadores_banco3(ctx: Contexto, flags, janelas, padrao) -> dict[str, _Janela]:
    """Janela de cada script do banco 3: a mais estreita/baixa dos diálogos que o chamam."""
    res: dict[str, _Janela] = {}
    for e in ctx.textos.get("dialogos", []):
        jan = _janela_de(e.id.rpartition(".t")[0], flags, janelas, {}, padrao)
        for m in _REF.finditer(e.pt or e.en):
            if m.group(1) == "s3":
                chave = f"b3.{int(m.group(2), 16):03X}"
                atual = res.get(chave)
                res[chave] = jan if atual is None else _Janela(
                    min(atual.largura, jan.largura), min(atual.altura, jan.altura))
    return res


def _efeito_subop(sub, args: list, est: _Estado, medidor: _Larguras) -> None:
    rel = _Relato()
    if sub == _SUB_LIMPA:
        est.col, est.pag = 0, 0
    elif sub == _SUB_CURSOR and args:
        est.col = int(args[0])
    elif sub == _SUB_ALTURA and args:
        est.altura = int(args[0])
    elif sub == _SUB_NUMERO:
        medidor.avancar(est, rel, DIGITOS_NUMERO)
    elif sub == _SUB_ITEM:
        medidor.avancar(est, rel, medidor.nome_item(est))
    elif sub == _SUB_DEF_ITEM and args:
        est.item = int(args[0])
    elif sub == _SUB_STRING_BYTE and args:
        medidor.avancar(est, rel, medidor.maior_do_banco(int(args[0]) & 3))
    elif sub == _SUB_DEF_STRING and len(args) >= 2:
        est.string_1c = (int(args[0]) & 3, int(args[1]))
    elif sub == _SUB_STRING:
        if est.string_1c is not None:
            medidor.expandir(f"b{est.string_1c[0]}.{est.string_1c[1]:03X}", est, None, rel)
        else:
            medidor.avancar(est, rel, max(medidor.maior_do_banco(b) for b in range(3)))
    elif sub == _SUB_QUIZ:   # string do banco 0 sorteada (pergunta/resposta do quiz)
        medidor.avancar(est, rel, medidor.maior_do_banco(0))
    elif sub in _SUB_PAUSA:
        medidor.fim_pagina(est, rel)


def _analisar_fluxo(esq: dict, medidor: _Larguras, textos_por_id: dict[str, str],
                    raizes: list[tuple[str, _Janela]]
                    ) -> tuple[dict[tuple[str, _Janela], _Estado], set[str]]:
    """Estado do cursor no início de cada trecho, seguindo o fluxo do script, e os
    trechos cuja última página é fechada pelo fluxo.

    Percorre ``esq["instrucoes"]`` a partir de cada raiz (rótulo, janela) e propaga o
    estado pelos trechos e pelas instruções estruturais (saltos, desvios condicionais,
    fim) até o ponto fixo; onde dois caminhos se encontram vale o pior caso.

    Uma página fecha quando o fluxo chega a ``00``, a uma pausa de menu, a um fim ou à
    limpeza da janela por qualquer caminho (inclusive saltos e subops sem texto entre o
    trecho e o fechamento): os trechos com a página aberta naquele ponto entram no
    conjunto devolvido.
    """
    instrucoes = esq.get("instrucoes", [])
    indice = {ins["rotulo"]: i for i, ins in enumerate(instrucoes) if ins.get("rotulo")}
    inicio: dict[tuple[str, _Janela], _Estado] = {}
    fecham: set[str] = set()
    for rotulo, jan in raizes:
        if rotulo not in indice:
            continue
        estados = {indice[rotulo]: _Estado(altura=jan.altura)}
        pendentes = [indice[rotulo]]
        while pendentes:
            i = pendentes.pop()
            est = estados[i].copia()
            ins = instrucoes[i]
            if "trecho" in ins:
                chave = (ins["trecho"], jan)
                if chave in inicio:
                    inicio[chave].juntar(est)
                else:
                    inicio[chave] = est.copia()
                medidor.medir(textos_por_id.get(ins["trecho"], ""), est, jan.largura, _Relato())
                est.abertos = frozenset({ins["trecho"]}) if est.pag else frozenset()
                sucessores = [i + 1]
            else:
                alvos = [indice[a] for a in ins.get("alvos", []) if a in indice]
                op, sub = ins.get("op"), ins.get("sub")
                if op == 0x00 or (op == 0x0B and sub in _FECHA_PAGINA):
                    fecham |= est.abertos
                    est.abertos = frozenset()
                if op == 0x00:
                    sucessores = []
                elif op == 0x06:
                    sucessores = alvos
                elif op == 0x0B:
                    _efeito_subop(sub, ins.get("args", []), est, medidor)
                    if sub in _SUB_FIM:
                        sucessores = []
                    elif sub in _SUB_SEMPRE_SALTA:
                        sucessores = alvos
                    else:
                        sucessores = [i + 1] + alvos
                else:
                    sucessores = [i + 1]
            for s in sucessores:
                if s >= len(instrucoes):
                    continue
                if s not in estados:
                    estados[s] = est.copia()
                    pendentes.append(s)
                elif estados[s].juntar(est):
                    pendentes.append(s)
    return inicio, fecham


def _b3_limpa_no_fim(esq: dict) -> set[str]:
    """Scripts do banco 3 cujo primeiro ``00`` vem logo depois de 0B 20 (limpa a janela e
    zera o cursor, 0x1A50): ex. b3.006, a pergunta do quiz."""
    instrucoes = esq.get("instrucoes", [])
    indice = {ins["rotulo"]: i for i, ins in enumerate(instrucoes) if ins.get("rotulo")}
    res = set()
    for raiz, rotulo in esq.get("raizes", {}).items():
        if not raiz.startswith("b3.") or rotulo not in indice:
            continue
        i = indice[rotulo]
        while i < len(instrucoes) and instrucoes[i].get("op") != 0x00:
            i += 1
        anterior = instrucoes[i - 1] if i > indice[rotulo] else {}
        if anterior.get("op") == 0x0B and anterior.get("sub") == _SUB_LIMPA:
            res.add(raiz)
    return res


def _estados_iniciais(ctx: Contexto):
    """(medidor, lista de (arquivo, entrada, casos, fecha)) de cada entrada dos
    ``ARQUIVOS_LARGURA`` (com ou sem pt); ``casos`` = [(janela, estado inicial)] e
    ``fecha`` = a página aberta no fim da entrada termina ali.

    Com o esqueleto (``ctx.extra["esqueleto"]``), cada trecho começa no estado em que o
    fluxo do script o alcança (coluna onde o trecho anterior parou, página em curso,
    recuo) e ``fecha`` vale se o fluxo fecha a página logo depois (fim, pausa, limpeza);
    sem ele, cada entrada começa na coluna 0 com página nova e a página termina no fim
    da entrada.
    """
    janelas, padrao = _janelas(ctx)
    esq = ctx.extra.get("esqueleto")
    flags = _flag_dialogos(esq)
    chamadores = _chamadores_banco3(ctx, flags, janelas, padrao)
    medidor = _Larguras(ctx.textos)
    if esq:
        medidor.b3_limpa_no_fim = _b3_limpa_no_fim(esq)
    por_trecho: dict[str, list[tuple[_Janela, _Estado]]] = {}
    fecha_pagina: set[str] = set()   # trechos cuja página o fluxo fecha (fim, pausa, limpeza)
    if esq:
        textos_por_id = {e.id: e.pt or e.en for a in ARQUIVOS_LARGURA
                         for e in ctx.textos.get(a, [])}
        raizes = [(rotulo, _janela_de(raiz, flags, janelas, chamadores, padrao))
                  for raiz, rotulo in esq.get("raizes", {}).items()
                  if raiz.startswith(("dialogo.", "b3."))]
        inicio, fecha_pagina = _analisar_fluxo(esq, medidor, textos_por_id, raizes)
        for (trecho, jan), est in inicio.items():
            por_trecho.setdefault(trecho, []).append((jan, est))
    res = []
    for arquivo in ARQUIVOS_LARGURA:
        for e in ctx.textos.get(arquivo, []):
            casos = por_trecho.get(e.id)
            if casos:
                res.append((arquivo, e, casos, e.id in fecha_pagina))
            else:
                jan = _janela_de(e.id.rpartition(".t")[0], flags, janelas, chamadores, padrao)
                res.append((arquivo, e, [(jan, _Estado(altura=jan.altura))], True))
    return medidor, res


def _medicoes(ctx: Contexto):
    """(arquivo, entrada, janela, relato do pt, relato do en, coluna inicial) de cada
    entrada checada (com pt), a partir dos estados de ``_estados_iniciais``."""
    medidor, entradas = _estados_iniciais(ctx)
    for arquivo, e, casos, fecha in entradas:
        if not e.pt:
            continue
        for jan, inicial in casos:
            relatos = []
            for texto in (e.pt, e.en):
                est = inicial.copia()
                rel = _Relato()
                medidor.medir(texto, est, jan.largura, rel)
                if fecha:
                    medidor.fim_pagina(est, rel)
                relatos.append(rel)
            yield arquivo, e, jan, relatos[0], relatos[1], inicial.col


@dataclass
class Pagina:
    """Uma página do texto como a janela a mostra: ``linhas`` desde o último
    ``[espera]`` (ou pausa), com as colunas iniciais como espaços e os valores em tempo
    de execução como marcadores (``‹item›``, ``‹preço›``); ``largura``/``altura`` da
    janela; ``espera`` = termina num ``[espera]`` da entrada (senão continua no trecho
    seguinte ou o fluxo a fecha). Com mais linhas que ``altura``, as primeiras rolam
    antes de o jogador ler. ``celulas``: o mesmo, coluna a coluna (cor e tiles), para
    desenhar."""
    linhas: list[str]
    largura: int
    altura: int
    espera: bool
    celulas: list[list[_Celula]] = field(default_factory=list, repr=False, compare=False)


def _texto_linha(celulas: list[_Celula]) -> str:
    partes, fim = [], 0
    for c in celulas:
        partes.append(" " * max(c.col - fim, 0) + c.texto)
        fim = max(fim, c.col + c.largura)
    return "".join(partes)


def _simulacao(ctx: Contexto):
    """Estados iniciais de ``_estados_iniciais`` por id, calculados uma vez por contexto
    (``ctx.extra["_simulacao"]``; os textos do contexto não devem mudar depois)."""
    if "_simulacao" not in ctx.extra:
        medidor, entradas = _estados_iniciais(ctx)
        ctx.extra["_simulacao"] = (medidor, {e.id: (e, casos) for _, e, casos, _ in entradas})
    return ctx.extra["_simulacao"]


def paginas(ctx: Contexto, entrada_id: str) -> list[Pagina]:
    """Páginas do ``pt`` da entrada como o motor de texto as exibe (``[]`` sem pt ou
    fora dos arquivos da janela de diálogo).

    Parte do pior estado de entrada (o mesmo de ``checar_linhas``; com mais de uma
    janela possível, a mais estreita) e segue as regras de ``_Larguras``; a diferença é
    que aqui o caractere que cai na borda quebra a linha, como no jogo. A última página
    entra mesmo aberta (ela continua no trecho seguinte ou o fluxo a fecha).
    """
    medidor, por_id = _simulacao(ctx)
    if entrada_id not in por_id or not por_id[entrada_id][0].pt:
        return []
    e, casos = por_id[entrada_id]
    # o mais apertado: janela mais estreita e mais baixa, mais linhas já ocupadas na
    # página e, por fim, a coluna mais à direita
    jan, inicial = min(casos, key=lambda c: (c[0].largura or _MAX_ESTADO,
                                             c[0].altura or _MAX_ESTADO,
                                             -c[1].pag, -c[1].col))
    est = inicial.copia()
    rel = _Relato(tela=_Tela(jan.largura))
    medidor.medir(e.pt, est, jan.largura, rel)
    if est.pag:
        rel.tela.fechar(False)
    res = []
    for linhas, espera in rel.tela.paginas:
        for linha in linhas:
            for c in linha:
                try:   # variável: o nome do marcador, desenhado na caixa dela
                    c.codigos = ctx.tabela.codificar(c.texto.strip("‹›") if c.variavel
                                                     else c.texto, e.id)
                except ErroTabela:
                    c.codigos = b""      # caractere sem glifo: desenhado como erro
        res.append(Pagina([_texto_linha(l).rstrip() for l in linhas], jan.largura,
                          jan.altura, espera, linhas))
    return res


# Nome de item copiado por 0x1E6A (baú 0x1EEC, listas do menu 0x7AD6 e 0x8428): a linha
# de cima (espaço ou a marca do prefixo FE/FF; move.b d2,(a3)+ em 0x1EC8) e as letras
# (move.b d3,$xx(a3) em 0x1EC4), sem limite no código. Na base o buffer era $8CE0/$8CF0
# (16 colunas, com a pilha das strings aninhadas em $8D00 logo depois); os patches
# buffer_nome.* (config/patches.yaml) o levam para $AB00/$AB20, 32 colunas em RAM que o
# jogo não usa (mapa-rom.md §6, "Buffer do nome de item"). O limite do nome é o menor
# entre o buffer e a linha do baú: "Você achou " + nome + "." em 30 colunas entre as
# bordas (o ajuste bau.centro_item de config/texto.yaml usa o mesmo valor e acusa se os
# textos fixos crescerem). Diálogos e loja têm janelas de 23 colunas (checar_largura).
BUFFER_NOME_ITEM = 0xAB00
BUFFER_NOME_ITEM_LETRAS = 0xAB20
COLUNAS_BAU = 30
MAX_NOME_ITEM_BAU = COLUNAS_BAU - len("Você achou ") - len(".")   # 18
MAX_NOME_ITEM = min(BUFFER_NOME_ITEM_LETRAS - BUFFER_NOME_ITEM, MAX_NOME_ITEM_BAU)   # 18


def checar_nomes_itens(ctx: Contexto) -> list[Achado]:
    """Erro se um nome do banco 1 (com as strings aninhadas expandidas) passa de
    ``MAX_NOME_ITEM`` colunas."""
    medidor = _Larguras(ctx.textos)
    achados = []
    for e in ctx.textos.get("banco1_itens", []):
        chave, sep, _ = e.id.rpartition(".t")
        if not sep or not re.fullmatch(r"b1\.[0-9A-F]+", chave):
            continue
        rel = _Relato()
        medidor.expandir(chave, _Estado(recuo=0), None, rel)
        largura = max(rel.linhas)
        if largura > MAX_NOME_ITEM:
            achados.append(Achado(
                "erro", "nome_item", f"banco1_itens:{e.id}",
                f"nome com {largura} colunas; o máximo é {MAX_NOME_ITEM} (linha do baú: "
                f"\"Você achou \" + nome + \".\" em {COLUNAS_BAU} colunas; buffer do nome: "
                f"linha de cima em ${BUFFER_NOME_ITEM:X}, letras em ${BUFFER_NOME_ITEM_LETRAS:X}; "
                f"mapa-rom.md §6)"))
    return achados


def checar_largura(ctx: Contexto) -> list[Achado]:
    """Erro se uma linha do ``pt`` passa da largura da janela do diálogo.

    Largura = ``ctx.extra["janelas"][flag]["largura"]`` (tabela 0x1DD74, pelo flag do
    diálogo no esqueleto; no banco 3, a janela dos diálogos que chamam o script); sem
    janela conhecida, ``ctx.extra["largura_linha"]``. Sem nenhum dos dois, não checa.
    """
    achados = []
    for arquivo, e, jan, rel, _, col0 in _medicoes(ctx):
        if not jan.largura:
            continue
        for numero, largura in enumerate(rel.linhas, 1):
            if largura > jan.largura:
                extra = (f" (o trecho começa na coluna {col0}, onde o anterior parou)"
                         if numero == 1 and col0 else "")
                achados.append(Achado(
                    "erro", "largura", f"{arquivo}:{e.id}",
                    f"linha {numero} tem {largura} colunas e o limite é {jan.largura}{extra}"))
    return achados


def checar_linhas(ctx: Contexto) -> list[Achado]:
    """Erro se uma página (texto entre duas esperas) tem mais linhas que a janela mostra.

    A janela rola (0x16C6) quando o texto passa da altura e as primeiras linhas somem antes
    de o jogador apertar o botão. Altura = ``janelas[flag]["altura"]`` (ou
    ``ctx.extra["linhas_por_caixa"]``); o subop 0B 32 muda a altura no meio do script.
    Onde o próprio ``en`` já passa da altura, o limite da entrada é a maior página do ``en``.
    """
    achados = []
    for arquivo, e, jan, rel, rel_en, _ in _medicoes(ctx):
        # o original rola em alguns lugares (menu SIM/NÃO numa página cheia em
        # dialogo.080.t02; notas da ocarina em b3.002): ali o limite é o do próprio en
        tolerado = max((n for n, _ in rel_en.paginas), default=0)
        for numero, (linhas, altura) in enumerate(rel.paginas, 1):
            if altura and linhas > max(altura, tolerado):
                achados.append(Achado(
                    "erro", "linhas", f"{arquivo}:{e.id}",
                    f"página {numero} tem {linhas} linhas entre esperas e a janela mostra "
                    f"{altura}: as primeiras rolam antes de o jogador ler"))
    return achados


def checar_nomes_menu(ctx: Contexto) -> list[Achado]:
    """Largura do nome de item em cada tela do menu (``ferramentas/nomes_menu.py``)."""
    from .nomes_menu import checar_nomes_menu as _checar

    return _checar(ctx)


CHECAGENS_PADRAO: list[Checagem] = [checar_caracteres, checar_controles, checar_glossario,
                                    checar_espaco, checar_inline, checar_nomes_itens,
                                    checar_nomes_menu, checar_largura, checar_linhas,
                                    checar_glifos, checar_hud]


def rodar(ctx: Contexto, checagens: list[Checagem]) -> list[Achado]:
    achados: list[Achado] = []
    for checagem in checagens:
        achados.extend(checagem(ctx))
    return achados


def tem_erros(achados: list[Achado]) -> bool:
    return any(a.nivel == "erro" for a in achados)


def formatar(achados: list[Achado]) -> str:
    linhas = [f"{a.nivel.upper()} [{a.checagem}] {a.local}: {a.mensagem}" for a in achados]
    erros = sum(a.nivel == "erro" for a in achados)
    avisos = sum(a.nivel == "aviso" for a in achados)
    linhas.append(f"{erros} erro(s), {avisos} aviso(s)")
    return "\n".join(linhas) + "\n"
