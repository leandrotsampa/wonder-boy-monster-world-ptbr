# Mapa técnico da ROM — Wonder Boy in Monster World (UE) [!]

Reconhecimento feito em 2026-11-11. Endereços são offsets na ROM (= endereço 68000, a ROM começa em 0).
Ferramentas: scripts Python ad hoc + disassembler capstone (m68k).

## 1. ROMs

| ROM | Tamanho | SHA-1 | Observação |
|---|---|---|---|
| Base (UE) [!] | 786.432 (768 KB) | `87a968f773c7e807e647c0737132457b06b78276` | checksum do cabeçalho `9D79` correto; fim da ROM `0BFFFF` |

Cabeçalho da base: serial `GM G-4060  -00`, região `UE`, SRAM declarada (`RA` em 0x1B0).

## 2. Tabela global de recursos — `0x1CC00`

Vetor de ponteiros de 32 bits lido pelo código (`movea.l $1CCxx.l, aN`). **Trocar um ponteiro aqui realoca o recurso sem patch de código**.

| Endereço | Aponta para | Uso conhecido |
|---|---|---|
| `0x1CC10` | `0x211CA` | **tabela mestra de bancos de strings** (§4) |
| `0x1CC14` | `0x1DD94` | **tabela de diálogos** (§3). Projeto → `0xA4C80` |
| `0x1CC18` | `0x1DD74` | janelas de diálogo, 8 registros × 4 bytes (`x`, `y`, largura, altura), indexados pelo byte `flag` do diálogo (§5, "Largura de linha") |
| demais (`0x1CC00`…`0x1CC68`) | 0x22460…0x3E9F8 | não textuais (a investigar só se necessário) |

## 3. Diálogos — tabela em `0x1DD94`

- 131 registros de 3 bytes: `flag(1)` + `offset(2, BE, com sinal)`, **relativo ao início da tabela**.
- Código: `0x276C` (`lea (a1,d1.w),a0`). Por ser word com sinal, os alvos ficam a ±32 KB da tabela.
- Primeiro alvo `0x1DF1D` (logo após a tabela). Região de scripts de diálogo: `0x1DF1D–0x211C9`.
- `flag` (0–7) → índice na tabela `0x1DD74` (janela: posição, largura e altura; `0x276C`/`0x27B0`).

## 4. Bancos de strings — tabela mestra em `0x211CA`

4 ponteiros de 32 bits. Cada banco é uma tabela de **offsets de 16 bits com sinal relativos à base do banco**.

| Banco | Base | Entradas | Conteúdo | Opcode |
|---|---|---|---|---|
| 0 | `0x211DA` | 232 (`0x00–0xE7`) | `0x00–0x3E`: strings de sistema (SIM/NÃO, GOLD, quiz…); **`0x3F–0xE7`: dicionário de 169 palavras** (em `0x21FFE–0x2245F`) | `0C xx` |
| 1 | `0x21720` | 65 | nomes de itens/equipamentos | `0D xx` |
| 2 | `0x21A06` | 43 | nomes próprios/lugares (Shion, Alsedo, Maugham Desert…) | `0E xx` |
| 3 | `0x21FCA` | 16 slots (9 usados; offsets negativos) | scripts de loja, estalagem, ocarina | `0F xx` |

- Leitura: `0x1566` (inserção inline, empilha o ponteiro e retorna ao fim da string) e `0x1ED0`.
- O banco é escolhido por `opcode & 3`.
- Contagem: entradas = menor offset positivo / 2. Há slots com offset 0 (não usados).

**Dicionário = compressão.** Palavras frequentes viram `0C xx`. O texto PT-BR **não deve reutilizar o dicionário inglês**. Opções para o Plano 2: (a) esvaziar o uso e escrever tudo por extenso (há espaço de sobra, ver §7); (b) gerar um dicionário PT-BR automaticamente no build.

## 5. Linguagem de script (interpretador em `0x14F4`)

Bytes `≥ 0x10` são caracteres. `FE`/`FF` + char = caractere com marca no tile de cima (mecanismo de dakuten herdado do japonês: tile superior `0xBE`/`0xBF`; normalmente o tile superior é `0x20`, espaço). **Cada caractere ocupa 2 linhas de tiles 8×8.**

| Op | Args | Significado (provável) |
|---|---|---|
| `00` | — | fim / retorno de string inserida |
| `01` | 1 | atributo/cor (`01 A0` destaca, `01 80` volta ao normal) |
| `02` | — | nova linha na coluna 0 (`0x16C6`) |
| `03` | 1 | velocidade/espera |
| `04` | 1 | avança N colunas (sem checar a borda) |
| `05` | — | espera botão (não limpa nem quebra a linha) |
| `06` | 2 | **salto relativo** incondicional: alvo = endereço do 1º byte do argumento + word com sinal |
| `07`/`08` | — | liga/desliga flag de janela |
| `09` | — | nova linha na coluna do recuo (`$8CAB`) |
| `0A` | 1 | define o recuo (`$8CAB`, nunca zerado) |
| `0B` | 1 + … | operação estendida; 51 subops (`0x00–0x32`, tabela em `0x15C8`) |
| `0C–0F` | 1 | insere a string `xx` do banco `op & 3` |

Execução: `0x14EC` carrega `a2` do slot da pilha de ponteiros (`$8CA8` → `$8C7A+n`); `0x1596` salva `a2` e retorna (cede a vez; o fluxo continua no quadro seguinte); `0x1566/0x1568` insere uma string de banco (empilha `a2`, o `00` da string desempilha em `0x162E`); `0x168C` é o salto relativo.

**Correção do original no esqueleto.** O menu SIM/NÃO (`0B 02 col_sim col_nao`) leva as colunas da seta. Na troca de Pedras Encantadas (`dialogo.080`, `0x1F8CA` e `0x1F9CB` na base) o original usava `03 07`, e a seta do NÃO ficava colada no "SIM" ("YES▶ NO"); as outras perguntas usam `03 08`. O esqueleto versionado (`dados/scripts/esqueleto.json`) traz `03 08` nessas duas; `test_esqueleto_versionado_atual` aceita só essas diferenças em relação à base (`CORRECOES_ESQUELETO`). Um `extrair` regera o esqueleto da ROM e desfaz a correção (o teste acusa).

#### Subops de `0B` (tabela de offsets em `0x15C8`)

Fonte de verdade: `ferramentas/script/opcodes.py` (`SUBOPS_0B`). Tipos: `B` byte, `R` salto rel16 (alvo = endereço do word + word, como o `06`), `W` word cru. Lido com o capstone contando as leituras de `(a2)+` em cada handler e nas sub-rotinas chamadas; desvio para `0x168C` = salto tomado, `addq #2,a2` = não tomado. "Usos" = ocorrências alcançadas a partir das raízes na ROM base.

| Sub | Handler | Args | Efeito (provável) | Usos |
|---|---|---|---|---|
| `00` | `17C4` | — | `rts` sem salvar `a2`: **encerra o fluxo** | 0 |
| `01` | `17C6` | B | insere string do banco `byte&3`, índice em `$8CAF` | 0 |
| `02` | `17D0` | B B R | menu de 2 opções (colunas do cursor), cede a vez; resolvido em `0x1484`: 2ª opção → salto | 7 |
| `03` | `17F6` | R | ouro < `$8CB2` → salto | 2 |
| `04` | `1808` | B | `$8CB2` = valor(byte) (`0x1D92`) | 1 |
| `05` | `1820` | — | insere `$8CB2` em decimal (string em RAM) | 2 |
| `06` | `1864` | — | insere nome do banco 1, índice em `$8CAE` | 1 |
| `07` | `187E` | — | ouro −= `$8CB2` | 2 |
| `08` | `1894` | B | dá item (`0x245A`) | 12 |
| `09` | `18B2` | — | | 3 |
| `0A` | `18BE` | B | `$8CAE` = byte | 52 |
| `0B` | `18C6` | — | `jsr 1C494` | 1 |
| `0C`/`0D` | `18D0`/`18DA` | — | liga bits de `$9BF3` | 1/1 |
| `0E` | `18E4` | B | `$965E` = byte | 5 |
| `0F` | `18EC` | B | `$8CB2` = preço[byte] (tabela `0x1906`) | 1 |
| `10` | `1946` | — | zera ouro | 1 |
| `11` | `194E` | B R | flag de evento ligada → salto | 27 |
| `12` | `1962` | B R | teste `0x274C` → salto | 35 |
| `13` | `1972` | B | liga flag de evento | 5 |
| `14` | `1980` | B | `0x2752` | 23 |
| `15` | `198A` | — | `jsr 1C330` | 2 |
| `16` | `1998` | B | `$8CC3` = byte | 0 |
| `17` | `19A0` | B R | tem o item (`0x23E4`) → salto | 13 |
| `18` | `19BA` | B | espera (`0x203A`) e cede a vez | 14 |
| `19` | `19C8` | B | som/efeito (`jsr 366`) | 10 |
| `1A` | `19D2` | B R R | sequência de botões (`0x2AAE`): d0<0 → 1º alvo, d0=0 → 2º alvo, d0>0 → segue | 1 |
| `1B` | `1A08` | B B | `$8CC4`/`$8CC5` = bytes | 3 |
| `1C` | `1A14` | — | insere string (banco `$8CC4`, índice `$8CC5`) | 1 |
| `1D` | `1A20` | — | `jsr F906` | 5 |
| `1E` | `1A2E` | B B | posição do cursor (coluna, linha) | 1 |
| `1F` | `1A40` | B | insere palavra do banco 0, índice em `$8CC6[byte]` | 4 |
| `20` | `1A50` | — | limpa a janela | 10 |
| `21` | `1A80` | — | quiz: espera resposta, cede a vez | 1 |
| `22` | `1A90` | — | quiz: sorteia respostas | 1 |
| `23` | `1B04` | — | quiz: inicializa (zera acertos `$8CD3`) | 1 |
| `24` | `1B66` | R×6 | tabela de saltos indexada por `$8CD3` (acertos 0–5 nas 5 perguntas); **sempre salta** | 1 |
| `25` | `1B7E` | W W | `$8CB2` = long e `rts` sem salvar `a2`: **encerra o fluxo** | 0 |
| `26` | `1B92` | — | ouro += `$8CB2` | 0 |
| `27` | `1B9E` | R×5 | tabela de saltos indexada pela contagem (0–4) de itens 7/15/23/31; **sempre salta** | 1 |
| `28` | `1BCE` | — | cede a vez | 1 |
| `29` | `1C10` | — | `0x24DC` | 8 |
| `2A` | `1C22` | B R | byte ≤ `$959C` → salto | 3 |
| `2B` | `1C32` | R | `$9F00` ≥ `0x0E00` → salto | 1 |
| `2C` | `1C3E` | R | `$95BE–$95C2` todos `0x0C` → salto | 1 |
| `2D` | `1C62` | R | vida atual ≥ máxima → salto | 0 |
| `2E` | `1C70` | R | `bsr 8E9C` (sobrescreve `a2`) e segue | 0 |
| `2F` | `1C76` | R | `$9F32` ≥ 0 → salto | 4 |
| `30` | `1C80` | — | +1 coração | 1 |
| `31` | `1CA6` | — | `jsr 76C4` | 1 |
| `32` | `1CB0` | B | `$8CA0` = byte (altura da janela) | 2 |

Encerram o fluxo: op `00`, op `06` e os subops `00`, `24`, `25`, `27`. Os tipos de `00`, `25`, `2D`, `2E` (e `01`, `16`, `26`) vêm só do código, sem uso nos scripts para confirmar.

