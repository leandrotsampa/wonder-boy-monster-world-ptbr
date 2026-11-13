"""Compressão de gráficos do Wonder Boy in Monster World (tipo 02).

Os gráficos ficam em blocos de 32 tiles (1 KB) listados na tabela
``0x41000`` (768 entradas de 32 bits, ``0x41000–0x41BFF``: byte de tipo + ponteiro de
24 bits; o primeiro blob, bloco 0, começa logo depois, em ``0x41C00``).
A rotina ``0x6BC4`` do 68000 expande um bloco num buffer da RAM; o tipo são
bits testados nesta ordem (ver ``ler_entrada``):

- bit 31: bloco vazio (zeros);
- bit 24 (``01``): 1 KB sem compressão (endereço par: lido com ``move.l``);
- bit 25 (``02``): **árvore de Huffman + LZ** (``0x6D9C``), usado em 695 blocos,
  inclusive a fonte. É o formato implementado neste módulo;
- nenhum (``00``): formato por tile (``0x6BFC``), raro (11 blocos), não tratado aqui.

Formato tipo 02 (fluxo de bits, MSB primeiro, sem cabeçalho de tamanho; a
saída tem sempre 1024 bytes):

1. Árvore em pré-ordem: ``1`` = nó interno (filho esquerdo, depois direito),
   ``0`` = folha seguida do símbolo — ``0`` + 8 bits (0x00–0xFF) ou
   ``1`` + 5 bits (0x100 + v, 0x100–0x11F). O primeiro bit é sempre ``1``
   (a raiz, que o 68000 já tem alocada e ignora).
2. Símbolos, decodificados pela árvore (bit ``0`` = esquerda, ``1`` = direita):
   - ``< 0x100``: byte literal;
   - ``0x100–0x11E``: cópia de ``símbolo - 0xFD`` bytes (3–33); o símbolo
     seguinte é a distância ``d`` e a cópia começa em ``posição - 1 - d``
     (byte a byte, pode sobrepor);
   - ``0x11F``: escape — o valor vem cru, como numa folha da árvore.
"""

from __future__ import annotations

import heapq

TABELA_GRAFICOS = 0x41000
TOTAL_BLOCOS = 768
TAMANHO_BLOCO = 0x400
#: blocos que formam a fonte (tiles 0x00–0xFF, slot n → VRAM n × 0x400);
#: o bloco 4 (kana 0x80–0x9F) é trocado em jogo pelo 0x235 (HUD).
BLOCOS_FONTE = (0, 1, 2, 3, 5, 6, 7)
#: bloco 2 da fonte: tiles 0x40–0x5F (``@``, ``A``–``Z``…).
END_FONTE = 0x41DEB

ESCAPE = 0x11F
_MIN_COPIA, _MAX_COPIA = 3, 0x11E - 0xFD   # 3..33
_MAX_DIST = 0x11E                          # distância codificada sem escape

#: Tipos efetivos de uma entrada, na ordem em que ``0x6BC4`` testa os bits.
TIPO_00, TIPO_CRU, TIPO_HUFFMAN, TIPO_VAZIO = 0x00, 0x01, 0x02, 0x80

#: Máximo de folhas na árvore de Huffman. O 68000 monta os nós em
#: ``$FF8F0A`` + 4 × k; com N folhas a árvore ocupa ``$FF8F0A–$FF8F0A+4(N−1)``.
#: Os blocos 0–404 usam no máximo 59 folhas (até ``$FF8FF2``); os de cima chegam
#: a 61. O compressor fica nas 59 (abaixo do que os originais já escrevem):
#: símbolos raros saem pelo escape ``0x11F``.
MAX_FOLHAS = 59


class ErroCompressao(Exception):
    pass


def _endereco_entrada(bloco: int) -> int:
    if not 0 <= bloco < TOTAL_BLOCOS:
        raise ErroCompressao(f"bloco {bloco} fora da tabela (0–{TOTAL_BLOCOS - 1})")
    return TABELA_GRAFICOS + 4 * bloco


