# Guia de tradução

Regras e decisões de estilo para preencher o campo `pt` em `traducao/textos/*.yaml`.
Nasceu do piloto (abertura, placa de Alsedo, senhora, loja) e é atualizado conforme a
tradução avança.

## Fluxo de trabalho

1. Editar o `pt` da entrada e mudar o `status` para `traduzido`.
2. `python -m ferramentas verificar`: barra linha longa (janela padrão de 23 colunas),
   mais de 3 linhas por página, caractere sem glifo e código de controle faltando ou
   fora de ordem.
3. `python -m ferramentas revisao --lote ID`: gera o relatório do lote em
   `build/revisao/<ID>.html` (lotes em `traducao/lotes.yaml`). Para cada entrada: onde
   aparece, quem fala, o original, a tradução e as páginas como a janela do jogo as
   mostra, desenhadas com a fonte do jogo (▼ = espera o botão; fundo vermelho = linhas
   que rolam antes de o jogador ler; caixa azul = nome de item ou preço, que entram em
   tempo de execução). Com `--capturas`, monta a ROM e roda cada diálogo do lote no
   emulador (só o primeiro caminho; lento, precisa da ROM e do core); as telas entram no
   relatório. `--lote todos` gera `build/revisao/todos.html`, com o progresso por arquivo
   e por status e o relatório de cada lote.
4. `python -m ferramentas construir` e conferir a cena no jogo.
5. Depois da revisão jogando, `status: revisado`.

## Estilo

- **Linguagem natural e fluida**, como uma conversa em português do Brasil. Prioridade
  sobre a fidelidade literal: adaptar a frase inteira em vez de traduzir palavra por
  palavra ("You have a discriminating eye" → "Você tem bom gosto!").
- **O tom vem do original e do contexto da cena.** Analisar quem fala, com quem e em
  que situação: vendedor simpático, guarda ríspido, vilão ameaçador, cena triste.
  "Natural" é como um falante de português diria *aquilo* naquela situação, não
  deixar tudo simpático.
- Ler o trecho inteiro antes de quebrar as linhas: cada `[espera]` fecha uma ideia, e as
  quebras não cortam expressões ("trazer / a paz novamente / à sua terra").