**Cobertura** (`testes/test_desmontador.py::test_cobertura_rom`): a partir das 131 entradas de diálogo + as entradas não nulas dos 4 bancos (468 raízes, 440 distintas), o desmontador decodifica 14.588 instruções (16.996 bytes) em `0x1DF1D–0x22460` sem sobreposição, e todo alvo de salto é início de instrução. Fora as tabelas de offsets dos bancos, sobram só 7 bytes, listados em `config/texto.yaml: lacunas_conhecidas`: 5 de código morto em `0x1E54D` (`0B 11 1E 00 36`, depois de um `00`, sem referência) e 2 bytes `00` de alinhamento antes das tabelas dos bancos 2 e 3.

**Consequência:** mudar o tamanho de um texto desloca os saltos internos do script (na estalagem, por exemplo, `08 FE D6` vira `08 FE F3` com o texto mais longo). O build tem que **montar** os scripts a partir de uma representação com rótulos.

### Largura de linha e linhas por página (Plano 3, Tarefa 6)

Regras confirmadas no jogo. Antes (Plano 2, Tarefa 7) a largura era o máximo observado no texto (25) e várias regras eram suposições. Agora elas vêm do motor de texto (`0x14F4–0x172C`) e de capturas no emulador. Código: `ferramentas/verificacao.py` (`_Larguras`, `checar_largura`, `checar_linhas`). Testes: `testes/test_largura.py` (regras) e `testes/test_validacao_jogo.py` (jogo).

**Como foi validado.** `testes/test_validacao_jogo.py` monta ROMs com um `pt` de teste numa cópia do projeto (o `pt` de teste nunca vai para o repositório) e roda `roteiros/validacao.yaml`: NEW GAME → páginas do 1.º diálogo (`pagina_0…7`) → casa → menus. O texto de teste vai em `dialogo.000.t01`. Para outras janelas e para loja/estalagem, a entrada 0 da tabela de diálogos da ROM montada recebe o flag ou o script de outro diálogo, que então roda no NEW GAME. As asserções leem nos pixels em que colunas de cada linha da janela há texto. As capturas de referência ficam em `build/capturas/validacao/<caso>/` (fora do git; o teste as recria):

| Caso | Conteúdo |
|---|---|
| `largura` | `dialogo.000.t01` com 8 páginas de teste (janela 0) + menus de status e magias com strings inline em PT |
| `janela4`, `janela7` | o mesmo diálogo com o flag 4 (17×5) e 7 (26×1): 36 caracteres seguidos |
| `loja` | `dialogo.010` (Excalibur, `[s3:00]`) com `b3.000` e o menu SIM/NÃO em PT |
| `estalagem` | `dialogo.046` (`[s3:01]`), texto original |

**(a) Largura física = largura da janela.** O motor compara a coluna (`$8C9A`) com `$8C9E`, que vem do 3.º byte do registro da janela (`0x27CA`); a altura (`$8CA0`) vem do 4.º. A tabela `0x1DD74` está em `config/texto.yaml: janelas` (conferida com a ROM em `test_janelas_conferem_com_a_rom`):

| Flag | Largura × altura | Uso |
|---|---|---|
| 0 | 23 × 3 | 93 diálogos, lojas, estalagem |
| 1 | 23 × 2 | 20 diálogos |
| 2 | 21 × 3 | |
| 3 | 17 × 1 | |
| 4 | 17 × 5 | Esfinge (quiz) |
| 5 | 19 × 3 | |
| 6 | 23 × 3 | |
| 7 | 26 × 1 | `dialogo.106` e `.120`, as linhas de 25 do original |

Capturas: `largura/pagina_0.png` (21 letras da coluna 2 à 22, e 23 depois de `[quebra2]`), `janela4/pagina_0.png` e `janela7/pagina_0.png`. Texto sem janela conhecida usa `largura_linha: 23` e `linhas_por_caixa: 3` (= janela 0).

**(b) Linhas por caixa: a janela rola.** Não há corte nem caixa nova. Em `0x16C6`, uma nova linha com a janela cheia rola o conteúdo uma linha para cima. A janela mostra `altura` linhas (3 na janela 0). Captura `largura/pagina_6.png`: 4 linhas entre duas esperas, e a 1.ª ("A") já sumiu quando o jogo para. Regra `checar_linhas`:

- **página** = linhas com texto desde a última `[espera]` ou pausa de menu (subops `02` SIM/NÃO, `21`, `1A`); passar da altura da janela é erro;
- linhas em branco antes do texto não contam (rolam sem perder nada);
- um `[linha]` antes da `[espera]` conta (o cursor desce e a 1.ª linha rola);
- o menu SIM/NÃO (`[s0:00]` = `[quebra2][$04][$04]YES  NO`) ocupa uma linha (`estalagem/pagina_2.png`);
- o original rola em `dialogo.080.t02` (3 linhas + menu), nas notas da ocarina (`b3.002`) e no final (abaixo). Nessas entradas o limite é o do próprio `en`;
- a página fecha quando o fluxo do script chega a `00`, a uma pausa de menu, a um fim ou a `0B 20` (limpa) **por qualquer caminho**: saltos (`06`) e subops sem texto (ex.: `0B 18`, espera de tempo) entre o trecho e o fechamento não impedem a checagem. `_analisar_fluxo` leva em `_Estado.abertos` os trechos com a página aberta e, onde caminhos se juntam, a união deles; cada trecho é checado a partir do pior estado inicial (maior coluna e página). Antes só se olhava a instrução logo depois do trecho, e 11 trechos ficavam sem a última página checada: `b3.001.t07`, `b3.001.t08`, `b3.006.t05`, `dialogo.056.t03`, `dialogo.056.t04` e `dialogo.122.t00`–`dialogo.127.t00` (`test_fluxo_esqueleto_real_fecha_as_paginas_finais`).

**O final (`dialogo.122`–`.127`).** Cada um é `trecho` + `0B 18 48` (espera 72) + `00`, sem `[espera]`: o texto sai devagar (`[$03][$08]`/`[$06]`) e o jogo segue sozinho. No `en`, `.122` tem 3 linhas, `.123`, `.124` e `.126` têm 4, `.125` e `.127` têm 6. A janela é a mesma da tabela: flag 6, 23 × 3 (`x=4, y=10`, na metade de baixo da tela). Conferido no emulador com a entrada 0 da tabela de diálogos trocada pela do `dialogo.125` (como em (f)): durante a impressão `$8C9E` = 23 e `$8CA0` = 3, e a janela rola. As primeiras linhas somem enquanto as seguintes são impressas, e no fim só as 3 últimas ("passed on from / generation to / generation.") estão na tela. Não há outra janela nem altura maior: o original rola de propósito, devagar, para ser lido enquanto sai. A regra fica a mesma (página = linhas desde a última espera, limite = altura da janela) e vale a tolerância do `en`: no final o `pt` pode ter por página no máximo as linhas que o `en` tem (`.122`: 3; `.124`: 4; `.125`: 6).

**(c) `[espera]`, `[linha]` e `[quebra2]`.**

- `[espera]` (05) só espera o botão (`0x1678`): não limpa a janela nem quebra a linha. O texto seguinte continua no mesmo lugar (`largura/pagina_4.png` → `pagina_5.png`: "AB", botão, "CD" na mesma linha). Nos dados ela vem seguida de `[linha]`, que rola.
- `[linha]` (09) = nova linha na coluna do recuo (`$8CAB`, definido por `[$0A][$NN]`).
- `[quebra2]` (02) = nova linha na coluna 0 (`largura/pagina_0.png`, `pagina_7.png`).
- Nenhum dos dois abre caixa nova. Limpar a janela é o subop `0B 20` (zera coluna e linha).
- O recuo nunca é zerado pelo código e o único valor usado é 2, então a regra usa recuo 2 (`RECUO_PADRAO`).

**(d) Estouro: o jogo quebra no meio da palavra.** Um caractere na coluna >= largura vai para a coluna 0 da linha seguinte (`0x14FC`), sem lixo nem corte (`largura/pagina_1.png`: 22 caracteres depois do recuo, o último na linha de baixo). Para o checador, é erro (`checar_largura`).

**(e) Itens que estavam "a confirmar":**

1. **`[$04]` depois de texto** só avança colunas (`0x166C`), sem checar a borda (`largura/pagina_2.png`: `ABCDE[$04][$03]FGH`). Se o avanço leva o cursor à borda (>= largura), o próximo caractere quebra para a coluna 0. É o caso de `dialogo.002.t01`: `world` termina na coluna 23 e `[$04][$02]` empurra o resto para a linha seguinte (`largura/pagina_3.png`). Regra: `[$04]` soma NN e só quebra a linha se chegar à borda. A regra antiga ("depois de texto sempre quebra") estava errada.
2. **Banco 3 (`[s3:XX]`).** O script roda na janela do diálogo que o chama, com o mesmo cursor (`loja/`, `estalagem/`). Ao medir um diálogo, só o 1.º trecho do script entra. Depois dele a linha recomeça com página nova: na coluna 0 se o script termina limpando a janela (`0B 20` antes do `00`: `b3.006`, quiz), senão no recuo (`b3.007` termina em `[espera][linha]`). Os scripts do banco 3 são medidos inteiros como raízes próprias, na janela mais estreita dos diálogos que os chamam (todos na janela 0, exceto `b3.006`/`b3.008`, na 4).
3. **Medição por entrada a partir da coluna 0**: trocada pela análise do fluxo do script (`_analisar_fluxo`, com o esqueleto). Cada trecho começa no estado em que o fluxo o alcança (coluna onde o anterior parou, recuo, página em curso), seguindo saltos e desvios até o ponto fixo; onde caminhos se juntam vale o pior caso. As instruções entre trechos contam: `0B 05` (número), `0B 06`/`0B 01` (nome), `0B 1C` (string de `0B 1B`), `0B 1F` (string do quiz), `0B 20` (limpa), `0B 1E` (cursor), `0B 32` (altura), `0B 0A` (item). Sem esqueleto, cada entrada é medida sozinha a partir da coluna 0.
4. **Lacuna de valor no banco 0.** Número = **6 dígitos** (`DIGITOS_NUMERO`). `0B 05` imprime `$8CB2` em decimal sem zeros à esquerda (`0x183E`). Os valores vêm da tabela de preços `0x1DAE` (maior 500000) ou da diária da estalagem `0x1906` (maior 300) (`test_digitos_numero_cobre_as_tabelas_de_preco`). Capturas: `loja/pagina_2.png` (`Custa` + `[$04][$01]` + `2500` + ` GOLD.`) e `estalagem/pagina_1.png` (`[$04][$03]15 GOLD.`). Nome de item (`[cor]` antes da lacuna): o do item que o fluxo define com `0B 0A`, senão o maior nome do banco 1 (`loja/pagina_1.png`: Excalibur em amarelo).
5. **Largura física**: ver (a).

**(f) Loja e estalagem.** Alcançadas trocando a entrada 0 da tabela de diálogos, sem jogar até uma loja.

- `loja/pagina_0–4.png`: `b3.000` em PT com o nome do item (`[s0:02]`), o preço (`[s0:03]`) e o menu SIM/NÃO (`[s0:00]`; cursor na coluna 3; `NÃO` com o til).
- `estalagem/pagina_0–7.png`: diária (`[s0:05]`), SIM/NÃO, gravação do jogo e a sala da estalagem.