def ler_entrada(rom: bytes, bloco: int) -> tuple[int, int]:
    """Devolve (tipo efetivo, endereço) da entrada ``bloco`` da tabela ``0x41000``.

    A entrada é um longword BE em ``0x41000 + 4·bloco``. ``0x6BC4`` testa os
    bits nesta ordem: 31 → ``TIPO_VAZIO``; 24 → ``TIPO_CRU``; 25 →
    ``TIPO_HUFFMAN``; nenhum → ``TIPO_00``. Os bits 26–30 sobram no ponteiro e
    só são inofensivos por causa do barramento de 24 bits.
    """
    entrada = int.from_bytes(rom[_endereco_entrada(bloco):_endereco_entrada(bloco) + 4], "big")
    if entrada & (1 << 31):
        tipo = TIPO_VAZIO
    elif entrada & (1 << 24):
        tipo = TIPO_CRU
    elif entrada & (1 << 25):
        tipo = TIPO_HUFFMAN
    else:
        tipo = TIPO_00
    return tipo, entrada & 0xFFFFFF


def escrever_entrada(rom: bytearray, bloco: int, tipo: int, endereco: int) -> None:
    """Grava a entrada ``bloco`` (byte de tipo canônico + ponteiro de 24 bits).

    ``TIPO_CRU`` é copiado com ``move.l`` (``0x6BEC``): endereço ímpar daria
    *address error* no 68000, então é recusado. Os tipos 02 e 00 leem bytes e
    aceitam endereço ímpar.
    """
    if tipo not in (TIPO_00, TIPO_CRU, TIPO_HUFFMAN, TIPO_VAZIO):
        raise ErroCompressao(f"tipo {tipo:#x} inválido")
    if not 0 <= endereco <= 0xFFFFFF:
        raise ErroCompressao(f"endereço {endereco:#x} não cabe em 24 bits")
    if tipo == TIPO_CRU and endereco & 1:
        raise ErroCompressao(f"bloco cru em endereço ímpar ({endereco:#x}): o 68000 lê com move.l")
    pos = _endereco_entrada(bloco)
    rom[pos:pos + 4] = ((tipo << 24) | endereco).to_bytes(4, "big")


class _LeitorBits:
    def __init__(self, dados: bytes, inicio: int) -> None:
        self.dados, self.pos = dados, inicio
        self.atual, self.restam = 0, 0

    def _byte(self) -> int:
        if self.pos >= len(self.dados):
            raise ErroCompressao(f"fluxo comprimido termina antes do fim (em {self.pos:#x})")
        b = self.dados[self.pos]
        self.pos += 1
        return b

    def bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            if not self.restam:
                self.atual, self.restam = self._byte(), 8
            self.restam -= 1
            v = (v << 1) | ((self.atual >> self.restam) & 1)
        return v

    def valor(self) -> int:
        """Símbolo cru (folha da árvore ou escape)."""
        return 0x100 | self.bits(5) if self.bits(1) else self.bits(8)


def descomprimir(rom: bytes, end: int) -> tuple[bytes, int]:
    """Expande o bloco tipo 02 em ``end``; devolve (1024 bytes, bytes consumidos)."""
    if end < 0:
        raise ErroCompressao(f"endereço negativo: {end}")
    leitor = _LeitorBits(rom, end)
    if not leitor.bits(1):
        raise ErroCompressao(f"{end:#x}: a árvore deve começar por um nó interno")

    def ler_no():
        # pilha explícita: árvores degeneradas podem ter centenas de níveis
        raiz: list = [None, None]
        pilha = [(raiz, 0)]
        while pilha:
            no, lado = pilha.pop()
            if lado == 0:
                pilha.append((no, 1))
            if leitor.bits(1):
                filho: list = [None, None]
                no[lado] = filho
                pilha.append((filho, 0))
            else:
                no[lado] = leitor.valor()
        return raiz

    arvore = ler_no()

    def simbolo() -> int:
        no = arvore
        while True:
            no = no[leitor.bits(1)]
            if not isinstance(no, list):
                return leitor.valor() if no == ESCAPE else no

    saida = bytearray()
    while len(saida) < TAMANHO_BLOCO:
        s = simbolo()
        if s < 0x100:
            saida.append(s)
            continue
        tamanho = s - 0xFD
        origem = len(saida) - 1 - simbolo()
        if origem < 0:
            raise ErroCompressao(f"{end:#x}: cópia antes do início do bloco")
        for i in range(tamanho):
            saida.append(saida[origem + i])
    # o 68000 escreve além de 1 KB se a última cópia passar; só 1 KB vai ao VDP
    return bytes(saida[:TAMANHO_BLOCO]), leitor.pos - end


# --- compressor ---------------------------------------------------------

