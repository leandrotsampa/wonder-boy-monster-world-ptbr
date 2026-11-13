"""Opcodes da linguagem de script (interpretador em 0x14F4, ver docs/tecnico/mapa-rom.md §5).

Cada opcode/subop é descrito por uma cadeia de tipos de argumento, lidos em ordem:

- ``B``: 1 byte;
- ``R``: salto relativo de 16 bits (BE, com sinal); alvo = endereço do 1º byte do
  word + word (mesma semântica do op ``06``, rotina ``0x168C``);
- ``S``: índice (1 byte) de string; o banco vem do opcode (``op & 3``);
- ``W``: word cru (2 bytes, BE).

Bytes ``0x10–0xFD`` são caracteres de 1 byte; ``FE``/``FF`` + 1 byte formam um
caractere de 2 bytes.

Os subops de ``0B`` estão em ``SUBOPS_0B`` com o endereço do handler (tabela de
offsets em ``0x15C8``). As leituras de ``(a2)+`` foram contadas no código de cada
handler e das sub-rotinas que ele chama. Desvio para ``0x168C`` = salto tomado;
``addq #2,a2`` = não tomado; ``0x1568`` = insere string de banco (dinâmica, sem
alvo estático); ``0x1596`` = cede a vez (o fluxo continua no próximo quadro).
"""

from __future__ import annotations

CHAR_MIN = 0x10
PREFIXOS_CHAR = {0xFE, 0xFF}

OPS: dict[int, str] = {
    0x00: "",   # fim / retorno de string inserida (0x162E)
    0x01: "B",  # atributo/cor (0x164A)
    0x02: "",   # nova linha (0x1656)
    0x03: "B",  # velocidade/espera (0x165E)
    0x04: "B",  # avança N colunas (0x166C)
    0x05: "",   # espera botão, cede a vez (0x1678)
    0x06: "R",  # salto relativo incondicional (0x168C)
    0x07: "",   # liga flag de janela (0x169A)
    0x08: "",   # desliga flag de janela (0x16A4)
    0x09: "",   # nova linha com recuo (0x16AE)
    0x0A: "B",  # define recuo (0x16BE)
    0x0B: "",   # operação estendida: subop em SUBOPS_0B (0x15B8)
    0x0C: "S",  # string do banco 0 (0x1566)
    0x0D: "S",  # string do banco 1
    0x0E: "S",  # string do banco 2
    0x0F: "S",  # string do banco 3
}

# Quantidade de entradas da tabela de saltos do subop 24: o índice é o número de
# acertos no quiz ($8CD3, zerado em 0x1B42 e incrementado a cada acerto em
# 0x1D26). O quiz tem 5 perguntas, então 0–5 acertos = 6 entradas (confirmado no
# único uso, em 0x201FA: os 6 words apontam para os 6 desfechos do quiz).
N_QUIZ = 6

SUBOPS_0B: dict[int, str] = {
    0x00: "",       # 17C4: rts sem salvar a2 (encerra o fluxo; não usado nos scripts)
    0x01: "B",      # 17C6: insere string do banco (byte & 3), índice em $8CAF -> 1568
    0x02: "BBR",    # 17D0: menu de 2 opções ($8CAC/$8CAD = colunas do cursor), salva a2
                    #       e cede a vez (1798); a escolha é resolvida em 0x1484, que
                    #       lê o word: 2ª opção ($8CA5 bit 1) -> salto, 1ª -> segue
    0x03: "R",      # 17F6: ouro ($962C) < $8CB2 -> salto
    0x04: "B",      # 1808: $8CB2 = valor(byte) via 1D92
    0x05: "",       # 1820: insere $8CB2 em decimal (string em RAM, 183E)
    0x06: "",       # 1864: insere string do banco 1, índice em $8CAE -> 1568
    0x07: "",       # 187E: ouro -= $8CB2
    0x08: "B",      # 1894: dá item (byte) via 245A
    0x09: "",       # 18B2
    0x0A: "B",      # 18BE: $8CAE = byte
    0x0B: "",       # 18C6: jsr 1C494
    0x0C: "",       # 18D0
    0x0D: "",       # 18DA
    0x0E: "B",      # 18E4: $965E = byte
    0x0F: "B",      # 18EC: $8CB2 = tabela de preços[byte]
    0x10: "",       # 1946: zera ouro
    0x11: "BR",     # 194E: flag de evento (byte) ligada -> salto
    0x12: "BR",     # 1962: teste via 274C -> salto
    0x13: "B",      # 1972: liga flag de evento (byte)
    0x14: "B",      # 1980: via 2752
    0x15: "",       # 198A: jsr 1C330
    0x16: "B",      # 1998: $8CC3 = byte
    0x17: "BR",     # 19A0: tem o item (byte) (23E4) -> salto
    0x18: "B",      # 19BA: espera (203A) e cede a vez
    0x19: "B",      # 19C8: som/efeito (jsr 366)
    0x1A: "BRR",    # 19D2: sequência de botões (2AAE): d0<0 -> 1º salto,
                    #       d0=0 -> 2º salto, d0>0 -> segue
    0x1B: "BB",     # 1A08: $8CC4/$8CC5 = bytes
    0x1C: "",       # 1A14: insere string ($8CC4 banco, $8CC5 índice) -> 1568
    0x1D: "",       # 1A20: jsr F906
    0x1E: "BB",     # 1A2E: posição do cursor (coluna, linha)
    0x1F: "B",      # 1A40: insere string do banco 0, índice em $8CC6[byte] -> 1568
    0x20: "",       # 1A50: limpa a janela
    0x21: "",       # 1A80: quiz: espera resposta e cede a vez
    0x22: "",       # 1A90: quiz: sorteia respostas
    0x23: "",       # 1B04: quiz: inicializa
    0x24: "R" * N_QUIZ,  # 1B66: tabela de saltos indexada por $8CD3 (acertos);
                    #       sempre salta (encerra o fluxo)
    0x25: "WW",     # 1B7E: $8CB2 = long (4 bytes) e rts sem salvar a2 (encerra o
                    #       fluxo; não usado nos scripts)
    0x26: "",       # 1B92: ouro += $8CB2
    0x27: "RRRRR",  # 1B9E: tabela de 5 saltos indexada pela contagem (0–4) de
                    #       itens 7/15/23/31 (23E4); sempre salta (encerra o fluxo)
    0x28: "",       # 1BCE: cede a vez
    0x29: "",       # 1C10: via 24DC
    0x2A: "BR",     # 1C22: byte <= $959C -> salto
    0x2B: "R",      # 1C32: $9F00 >= $0E00 -> salto
    0x2C: "R",      # 1C3E: $95BE–$95C2 todos = 0x0C -> salto
    0x2D: "R",      # 1C62: vida atual >= máxima ($9F00) -> salto
    0x2E: "R",      # 1C70: bsr 8E9C e segue (8E9C sobrescreve a2: não usado nos scripts)
    0x2F: "R",      # 1C76: $9F32 >= 0 -> salto
    0x30: "",       # 1C80: +1 coração
    0x31: "",       # 1CA6: jsr 76C4
    0x32: "B",      # 1CB0: $8CA0 = byte (altura da janela)
}

FIM = {0x00}
SALTO_INCONDICIONAL = {0x06}
# Subops após os quais o fluxo não continua no byte seguinte.
SUBOPS_FIM = {0x00, 0x24, 0x25, 0x27}