- Gramática cuidada (crase, acentos, concordância) mesmo em textos curtos.
- Títulos em minúscula antes do nome ("a rainha Eleanora", "a princesa"). Artigo antes
  de nome de pessoa segue a fala: moradores e conhecidos usam ("Pergunte à Sonia", "Eu
  sou a Sonia"); em fala mais formal ou de realeza, sem artigo ("Leve Priscilla com
  você"). Vale só para nomes fixos no texto, nunca para os inseridos pelo jogo.
  Poseidon é deus, não morador: fica sem artigo como nome de divindade ("encontrar
  Poseidon", "o Tridente de Poseidon").
  Os dragões sábios (o Dragão Ancião e o dragão da Capital do Gelo) falam de modo solene,
  como a realeza: "Leve Shabo com você.". O ferreiro e os moradores de Begonia são
  informais ("Vai lá falar com ele.").
- Na fala informal, "você" com "te" é aceito ("é só voltar aqui que eu te ajudo").
- Algumas janelas são mais estreitas que 23 colunas (a da rainha Eleanora tem 21); o
  `verificar` usa a largura real de cada diálogo.
- Cada `[linha]` começa na coluna 2, então sobram 21 colunas de texto na janela de 23 e
  17 na de 19 (a do Dragão Ancião, `dialogo.073`). Termo do glossário que não cabe nisso
  se parte entre palavras; o `verificar` lê o termo partido por `[linha]`, `[quebra2]`
  ou `[espera]` como inteiro. Não misture `[linha]` e `[quebra2]` no mesmo diálogo: a
  linha na coluna 0 fica fora do alinhamento das outras. Em `dialogo.073.t07`,
  "Castelo de Purapril" (19) fica "Castelo de" / "Purapril, suba na".

## O que pode e o que não pode mudar

- **Livres** (pode mover, tirar ou acrescentar): `[linha]` (nova linha com recuo de 2),
  `[quebra2]` (nova linha na coluna 0), `[espera]` (aguarda o botão; a janela rola),
  `[cor]` e `[/cor]`.
- **Obrigatórios, na mesma ordem do original:** `[nome:XX]`, `[item:XX]`, `[s0:XX]`,
  `[s3:XX]` e os códigos com argumento (`[$03][$06]`, `[$04][$02]`, `[$0A][$02]`…).
- Cada entrada (`.tNN`) é um pedaço entre lógicas do jogo (escolhas, saltos). O texto
  não atravessa essa fronteira: cada pedaço precisa fazer sentido sozinho.

## Variáveis no meio da frase

- Nomes de itens, magias e preços entram em tempo de execução (`[s0:02]`, `[s0:03]`).
  **Não usar artigo nem concordância de gênero com eles.** O mesmo texto serve para
  "Excalibur" e para "Elixir".
  - Bom: "Este item é [s0:02]." / "Custa[s0:03]."
  - Evitar: "Aqui está a [s0:02]".
- O preço já vem com espaço à esquerda e a palavra `MOEDAS` ("Custa 2500 MOEDAS.").
- A diária da estalagem (`[s0:05]`) também: "Uma boa noite de sono / custa 15 MOEDAS."
  (`b0.005.t00` avança 1 coluna antes do valor; no original eram 3, porque o preço
  começava a linha).

## Scripts compartilhados

- `banco3_lojas` (`b3.000`) é o diálogo de **todas** as lojas e `b3.001` o de todas as
  estalagens. O texto não pode supor o gênero de quem fala: "Agradeço a compra!" em vez
  de "Muito obrigada!".

## Termos (glossário inicial)

| Original | PT-BR | Nota |
|---|---|---|
| Monster World | Monster World | nome do mundo e do jogo, mantido |
| Shion, Purapril, Alsedo… | (mantidos) | nomes próprios |
| Purapril Castle | Castelo de Purapril | |
| the fairy village | a vila das fadas | placas: "Alsedo, / a vila das fadas" |
| the dwarf village | a vila dos anões | placa: "Lilypad, / a vila dos anões" |
| Maugham Desert | Deserto de Maugham | lugares: a parte genérica é traduzida, o nome próprio fica |
| Aqua Capital / Ice Capital | Capital das Águas / Capital do Gelo | confirmado pelo autor |
| Ice World / Ice Castle | Mundo do Gelo / Castelo de Gelo | "de Gelo": o castelo é feito de gelo |
| Darkworld / Devil World | Mundo das Trevas | o inglês alterna os dois nomes para o mesmo lugar |
| Prince of the Devil World | Príncipe do Mundo das Trevas | título, não nome próprio |
| Nightmare Castle / Castle of Illusion | Castelo do Pesadelo / Castelo da Ilusão | |
| Bell Tower / Pyramid | Torre do Sino / Pirâmide | |
| Biomeka / Bio-Mecha | Bio-Mecha | o chefe final; o inglês grafa dos dois jeitos, em PT só a forma do banco 2 (`b2.029`) |
| Gold Gem / Blue Gem | Topázio / Safira | nas falas do encaixe (`dialogo.115`, `.116`), como os itens do banco 1 |
| Elder Dragon | Dragão Ancião | título com palavras comuns, traduzido |
| Gragg & Glagg / Almighty Demon King | (mantidos) | chefes; avisos "Gragg & Glagg!" e "O Almighty Demon King!", no padrão de "O Myconid!" |
| Wonder Boy | Wonder Boy | nome da série (desfecho) |
| Blacksmith | ferreiro | profissão, não nome: minúscula e com artigo ("o ferreiro") |
| Sphinx | Esfinge | monstro, mas palavra comum com forma consagrada (confirmado pelo autor) |
| Monster (banco 2) | Monstro | palavra comum, não nome (confirmado pelo autor) |
| GOLD | MOEDAS | decisão do autor; sempre em maiúsculas, como o original |
| YES / NO | SIM / NÃO | mesmas colunas (o "N" na coluna 5) para a seta alinhar |
| SELECT | SELECIONAR | cabeçalho do menu do START |
| WEAPON / ARMOR / SHIELD / BOOTS / ITEM / MAGIC | ARMA / ARMADURA / ESCUDO / BOTAS / ITEM / MAGIA | menus, com **ARMA** (decisão do autor) |
| FIRE STORM / QUAKE / THUNDER / POWER / SHIELD / RETURN | BOLAS DE FOGO / TERREMOTO / TROVÕES / SUPER FORÇA / BLINDAGEM / VOLTAR | magias, com **TERREMOTO** (decisão do autor) |
| AP / DP / SP | PA / PD / PE | tela de status |

Nomes de pessoas e monstros ficam como no inglês (Eleanora, Myconid, Hotta, Bio-Mecha…).
Lista completa, com o motivo de cada decisão, em `traducao/glossario.yaml`; o mapa de
cenas (lote, lugar e quem fala de cada diálogo) em `traducao/lotes.yaml`.

O `onde` do mapa de cenas foi deduzido do texto e pode errar: em Alsedo apareceram em
inglês uma loja, uma placa, a estalagem e o aviso do chefe da caverna, que estavam em
lotes posteriores. O que o autor confere no jogo é movido para o lote certo, com
"(conferido pelo autor no jogo)" no `onde`. Avisos curtos de sistema (nome do chefe ao
aparecer, placas) entram no lote da região onde aparecem, não num lote "de chefes".

## Observações visuais

- Maiúsculas acentuadas (Ã, É…) ficam apertadas no tile de 8×8 (o acento divide o
  espaço com a letra). São legíveis, mas no texto corrido
  prefira frases que não dependam delas em excesso.
- O texto aparece letra por letra; a página só fecha no `[espera]`.

## Decisões do autor (piloto)

- **Itens e magias são traduzidos** (banco 1 e menu de magias). Nomes que já são
  próprios ficam (Excalibur, Elixir). Se a forma completa não couber num slot fixo, usar
  uma forma curta coerente e registrar aqui.
- **GOLD vira MOEDAS em todo lugar**, inclusive nos pontos de tamanho fixo: o rótulo do
  HUD (Plano 4, Task 1) e a mensagem do baú (`bau.ouro`, Task 2). A tela de status não
  tem rótulo de ouro.

## Nomes de itens (`banco1_itens.yaml` e `banco1_menu.yaml`)

- **Completo** (`banco1_itens`, `b1.XXX`): o nome dos diálogos, da loja (`[s0:02]`) e do
  baú ("Você achou Botas de Couro."). No máximo **18 colunas**: a linha do baú
  ("Você achou " + nome + "." em 30 colunas; o buffer da cópia do nome tem 32 desde os
  patches `buffer_nome.*`); o `verificar` acusa.
- **Menu** (`banco1_menu`, `b1m.XXX`, mesmo índice): o nome nas listas do menu do START.
  Vazio = a tela mostra o completo. Largura por tela (o `verificar` acusa o nome que a
  tela mostra, curto ou completo): **ARMA, ARMADURA, ESCUDO e BOTAS 17** colunas (nome
  centrado nas colunas 14–30, com a seta do cursor na 13; patches `lista_equip.*`, na base
  eram 14); **ITEM 9** (três
  colunas de 10, a última encosta na moldura).
- Nas telas de equipamento todos os nomes completos cabem, então **o menu mostra o
  completo** (decisão do autor: em ARMA os itens não se explicam sozinhos, há espadas e
  lanças, e as outras telas seguem o mesmo padrão). Nome curto só onde não cabe: hoje só
  na tela ITEM ("Chave do Sol" → "Chave Sol").
- Armas são espadas e lanças (não "Poder X"); magias como no menu de magias
  (TERREMOTO); nomes próprios ficam (Excalibur, Gradius, Elixir).
- Só traduzir quando o português soar natural: termos da série e nomes que funcionam em
  inglês ficam (Gradius, Rapid Pad, **Pygmy**: "Espada Pygmy", também no menu).
- Sem artigo antes do nome no texto ("Aqui estão [s0:02]"): o mesmo texto serve para
  qualquer item.
- **Knight** vira **Militar** (sugestão do autor): "Espada/Armadura/Escudo do Cavaleiro"
  (19–21 colunas) não cabia no menu nem no baú; "Militar" cabe em todo lugar e o nome é
  o mesmo nas falas e no menu.
- **Hard** vira **Robusta/Robusto** (escolha do autor; "Armadura Reforçada", com 18
  colunas, não cabe nas 17 do menu).
- Os slots `b1.026` e `b1.030` têm lixo do original e não são usados: ficam vazios.

**Armas (tela ARMA)**

| Original | Completo | Menu | Nota |
|---|---|---|---|
| Legend Sword | Espada Lendária | — |  |
| Excalibur | Excalibur | — | nome próprio |
| Knight Sword | Espada Militar | — | Knight → Militar (autor) |
| Gradius | Gradius | — | nome próprio |
| Battle Spear | Lança de Batalha | — |  |
| Trident | Tridente | — |  |
| Small Spear | Lança Curta | — |  |
| Pygmy Sword | Espada Pygmy | — | Pygmy: termo da série, fica |

**Armaduras (tela ARMADURA)**

| Original | Completo | Menu | Nota |
|---|---|---|---|
| Legend Armor | Armadura Lendária | — |  |
| Flame Armor | Armadura de Fogo | — |  |
| Knight Armor | Armadura Militar | — | Knight → Militar (autor) |
| Steel Armor | Armadura de Aço | — |  |
| Hard Armor | Armadura Robusta | — | Hard → Robusta (autor) |
| Chain mail | Cota de Malha | — | não leva a palavra da categoria |
| Leather Armor | Armadura de Couro | — |  |
| Pygmy Armor | Armadura Pygmy | — |  |

**Escudos (tela ESCUDO)**

| Original | Completo | Menu | Nota |
|---|---|---|---|
| Legend Shield | Escudo Lendário | — |  |
| Flame Shield | Escudo de Fogo | — |  |
| Knight Shield | Escudo Militar | — | Knight → Militar (autor) |
| Steel Shield | Escudo de Aço | — |  |
| Hard Shield | Escudo Robusto | — | Hard → Robusto (autor) |
| Shell Shield | Escudo de Concha | — |  |
| Wood Shield | Escudo de Madeira | — |  |
| Pygmy Shield | Escudo Pygmy | — |  |

**Botas (tela BOTAS)**

| Original | Completo | Menu | Nota |
|---|---|---|---|
| Legend Boots | Botas Lendárias | — |  |
| Ceramic Boots | Botas de Cerâmica | — |  |
| Oasis Boots | Botas do Oásis | — |  |
| Marine Boots | Botas Marinhas | — |  |
| Ladder Boots | Botas de Escalada | — |  |
| Leather Boots | Botas de Couro | — |  |
| Cloth Boots | Botas de Pano | — |  |
| Pygmy Boots | Botas Pygmy | — |  |

**Magias (só diálogos, loja e baú; o menu de magias é o bloco `menu.magias`)**

| Original | Completo | Menu | Nota |
|---|---|---|---|
| Fire Storm | Bolas de Fogo | — | magia; como no menu de magias (Task 3) |
| Quake | Terremoto | — | magia; TREMOR DE TERRA -> TERREMOTO (autor) |
| Thunder | Trovões | — | magia |
| Power | Super Força | — | magia |
| Shield | Blindagem | — | magia |
| Return | Voltar | — | magia |

**Consumíveis e itens de missão fora das listas (só diálogos, loja e baú)**

| Original | Completo | Menu | Nota |
|---|---|---|---|
| Ocarina | Ocarina | — |  |
| Charmstone | Pedra Encantada | — |  |
| Elixir | Elixir | — | nome próprio |
| Medicine | Remédio | — |  |
| Potion | Poção | — |  |
| Holywater | Água Benta | — |  |
| Hi-Potion | Super Poção | — |  |
| Heart | Coração | — |  |

**Itens (tela ITEM)**

| Original | Completo | Menu | Nota |
|---|---|---|---|
| Lamp | Lamparina | — |  |
| Amulet | Amuleto | — |  |
| Sun-Key | Chave do Sol | Chave Sol |  |
| Moon-Key | Chave da Lua | Chave Lua |  |
| Star-Key | Chave da Estrela | C.Estrela | fica na coluna 22: 9 colunas até a moldura |
| Gold-Gem | Topázio | — | Gold-Gem; pedra dourada |
| Blue-Gem | Safira | — | Blue-Gem; pedra azul |
| Old Axe | Machado Velho | Machado |  |
| Fire-Urn | Urna de Fogo | Urna |  |
| Bracelet | Bracelete | — |  |
| Rapid Pad | Rapid Pad | — | nome do aparelho, mantido |

## Mensagens do baú (`inline.yaml`, `bau.*`)

- Montagem: `bau.achou_o` + nome do item + `bau.ponto` e `bau.achou` + valor + `bau.ouro`.
  Ex.: "Você achou Botas de Couro." / "Você achou 25 MOEDAS." (sem artigo antes do
  nome, que é variável).
- São repontáveis (sem o limite do slot original), mas a linha tem 30 colunas: os textos
  fixos + 16 (nome do item) ou + 6 (dígitos) não podem passar disso. O `verificar` acusa.

## Ocarina (`inline.yaml`, `ocarina.*`)

- Slots de tamanho fixo (completados com espaço à direita): `ocarina.N.shion` tem 11
  colunas e `ocarina.N.the` 4. A frase é `ocarina.N.shion` + `ocarina.N.the` + nome do
  item (a Ocarina, `b1.028`, em amarelo) + ".". No original havia uma nova linha entre os
  dois slots; os patches `ocarina.*.linha` a trocam por um código que não imprime nada.
- "Shion plays the Ocarina." vira "Shion toca sua Ocarina." (23 colunas, uma linha, pedido
  do autor): "a" sozinho deixaria espaços sobrando antes do nome, e "sua " ocupa as 4
  colunas exatas.
- Depois dessa frase o jogador toca as notas: melodia certa → `ocarina.3.voce`; nota
  errada → `ocarina.5.melodia`; nada tocado a tempo → `ocarina.4.*` ("Mas eu não sei tocar
  / bem.", a desculpa do Shion; o autor preferiu manter a primeira pessoa do original).
- `ocarina.4.mas` + nova linha + `ocarina.4.bem` é uma frase só, quebrada em duas linhas.
- A janela tem 23 colunas e o `verificar` não mede esses slots: o motor quebra no meio da
  palavra o que passar disso (o slot `ocarina.5.melodia` tem 29). Manter cada linha em
  até 23 colunas. Conferido no emulador copiando os mini-scripts para o diálogo 0.

## Quiz da Esfinge (`banco0_sistema`, `b0.00B`–`b0.032`; `inline.yaml`, `quiz.*`)

- O `verificar` não mede o quiz: medir à mão. Janela 4, 17 colunas. **Pergunta**: até
  17 colunas por linha, linhas separadas por `[quebra2]`, no máximo 4 linhas. A área da
  pergunta tem 2 linhas e rola: quando as respostas aparecem, só as **duas últimas
  linhas** ficam na tela, então elas devem carregar o essencial ("a loja Wanderer / não
  vende?"). **Resposta**: começa na coluna 3, depois do ícone A/B/C, então no máximo
  **14** colunas ("5000000 MOEDAS" ocupa as 14).
- Respostas que são itens usam o nome do banco 1 quando cabe ("Escudo de Aço",
  "Lamparina"); as chaves usam a forma curta do menu ("Chave Sol", "Chave Lua") e
  "Chave Estrela" (o menu tem "C.Estrela"; "Chave da Estrela" passa de 14; confirmado pelo autor). Magias como
  nos itens ("Bolas de Fogo", "Terremoto"). Nomes de pessoas, monstros e lojas ficam.
- Respostas inventadas seguem a piada do original quando dá: "Puss'n Boots" → "Gato de
  Botas"; "Desert Boots" → "Botas de Areia" (14). "Lilian / Lilypad / Lollipop" ficam,
  porque a graça é o som parecido.
- Termo do glossário que não cabe em 17 colunas: a pergunta é montada para a quebra
  automática cair entre duas palavras (a linha enche as 17 colunas terminando em espaço
  e a palavra seguinte desce para a coluna 0). Em `b0.02B` a linha "cruzou o Deserto "
  tem 17 colunas e "de Maugham?" desce sozinho; assim "Deserto de Maugham" fica inteiro
  no texto, como o glossário pede (conferido no emulador).
- `quiz.*` são slots de tamanho fixo (10, 10 e 8 colunas): "Sem tempo.", "Errou.",
  "Acertou.".
- A Esfinge fala solto e brincalhão ("Tenho um fraco por um bom quiz", "Lá vai a
  primeira pergunta."), sem adjetivo de gênero sobre si mesma.

## Lojas com nome próprio

- Cada loja tem a sua voz (a Bacchus se gaba do atendimento, a Kishera e a Labyrinth são
  formais e falam em "nós", o dragão é brincalhão, a Gooningle's ri de si mesma). O
  aviso de estoque esgotado segue essa voz em vez de repetir uma frase padrão.
- Quem avisa que acabou é quem vende, falando do próprio estoque: "estamos sem estoque",
  "o nosso estoque esgotou". Nunca "acabou o estoque desse aí" ou "esse item está em
  falta": o jogador fala com o vendedor e escolhe o item na prateleira, não aponta para
  ele (revisão do autor em Alsedo).
- Nome de loja leva "à" (a loja): "Bem-vindo à Kishera". Agradecimento sem gênero
  ("Agradecemos!", "Agradeço."), nunca "obrigado/obrigada".

## Desfecho (`dialogo.122`–`.127`)

- Janela 6 (23 × 3), texto impresso devagar e sem `[espera]`: a janela rola sozinha e só
  as 3 últimas linhas ficam na tela. Por página, no máximo as linhas que o `en` tem
  (mapa-rom.md §5, "O final"); termo do glossário numa linha só ("Monster World").
- `.122`–`.126` são um narrador só, em tom de fecho de história ("Enfim, a longa e
  perigosa jornada chegou ao fim."); `.123` e `.124` são uma frase só, partida em duas
  telas ("Ninguém em Monster World jamais vai esquecer o que passou," / "nem o herói
  que lhes devolveu a vida de antes."). `.127` é a princesa: "Bem-vindo de volta, Shion."

## Créditos (`inline.yaml`, `creditos.*`)

- Só os cargos são traduzidos; os nomes ficam. Slots de tamanho fixo (`tam` em
  config/texto.yaml), em maiúsculas como no original; os glifos acentuados aparecem na
  cena dos créditos (Ú conferido no emulador).
- O jogo centra cada linha em 20 colunas pelo tamanho do slot inteiro, espaços incluídos
  (`0x1AF6A`: `(20 − tam) / 2`, arredondado para cima). Cargo mais curto que o slot leva
  espaços à esquerda para continuar centrado: `(tam − n) / 2` (" DESIGN  ", 6 em 9).
- Formas curtas onde a completa não cabe: **PROG. CHEFE** (CHIEF PROGRAMMER, 16;
  "PROGRAMADOR-CHEFE" tem 17), **PROG.** (PROGRAMMER, 10; "PROGRAMADOR" tem 11),
  **MÚSICA E SONS** (MUSIC / EFFECTS, 15), **DESIGN** (DESIGNERS, 9). Ficam iguais:
  **STAFF** (5; "EQUIPE" tem 6, e "staff" é de uso corrente em créditos) e
  **SUPERVISOR**. **DIRETORES** e **AGRADECIMENTOS** cabem exatos.

## Menus e magias (`inline.yaml`, `menu.*`, `magia.*`, `magia_hud.*`)

- São blocos repontáveis (sem o limite do slot original), mas cada rótulo tem a largura
  do seu painel; o `verificar` acusa (colunas: cabeçalhos 11, ITEM/MAGIA 14; opções 7 à
  esquerda e 8 à direita; magias 14 à esquerda e 13 à direita; HUD 10).
- Os cabeçalhos das telas SELECIONAR, ARMA, ARMADURA, ESCUDO e BOTAS são escritos um por
  cima do outro: todos com o mesmo tamanho, completados com espaços dos dois lados para
  ficarem centrados (`"   ARMA   "`).
- `magia_hud.*` é o nome que aparece no HUD ao lançar a magia, centrado em 10 colunas:
  forma curta quando o nome do menu não cabe ("BOLAS DE FOGO" → "FOGO", "SUPER FORÇA" →
  "FORÇA"); os outros ficam iguais aos do menu.