**(g) Strings inline.** `largura/menu_magia.png`: `FOGO`, `TREM`, `RAIO`, `FORÇA` (o Ç aparece com a cedilha do glifo `0xAC`), `ESCUDO` e `VOLTA`, sem lixo depois do texto. Antes eram slots fixos completados com espaço; desde o Plano 4 (Tarefa 3) as magias são o bloco repontável `menu.magias` (§6, "Menus e magias") e a cópia nova não tem espaços. `largura/menu_status.png`: `AT`/`DF`/`VL`. O `GOLD` de `0x84E7` era o rótulo do HUD, escrito com a fonte (§8, Plano 4); não há `GOLD` na tela de status. Créditos e ocarina foram vistos depois, fora das sessões de validação: os créditos numa cópia da ROM que pula para o final (`jmp $4F58` em `0x4CEC`), com os cargos centrados pelo tamanho da string (`0x1AF6A`: `(20 − tam) / 2`, `tam` contado até o `00` por `0x1B004`); a ocarina com os mini-scripts copiados para o diálogo 0.

**(h) Invariante da fonte.** O passo `checar_fonte` dos roteiros grava a RAM e falha se `$A144` (word em `$FFA144`) > 40 (o alocador chegaria ao slot 7; o 6 tem o rótulo MOEDAS do HUD) ou se os slots 5–7 não têm os blocos 5–7 (`vram_cenas.checar_invariante_fonte`; docs/tecnico/vram.md §3.1). Ele está em toda captura de `validacao.yaml` e nas cenas de jogo de `cenas.yaml` e `dialogo.yaml`. Valores vistos: 0 na casa, no campo e nos menus; 5 no toco; 6 dentro da estalagem.

**Arquivos checados**: `dialogos` e `banco3_lojas`. Entradas com `pt` vazio são ignoradas, e o `en` original passa nas duas checagens (`test_en_original_passa`). Não são checados (só servem de referência para as variáveis):

- `banco0_sistema`: strings curtas e o quiz. A janela 4 tem 17 colunas; a pergunta é impressa devagar numa área de 2 linhas que rola (`0B 32 02`), e as respostas começam na coluna 3;
- `banco1_itens`/`banco2_nomes`: nomes (o banco 1 tem checagem própria do tamanho do nome: no máximo 18 colunas, §6 "Limite do nome de item");
- `inline`: tamanho fixo, com checagem própria.

## 6. Strings fora das tabelas (inline no código)

| Endereço | Conteúdo | Observação |
|---|---|---|
| `0x1D72` / `0x1D7D` / `0x1D88` | `Time's up.` / `Incorrect.` / `Correct.` | tamanho fixo (completar com espaços) |
| `0x1FE6` / `0x1FFF` / `0x1FF1` / `0x1FF8` | `Found the ` / `.` / `Found ` / ` GOLD.` | mensagens do baú: **repontáveis** (abaixo) |
| `0x2B59–0x2C05` | ocarina ("Shion plays the…") | mini-scripts; 5 referências `move.l #$2B56/$2B8F/$2BA9/$2BC4/$2BE5` em `0xC4B0–0xC530`. Decisão: slots inline de tamanho fixo por trecho de texto (controles intocados); reapontar/realocar fica adiado |
| `0x7C0A…0x7C43` (tabela `0x7BFE`) | menu de magias (FIRE STORM, QUAKE…) | coluna, linha, texto; **bloco repontável** `menu.magias` (+ `menu.magias_hud`): "Menus e magias", abaixo |
| `0x7F4E` | `PAUSE` | START com `$9659` bit 2 ligado (o herói andando): `0x90EA` chama `0x7F0E`, que imprime a string (`lea $7F4E(pc)` em `0x7F1E`, `0x7870`) na janela, coluna 14, linha 8, em vez de abrir o menu. Achada na Task 10 do plano de lotes (estava fora da config); item `pausa`, tamanho fixo, "PAUSA" visto no jogo |
| `0x82B6…0x82F2` | `SELECT` `WEAPON` `ARMOR ` `SHIELD` `BOOTS ` `ITEM` `MAGIC` | cabeçalhos e opções do menu do START; **blocos** `menu.cabecalhos` e `menu.opcoes` (abaixo) |
| `0x84DE` | `AP` `DP` `SP` `GOLD` | `AP`/`DP`/`SP`: tela de status (um `lea $84DE(pc)` em `0x84C8`; o laço de `0x84CE` lê as 3 em sequência). `GOLD` (`0x84E7`) era o rótulo do HUD, sem leitor depois do patch `hud.moedas_chamada` (§8): saiu da config (`status.ouro`) |
| `0x1ABD2…0x1ACCD` (créditos `0x1ABD2–0x1AD5D`) | créditos (separador `9A`, fim `99`) | maiúsculas; fluxo de um só ponteiro (`lea $1ABD2` em `0x1AB10`), tamanho medido na hora (`0x1B004`): os cargos têm tamanho livre, até 20 colunas, desde que o bloco caiba (sequência `creditos` em `config/texto.yaml`) |

Endereços reais conferidos pelos `lea (pc)` do código e registrados em `config/texto.yaml` (`inline:`), um item por string, com `tam` = tamanho original sem o terminador `00`.

### Repontáveis (Plano 4, Tarefa 2)

`inline_repontavel` em `config/texto.yaml` (`ferramentas/repontavel.py`, etapa `etapa_repontavel`, logo depois de `etapa_inline`): o `pt` vai para a região livre do build (`RegiaoLivre`, depois do texto) com o terminador `00`, e cada instrução listada em `refs` passa a apontar para a cópia nova. O texto original fica intacto; com o `pt` vazio nada é gravado (ida e volta igual à base). Antes de gravar, cada referência é conferida na ROM (opcode e alvo = endereço do item); uma referência que sobrepõe um patch de `config/patches.yaml` é erro.

Tipos de referência (todos sem mudar o tamanho do código):

| Tipo | Original | Novo |
|---|---|---|
| `lea_pc` | `lea d16(pc),An` (4 bytes) | só o deslocamento; erro se a cópia ficar fora de ±32 KB |
| `lea_pc_bsr` | `lea d16(pc),An` + `bsr.w alvo` (8 bytes) | `lea abs.l,An` + `bsr.b alvo` (erro se o `bsr.b` não alcança) |
| `abs_l` | operando de 32 bits (`move.l #end`, `lea end.l`…) | o endereço novo |

O código das mensagens fica em `0x1F00–0x1F8A` e a área livre em `0xA4C80+`: o `lea (pc)` não alcança, por isso `lea_pc_bsr` (todas as chamadas são `lea` + `bsr.w $1F8E`, a rotina que escreve a string no buffer da linha `$8D12`).

`ajustes`: imediatos de 16 bits que dependem do tamanho dos textos, recalculados como `base + soma dos tamanhos` (o valor da base é conferido com os tamanhos originais) e com checagem de largura (`verificar` dá erro se a linha estourar).

**Mensagens do baú** (`0x1FCA` = baú de ouro, chamado de `0xF216`; `0x1FD0` = baú de item, chamado de `0xC2CA`). A linha tem 30 colunas entre as bordas (`$8D12`, 32 words; a de cima, em `+$40`, recebe as marcas `FE`/`FF`); o código centraliza com `(0x1C − (n + 6)) & ~1` (item, `n` = letras do nome, `$8CDE`) e `(0x1A − (d + 5)) & ~1` (ouro, `d` = dígitos) bytes a partir da borda, ou seja `(33 − L) & ~1` para a linha de `L` caracteres. Os imediatos `6` e `5` são os ajustes `bau.centro_item` (`0x1EFA`, base −5) e `bau.centro_ouro` (`0x1F5E`, base −7). Largura: nome do item até 18 letras (`"Você achou "` + 18 + `"."` = 30; o buffer, em `$AB00` desde os patches `buffer_nome.*`, guarda a linha de cima, com as marcas, e as letras em `+$20` = `$AB20`), valor até 6 dígitos (999999). **Cores:** `0x1F8E` escreve cada letra com o byte alto de `d0` (paleta) e a linha de cima com `d1`; o nome do item sai em amarelo (`move.w #$A000,d0` em `0x1F1C`) e o resto em branco (`$8020`). Pedido do autor: no baú de ouro o valor também em amarelo. Patches `bau.valor_amarelo_*`: a chamada do valor (`movea.l a1,a0; bsr.w $1F8E` em `0x1F7C`) vira `jsr $9F7C0.l`, rotina que escreve os dígitos com `$A020` e volta a `$8020` antes de `" MOEDAS."`. Vale para todo achado de ouro que passa por `0x1FCA`; as falas e a loja não passam por aqui (`test_baus_e_status_no_jogo` confere a paleta de cada coluna).

**Limite do nome de item: 18 colunas.** `0x1E6A` copia o nome do banco 1 (expandindo as strings aninhadas `0C–0F`, com pilha em `$8D00` e contador em `$8D10`) para duas linhas: a de cima (espaço, ou a marca do prefixo `FE`/`FF`; `move.b d2,(a3)+` em `0x1EC8`, com `lea buffer.w,a3` em `0x1E72`) e a das letras (`move.b d3,$xx(a3)` em `0x1EC4`), contando as colunas em `$8CDE`. Não há limite no código. Na base o buffer é `$8CE0`/`$8CF0` (16 colunas): acima disso a linha de cima invade a das letras e as letras passam de `$8D00`, a pilha e o contador das aninhadas (risco de travar). Os patches `buffer_nome.*` levam o buffer para `$AB00`/`$AB20` (32 colunas cada; abaixo, "Buffer do nome de item"). O limite passa a ser o menor entre o buffer (32), a linha do baú (`"Você achou "` + nome + `"."` em 30 colunas: 18) e as janelas dos diálogos e da loja (23 colunas, `checar_largura`): **18** (`MAX_NOME_ITEM` em `ferramentas/verificacao.py`; o ajuste `bau.centro_item` usa o mesmo valor e acusa se os textos fixos do baú crescerem). Chamadores (busca em todo endereço par, `testes/test_nomes_menu.py::test_chamadas_da_rotina_na_base`): baú de item (`bsr.w` em `0x1EEC`), lista de itens do menu (`jsr $1E6A.w` em `0x7AD6`) e lista de equipamentos (`jsr $1E6A.w` em `0x8428`); a rotina dos nomes curtos (abaixo) refaz o preparo e segue no laço de `0x1E7C`. A fala da loja (`[s0:02]`) não passa por aqui (o motor de texto `0x1566` empilha e imprime a string direto). `verificar` dá erro acima de 18 (`checar_nomes_itens`). Cada tela do menu tem um limite menor (abaixo).

### Buffer do nome de item (`$AB00`)

**Referências ao buffer antigo** (`testes/test_buffer_nome.py::test_auditoria_do_buffer_na_base`: `ferramentas/script/auditoria.py::referencias_ram`, força bruta em cada endereço par de `0x200–0x1C600`, absoluto `.w`/`.l` e imediato em registrador de endereço; o código não tem desvios para depois de `0x1C600`). Cada uma vira um patch de mesmo tamanho em `config/patches.yaml`:

