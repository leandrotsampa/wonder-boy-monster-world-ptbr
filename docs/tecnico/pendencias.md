# Pendências técnicas

Registradas a partir da execução de 2026-11-11. A primeira seção lista o que falta antes da distribuição; as demais são itens menores, que não bloqueiam o uso atual.

## O que falta para a distribuição (plano de lotes, Task 10)

Nada. O texto está completo e foi revisado jogando, do início ao fim: toda entrada traduzível tem `pt` e status `revisado` (as entradas só com códigos, como `[s0:06]` ou `[espera]`, ficam vazias e `pendente`, e o montador mantém o original).

- [resolvido] **Revisão jogando**, pelo autor, do início ao fim, incluindo as placas `HOT` e `SAÍDA`, o `FIM DE JOGO` depois de uma morte, o cursor do SIM/NÃO da pedra encantada, os créditos e o final.
- [resolvido] **Texto desenhado em tiles**: `FIM`, `CONTINUA...`, `HOT`, `SAÍDA` e `FIM DE JOGO` (itens de `config/graficos.yaml`; mapa-rom.md §8).
- [resolvido] **Distribuição**: o patch versionado em `patch/wbmw-ptbr.ips` (regravado por `construir`), o `patch/LEIA-ME.txt` e a release por tag (`.github/workflows/release.yml`; README, "Publicar uma versão").

## Confirmados no emulador (Plano 3, Tarefa 6)

Evidência e capturas em docs/tecnico/mapa-rom.md, "Largura de linha e linhas por página" (`testes/test_validacao_jogo.py`, `build/capturas/validacao/`).

- [resolvido] Largura física: é a da janela do diálogo (tabela `0x1DD74`, `config/texto.yaml: janelas`); 23 colunas na janela 0. `largura_linha` passou de 25 para 23 (padrão para texto sem janela conhecida).
- [resolvido] Heurísticas 'A CONFIRMAR (Plano 3)' de `verificacao.py`: `[$04]` só avança (quebra só na borda); banco 3 recomeça na coluna 0 ou no recuo conforme o fim do script; medição por entrada trocada pela análise do fluxo do script; número = 6 dígitos.
- [resolvido] Linhas por caixa: a janela rola; nova checagem `checar_linhas` (página entre esperas <= altura da janela; `linhas_por_caixa: 3` como padrão).
- [resolvido] `[espera]` não limpa nem quebra; `[linha]` = recuo 2, `[quebra2]` = coluna 0 (README corrigido).
- [resolvido] Preenchimento com espaços das strings inline: menu de magias e status ok (tiles vazios sobre fundo preto).
- [resolvido] Invariante da fonte (`$A144` <= 40, slots 5–7 = blocos 5–7; era 42 até o Plano 4, quando o slot 6 passou a ter o rótulo do HUD): passo `checar_fonte` nos roteiros.
- [resolvido] Bolha d'água embaixo d'água aparecia como um tile preto com traço branco (visto jogando): o rótulo MOEDAS ocupava `0xC0–0xCB`, e `0xC0–0xC5`/`0xD0` não são kana, são as bolhas. O rótulo foi para `0xC6–0xCB` e `0xD3–0xD8`; `TILES_EFEITO` e `testes/test_bolha.py` (sala `0x69`) guardam os tiles das bolhas (vram.md §3).
- Tiles de efeito `0xC0–0xC3`, `0xFE` e `0xFF`: não apareceram em sprite na varredura das salas (só `0xC4`, `0xC5` e `0xD0`, na sala `0x69`). Pela arte, devem ser bolhas maiores ou respingos; ficam protegidos por `TILES_EFEITO`.

## Ainda não verificados no jogo

- Strings inline dos créditos: vistas numa cópia da ROM que pula para o final (lote final), não numa sessão de validação. As da ocarina foram vistas com os mini-scripts copiados para o diálogo 0 (a cena real não foi visitada); os patches `ocarina.*.linha` trocam o `02` do meio da frase por `07` (no-op) para "Shion toca sua Ocarina." caber numa linha. (O `GOLD` de `0x84E7` era o rótulo do HUD e saiu da config no Plano 4.)
- Janelas 1, 2, 3, 5 e 6: só os valores da tabela (as janelas 0, 4 e 7 foram vistas).
- Quiz (`banco0_sistema`) continua sem checagem de largura: janela 4 (17 colunas), pergunta impressa numa área de 2 linhas que rola, respostas a partir da coluna 3.
- Medição de `[s3:XX]` dentro de um diálogo: só o 1.º trecho do script entra (os demais são medidos como raízes próprias).
- `0B 1F` (string do quiz) e `0B 01` contam a maior string do banco, não a sorteada.
- Recuo fixo em 2: se um `pt` usar `[$0A]` com outro valor num diálogo, os seguintes no jogo herdam esse recuo, mas a checagem de cada diálogo parte de 2.

