# Tradução em lotes: plano de implementação

**Goal:** preencher todo `pt` que falta (diálogos, placas, lojas e estalagens, nomes de
lugares, quiz, ocarina e créditos) em lotes por região da história, cada lote entregue
com um relatório de revisão que mostra cada página como o jogo a exibe, até a ROM ficar
pronta para a revisão jogando do autor.

**Architecture:** duas peças de ferramenta antes da tradução. (1) `traducao/lotes.yaml`:
o mapa de cenas, que diz a que lote, lugar e personagem pertence cada diálogo e script,
e serve de contexto para traduzir e revisar. (2) O comando `revisao`, que gera
`build/revisao/<lote>.html` com o original, a tradução e as páginas desenhadas com a
fonte do jogo, simuladas pela mesma análise de fluxo do `verificar`, e, com
`--capturas`, as telas reais do emulador. Depois, um lote por tarefa: traduzir, passar
no `verificar`, gerar o relatório e commitar.

**Tech Stack:** Python 3.11+, PyYAML, Pillow e pytest (o que o projeto já usa), o core
libretro do emulador já fixado em `emu/`.

**Spec:** `docs/projeto/design/2026-11-11-traducao-wbmw-ptbr-design.md` (§5 regras,
§5.1 quem faz o quê, §7 fases 7 a 9). Regras de estilo e decisões do autor:
`docs/projeto/guia-traducao.md`. Referência técnica: `docs/tecnico/mapa-rom.md` §5
(janelas, quebras, páginas) e `docs/tecnico/vram.md`.

**Escopo:** fases 7 (tradução do texto) e 8 (gráficos com texto que ainda faltarem) do
design. A revisão jogando (fase 9) é do autor e começa no fim deste plano. A
distribuição (IPS final, README de aplicação) fica para o plano seguinte.

## Global Constraints

- Mensagens de commit simples, **sem menção a IA e sem linhas de coautoria**; nada de IA
  em código ou documentação.
- Só commitar com a suíte inteira passando e o `verificar` com **0 erros**.
- Nenhuma ROM no git; o build continua determinístico; **CRC32 `1592f5b0` e checksum
  `9D79`** continuam iguais aos da ROM original (`compensacao` em `config/rom.yaml`).
- Estilo (guia, "Estilo"): **linguagem natural e fluida**, PT-BR conversado; **o tom vem
  do original e da cena** (vendedor simpático, guarda ríspido, vilão ameaçador, cena
  triste); adaptar a frase inteira; quebras que não cortam expressões; gramática
  cuidada.
- Nomes de pessoas e monstros ficam (design §5). Lugares: a parte genérica é traduzida
  ("Purapril Castle" → "Castelo de Purapril"); o nome próprio fica.
- GOLD → MOEDAS; itens com os nomes de `banco1_itens` (Knight = Militar, Hard =
  Robusta, Pygmy fica); magias como no menu (TERREMOTO).
- Códigos obrigatórios na mesma ordem (`[nome:XX]`, `[item:XX]`, `[s0:XX]`, `[s3:XX]`,
  `[$xx]` com argumento); `[linha]`, `[quebra2]`, `[espera]` e `[cor]` são livres. Cada
  `.tNN` faz sentido sozinho.
- Sem artigo nem concordância com nomes inseridos em tempo de execução; scripts
  compartilhados (lojas, estalagens) neutros em gênero.
- A tradução parte do inglês.
- Entrada traduzida = `status: traduzido`. `revisado` só depois do autor jogar.

## Review Focus

1. **Trecho alcançado por mais de um caminho** (saltos, escolhas SIM/NÃO, flags): a
   página tem de caber a partir do pior estado de entrada, não só do caminho que o
   relatório ou a captura mostram. Coberto pelo `verificar`; o relatório marca quais
   páginas foram simuladas e quais foram vistas no emulador.
2. **Mesmo termo traduzido de dois jeitos em lotes diferentes** (lugares, títulos como
   "Elder Dragon", "legendary hero"): cada termo recorrente entra no
   `glossario.yaml` no lote em que aparece primeiro, e o `verificar` avisa as
   divergências. Teste na Task 2.
3. **Texto que aparece fora da janela padrão** (janela 4 do quiz com 17 colunas, janela
   7 com uma linha, final na janela 6 que rola devagar): a largura vem da janela do
   diálogo; o relatório desenha cada página com a largura certa. Teste na Task 1.
4. **Simulação divergente do jogo:** o relatório não pode mostrar uma página diferente
   da que o emulador mostra. Teste na Task 1 comparando a simulação com a captura do
   piloto.
5. **Strings japonesas que sobraram** (`b1.026`, `b1.030`, `b2.006` e o que
   `test_texto_ingles_nao_usa_kana` lista): ficam vazias, nunca "traduzidas".

---

### Task 1: Comando `revisao` (relatório por lote)

Promove para o projeto o gerador do relatório usado na revisão do Plano 4 (até aqui um
script avulso) e acrescenta a simulação das páginas.