| Endereço | Instrução na base | Quem | Patch | Novo |
|---|---|---|---|---|
| `0x1E72` | `lea $8CE0.w,a3` | cópia (`0x1E6A`) | `buffer_nome.copia_cima` | `lea $AB00.w,a3` |
| `0x1EC4` | `move.b d3,$10(a3)` | cópia: letras | `buffer_nome.copia_letras` | `move.b d3,$20(a3)` |
| `0x1F18` | `lea $8CE0.w,a0` | baú (`0x1EEC`) | `buffer_nome.bau_cima` | `lea $AB00.w,a0` |
| `0x1F26` | `move.b $10(a0),d0` | baú: letras | `buffer_nome.bau_letras` | `move.b $20(a0),d0` |
| `0x7AEE` | `lea $8CE0.w,a1` | tela ITEM | `buffer_nome.itens_cima` | `lea $AB00.w,a1` |
| `0x7AFA` | `lea $8CF0.w,a1` | tela ITEM | `buffer_nome.itens_letras` | `lea $AB20.w,a1` |
| `0x8446` | `lea $8CE0.w,a0` | equipamentos | `buffer_nome.equip_cima` | `lea $AB00.w,a0` |
| `0x844C` | `lea $8CF0.w,a0` | equipamentos | `buffer_nome.equip_letras` | `lea $AB20.w,a0` |

O único outro achado em `$8CE0–$8CFF` é `0x1F16`, o meio de `bsr.w $1F8E; lea $8CE0.w,a0` (`0x1F14`) lido fora de fase. Os leitores percorrem as linhas com `(An)+` contando `$8CDE` (`0x7B70`, `0x8492`, `0x1F26`); a centralização das listas (`moveq #$E` em `0x842E`) é a largura da tela, não do buffer, e não muda. A rotina dos nomes curtos (`etapa_nomes_menu`) refaz o preparo de `0x1E6A` com os patches aplicados (`lea $AB00.w,a3`), porque os patches são gravados depois dela. A contagem `$8CDE`, a pilha `$8D00` e o contador `$8D10` ficam onde estão; `$8CE0–$8CFF` deixa de ser usado.

**Por que `$AB00–$AB3F` está livre.**

- *Código*: nenhuma instrução endereça `$A3C0–$BFFF` (`test_area_nova_sem_referencias_no_codigo`; os dois achados, `0x96CC`/`0x96CE`, são dados depois do `rts` de `0x96BA`, passados por `lea $96BC(pc),a0`). A última variável antes é `$A3BE` (usada pelo código de `0x1B250–0x1B966`); depois vem `$C000`, a primeira das 32 páginas de 256 bytes da tabela de objetos (`$C000–$DFFF`, campo = página, objeto = `a4` de 0 a `$FF`: `-$3800(a4)` = `$C800 + a4`). Acesso por base + deslocamento: os campos de objeto usam deslocamentos de `-$4000` a `-$2001` (páginas `$C0–$DF`); os deslocamentos que cairiam nas páginas `$A4–$BF` aparecem só em dados lidos como código (`0x5AD6`, `0x5B40`, `0x5B7E`, `0x5E58`, `0x623A`, `0x624C`, `0x6342`, `0x73B0`, e outros fora de fase). Nenhuma palavra de `$AA00–$ACFF` no código é ponteiro para a RAM (são deslocamentos de `bra.w`/`bsr.w`, `jmp $1AA3C` e tabelas). A limpeza de RAM do boot (`0x25C`, a RAM inteira com `move.l d0,-(a6)`) zera a área no 2.º quadro, antes de qualquer uso; o reset não a limpa de novo.
- *Emulador*: três sessões longas (28 mil quadros no total): **título** (3000 quadros, abertura), NEW GAME, fala de abertura, saída de casa, **campo** (andar para os dois lados, pular, atacar, mudar de área), **baú** de ouro e de item (o gancho de `test_repontavel.py`), **menus** (seleção, listas de equipamento e tela ITEM, com itens dados pela RAM); **estalagem** (`dialogo.046` na entrada 0) com save, reset, **CONTINUE** e o jogo carregado andando; **loja** (`dialogo.010`, item `0x1D`, SIM/NÃO, sem dinheiro). Lendo a RAM a cada quadro, nenhum byte de `$A400–$BFFF` muda. Com um padrão gravado em toda a faixa depois da limpeza do boot (e de novo depois do reset), o padrão sobrevive em todas as 27 cenas conferidas e a RAM fora da faixa e as telas são idênticas às da sessão sem padrão: o jogo não escreve nem lê ali. Fora dessa faixa, as áreas paradas nas sessões são usadas em outras situações (`$8248–$8A47`: 16 tarefas de 128 bytes, de `0x444`/`0x4B96`; `$8F0A–$9509`: árvore do descompressor; `$C000–$DFFF`: objetos), por isso não servem.
- *Teste*: `test_save_e_load_com_todos_os_patches` repete estalagem → reset → CONTINUE na ROM do build e nela sem o buffer novo (iguais: telas e RAM) e com o padrão em `$AB00–$AB3F` (intacto); `test_bau_com_o_nome_mais_longo_no_jogo` mostra no baú um nome de 18 colunas (só na cópia do projeto do teste) inteiro, centrado e com as bordas intactas, com o nome em `$AB00`/`$AB20` e `$8CE0–$8CFF` zerado (captura `build/capturas/bau_nome_longo_zoom.png`).

Auditoria das referências (busca por força bruta em `0x200–0x1C600` e na ROM inteira, `ferramentas/script/auditoria.py::referencias_a`: decodifica uma instrução em cada endereço par e aceita PC-relativo, absoluto `.w`/`.l` e imediato; `testes/test_repontavel.py::test_auditoria_referencias`):

| String | Endereço | Referências no código | Item / decisão |
|---|---|---|---|
| `Found the ` | `0x1FE6` | `0x1F10` `lea $1FE6(pc),a0` + `bsr.w $1F8E` | `bau.achou_o`, `lea_pc_bsr` |
| `.` | `0x1FFF` | `0x1F3C` `lea $1FFF(pc),a0` + `bsr.w $1F8E` | `bau.ponto`, `lea_pc_bsr` |
| `Found ` | `0x1FF1` | `0x1F74` `lea $1FF1(pc),a0` + `bsr.w $1F8E` | `bau.achou`, `lea_pc_bsr` |
| ` GOLD.` | `0x1FF8` | `0x1F82` `lea $1FF8(pc),a0` + `bsr.w $1F8E` | `bau.ouro`, `lea_pc_bsr` |
| `AP` `DP` `SP` | `0x84DE` | `0x84C8` `lea $84DE(pc),a1` (laço de 3) | ficam de tamanho fixo (`status.*`) |
| `GOLD` | `0x84E7` | `0x85A0` `lea $84E7(pc),a1` — trocado pelo patch `hud.moedas_chamada` | sem leitor no build; saiu da config |

Fora do código só aparecem falsos positivos em dados gráficos (`0x36EF8`, `0x4F2F6`, `0x637FC`, palavras `1FF8`/`1FFA` no meio de tiles). A tela de status (menu do START) não tem rótulo de ouro: durante o menu o quadro do ouro do HUD dá lugar ao ícone do controle (captura `build/capturas/bau_base/status.png`).

**Teste no jogo** (`test_baus_e_status_no_jogo`): sem baú perto do início, a ROM de teste (só no teste) troca o começo de `0x400` (troca de tarefa) por `jmp $9F900`, um toco em espaço livre que, com um valor mágico no ouro (`$FF962C` = `0xABCDE0`/`0xABCDE1`, acima do limite 999999), chama `0x1FCA` (d0 = 999999) ou `0x1FD0` (d0 = `0x0E`, "Leather Armor", o maior nome em inglês) e segue. A mensagem aparece na linha 9 da janela (bordas `0x87A1`); capturas em `build/capturas/bau_base/` e `bau_ptbr/`.

### Nomes de itens nos menus (Plano 4, Tarefa 4)

O nome completo fica no banco 1 e serve aos diálogos, à loja e ao baú; as duas listas do menu do START leem antes uma segunda tabela, a dos nomes curtos (`traducao/textos/banco1_menu.yaml`, ids `b1m.XXX` com o índice do item; vazio = mostra o completo). Config `nomes_menu` em `config/texto.yaml`, etapa `etapa_nomes_menu` (`ferramentas/nomes_menu.py`, logo depois das strings repontáveis).

| Tela | Chamada | Itens | Largura |
|---|---|---|---|
| ARMA, ARMADURA, ESCUDO, BOTAS | `0x8426–0x842B`: `add.w d1,d0; jsr $1E6A.w` (índice = (`$95FA` − 1) × 8 + posição) | `0x00–0x1F` | **17** (base 14): `0x842E` centraliza com `moveq #$E,d1; sub.w $8CDE,d1; lsr.w #1,d1` a partir da coluna 15 (`move.w #$F06,d7` em `0x83D4`), colunas 15–28; acima da largura a margem fica negativa e o `lsr` a transforma em ~32 mil espaços escritos pelo laço de `0x8484`. Patches `lista_equip.*`: 17 colunas a partir da 14 (abaixo) |
| ITEM | `0x7AD2–0x7AD9`: `ori.w #$30,d0; jsr $1E6A.w` (índice = `0x30` + espaço do inventário `$958C+n`) | `0x31–0x3B` | **9**: posição fixa por espaço (tabela `0x7B0A`, colunas 2, 12 e 22, linhas 7/9/11/13 + 1 para as letras); 9 deixa uma coluna livre antes da coluna seguinte e da moldura (31) |

**Como.** O `jsr $1E6A.w` só alcança `0x0000–0x7FFF` e lá não há espaço livre, então cada trecho vira `jsr trampolim.l` (+ `nop`) e o trampolim, na região livre, refaz a instrução de antes e chama a rotina nova (nenhum desvio cai dentro dos trechos, `test_trampolins_reais`). A rotina nova: `d3 = d0 & 0xFF`; índice fora da tabela ou entrada `0000` → `jmp $1E6A` (banco 1, completo); senão `a2` = tabela + deslocamento, refaz o preparo de `0x1E6A` (os 12 primeiros bytes: `clr.w $8D10`, `clr.w $8CDE`, `lea $AB00,a3`, já com o patch `buffer_nome.copia_cima` aplicado à cópia) e segue no laço de cópia original (`jmp $1E7C`). Assim a cópia, a contagem `$8CDE`, a centralização e o desenho são os mesmos. A tabela tem uma word por item até o maior índice das telas (`0x3C`), com o deslocamento a partir dela. Sem nenhum nome curto nada é gravado (`test_ida_e_volta_sem_nomes_curtos`); a rotina `0x1E6A` e o baú só mudam pelos patches `buffer_nome.*` (buffer em `$AB00`).

**Lista de equipamentos alargada** (patches `lista_equip.*`, `config/patches.yaml`). O painel tem moldura nas colunas 12 e 31 (traço nos pixels 1–6 de cada tile) e fundo preto nas colunas 13–30 (`0x8020` onde a lista escreve, `0x87A0` no resto). Na base a seta do cursor (tile `0x87B5`/`0x8FB5`, piscando; posição em `$9624`/`$9625`, desenhada por `0x81D6`) fica na coluna 14: `move.w #$0E07,$9624.w` em `0x7848` e a linha em `0x8264`. O item equipado pisca: `0x7E46` (`move.w #$F06,d7`) apaga as 2 linhas dele com `moveq #$D,d5` + o laço `subq`/`bne` de `0x8762` (13 tiles a partir da 15) e depois redesenha a lista (`0x83D0`). Os patches levam a seta para a coluna 13 (`0x7848`), os nomes para 17 colunas a partir da 14 (`0x83D4`, `0x842E`) e o pisca para as mesmas 17 (`0x7E46`, `0x7E76`): todos os nomes completos de equipamento cabem (o maior tem 17). Ao voltar para a seleção, `0x7808` limpa 9 linhas a partir da coluna 13 com `moveq #$11,d5` (17 tiles, até a coluna 29); com a lista indo até a coluna 30, o fim do nome ficava no painel (achado do autor). O patch `lista_equip.volta_largura` (`0x7812`) limpa 18 tiles. Testes: `test_lista_de_equipamentos_alargada` e `test_nomes_no_jogo` (nome centrado nas 17 colunas, seta fora delas, molduras intactas, e a seleção igual à de antes ao voltar de cada tela).