def _tokens(dados: bytes) -> list[tuple[int, ...]]:
    """LZ guloso com um passo de antecipação: (literal,) ou (tamanho, distância)."""
    n = len(dados)

    def melhor(pos: int) -> tuple[int, int]:
        mt, md = 0, 0
        limite = min(_MAX_COPIA, n - pos)
        for origem in range(pos - 1, max(-1, pos - 2 - _MAX_DIST), -1):
            t = 0
            while t < limite and dados[origem + t] == dados[pos + t]:
                t += 1
            if t > mt:
                mt, md = t, pos - 1 - origem
                if t == limite:
                    break
        return mt, md

    tokens: list[tuple[int, ...]] = []
    pos = 0
    while pos < n:
        t, d = melhor(pos)
        if t >= _MIN_COPIA and pos + 1 < n and melhor(pos + 1)[0] > t:
            t = 0  # adiar: o próximo byte abre uma cópia maior
        if t >= _MIN_COPIA:
            tokens.append((t, d))
            pos += t
        else:
            tokens.append((dados[pos],))
            pos += 1
    return tokens


def _codigos(freq: dict[int, int]) -> tuple[object, dict[int, str]]:
    """Árvore de Huffman determinística (empates pela ordem de criação)."""
    simbolos = sorted(freq)
    if len(simbolos) == 1:  # a raiz precisa de dois filhos
        extra = 0 if simbolos[0] != 0 else 1
        freq = {**freq, extra: 0}
        simbolos = sorted(freq)
    heap = [(freq[s], i, s) for i, s in enumerate(simbolos)]
    heapq.heapify(heap)
    seq = len(heap)
    while len(heap) > 1:
        f1, _, a = heapq.heappop(heap)
        f2, _, b = heapq.heappop(heap)
        heapq.heappush(heap, (f1 + f2, seq, (a, b)))
        seq += 1
    arvore = heap[0][2]
    codigos: dict[int, str] = {}
    pilha = [(arvore, "")]
    while pilha:
        no, prefixo = pilha.pop()
        if isinstance(no, tuple):
            pilha.append((no[1], prefixo + "1"))
            pilha.append((no[0], prefixo + "0"))
        else:
            codigos[no] = prefixo
    return arvore, codigos


def _bits_valor(v: int) -> str:
    return f"1{v - 0x100:05b}" if v >= 0x100 else f"0{v:08b}"


def comprimir(dados: bytes, max_folhas: int = MAX_FOLHAS) -> bytes:
    """Comprime 1024 bytes no formato tipo 02 (determinístico).

    A árvore terá no máximo ``max_folhas`` folhas (2–``MAX_FOLHAS``); os
    símbolos menos frequentes passam a sair pelo escape ``0x11F``.
    """
    if len(dados) != TAMANHO_BLOCO:
        raise ValueError(f"o bloco deve ter {TAMANHO_BLOCO} (1024) bytes, não {len(dados)}")
    if not 2 <= max_folhas <= MAX_FOLHAS:
        raise ErroCompressao(f"max_folhas deve ficar entre 2 e {MAX_FOLHAS}, não {max_folhas}")
    tokens = _tokens(bytes(dados))
    simbolos: list[int] = []
    for tok in tokens:
        if len(tok) == 1:
            simbolos.append(tok[0])
        else:
            simbolos += [tok[0] + 0xFD, tok[1]]
    freq: dict[int, int] = {}
    for s in simbolos:
        freq[s] = freq.get(s, 0) + 1
    escapados: set[int] = set()
    if len(freq) > max_folhas:
        ordem = sorted(freq, key=lambda s: (-freq[s], s))
        escapados = set(ordem[max_folhas - 1:])
        freq = {s: freq[s] for s in ordem[:max_folhas - 1]}
        freq[ESCAPE] = sum(1 for s in simbolos if s in escapados)
    arvore, codigos = _codigos(freq)
    if len(codigos) > max_folhas:  # defensivo: _codigos acrescenta no máximo 1 folha
        raise ErroCompressao(f"árvore com {len(codigos)} folhas (máximo {max_folhas})")

    partes = ["1"]  # raiz (sempre interna: há ao menos dois símbolos)
    pilha = [arvore[1], arvore[0]]
    while pilha:
        no = pilha.pop()
        if isinstance(no, tuple):
            partes.append("1")
            pilha.append(no[1])
            pilha.append(no[0])
        else:
            partes.append("0" + _bits_valor(no))
    for s in simbolos:
        partes.append(codigos[ESCAPE] + _bits_valor(s) if s in escapados else codigos[s])
    bits = "".join(partes)
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")