**Files:**
- Create: `ferramentas/revisao.py`, `testes/test_revisao.py`
- Modify: `ferramentas/cli.py` (subcomando `revisao`), `ferramentas/verificacao.py`
  (expor a simulação de páginas que `_Larguras` já calcula), `docs/projeto/guia-traducao.md`
  ("Fluxo de trabalho")

**Interfaces:**
- Produces:
  - `def paginas(ctx: Contexto, entrada_id: str) -> list[Pagina]`: as páginas do `pt`
    como o motor de texto as exibe, a partir do pior estado de entrada (o mesmo do
    `checar_linhas`). `Pagina = {linhas: list[str], largura: int, altura: int,
    espera: bool}`; variáveis em tempo de execução viram marcadores legíveis
    (`‹item›`, `‹preço›`, `‹SIM/NÃO›`, o nome de `[nome:XX]` do `banco2`).
  - `def desenhar(pagina: Pagina, fonte_png: Path) -> PIL.Image.Image`: a janela com a
    fonte do jogo (índices 0/1 = fundo; texto de `[cor]` em amarelo).
  - CLI: `python -m ferramentas revisao --lote ID [--capturas]` grava
    `build/revisao/<ID>.html`. Para cada entrada do lote: onde aparece (de
    `lotes.yaml`), quem fala, original, tradução, páginas desenhadas e, com
    `--capturas`, as telas do emulador (entrada 0 da tabela de diálogos trocada pela do
    diálogo, só na ROM de teste, como em `testes/test_nomes_menu.py::_trocar_dialogo_0`).
  - `--lote todos` gera um índice com o progresso por arquivo e por status.

- [ ] **Step 1:** testes em `test_revisao.py`:
  - `test_paginas_do_piloto`: `paginas(ctx, "dialogo.000.t01")` dá as 4 páginas da
    abertura aprovada (uma por `[espera]`), com as linhas fixadas no teste; com a ROM e
    o core, as mesmas linhas lidas do tilemap da janela nas capturas do emulador (como
    `test_validacao_jogo.py` já faz).
  - `test_paginas_janela_estreita`: entrada de teste na janela 4 (17 colunas) quebra
    onde o jogo quebra; `largura == 17`.
  - `test_variaveis_legiveis`: `b3.000.t00` mostra `‹item›` e `‹preço›` no lugar dos
    códigos.
  - `test_html_do_lote`: `revisao --lote piloto` (lote de teste com as entradas do
    piloto) gera um HTML com uma linha por entrada, o `en`, o `pt` e uma imagem por
    página; entrada sem `pt` aparece como "pendente".
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar `paginas` sobre a análise de fluxo de `verificacao.py`
  (sem duplicar as regras de `[linha]`, `[quebra2]`, `[espera]` e rolagem), `desenhar`
  e o comando.
- [ ] **Step 4:** rodar `pytest testes/test_revisao.py -v`. Esperado: PASS.
- [ ] **Step 5:** guia: passo "gerar o relatório do lote" no fluxo de trabalho.
- [ ] **Step 6:** suíte inteira verde; commit `revisao: relatório por lote com as páginas
  simuladas e capturas do emulador`.

### Task 2: Mapa de cenas (`lotes.yaml`) e glossário de lugares

**Files:**
- Create: `traducao/lotes.yaml`, `testes/test_lotes.py`
- Modify: `traducao/glossario.yaml`, `traducao/textos/banco2_nomes.yaml`,
  `docs/projeto/guia-traducao.md` ("Termos")

**Interfaces:**
- Produces: `traducao/lotes.yaml` = lista de lotes `{id, titulo, entradas: [{id,
  onde, quem, nota}]}`, onde `id` é um diálogo (`dialogo.NNN`, todas as suas `.tNN`), um
  script do banco 3 (`b3.NNN`) ou uma entrada de outro arquivo (`b0.NNN.tNN`,
  `inline.*`, `b2.NNN.tNN`). Consumido pelo `revisao` (Task 1) e pelas Tasks 3–9.

- [ ] **Step 1:** testes em `test_lotes.py`:
  - `test_toda_entrada_em_um_lote`: toda entrada com `en` traduzível de
    `dialogos`, `banco0_sistema`, `banco2_nomes`, `banco3_lojas` e `inline` está em
    exatamente um lote; as que ficam vazias (strings japonesas, slots sem uso) estão
    num lote `sem_traducao` com o motivo.
  - `test_lotes_conhecidos`: os ids dos lotes são os das Tasks 3–9, nesta ordem.
  - `test_glossario_de_lugares`: cada nome de lugar de `banco2_nomes` tem uma linha em
    `glossario.yaml` (`en`, `pt`, `nota`).
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** ler todos os diálogos e scripts e classificar por região e cena
  (`onde`: lugar e situação; `quem`: personagem, ou "placa", "narrador", "sistema").
  Diálogos vazios no texto (só chamam `[s3:XX]`) entram no lote do script que chamam.
  Lotes:
  1. `alsedo`: Alsedo, a floresta e o Castelo de Purapril no começo (inclui o piloto já
     aprovado, para contexto).
  2. `lilypad`: Lilypad e o deserto de Maugham.
  3. `begonia`: Begonia, o Elder Dragon e o Castelo de Gelo.
  4. `childam`: Childam e o Mundo das Trevas.
  5. `purapril`: a capital aquática, o santuário no fundo do mar e a Esfinge (quiz).
  6. `final`: chefes, o castelo final, o desfecho e os créditos.
  7. `geral`: lojas e estalagens (`banco3_lojas` e as saudações), placas, avisos curtos,
     mensagens de sistema e ocarina.
  A ordem e a divisão podem ser ajustadas pelo que a leitura mostrar (ruling no
  registro do plano); o teste fixa a lista final.