**Checagem.** `verificar` (`checar_nomes_menu`) dá erro se o nome que a tela mostra passa da largura dela: o curto ou, sem ele, o completo do banco 1 (com as aninhadas expandidas); também se o curto tem tags/códigos ou é de um item fora das telas. O build confere os bytes originais das chamadas e do prólogo antes de gravar.

**No jogo** (`test_nomes_no_jogo`; capturas em `build/capturas/nomes_menu_base/`, `nomes_menu_ptbr/` e `nomes_menu_*_comparacao.png`): com equipamentos e itens dados pela RAM (posse por categoria em `$95CA–$95CD`, equipado em `$95CE–$95D1`, itens em `$958D–$9597`), cada categoria mostra o nome completo centrado (sem nome curto nas telas de equipamento) e a tela ITEM os curtos nas posições de `0x7B0A`. A fala da senhora (`dialogo.002`: Elixir e Bolas de Fogo) e a da loja (`dialogo.010` com o item trocado para `0x1C` só na ROM de teste: "Botas de Escalada", 17 colunas) mostram o completo (`build/capturas/nomes_senhora_*.png`, `nomes_loja_1c.png`); o baú também (`test_baus_e_status_no_jogo`, item `0x0E`: "Armadura de Couro").

### Menus e magias (Plano 4, Tarefa 3)

**Tudo é texto da fonte, nenhum rótulo é gráfico.** O menu do START fica no plano da janela (`0xD800`, 32 colunas), desenhado pelo código com os tiles da fonte (`$8000 | byte` por `0x7870`, paleta 0; `$A000 | byte` por `0x786A`, paleta 1). Conferido no emulador lendo o tilemap (`testes/test_menus.py::test_menus_no_jogo`; capturas em `build/capturas/menus_base/`, `menus_ptbr/` e as comparações `build/capturas/menus_*_comparacao.png`). Painel da direita (seleção e telas 1–4): moldura nas colunas 12 e 31, fundo preto (`0x8020`) nas colunas 13–29; telas de item e magia: painel inteiro, moldura nas colunas 0 e 31, fundo `0x87A0`.

| O quê | Onde fica / quem desenha | Como |
|---|---|---|
| Cabeçalho (`SELECT`, `WEAPON`… `MAGIC`) | `0x8272`: índice da tela `$95FA` → tabela de deslocamentos **`0x82B6`** (7 words a partir da própria tabela; `lea $82B6(pc),a1; adda.w (a1,d0.w),a1` em **`0x8278`**). Coordenada: word **`0x82B2`** (`0x1004` = coluna 16, linha 4) nas telas 0–4 e `0x82B4` (`0x0B04`, coluna 11) em item e magia (`move.w $82B2(pc,d1.w),d7` em `0x828A`) | linha 4: enfeite `0x87AE 0x87AF`, espaço, texto (paleta 1), espaço, enfeite `0x8FAF 0x8FAE`. A linha **não é limpa** entre as telas 0–4: o original completa `ARMOR`/`BOOTS` com espaço até 6 letras |
| Opções da seleção (`WEAPON`… `MAGIC`) | `0x77CC`: `lea $82CB(pc),a1; moveq #5,d2` em **`0x77D4`**, 6 strings em sequência (as mesmas bytes dos cabeçalhos 1–6), posições da tabela **`0x7D6E`** (coluna, linha: 15/24 × 7/10/13) | paleta 0. O cursor (`0x87B5`) fica uma coluna antes (`0x77EC`, `0x7D2E`: coluna − 1) e a posição antiga é apagada com `0x8020` (`0x81C0`) |
| Lista de magias | `0x7BB6`: `moveq #0,d4; lea $7C0A(pc),a1`, 6 entradas (coluna, linha, texto, `00`) em sequência: colunas 3 e 18, linhas 6/9/12; contadores na linha de baixo (`0x7C68`). Ao equipar (`0x7A18` → `0x7C44`/`0x7C56`) cada entrada é achada pela tabela **`0x7BFE`** (`lea $7BFE(pc),a1; adda.w (a1,d0.w),a1`) e redesenhada (paleta 1 = equipada, `$9F10`/`$9F11`) | o cursor da coluna da direita fica na 17 (`0x7D62`) |
| Nome da magia no HUD | ao lançar (`0x11402`: `d0 = $9F7B & 0x7F; jmp $8778`): `0x8778` → `lea $7BFE(pc),a1; add.w d0,d0` em **`0x8784`**, `adda.w`, `+2` (pula a coordenada), conta as letras (`0x1B004`) e **centraliza em 10 colunas** a partir de (21, 1) (`0x87A0`); limpa (21, 2) | **10 colunas no máximo** (acima disso o código passa da moldura) |
| `AP` `DP` `SP` | `0x84DE` (laço de 3 em `0x84CE`), coluna 2, linhas 9/11/13 | inline fixo de 2 letras (`status.*`) |

**Blocos repontáveis.** Os textos são lidos em sequência ou por tabelas de words relativas, por isso cada lista muda de lugar inteira (`inline_repontavel.blocos` em `config/texto.yaml`, `ferramentas/repontavel.py`): com algum `pt`, o bloco é copiado para a região livre (tabela refeita na frente, entradas com o prefixo original) e as referências passam a ler a cópia; sem nenhum `pt`, nada muda. O `lea (pc)` não alcança `0xA4C80+` e não há `bsr` para encurtar: as referências são do tipo **`trampolim`** (o trecho `[ini, fim)` com o `lea` vira `jsr trampolim.l` + `nop`; o trampolim, em endereço par na região livre, refaz o trecho com `lea abs.l` e volta). Os bytes levados para o trampolim não usam o PC nem a pilha, e nenhum desvio cai dentro do trecho (`test_trampolins_reais`).

| Bloco | Origem | Referências (trampolim) | Trocas (só com o bloco traduzido) |
|---|---|---|---|
| `menu.cabecalhos` | `0x82C4`, 7 entradas | tabela `0x82B6`: `0x8278–0x827F` | `0x82B2`: `1004` → `0E04` (coluna 14, para caber `SELECIONAR`) |
| `menu.opcoes` | `0x82CB`, 6 entradas | `0x77D4–0x77D9` | `0x7D6E`: colunas 15/24 → **14/22** (`ARMADURA` cabe na direita) |
| `menu.magias` | `0x7C0A`, 6 entradas (prefixo 2) | `0x7BB6–0x7BBB` (com o `moveq`); tabela `0x7BFE`: `0x7C56–0x7C5D` | — |
| `menu.magias_hud` | a mesma origem, outra cópia | tabela `0x7BFE`: `0x8784–0x8789` (com o `add.w`) | — |

Largura (colunas por entrada, `largura`; `verificar` e build dão erro acima): cabeçalhos das telas 0–4 na coluna 14 = 11 (enfeite + espaço + texto + espaço + enfeite até a coluna 30) e **do mesmo tamanho** entre si (`iguais`); item/magia na coluna 11 = 14; opções: esquerda 7 (colunas 14–20; o cursor da direita fica na 21), direita 8 (22–29); magias: esquerda 14 (3–16), direita 13 (18–30); HUD: 10.

Auditoria (`test_auditoria_referencias_dos_menus`): `0x7C0A–0x7C43` só é lido por `0x7BB8` (os demais achados, `0x8E50` e `0x1B14E…0x1B200`, são tabelas de dados); `0x7BFE` por `0x7C56` e `0x8784`; `0x82B6` por `0x8278` (`0x632E` é dado); `0x82C4–0x82F1` por `0x77D4`; `0x82B2` por `0x828A`; `0x7D6E` por `0x77D0`, `0x77EC` e `0x7D2E`.

As duas leituras da tabela `0x7BFE` (o desenho da lista e o destaque ao equipar/nome no HUD) são repontadas; sem isso elas apontariam para a área antiga. O HUD tem nomes curtos de até 10 letras.

### Auditoria de referências absolutas (Plano 2, Tarefa 1)

`ferramentas/script/auditoria.py` varre o código (`0x200–0x1C600`) com o capstone (68000) e lista operandos absolutos de 32 bits (`$xxxx.l` ou `#$xxxx`) na faixa de texto `0x1DD94–0x22460`. Resultado na ROM base:

| Operando | Valor | Decisão | Motivo |
|---|---|---|---|
| `0x1BABC` | `0x21001` | ignorada | falso positivo: `0x1BA90–0x1BAF0` é tabela de dados (atributos de sprite), decodificada como instrução pelo varredor linear |

- Nenhum script de texto é referenciado direto pelo código: `raizes_extra` fica vazio (`config/texto.yaml`).
- O código em `0x1570`/`0x1ED8`/`0x2774`/`0x2794` lê as tabelas pela tabela global `0x1CC00` (§2), que é dado e tratada na Task 5.
- Conferência independente: busca bruta por opcodes com modo absoluto longo (`xxF9`/`xx79`/`xx39`) em `0x200–0x1C600` também não acha referências à faixa. Valores que parecem ponteiros em dados fora do código (por exemplo `0x5E77C → 0x1F11F`) apontam para o meio de texto e são ruído de dados gráficos/mapas, não raízes.
- O teste `test_referencias_rom` guarda isso: referência nova sem classificação em `config/texto.yaml` quebra o teste.

## 7. Espaço livre na base (runs de `FF`)

| Faixa | Tamanho |
|---|---|
| `0x1C602–0x1CC00` | 1,5 KB |
| `0x409FA–0x41000` | 1,5 KB |
| `0x9622B–0x98000` | 7,5 KB |
| `0x9F777–0xA0000` | 2 KB (`0x9F780–0x9F7AF`: rotina do HUD, patch `hud.moedas_rotina`, §8) |
| **`0xA4C77–0xC0000`** | **109 KB** |

**Área de compensação `0xBFFF8–0xBFFFF`** (8 bytes, `compensacao` em `config/rom.yaml`): reservada para o CRC32 e o checksum do cabeçalho do build ficarem iguais aos da original (`1592F5B0` e `9D79`). Por isso `regiao_destino` termina em `0xBFFF8`; o alocador (`espaco.regiao_livre`) e os patches (`etapa_patches`) recusam sobreposição, e a compensação recusa a área se alguma etapa a tiver alterado. Na base é `FF` (fim do run livre que começa em `0xA4C77`); nenhuma instrução a referencia (na faixa `000BFFF0–000BFFFF`, os únicos longs na ROM são o campo de fim da ROM do cabeçalho em `0x1A4` (`000BFFFF`, que não muda) e `0xBC04`, que é o imediato/deslocamento de `andi.b #$B,-$C(a6)` em `0xBC02`, os bytes `000B FFF4`, não um endereço); é só o enchimento até o fim do arquivo (lida apenas pela soma do checksum, que continua válida). Layout gravado pela última etapa do build (`ferramentas/compensacao.py`), depois de `corrigir_cabecalho`: `V` (word) + `W` (word) + `F` (4 bytes). O campo `0x18E` recebe o valor da original; para cada (`V`, `W`) em ordem crescente, `F` é forjado com a tabela inversa do CRC32 (4 passos para trás a partir do CRC final dão os índices da tabela, o passo para frente dá os bytes) e a soma das words de `0x200` ao fim é conferida; a 1.ª combinação que fecha a soma é a usada (~65 mil tentativas, determinístico). Se a ROM já tem o CRC32 e o checksum da original, nada é gravado.