## Decisões a revisitar

- [resolvido] **Nome de item: no máximo 18 colunas** (era 16 até a troca do buffer). A cópia do nome em `0x1E6A–0x1ECE` não tem limite; na base as duas linhas ficavam em `$8CE0`/`$8CF0` (16 colunas, com a pilha das aninhadas em `$8D00` logo depois). Os patches `buffer_nome.*` (`config/patches.yaml`) levam o buffer para `$AB00`/`$AB20` (32 colunas), em RAM sem uso no jogo (prova em mapa-rom.md §6, "Buffer do nome de item"). O limite agora vem da linha do baú (`"Você achou "` + nome + `"."` em 30 colunas): `MAX_NOME_ITEM` = 18 em `ferramentas/verificacao.py`, cobrado por `checar_nomes_itens`. As telas do menu têm limite próprio (`checar_nomes_menu`): equipamentos **17** (patches `lista_equip.*`; na base 14), ITEM **9**; o nome curto de menu fica em `banco1_menu.yaml` (mapa-rom.md §6, "Nomes de itens nos menus"). Knight virou "Militar" (sugestão do autor; "do Cavaleiro", 19–21 colunas, não cabia) e Hard "Robusta/Robusto".

- **Save e emulador (para o README da distribuição; item 4 de "O que falta").** O save é uma EEPROM (mapa-rom.md §8.1). O Genesis Plus GX a reconhece pelo código do produto `G-4060` e grava e carrega com a ROM traduzida (conferido gravando na estalagem e respondendo NÃO a "Vai seguir viagem amanhã de manhã?": o jogo volta ao título, como no original, e o CONTINUAR aparece). Emuladores que ligam a EEPROM pelo hash da ROM original (ares) não a ligam na ROM traduzida, e o save se perde (o autor viu o CONTINUAR sumir). O README do patch deve recomendar o Genesis Plus GX ou explicar como forçar a EEPROM.

- Ocarina: 9 slots inline de tamanho fixo; se o PT não couber, repontar os 5 mini-scripts via imediatos em 0xC4B0–0xC530 (o tipo `abs_l` de `inline_repontavel` serve, mas o alvo é o início do mini-script, não o texto: exige estender o item).
- raizes_extra: o montador recusa raízes extra.* (lista vazia hoje); se surgir uma, criar schema com endereço do ponteiro.

## Pequenos defeitos adiados

- auditoria.py:130 branch skipdata morto
- auditoria.py:145 heurística de ressincronização sem comentário/varredura bruta no teste
- test_auditoria sem caso de imediato e sem detectar referencias_ignoradas obsoletas
- test_sobreposicao match fraco ("0x6")
- cadeia vazia quando o endereço inválido é a própria raiz
- subops 00/25 tratados como fim (montador não deve emiti-los)
- com tabela real ([ e ] mapeados), código mistipado vira ASCII em codificar; pego por checar_controles — falta teste/nota
- segmentos.py:127/115 KeyError cru se instrução sem dono
- ler_dicionario corta no primeiro 00 (frágil se palavra tiver arg 00)
- tabela.tbl "20= " depende de espaço final (sem teste/comentário)
- LIMITES constante da ROM base em raizes.py
- ErroScript/ValueError de extrair_texto fora de ERROS_ESPERADOS (traceback); texto.yaml não-mapeamento → AttributeError — carregado no dispatch da T5
- grupos que deixam de existir (ex. extras.yaml) não são mesclados/marcados órfãos
- test_extrair_contagens extrai duas vezes; import dentro do teste
- montador.py:105/108 trunca args fora de faixa (& 0xFF/0xFFFF) em vez de erro
- except ValueError amplo em cmd_extrair mascara bugs
- bytes.fromhex de trecho corrompido escapa como traceback em verificar/construir
- ramo inalcançável em checar_espaco
- test_build_cli_com_texto confere só 1 das 4 bases de banco
- _verificar sem aviso quando config/texto.yaml ausente (checar_inline vira no-op)
- checar_inline wrapper em verificacao.py só para evitar ciclo de import
- fragmentos da ocarina dependem da inserção 0B 0A 28 0C (risco de qualidade de tradução)
- item inline não-dict ainda gera erro cru
- _COM_ARG engole sempre o próximo token (não testado)
- banco0_sistema (quiz) sem checagem de largura — janela confirmada (4, 17 colunas); falta a regra
- [resolvido] README afirma recuo em [linha] vs [quebra2] sem evidência (confirmado e corrigido)
- _expandir sem memoização
- região destino não verificada como FF (teste de 1 linha)
- [resolvido] limite de número de linhas por caixa não checado (checar_linhas)
- pt intencionalmente vazio não expressável (documentar)