- [ ] **Step 4:** decidir os nomes de lugar (parte genérica traduzida, nome próprio
  mantido: "Maugham Desert" → "Deserto de Maugham", "Ice Capital", "Castle of Illusion",
  "Prince of the Devil World"…), gravar em `glossario.yaml` com a nota do motivo, e
  preencher `banco2_nomes` (pessoas e monstros ficam iguais ao `en`, com `status:
  traduzido`; `b2.006` vazio).
- [ ] **Step 5:** rodar os testes e o `verificar`. Esperado: PASS e 0 erros.
- [ ] **Step 6:** suíte verde; commit `traducao: mapa de cenas por lote e glossário de
  lugares`.

### Tasks 3–9: um lote por tarefa

Mesma forma para cada lote (`alsedo`, `lilypad`, `begonia`, `childam`, `purapril`,
`final`, `geral`, na ordem de `lotes.yaml`).

**Files:** `traducao/textos/*.yaml` (as entradas do lote), `traducao/glossario.yaml`
(termos novos), `docs/projeto/guia-traducao.md` (decisões de estilo novas).

- [ ] **Step 1:** ler o lote inteiro em inglês com o `onde`/`quem` de `lotes.yaml` antes de
  escrever qualquer `pt` (tom, quem fala com quem, o que vem antes e depois).
- [ ] **Step 2:** escrever o `pt` de cada entrada e marcar `status: traduzido`. Termo
  recorrente novo vai para o glossário; decisão de estilo nova vai para o guia.
- [ ] **Step 3:** `python -m ferramentas verificar`. Esperado: 0 erros, nenhum aviso de
  glossário. Ajustar o texto (nunca a regra) até passar.
- [ ] **Step 4:** `python -m ferramentas revisao --lote <id> --capturas` e ler cada página
  desenhada e cada captura: corte de expressão, linha sobrando, `[espera]` no meio de
  uma ideia, tom errado.
- [ ] **Step 5:** releitura de estilo do lote inteiro (naturalidade, tom da cena,
  consistência com os lotes anteriores e com o piloto).
- [ ] **Step 6:** suíte verde, `construir` com CRC `1592f5b0`; commit
  `traducao: lote <id>`.

Lote `final` (Task 8): o desfecho (`dialogo.122`–`.127`) roda devagar na janela 6 e
rola de propósito: por página, no máximo as linhas que o `en` tem (mapa-rom.md §5,
"O final"). Créditos: só os cargos são traduzidos; os nomes ficam.

Lote `geral` (Task 9): `b3.000`/`b3.001` são de todas as lojas e estalagens (neutros em
gênero; o piloto da loja já está aprovado); o quiz usa a janela 4 (17 colunas) com as
respostas na coluna 3; as frases da ocarina são montadas pelo código (`inline.ocarina.*`):
conferir a frase inteira no emulador.

### Task 10: Gráficos com texto que faltarem e fechamento

**Files:** `config/graficos.yaml` e `graficos/telas/` (se houver tela a traduzir),
`docs/tecnico/mapa-rom.md`, `docs/tecnico/pendencias.md`, `README.md`

- [ ] **Step 1:** varrer no emulador as telas que ainda não foram vistas (game over,
  créditos, final, telas de transição) e listar as que têm texto desenhado em tiles.
  Registrar em `mapa-rom.md` §8 (o logo do título fica, design §5).
- [ ] **Step 2:** para cada tela com texto desenhado: item em `config/graficos.yaml`,
  PNG editável, teste com captura (como `titulo`). Sem nenhuma, registrar isso.
- [ ] **Step 3:** `revisao --lote todos`: nenhuma entrada traduzível pendente; o
  índice mostra 100% `traduzido` (fora do lote `sem_traducao`).
- [ ] **Step 4:** teste `test_tudo_traduzido` (em `test_lotes.py`): toda entrada fora de
  `sem_traducao` tem `pt` e `status` ≥ `traduzido`.
- [ ] **Step 5:** pendências e README atualizados (o que falta: revisão jogando e
  distribuição); suíte verde; commit `traducao: texto completo, pronto para a revisão
  jogando`.

### Pontos de parada

- **Depois da Task 3 (lote `alsedo`)** o trabalho **para** para o autor revisar o
  relatório e jogar o começo: é a calibragem do tom e das quebras para os lotes
  seguintes. Os ajustes pedidos viram regras no guia antes da Task 4.
- **Depois da Task 10** o trabalho para de novo: o autor joga do início ao fim; as
  correções voltam para os YAML e as entradas validadas passam a `revisado`. A
  distribuição só começa depois disso, num plano próprio.