O texto todo (diálogos + bancos) ocupa ~17 KB, então **não é preciso expandir a ROM** para o texto. A restrição real é o offset de 16 bits com sinal: cada tabela e os seus alvos têm que ficar na mesma janela de ±32 KB. Basta pôr tabela + scripts juntos em `0xA4C80+`.

**Layout do build** (`ferramentas/script/montador.py`, com o texto original): 18.104 bytes em `0xA4C80–0xA9338`, em 5 blocos, cada um com a sua tabela no início — diálogos `0xA4C80` (13.362 B), banco 0 `0xA80B2` (1.350 B), banco 1 `0xA85F8` (742 B), banco 2 `0xA88DE` (376 B), banco 3 `0xA8A56` (2.274 B, inclui o dicionário do banco 0, que na ROM fica depois da tabela do banco 3). A ordem original das instruções é mantida e os rótulos são resolvidos num mapa global. Ponteiros trocados: `0x1CC14` e as 4 bases em `0x211CA–0x211D9`; a região antiga fica intacta. Tabelas dos bancos em endereço par (padding `00`).

## 8. Fonte e gráficos

### Tabela de blocos de gráficos — `0x41000` (Plano 3, Tarefa 2)

- **768 entradas de 32 bits big-endian** em `0x41000 + 4·bloco` (`0x41000–0x41BFF`; o blob do bloco 0 começa logo depois, em `0x41C00`): byte de tipo + ponteiro de 24 bits. Há buracos `FFFFFFFF` (42 entradas vazias, inclusive a 405 e as últimas). Ex.: bloco `0x235` (HUD, slot 4 em jogo) = `0x020815AE`. `TOTAL_BLOCOS = 768` (Tarefa 2 contava 405 por engano; corrigido na Tarefa 4). Cada entrada é um **bloco de 32 tiles (1 KB)**. Referenciada por `adda.l #$41000` em `0x22C8` e `0x6BC8`. Ler/gravar com `ler_entrada`/`escrever_entrada` (`ferramentas/compressao.py`).
- **O tipo são bits testados em ordem** por `0x6BCE–0x6BF8`, não um valor de byte:
  1. bit 31 (`bpl`) → bloco vazio (zeros), ponteiro ignorado;
  2. senão bit 24 (`bclr #$18`) → **cru**, 1 KB copiado com `move.l` (`0x6BEC`);
  3. senão bit 25 (`bclr #$19`) → **tipo 02**, Huffman + LZ, rotina `0x6D9C` (695 blocos, inclusive a fonte);
  4. senão → **tipo 00**, formato por tile, rotina `0x6BFC` (11 blocos: `0x11 0x50 0x79 0x98 0x12D 0x135 0x149 0x186 0x2E2 0x2E3 0x2E5`; não implementado). Os outros: 20 crus (`01`) e 42 vazios.
  Logo `03` seria cru. Os bits 26–30 (e 25 num bloco cru) sobram no ponteiro e só funcionam porque o barramento é de 24 bits — `escrever_entrada` grava sempre o byte canônico (`00`, `01`, `02`, `80`).
- **Alinhamento**: bloco **cru precisa de endereço par** (`move.l` em endereço ímpar = *address error*; `escrever_entrada` recusa). Tipos 02 e 00 leem byte a byte e aceitam endereço ímpar (331 dos 695 blobs tipo 02 originais são ímpares).
- Entradas da fonte: blocos 0–7, entradas `0x41000–0x4101C` (tabela abaixo).
- Carga: `0x22F0` percorre 64 *slots* em `$FF8E08` (word = número do bloco; `$FFFF` = livre; cache em `$FF8E88`). Para o slot `n`, `0x6BC4` (d0 = bloco, a1 = `$FF2D00`) expande o bloco na RAM e o laço `0x2332` copia 256 longwords para o VDP no endereço **VRAM `n × 0x400`** (comando montado por `0x5A0`). `0x22A8` copia tiles avulsos só de blocos tipo `01`.

### Formato tipo 02 (Huffman + LZ) — `ferramentas/compressao.py`

Não é Nemesis, Kosinski nem Enigma: é um formato próprio (sem cabeçalho de tamanho; a saída é sempre 1024 bytes, `move.w #$3FF,d2` em `0x6DEA`). Fluxo de bits, MSB primeiro:

1. **Árvore em pré-ordem**: `1` = nó interno (esquerdo, depois direito), `0` = folha + símbolo cru. O primeiro bit é sempre `1` (a raiz; o 68000 o descarta em `0x6DA0`). Nós montados na RAM a partir de `$FF8F0A` (4 bytes por nó, pilha temporária no próprio buffer de saída).
2. **Símbolo cru** (`0x6E4E`): `0` + 8 bits → `0x00–0xFF`; `1` + 5 bits → `0x100 + v` (`0x100–0x11F`).
3. **Dados** (`0x6E2E`, bit `0` = esquerda, `1` = direita):
   - símbolo `< 0x100` → byte literal;
   - `0x100–0x11E` → cópia de `símbolo − 0xFD` bytes (3–33); o próximo símbolo é a distância `d`; origem = `posição − 1 − d` (byte a byte, pode sobrepor);
   - `0x11F` → escape: o valor vem cru (como na folha), seja literal, comprimento ou distância.
- Verificação: os 695 blocos tipo 02 descomprimem e, nos blocos 0–404, o consumo termina no início do blob seguinte (ou 1 byte antes).
- **Limite de RAM da árvore**: o 68000 aloca os nós internos em `$FF8F0A + 4k` (raiz em `$FF8F0A`); com N folhas a árvore ocupa `$FF8F0A … $FF8F0A + 4(N−1)`. Os blocos 0–404 usam **no máximo 59 folhas** (até `$FF8FF2`); os blocos acima de 404 chegam a 61. Nenhuma instrução do código referencia `$FF8F0C–$FF9509` por endereço absoluto além do descompressor (a variável seguinte é `$FF950A`), mas acesso indexado não está descartado, e na abertura do jogo só se viu escrita até `$FF8FE1`. Por isso `comprimir` limita a árvore a `MAX_FOLHAS = 59`: os símbolos menos frequentes saem pelo escape `0x11F` (custo de 6–9 bits a mais cada). Assim nunca se escreve RAM além do que os blocos originais já escrevem. O bloco 5 da fonte com os acentos recomprimido usa exatamente 59 folhas e decodifica certo no 68000 (`testes/test_fonte.py::test_jogo_mostra_acento`, VRAM = PNG).
- `comprimir()`: LZ guloso com 1 passo de antecipação (distância ≤ `0x11E`, comprimentos 3–33) + Huffman determinístico limitado a 59 folhas; no total dos 377 blocos tipo 02 de 0–404 fica ~3% maior que o original (164.877 vs 160.664 bytes). Para trocar um bloco: recomprimir e, se não couber no lugar, gravar em espaço livre e trocar a entrada (tipo `02`, qualquer endereço) — ou gravar cru em **endereço par** com tipo `01`.

### Fonte

- **Os códigos de caractere são índices de tile diretos (offset 0)**: tile `0x41` = `A`, `0x61` = `a`, `0x30` = `0`. Fonte em 2 cores (índice 1 = fundo, 15 = traço), 1 tile 8×8 por caractere (a linha de cima, §5, é o tile `0x20`/`0xBE`/`0xBF`).
- Blocos na tabela `0x41000` → slot = tiles `32n…32n+31` → VRAM `n × 0x400`:

| Bloco | Entrada | Blob | Tiles / VRAM | Conteúdo |
|---|---|---|---|---|
| 0 | `0x41000` | `0x41C00` | `0x00–0x1F` / `0x0000` | vazio + símbolos (setas, ABC, numerais romanos) |
| 1 | `0x41004` | `0x41CCF` | `0x20–0x3F` / `0x0400` | espaço, pontuação, `0–9` |
| 2 | `0x41008` | **`0x41DEB`** (`END_FONTE`) | `0x40–0x5F` / `0x0800` | `@`, `A–Z`, `¥ ] _` |
| 3 | `0x4100C` | `0x41F23` | `0x60–0x7F` / `0x0C00` | `a–z` |
| 4 | `0x41010` | `0x42019` | `0x80–0x9F` / `0x1000` | kana; no diálogo o slot 4 recebe o bloco `0x235` (HUD) |
| 5 | `0x41014` | `0x4214F` | `0xA0–0xBF` / `0x1400` | kana, marcas `0xBE`/`0xBF` (projeto: acentos em `0xA1–0xAC` e `0xB1–0xBC`) |
| 6 | `0x41018` | `0x422A8` | `0xC0–0xDF` / `0x1800` | kana |
| 7 | `0x4101C` | `0x423FA` | `0xE0–0xFF` / `0x1C00` | kana |

- Em jogo, `$FF8E08` começa com `0,1,2,3,0x235,5,6,7`. Os tiles `0x5C`, `0x5D` e `0x5F` (¥ ] _) são zerados no VRAM logo depois da carga (entre ~12 e ~68 quadros após NEW GAME); o resto bate byte a byte com o VRAM (`testes/test_compressao.py`, roteiro `roteiros/dialogo.yaml`).
- **Fonte editável** (Tarefa 4): `graficos/fonte/fonte.png` (16 × 16 tiles = blocos 0–7) e `graficos/fonte/fonte.yaml` (metadados, origem dos glifos), via `ferramentas/fonte.py`. `etapa_fonte` recomprime só os blocos que mudaram; cabe no lugar (≤ bytes consumidos pelo original) → grava no lugar, senão vai para a região livre depois do texto (`ferramentas/espaco.py`, `RegiaoLivre` compartilhada em `Projeto.regiao`) e a entrada é reapontada. Recomprimidos sem mudança, os 8 blocos ficam 4–12% maiores que os originais (207→232, 284→306, 312→330, 246→258, 310→327, 345→367, 338→357, 340→348), por isso blocos intactos não são regravados. O bloco 5 com os 24 acentos (glifos do projeto) recomprime em 309 bytes (original 345): fica no lugar, `0x4214F`.
- Tabela de caracteres: só mapeia tiles visíveis com glifo (`checar_glifos`): saíram `5C 5D 5F` (zerados pelo jogo) e `5E 60 7C 7D 7E` (tiles vazios); `80–9F` nunca.

### Outros