## Pequenos defeitos adiados (Plano 3)

- fallback de memory maps não testado (ponteiros podem pender)
- sem guarda de uso após fechar() (segfault possível)
- exceção em callback ctypes é engolida
- retro_deinit pulado se read_bytes falha após retro_init; fixture param não usado
- cross-check da SAT só compara 4 bytes/entrada; possível falso "SAT não bate" se reg 5 acabou de mudar
- tiles 0x5C/0x5D/0x5F zerados pelo jogo sem causa conhecida (TODO no teste)
- doc diz comprimento 3-33, escape 0x11F dá 34; teste aleatório com uma semente só
- vram_dialogo deixa emulador compartilhado no meio do jogo
- tipo 00 (8 blocos, rotina 0x6BFC) não implementado
- test_acentos_nos_codigos_do_bloco_5 só fixa a config (detector de mudança)
- tiles de acento provados = fonte só na cena dialogo (outras cenas só em prosa)
- test_vram_cenas usa _emulador_sessao/caminho_rom_base em vez de emulador/rom_base
- vram_cenas importa nomes privados de libretro
- cenas.yaml repetir:12 frágil, sem verificação de que cada cena foi alcançada
- comentário em test_vram_cenas cita "vram.md §6" (é §3.2)
- teste visual não fixa folhas == MAX_FOLHAS no bloco 5
- capturas do teste visual em build/capturas (não tmp)
- sem teste da contabilidade combinada texto+fonte via construir/verificar
- verificar sem ROM não conta fonte realocada (construir pode falhar depois) — documentar
- assert de test_ler_entrada deslocado; diferentes in ([],[2]) frouxo; tile_vazio {0,1}; regiao: object
- sem teste da contabilidade de bytes de gráficos em montagem/checar_espaco
- extensão de tiles do CONTINUE inconsistente (0x3D4–0x3E3 vs 0x3EB) entre mapa-rom/README/código; lacuna "CONTINUAR só no VRAM" não está no README
- importar_tiles retorna [] ignorado; YAML de metadados sem escape de aspas
- merge por coluna máxima não é pior caso com [$04] (falso negativo teórico em pt)
- fecha_pagina só olha a instrução seguinte; página final pode não ser checada (falso negativo em checar_linhas)
- falta teste de caminhos convergentes; _b3_limpa_no_fim varre linear; teste reescreve build/capturas/validacao; lru_cache não cacheia falha; cabeçalho de pendencias.md diz "Plano 2"
- merge por coluna máxima com [$04] (nenhum caso atual)
- escrita no lugar não confere outras entradas apontando para a faixa (seguro para blocos 0–404)
- verificar sem ROM não conta realocação de fonte/gráficos nem valida PNG do título (documentar no README)
- README sugere 0xC0–0xFD sem avisar que blocos 6/7 crescem e são realocados
- tolerância en em checar_linhas é por entrada, não por página (afeta entradas com várias páginas)
- caminho que sai do fim das instruções sem 00/pausa/fim/limpa não fecha página

## Pequenos defeitos adiados (Plano 4: moedas, menus e itens)

- salvar/carregar o jogo não foi exercitado com o conjunto completo de patches (HUD, menus, nomes de itens, compensação)
- os testes no jogo gravam roteiros e capturas em `build/capturas` em vez de `tmp_path`
- a auditoria de referências (`auditoria.referencias_a`) cobre só as regiões de código; tabelas de ponteiros em áreas de dados não são cobertas
- testes importam auxiliares privados (`_desmontar`, `_tile`, nomes com `_` dos módulos)
- nome do banco 1 com vários segmentos gera achados repetidos (um por segmento) no `verificar`
- a estimativa de espaço ignora o padding de alinhamento e a recodificação `FE`/`FF` dos blocos repontáveis
- `verificar` não acusa `regiao_destino` sobrepondo a área de compensação (só `construir` recusa)
- `raise` final inalcançável em `ferramentas/compensacao.py`
- Comentários "$A144 > 42" em `roteiros/validacao.yaml` e `roteiros/cenas.yaml` ainda citam o limite antigo (o atual é 40).
- `MAX_NOME_ITEM_BAU` repete a frase do baú ("Você achou ") em vez de derivar de `inline.yaml`.
- `_preparo` (nomes_menu) não confere o `original` do patch contra o prólogo que sobrepõe (garantido pela ordem das etapas).
- A prova de RAM livre em `$AB00–$AB3F` cobre o início do jogo; repetir o canário com um save de fase avançada.