- **Tela de título** (Plano 3, Tarefa 5): os textos são **sprites** (paleta 3), não plano nem fonte. Tiles de cada texto, lidos na tabela de sprites do VRAM (`SPRITES_TITULO` em `ferramentas/graficos.py`, `testes/test_graficos.py::test_tiles_de_cada_texto_do_titulo_no_jogo`):
  - "PRESS START BUTTON" (título) = sprites 26–31 (y=251): tiles `0x3E8–0x3FF`, `0x404–0x413` e `0x416–0x417` (5 sprites 4×2 e um 1×2; `0x400–0x403` são da seta e `0x414–0x415` não aparecem);
  - "NEW GAME" (menu) = sprites 26–28: tiles `0x3C0–0x3D3` (80 pixels);
  - "CONTINUE" (menu, só com save na SRAM) = sprites 29–31, uma linha abaixo: tiles `0x3D4–0x3E7` (80 pixels). Conferido gravando o jogo na estalagem (entrada 0 da tabela de diálogos trocada pela do `dialogo.046`), reiniciando o console e lendo os sprites do menu; a seta passa para o sprite 32;
  - seta do menu = sprite 29 (sem save) ou 32 (com save): tiles `0x400–0x403`;
  - tiles `0x418–0x41F`: sem uso.

  Os dois textos piscam. Todos os sprites têm 2 tiles de altura, tiles em ordem de coluna. O script de slots `0x72F8` põe os blocos `0x140–0x15D` (logo e arte) nos slots 0–29 e **`0x166`, `0x167`, `0x168`** (tipo 02 em `0x6A2C9`, `0x6A3F5`, `0x6A4FE`; 300, 265 e 250 bytes) nos slots 30–32 = tiles `0x3C0–0x41F`. As posições dos sprites ficam no código e não mudam.
  - **Projeto**: item `titulo` em `config/graficos.yaml` (`graficos/telas/titulo.png`, arte do projeto editada à mão, sem origem de importação): "APERTE START", "NOVO JOGO" e "CONTINUAR" em letras condensadas com contorno. No build, `0x166` e `0x168` recomprimidos cabem no lugar; `0x167` (278 bytes) vai para a região livre. Roteiro `roteiros/titulo.yaml` (título com o texto aceso + menu).
- Uso dos tiles `0x80–0xFF` por cena, scripts de slots (`0x234C`) e códigos dos acentos: ver `docs/tecnico/vram.md`. No jogo o slot 4 (`0x80–0x9F`) recebe o bloco `0x235` (HUD/efeitos); `0xA0–0xFF` continua fonte.

### HUD: quadro do ouro (Plano 4, Tarefa 1)

- O HUD fica no **plano da janela** (registrador 3 → `0xD800`, 32 colunas, H32; registrador 18 = `0x08`: linhas 0–7 da tela). O quadro do ouro ocupa as colunas 21–30 das linhas 4–6 (moldura nas colunas 20/31 e linhas 3/7, tiles `0x7A0–0x7B7` dos blocos `0x20–0x22`, slots 60–62). Fundo interno: `0x87A0`.
- **O rótulo "GOLD" não é gráfico**: são os tiles da fonte (`0x47 0x4F 0x4C 0x44`, paleta 1, prioridade: `0xA047…`) na linha 5, colunas 22–25. Quem escreve é a rotina `0x8596`: `moveq #6,d3; move.w #$1605,d7; bsr $83B0` (endereço da janela; `d7` = coluna·256 + linha, VRAM `0xD800 + 2·(coluna + 32·linha)`), `lea $84E7(pc),a1; bsr $786A` (`0x786A` escreve cada byte da string como `$A000 | byte`; `0x84E7` = `"GOLD",0`). `0x8596` só é chamada depois de redesenhar o HUD inteiro: `0x7576` (início do jogo/sala) e `0x7EE4` (fechar o menu de status). Não há tilemap do HUD em ROM para esse rótulo.
- **Valor do ouro**: long binário em **`$FF962C`**. `0x85A8` (entrada das atualizações: `0x1888`, `0xF21A`) limpa 6 posições a partir da coluna 24 da linha 6 e `0x84EC` converte para decimal, limitado a **999999** (`0xF423F`): no máximo 6 dígitos (`$8030 + dígito`, paleta 0), alinhados à direita na coluna 29 (colunas 24–29). Os dígitos e as letras da fonte ocupam as 8 linhas do tile, então o "GOLD" (linha 5) encostava no valor (linha 6).
- `0x8666` também escreve em (22, 5) (ícone `0x7E8`, depende de `$95EE`), mas não tem chamador direto na ROM; não foi visto no jogo.
- **Projeto**: "MOEDAS" com as letras da fonte nas colunas 23–28, **3 pixels acima**, dividido entre as linhas 4 e 5 da janela. Os 12 tiles ficam na fonte, códigos **`0xC6–0xCB`** e **`0xD3–0xD8`** (kana do slot 6 que nenhum texto usa, sempre carregados no jogo: slots 5–7 = blocos 5–7, vram.md §3.1): `0xC6–0xCB` = as 3 linhas de cima de cada letra (embaixo do tile, linha 4) e `0xD3–0xD8` = as 5 de baixo (linha 5), com 3 linhas livres antes do valor. Gerados por `ferramentas/fonte.py` (`HUD_*`, `tiles_hud`) em `graficos/fonte/fonte.png`; origem em `graficos/fonte/fonte.yaml` (`hud`).
- **Não usar `0xC0–0xC5` nem `0xD0`**: não são kana, são as bolhas d'água (sprites com os tiles `0xC4`, `0xC5` e `0xD0` na sala `0x69`; `TILES_EFEITO` em `ferramentas/fonte.py`, com `0xFE`/`0xFF`). Até a correção, o rótulo ficava em `0xC0–0xCB` e a bolha que sobe do herói aparecia como o alto do "S" de MOEDAS (`testes/test_bolha.py`; capturas em `build/capturas/bolha/`). `0xCF`, `0xD1`, `0xD2` e `0xDD` ficam de fora porque as strings japonesas que sobraram no inglês os usam (vram.md §3.2).
- Patches (`config/patches.yaml`): **`hud.moedas_chamada`** em **`0x85A0`** troca `lea $84E7(pc),a1; bsr.w $786A` por `jsr $9F780.l; nop`; **`hud.moedas_rotina`** em **`0x9F780`** (espaço livre, §7) imprime `C6–CB` em (23, 4) e `D3–D8` em (23, 5) com `0x83B0`/`0x786A` e volta. A coluna 22 da linha 5 fica com o fundo da moldura. O resto do HUD não muda (`testes/test_hud.py::test_hud_moedas_no_jogo`: tilemap da janela igual ao da base fora das colunas 22–28 das linhas 4–5, e a tela igual fora do rótulo, com o ouro em 999999 posto na RAM e o HUD redesenhado pelo menu; capturas em `build/capturas/hud_base/` e `hud_ptbr/`).

### Texto desenhado em tiles: varredura das telas (plano de lotes, Task 10)

Procura de texto que não sai da fonte (letras desenhadas em blocos da tabela `0x41000`), feita depois de todo o texto traduzido. O logo do título fica como está (design §5).

**Como foi visto:**

- **Final** (créditos, desfecho, "THE END", "TO BE CONTINUED"): cópia da ROM gerada na pasta temporária do sistema (fora do repositório), com `jmp $4F58` (`4EF9 00004F58`) em `0x4CEC` e o checksum do cabeçalho (`0x18E`) refeito. O NEW GAME vai direto para o final. Foram 30 000 quadros com uma captura a cada 60 e o botão A a cada 240. A ROM do projeto não foi tocada. Os tilemaps, a tabela de sprites e os slots (`$FF8E08`) foram lidos dos save states nos quadros de "THE END" e "TO BE CONTINUED".
- **Abertura, título e menu**: roteiros `boot`, `titulo`, `dialogo` (já cobertos).
- **Campo**: NEW GAME, fim da abertura, START parado (menu) e START andando (`PAUSE`, string da fonte; §6).
- **Game over**: não foi visto na varredura (zerar na RAM os candidatos a vida não matou o herói, e não há "GAME OVER" na ROM em ASCII nem em words da fonte). O texto é desenhado no bloco `0xFF`; achado depois pelo código (ver "Game over" abaixo).
- **Blocos de gráficos**: os blocos da tabela `0x41000`, desenhados lado a lado, dão os da tabela abaixo com letras.

**Texto em tiles encontrado** (traduzido na Task 10b; ver abaixo):

| Onde | Texto | Tiles | Tilemap / uso |
|---|---|---|---|
| Final, depois do desfecho, rolando da direita | `THE END` | `0x450–0x45F` (bloco `0x2EE`, tiles 16–31, slot 34), 16 tiles de letras 2 × 2 com espelhamento (T, H, E, N, D, O, B, C, I, U; 1 tile pode ser 4 quartos) | plano A, de um fluxo de **64 colunas × 2 words** (em cima, embaixo) em `0x1B61A–0x1B719` (`lea $1B61A(pc)` em `0x1B3B8`, ponteiro `$A3B6`, uma coluna por vez por `0x1B8DA`). As colunas 0–31 são a 1.ª tela (`THE END` nas colunas 10–22) |
| Final, última tela (fica até o reset) | `TO BE CONTINUED` | os mesmos | colunas 32–63 do mesmo fluxo (`0x1B69A–0x1B719`; texto nas colunas 34–61) |
| Estalagens (placa) | `INN` | 2 tiles por cópia: blocos `0x37` (tiles 12–13 e 28–29), `0x88` (28–29), `0xD3` (12–13 e 28–29), `0x10B` (28–29), `0x11C` (12–13) | cenário das vilas |
| Placa de saída | `EXIT` | bloco `0xB8`, tiles 25–28 | cenário |
| Título, abaixo do logo | copyright | bloco `0x14F` | título; **fica** (não é texto a traduzir) |

O balão `HA` / `HAHAHA` do "THE END" usa a fonte (`0x48`, `0x41`, plano A, de `0x1B71A`, `lea` em `0x1B4CA`), e "HA" fica igual em português.

**Tradução (Task 10b, decisões do autor):** `FIM`, `CONTINUA...`, `HOT` e `SAÍDA`, com letras desenhadas pelo projeto no estilo das originais. Itens `final`, `placas_hot` e `placa_saida` em `config/graficos.yaml`, com a disposição `fundo` (PNG = 2 linhas de 16 tiles por bloco, na ordem do bloco; blocos empilhados). A origem é a ROM base, e os desenhos são os `RETOQUES` de `ferramentas/graficos.py`. Testes em `testes/test_texto_tiles.py`.

- **Final**: o bloco `0x2EE` tem só os 16 tiles das letras (`0x450–0x45F`), e o texto novo cabe neles com espelhamento:
  - T, I, C, O, N e U ficam como estavam;
  - os tiles que só o E, o B e o D usavam viraram o alto do M (`0x453`), o pé do F (`0x454`, `0x455`; o alto do F é o do E), o ponto (`0x45C`) e o alto do A (`0x45D`, sobre a base do H). O M e o A são simétricos: o lado direito é o esquerdo espelhado. O pé do M é a haste do U virada.
  - O tilemap muda por dois patches em `config/patches.yaml`, com `original`/`novo` de 128 bytes cada: `final.fim` (`0x1B61A`, colunas 0–31) e `final.continua` (`0x1B69A`, colunas 32–63). O tamanho e o endereço do fluxo não mudam (o ponteiro `$A3B6` e a rotina `0x1B8DA` ficam iguais).
  - Centralização como a dos originais (com as colunas que sobram, a de mais fica à esquerda, como no `THE END`): `FIM` nas colunas 13–18 e `CONTINUA...` nas colunas 7–25 da tela (39–57 do fluxo). Cada letra tem 2 colunas, e cada ponto, uma.
  - No jogo, o fluxo vai para as linhas 14–15 do plano A (H32, sem rolagem do plano A): colunas 0–31 na 1.ª tela, e as 32–63 por cima delas na última.
- **Placas `HOT`**: 12 × 4 pixels no lugar das letras de `INN` (colunas 2–13 da placa de 16 pixels), com as cores de cada bloco: letra, sombra (a do I de `INN`, que vai para a haste do T) e fundo. Fica `6/C/1` em `0x37`, `0x88` e `0xD3`, `5/3/2` em `0x10B` e `9/C/1` em `0x11C`. A linha das letras muda por bloco: 6, 9, 7, 9 e 2 na folha de 16 linhas.
- **Placa `SAÍDA`**: letras de 7 linhas, cor `A`, hastes de 2 pixels e sombra `9` abaixo dos traços, como no `EXIT`. Ficam nos pixels 73–100 da folha, as mesmas colunas do `EXIT`; mais à direita, os tiles da moldura entram nas linhas 9–11. O acento do Í fica nas linhas 5–6 do tile 10 (em cima), com a linha 7 livre. No tilemap das salas com a placa, o tile 10 só aparece acima dela: nas salas `0x0A`, `0x0B`, `0x85` e `0x86`, os tiles 8–13 ficam na linha 8 e os 24–29 na linha 9 do plano, uma vez cada (plano A de 64 × 32 lido 500 quadros depois do NEW GAME).
- No build, `0x10B`, `0x11C` e `0x2EE` recomprimidos não cabem no lugar e vão para a região livre (relatório do `construir`); os outros ficam no lugar.

**Como as telas foram vistas (e como o teste as reproduz):**

- **Final**: cópia temporária da ROM com `jmp $4F58` em `0x4CEC` (onde a base tem `4A3880C8 6B18`) e o checksum refeito, com A a cada 240 quadros. A 1.ª tela é capturada 60 quadros depois de aparecerem tiles `0x450–0x45F` no plano A com o bloco `0x2EE` no slot 34. A última, quando o plano A fica 300 quadros sem mudar depois da troca. Com a ROM base, isso dá ~11 000 e ~11 900 quadros.
- **Placas**: no NEW GAME, `0x8F98` põe em `$9676` (sala atual) o word da tabela `0x8FAA`, indexada por `$965E` (4 bytes por entrada; a 1.ª é a sala 0, o início do jogo; as outras são as salas de volta das estalagens: `0x57`, `0x58`, `0x59`, `0x5C`, `0x20`). Numa cópia temporária da ROM, trocar o word de `0x8FAA` (checksum refeito) faz o jogo começar na sala escolhida. A fala de abertura começa por cima da cena, mas a placa fica visível embaixo. Uma varredura das 138 salas (`0x1CC00` → tabela de salas), olhando os slots e o plano A 500 quadros depois do NEW GAME, achou:
  - `INN` visível no início das salas `0x57`/`0x5D` (bloco `0xD3`) e `0x59` (bloco `0x88`);
  - `EXIT` nas salas `0x0A`, `0x0B`, `0x85` e `0x86` (bloco `0xB8`);
  - os blocos `0x37` (salas 0, 1, `0x12–0x16`, `0x58`), `0x10B` (`0x20`, `0x36`, `0x37`, `0x70`) e `0x11C` (`0x31`, `0x33`, `0x5C`) carregados, mas sem a placa na tela do início, nem andando para os dois lados a partir dele. Para esses, o teste confere só o VRAM (tiles do bloco = PNG) nas salas `0x58`, `0x20` e `0x5C`.
- `test_placas_no_jogo` acha a placa antiga na captura da base (casamento dos índices do bloco com as cores da tela). Depois confere que a placa nova aparece no mesmo lugar e com as mesmas cores na ROM traduzida, e que a antiga sumiu. `test_final_no_jogo` confere o VRAM, as duas linhas do plano A (= as 32 colunas do fluxo de cada tela) e, na captura, o traço das letras numa cor só (branco) no lugar do texto.
- Capturas: `build/capturas/final_base/` e `final_ptbr/` (`fim.png`, `continua.png`); `build/capturas/placas_base/` e `placas_ptbr/` (`sala_57.png`, `sala_59.png`, `sala_0a.png`, e `sala_58/20/5c.png` sem a placa na tela).

### Game over

- **Como se chega**: o laço do jogo (`0x8FFC`) testa `$FF9F03` em `0x9038` (`tst.b $9F03.w; bpl.b $9042`). Com o bit 7 ligado, cai em `bra.w $9144`: escurece a tela (`0x5842`), limpa (`0x5188`), roda o script de slots `0x91BE` (`89 00FF FF`: bloco `0xFF` no slot 9 = tiles `0x120–0x13F`), desenha o tilemap de `0x91C2` com `0x69AE`, carrega as paletas (`0x135C` com `0x91BA`) e clareia a tela (`0x581A`) e espera 240 quadros (`move.w #$F0,$40(a5)`) ou um botão. Depois escurece e volta ao título (`jmp $4CA8` com `d0 = 0`). Só `0x903E` desvia para `0x9144`.
- **Tilemap** (`0x91C2`, linguagem de `0x69AE`: `01 col lin` posição, `02 a` byte alto do word, `09 n` quebra a cada `n + 1` tiles, bytes `> 0x0C` = tile, `00` fim): `01 08 0C 02 01 09 0F 20 21 … 3F 00` = 16 × 2 tiles nas colunas 8–23 das linhas 12–13 do plano A (H32, centralizado), words `0x0120–0x013F` (paleta 0, sem prioridade).
- **Letras**: o bloco `0xFF` (tipo 02 em `0x5D47B`, 436 bytes) é todo o texto, 128 × 16 pixels nos 32 tiles. Letras de 14 × 16 pixels: traço de 2 pixels (máscara de 12 × 14), contorno de 1 pixel nos 8 vizinhos do traço (índice 1, preto como o fundo, índice 0) e a cor do traço só pela linha, em degradê simétrico: linhas 1–2 e 13–14 índice `B` (vermelho, `(205, 0, 0)` na captura), 3–4 e 11–12 `C` (laranja), 5–6 e 9–10 `9` (amarelo) e 7–8 `F` (branco). `GAME OVER` ocupa os pixels 3–124: 1 pixel vazio entre letras e 4 entre as palavras.
- **Projeto**: item `game_over` em `config/graficos.yaml` (`graficos/telas/game_over.png`, disposição `fundo`), com o retoque gerado por `compor_game_over` em `ferramentas/graficos.py`: **`FIM DE JOGO`**. G, M, E e O são as máscaras do original, pixel a pixel. F (o E sem a barra de baixo), I (só a haste, 4 pixels com o contorno), D (lado esquerdo do E com a curva do O) e J (haste da direita com a curva do O embaixo, 10 pixels de traço) foram desenhados no mesmo molde. **Largura**: 9 letras e 2 espaços em 128 pixels, com os espaços do original (1 pixel entre letras, 4 entre palavras); cabe porque o I é estreito e o J tem 2 pixels a menos. O texto ocupa os pixels 0–127 (o original, 3–124): a 1.ª e a última coluna são só contorno, preto como o fundo, então a margem visível é de 1 pixel de cada lado (era 4) e o texto fica centralizado como o original. O tilemap e o script de slots não mudam (nenhum patch). No build, o bloco recomprimido (473 bytes) não cabe no lugar e vai para a região livre.
- **Teste**: `testes/test_texto_tiles.py::test_game_over_no_jogo` usa uma cópia da ROM em `tmp_path` com o `bpl.b` de `0x903C` trocado por `nop` (`4E71`) e o checksum refeito: passada a fala de abertura (A a cada 60 quadros), o laço cai no game over. A captura é feita 60 quadros depois de o bloco `0xFF` entrar no slot 9 e os 32 tiles aparecerem no plano A (~1 200 quadros depois do NEW GAME), sem apertar mais nada. Confere o VRAM (`0x120–0x13F` = bloco), as linhas 12–13 do plano A e, na tela, fundo e contorno pretos e o traço com a cor da linha, igual nas duas ROMs. Capturas: `build/capturas/game_over_base/` e `game_over_ptbr/` (`game_over.png` e a faixa do texto ampliada 4 vezes, `game_over_4x.png`).

## 8.1 Save em EEPROM e o patch anti-travamento

- O save é uma EEPROM serial X24C01 (128 bytes) acessada por I2C em `$200001`
  (bit 0 = SDA lido; escrita de SDA/SCL pelos bits 0/1). Rotinas em `0x1C4AC–0x1C5A4`:
  `0x1C4C4`/`0x1C4D0` sobem/descem SCL, `0x1C4F0` lê 1 byte, `0x1C51A` escreve 1 byte,
  `0x1C538–0x1C558` confere o ACK.
- Original em `0x1C552`: sem ACK (bit 0 = 1), `bsr.w $1C57E` (STOP) e laço infinito
  (`nop; bra.b *-2`). É o travamento no START em emuladores sem a EEPROM.
- O cabeçalho declara `RA E8 40` com RAM de `0x200001` a `0x200001`. Emuladores que
  usam só o cabeçalho criam 1 byte de SRAM, e o jogo não recebe ACK.
- ares: a EEPROM é ligada por hash (SHA-256) da ROM original
  (`6b2ac36f…7a43b9`, modo X24C01, `rsda=0 wsda=0 wscl=1`). Genesis Plus GX reconhece pelo
  código do produto `G-4060`.
- Patch `eeprom.nack_sem_trava` (`config/patches.yaml`): `6100002A 4E71` →
  `4EF9 0001C57E` (`jmp $1C57E.l`): sem ACK manda o STOP e
  retorna. Com a EEPROM presente o ACK sempre chega e o caminho não roda
  (`testes/test_patches.py::test_save_e_load_iguais_com_patch`: grava na estalagem,
  reinicia, CONTINUE carrega o mesmo estado de RAM com e sem o patch).
- **Conteúdo do save** (descoberto ao converter os save states do ares do autor para o
  Genesis Plus GX; conferido byte a byte contra uma gravação real na estalagem). O script da
  estalagem chama o subop `0B 15` (`0x198A` → `0x1C330`), que monta 64 bytes em `$FF3300`:
  +2 quatro espaços; +7 nibbles de `$9F10`; +8 `$965E` (última estalagem) no nibble alto e
  o nibble baixo de `$962D`; +9/+A `$962E`/`$962F` (ouro, 20 bits com o nibble anterior);
  +B `$959C`; +C `$9F00`; +D–F `$95BE`/`$95C0`/`$95C2` compactados; +10 long `$95CA`; +14
  word dos equipamentos (`$95CE–$95D1`, `$959D`, `$959E`); +16 16 bits de posse de
  `$958C–$959B` (só tem/não tem); +18 36 bytes de `$99BA`; +3C checksum = soma dos bytes
  +2..+3B + `0x1234`; +3E zero. Depois o subop `0B 0B` (`0x18C6` → `0x1C494`) grava esses 64
  bytes na EEPROM a partir do endereço 0, em páginas de 4 bytes; não há slots e os bytes
  64–127 não são usados. O local exato e os corações atuais não são gravados: o CONTINUAR
  volta na última estalagem, com os corações cheios.
- O `.srm` do Genesis Plus GX (libretro) para este jogo é a EEPROM crua a partir do
  endereço 0 (64 bytes depois de uma gravação). Num save state do ares (`BST1`, v145) a RAM
  de trabalho de 64 KB começa no deslocamento `0x2B0`, em words little-endian; com ela dá
  para montar o mesmo buffer de 64 bytes e gerar um `.srm` (foi o que se fez para o autor,
  com um script fora do repositório).

## 9. Referências externas

Não há ROM map público deste jogo (Data Crystal, romhacking.net). Existe um text dump (oblivion, 2009) útil como checklist de cobertura: video-games-museum.com, FAQ 3698.
