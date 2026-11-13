# Mapa de VRAM da área da fonte (tiles 0x00–0xFF) e códigos dos acentos

Pergunta: dos tiles `0x80–0xFD`, quais o jogo usa para outra coisa nas cenas com texto, e quais ficam livres para as letras acentuadas? Resposta curta: **`0x80–0x9F` não servem** (no jogo viram gráficos de HUD/efeitos). **`0xA0–0xFF` são sempre a fonte** (kana que o texto em inglês não usa) em toda cena com texto. Os acentos ficam em `0xA1–0xAC` e `0xB1–0xBC`.

Base: mapa-rom.md §5 (caractere = índice do tile, 2 linhas de tiles por caractere, prefixo `FE`/`FF` → tile de cima `0xBE`/`0xBF`) e §8 (tabela de blocos `0x41000`, slots de 1 KB em `$FF8E08`, fonte = blocos 0–7 em VRAM `n × 0x400`).

## 1. Ferramentas

- `roteiros/cenas.yaml` visita as cenas a partir do NEW GAME e grava `.png`, `.vram` e `.estado` de cada uma em `build/capturas/cenas/` (ignorado pelo git). Rodar com `python -m ferramentas.emulador roteiros/cenas.yaml`. O passo novo `repetir: N` + `passos:` (em `ferramentas/emulador/roteiro.py`) repete uma sublista.
- `python -m ferramentas.emulador.vram_cenas build/capturas/cenas/*.estado` lê cada save state e mostra:
  - os blocos dos slots 0–7 (`$FF8E08`);
  - os tiles `0x80–0xFF` referenciados pelas tabelas de nomes (plano A, plano B, janela; endereços e tamanhos tirados dos registradores do VDP no estado) e pela tabela de sprites (lista ligada a partir da entrada 0, sem as entradas com x = 0 ou y = 0);
  - para cada tile, se o conteúdo é igual ao da fonte descomprimida (`fonte`), zero (`zero`) ou outra coisa (`outro`).

  `--inicio/--fim` mudam a faixa (ex.: `--inicio 0` para ver `0x00–0xFF`).

Controles descobertos (controle de 3 botões): B ataca, C pula e avança o texto, START abre o menu de status. **Cima+A** entra por uma porta (só cima não basta). Baixo sai da cama no começo.

## 2. Cenas alcançadas (ROM base)

| Cena (`cenas.yaml`) | Como | Slots 0–7 | Tiles `0x80–0xFF` usados por planos/sprites | Conteúdo `0x80–0x9F` / `0xA0–0xFF` |
|---|---|---|---|---|
| `titulo`, `titulo_menu` | boot + START; menu NEW GAME | `140–147` | plano B usa `0x80–0xFF` (arte do título) | tudo `outro` (arte do título, sem fonte) |
| `dialogo` | NEW GAME, 1.ª fala ("Monster World was once a") | `0 1 2 3 235 5 6 7` | nenhum | `outro` (bloco 0x235) / **fonte** |
| `casa` | fim da fala de abertura (144 × C) | idem | nenhum | idem |
| `menu_casa` | START dentro de casa (menu de status) | idem | nenhum | idem |
| `campo` | baixo: sai de casa | idem | nenhum | idem |
| `menu` | START no campo (SELECT) | idem | nenhum | idem |
| `menu_arma` | SELECT → WEAPON | idem | nenhum | idem |
| `menu_item` | SELECT → ITEM | idem | nenhum | idem |
| `menu_magia` | SELECT → MAGIC (FIRE STORM, QUAKE…) | idem | nenhum | idem |
| `campo_toco` | anda para a direita até o toco com porta | idem | nenhum | idem |
| `toco` | cima+A na porta do toco (interior com um morador) | idem | nenhum | idem |

Em todas as cenas de jogo, `0x80–0x9F` é exatamente o bloco `0x235` descomprimido (conferido byte a byte; os tiles `0x9E–0x9F` são zero no próprio bloco). `0xA0–0xFF` é exatamente a fonte (blocos 5–7).

Também conferido: 900 quadros de jogo a partir de `campo_toco` (andando, atacando e pulando), com a análise a cada 3 quadros. Nenhum sprite usou `0x80–0xFF` e `0xA0–0xFF` nunca mudou.

Fora de `0x80–0xFF`, só para registro: os sprites usam `0x00–0x03` e `0x5C–0x5F`. Os tiles `0x5C–0x5F` são reescritos em jogo por `0x1B254` (rotina `0x22A8`: VRAM `0x0B80`, 4 tiles do bloco `0x60`). É isso que "zera" ¥ ] _ (Task 2).

### Cenas não alcançadas

- **Loja, estalagem, quiz, diálogos de cidade**: o morador do toco não respondeu (cima, cima+A, A, B, C, encostar) e a saída do campo depende de um pulo mais alto que o alcançado (a parede depois do toco). Seguir exigiria jogar de verdade, e não há save do jogo para partir. **Impraticável nesta tarefa.** Essas falas usam a mesma janela de diálogo da cena `dialogo`, dentro de salas de jogo. A conclusão para elas vem do código (§3).
- **Créditos/final**: impraticável (fim do jogo). Coberto pelo código (§3).

## 3. Evidência do código: quem escreve nos slots 0–7

Os slots são preenchidos por um mini-script de bytes interpretado em `0x234C` (a1 = slot atual):

| Byte | Efeito |
|---|---|
| `00–7F` | word (bloco) = byte·256 + próximo byte, no slot atual; avança |
| `80–BF` | slot atual = `byte & 0x3F` |
| `C0` | pula um slot |
| `C1–F7` | `byte & 0x3F` slots seguidos com blocos consecutivos a partir do word seguinte |
| `F8–FE` | `(byte & 7) + 1` slots = `FFFF` (vazio) |
| `FF` | fim |

A carga para o VDP é feita depois por `0x22F0`, que só manda os slots que mudaram.

Varredura: as 14 chamadas externas de `$234C` (`jsr`/`jmp`, ver §3.1 (iii)), mais a tabela de salas (`0x1CC1C` → `0x22460`, entradas de 16 bytes, script no deslocamento 12), mais as tabelas de deslocamentos `0xF680` (magias), `0xF710` e `0x1B830`, e as sub-rotinas `0x9510`/`0xD50C`/`0xF6A4`. Uma busca bruta na ROM inteira por scripts válidos que começam em slot < 8 só achou falsos positivos nas áreas de dados. Conferi um a um os que caem na região das salas (`0x27286`, `0x28327`, `0x29EFC`, `0x2B2AD…`, `0x2E475`, `0x37964`, `0x3BE46`): o "`0x8x`" ali é byte baixo de um word, não seleção de slot. Resultado: **só quatro scripts de `0x234C` mexem nos slots 0–7** (há outros dois escritores da tabela de slots, ver §3.1 (i)):

| Script | Slots 0–7 | Cena |
|---|---|---|
| `0x96BC` (carga de sala/jogo, perto de `0x9686`) | `0 1 2 3 235 5 6 7` | todo o jogo: campo, salas, lojas, menus, diálogos |
| `0x701C` (rotina em `0x6F86–0x6FA2`, ponteiro na tabela de modos em `0x4D0C`) | `0 1 2 3 4 5 6 7` | não identificada (fonte completa com o kana do bloco 4) |
| `0x1B796` (código em `0x1B778`, junto dos créditos) | `0 1 2 3 4 5 6 7` | provavelmente créditos/final |
| `0x72F8` (`0x70D6`) | `140–15D` nos slots 0–29 | título (confere com a cena `titulo`) |

Os scripts das salas começam no slot 21 (`0x95`) ou acima. As outras tabelas e sub-rotinas também ficam acima do slot 7: `0x51C0` slots 48–59, `0x91BE` slot 9, `0xD6F1`/`0xD6FA` 23–26, `0xF6D8–0xF6E8` 8–12, `0xF680[0–3]` 15, `0xF710[0–6]` 13–14 e `0x1B830[0–5]` 8–47.

Escritas diretas de tiles fora dos slots passam pela rotina `0x22A8` (VRAM d0, tile d1, d2 longs; d1 = 0 zera). Destinos fixos:
- `0x0B80`: `0x1B254`, e também `0xF752` (d1 = 0 quando `$95D0` < 0, ou seja, zera; é esse o caminho que zera ¥ ] _);
- `0x5000` (`0xD1AA`) e `0x5200` (`0xDA9E`);
- `0x5380` (`0x19612`, `0x197F6`);
- `0xFC80`/`0xFD00` (`0x8652`/`0x866A`);
- `0xFD80` (`0xC3DC`);
- `0xFE00+` (`0x12D64`, ícones de item). Nenhum cai em `0x1000–0x1FFF` (tiles `0x80–0xFF`). A exceção é `0x6F72`, que anima tiles de objetos no endereço que o objeto traz em `+4`. Esse caso só é coberto pela evidência dinâmica: nada mudou em `0xA0–0xFF` nas cenas acima. Não há comando VDP literal para VRAM `0x1000–0x1FFF` no código (`0x200–0x1CC00`).

**Conclusão:**
- `0x80–0x9F`: **ocupados** em todo o jogo (bloco `0x235`, gráficos de HUD/efeitos). Só são kana em `0x701C`/`0x1B796`. Fora de cogitação.
- `0xA0–0xFF`: **fonte** (blocos 5–7) em toda cena que tem fonte. O texto em inglês não usa esses kana, exceto 4 strings japonesas que sobraram (§3.2). **Livres** para glifos novos, exceto `0xBE`/`0xBF`, que o prefixo `FE`/`FF` usa como tile de cima e que ficam reservados. `0xC6–0xCB` e `0xD3–0xD8` são o rótulo "MOEDAS" do HUD (Plano 4, Tarefa 1; mapa-rom.md §8).
- **Exceção: `0xC0–0xC5`, `0xD0`, `0xFE` e `0xFF` não são kana.** São os únicos tiles de `0xA0–0xFF` da fonte base fora do formato de glifo (fundo transparente e cores 3/b–e, em vez de fundo 1 e traço 15): gráficos de sprite carregados junto com a fonte. `0xC0–0xC5` e `0xD0` são as bolhas d'água: na sala `0x69` (embaixo d'água), a bolha que sobe do herói é o sprite `attr 0x00C5`, a bolha pequena `0x40C4` e o brilho `0x50D0`/`0x58D0`. Numa varredura das 138 salas (início de cada sala, SAT a cada 10 quadros por 300 quadros), essa foi a única sala com sprites em `0xA0–0xFF`. Ficam em `TILES_EFEITO` (`ferramentas/fonte.py`), e `testes/test_bolha.py` exige que a fonte do projeto os mantenha iguais aos da base. O rótulo do HUD ficava em `0xC0–0xCB` e a bolha aparecia como o alto do "S" de MOEDAS.
- No título não há fonte nenhuma (`NEW GAME` é arte do bloco `0x140+`). Traduzir o título é trabalho de gráficos, não de texto.

### 3.1 Invariante e como refutar

**Invariante.** O slot 5 (VRAM `0x1400–0x17FF`, tiles `0xA0–0xBF`, onde ficam todos os acentos) só recebe um bloco de três maneiras:
1. pelos scripts `0x234C` `0x96BC`, `0x701C`, `0x1B796` e `0x72F8`. Todos põem o bloco 5 no slot 5, exceto `0x72F8` (título, sem texto);
2. pelo alocador `0x125C4` (achado na checagem (i) abaixo), que só chegaria ao slot 7 com 41 slots alocados, ao 6 com 42 e ao 5 com 43 (ver abaixo);
3. pela liberação `0x18290`, que grava `FFFF`. O carregador `0x22F0` pula entradas negativas (`bmi`), então o VRAM não muda.

O mesmo vale para os slots 6–7 (`0xC0–0xFF`). Além disso, nenhuma escrita direta de tiles (`0x22A8`) tem destino fixo em `0x1000–0x1FFF`.

**Como refutar:** achar, em qualquer cena com texto, `vram_cenas` reportando slot 5 ≠ `005`, ou conteúdo de `0xA0–0xBF` ≠ `fonte`. Ou achar um escritor de `$FF8E08–$FF8E87` fora da lista abaixo.

Checagens de completude:

**(i) Quem escreve em `$FF8E08` (`SLOTS_RAM`).**
- *Busca:* todo word `0x8E08–0x8E87` em posição par de `0x200–0x1CC00`, desmontado no contexto. Isso pega `$8E08.w` absoluto e deslocamentos `-$71F8…` (mesmos bytes). O long `FF8E08` não aparece na ROM.
- *Resultado:*
  - `0x22F4` (carregador: só lê);
  - `0x2364` (o próprio `0x234C`);
  - `0x6BA0` (zera tudo para `FFFF` na inicialização);
  - `0x18290` (libera slots com `FFFF`, a partir do tile do objeto);
  - **`0x12632`**: sub-rotina do alocador `0x125C4`, que grava slots a partir de `0x30 − $A144`. `$A144` é o total alocado, zerado em `0x13804` (`move.l d0,$A142`);
  - escritas em `$8E36`, `$8E64` e `$8E76` (slots 23, 46 e 55; `0x17BE2`, `0x189AE`, `0x113E4` e outras), todas ≥ 8.
- *Sobre o alocador:* ele ocupa os slots `0x30 − $A144` … `0x2F`, então com `$A144` = 41 chega ao slot 7 (`0xE0–0xFF`, letras), com 42 ao slot 6 e com 43 ao slot 5 (acentos). O slot 6 (`0xC0–0xDF`) tem desde o Plano 4 o rótulo MOEDAS do HUD (`0xC6–0xCB` e `0xD3–0xD8`, `HUD_CODIGOS_*` em `ferramentas/fonte.py`), que fica na tela **durante todo o jogo**, não só nas cenas com texto: qualquer sobrescrita do slot 6 apareceria no HUD. Por isso o limite é **40** (`MAX_ALOCADOS` em `ferramentas/emulador/vram_cenas.py`): o slot mais baixo alocado é o 8, e os slots 5–7 ficam fora do alcance. Os slots 8–~35 da sala seriam sobrescritos antes, e os gráficos da própria sala quebrariam visivelmente. Valor medido: `$A144` = 0 em todas as cenas e 5 em `campo_toco`/`toco` (slots 0x2B–0x2F). **Um limite superior estático não foi provado**: depende das tabelas de inimigos por sala, que não percorri.
- *Guarda dinâmica (Plano 3, Tarefa 6):* o passo `checar_fonte` dos roteiros (`ferramentas/emulador/roteiro.py`) lê a RAM e falha se `$A144` (word em `$FFA144`, gravado em `0x12606`) > 40 (`MAX_ALOCADOS`; acima disso o alocador alcança o slot 7 e depois o 6, do HUD) ou se os slots 5–7 não têm os blocos 5–7. Está em toda captura de `roteiros/validacao.yaml` e nas cenas de jogo de `cenas.yaml`/`dialogo.yaml`. Também visto: `$A144` = 6 dentro da estalagem (`build/capturas/validacao/estalagem/`).

**(ii) Valor inicial de a1.** `0x234C` não inicializa a1: um script que não começa com `80–BF` escreve onde o chamador deixou a1. Todos os scripts enumerados (os 4 da tabela acima, as 6 salas e as entradas de `0xF680`, `0xF710` e `0x1B830`, 35 ao todo, contando também `0x51C0`, `0x91BE`, `0xD6F1`, `0xD6FA` e `0xF6D8–0xF6E8`) começam com seleção de slot (`80`, `88`, `89`, `8C`, `8D`, `8F`, `95`, `97`, `A9`, `B0`), então a1 na entrada é irrelevante para eles. **Não verificado:** os scripts chamados por `0x9510`. O ponteiro deles vem do fluxo de eventos da sala (a2), e o chamador repassa o a1 que tiver. Eles não foram enumerados, e a busca bruta só encontra scripts que começam com seleção de slot. Esse caso fica coberto só pela evidência dinâmica e pela invariante: na cena `toco`, uma sala com sub-script, os slots 0–7 ficaram intactos e só mudaram os slots 27–33.

**(iii) Listas de chamadores.**
- *Busca:* `jsr`/`jmp` `.w` e `.l`, `bsr`/`bra` curtos e longos, e ponteiros de 32 bits na ROM inteira.
- `0x234C`: 14 chamadas externas (`0x51BC`, `0x6F92`, `0x70DE`, `0x915C`, `0x9518`, `0x9686`, `0x970C`, `0xD520`, `0xF678`, `0xF6BC`, `0xF6D0`, `0xF708`, `0x1B782`, `0x1B82C`), mais 5 desvios internos. Nenhum ponteiro.
- `0x22A8`: 10 chamadas (`0x6F72`, `0x86B4`, `0xC3E2`, `0xD1B2`, `0xDAA8`, `0xF75A`, `0x12D9E`, `0x1961C`, `0x197FC`, `0x1B260`), destinos acima. Há um ponteiro em `0x1B262`, que é o operando do `jsr.l` em `0x1B260`.
- `0x22F0`: 18 chamadas, e ele só copia os slots que mudaram.
- Chamada indireta por registrador (`jsr (aN)`) não é detectável assim: as listas cobrem chamadas diretas.
- O destino de `0x6F72` vem de um campo do objeto (`+4`), então é **só dinâmico**.

**Quem escolhe `0x96BC`:** `0x967E` (`lea $96BC(pc)` em `0x9682`). Ele é chamado em `0x9330` e em `0x96E2`, dentro da carga de área `0x96D6`, que lê a tabela `0x1CC1C`. Portanto toda carga de área recarrega `0x96BC`. As salas internas (lojas, casas, o toco) não recarregam: mudam só os slots ≥ 8 por sub-scripts, como se vê em `toco`. Que **toda** loja/estalagem siga esse caminho **não está provado**, mas qualquer desvio seria pego pela invariante.

### 3.2 O texto em inglês e os bytes `0x80–0xFD`

- *Varredura:* todos os 638 trechos extraídos da ROM base (`extrair_texto`; igual a `dados/scripts/esqueleto.json`) e todos os itens inline de `config/texto.yaml`.
- *Separação caractere × argumento:* argumento de `01/03/04/0A/0C–0F` não conta; `02/05/09` não têm argumento; `FE/FF` + caractere conta os dois bytes.
- *Bytes ≥ `0x80` usados como caractere:*

| Trecho | Bytes |
|---|---|
| `b0.004.t00` | `95 97 8C 98 9B BD` |
| `b1.026.t00` | `AF AE 93 A9 B3 A4` |
| `b1.030.t00` | `FB CF FE E4` (`FE` = prefixo) |
| `b2.006.t00` | `FF EA D2 D1 FA DD` (`FF` = prefixo) |

São as 4 strings japonesas que sobraram. Nenhum item inline tem byte ≥ `0x80`. Só `b1.026` cruza com os códigos dos acentos (`A4`, `A9`, `B3`). O teste `testes/test_vram_cenas.py::test_texto_ingles_nao_usa_kana` fixa essa lista.

## 4. Códigos dos acentos

Maiúsculas em `0xA1–0xAC` e minúsculas em `0xB1–0xBC`, na mesma ordem:

| Código | Letra | Código | Letra |
|---|---|---|---|
| `A1` | À | `B1` | à |
| `A2` | Ã | `B2` | ã |
| `A3` | Â | `B3` | â |
| `A4` | Á | `B4` | á |
| `A5` | É | `B5` | é |
| `A6` | Ê | `B6` | ê |
| `A7` | Í | `B7` | í |
| `A8` | Ó | `B8` | ó |
| `A9` | Õ | `B9` | õ |
| `AA` | Ô | `BA` | ô |
| `AB` | Ú | `BB` | ú |
| `AC` | Ç | `BC` | ç |

Os glifos (`ferramentas/fonte.py: GLIFOS_ACENTOS`, desenhados pelo projeto no estilo da fonte original) ocupam o tile inteiro: o acento fica nas 2 linhas de cima e a letra é espremida nas 6 de baixo (no `Õ`, til ondulado de 2 linhas; no `Ç`, cedilha separada nas 2 de baixo). Não usam o prefixo `FE`/`FF`.

## 5. Códigos escolhidos (`config/texto.yaml: acentos`)

Os da tabela do §4, um por um:

- todos ficam em `0xA1–0xAC` / `0xB1–0xBC`, dentro do bloco 5 (`0xA0–0xBF`), que é fonte em toda cena com texto (§2, §3);
- nenhum fica em `0x80–0x9F` (bloco `0x235` no jogo) nem em `0xBE`/`0xBF`/`FE`/`FF`;
- cobrem as 24 letras pedidas (`á à â ã é ê í ó ô õ ú ç` e maiúsculas). Sobram livres `0xA0`, `0xAD–0xB0`, `0xBD`, `0xCC–0xCF` e `0xD9–0xFD`, menos `0xD0` e os usados pelas strings japonesas de §3.2 (`0xC6–0xCB` e `0xD3–0xD8` passaram a ser os tiles do rótulo "MOEDAS" do HUD, mapa-rom.md §8; `0xC0–0xC5`, `0xD0`, `0xFE` e `0xFF` são gráficos de sprite, §3) para o que vier, como `ü`, `º`/`ª`, aspas ou glifos de maiúscula alternativos;
- maiúscula e minúscula da mesma letra ficam a `0x10` de distância.

Não foi preciso nenhum ruling de falta de espaço: há códigos livres de sobra (§3).

## 6. Riscos

- **Strings japonesas que sobraram no inglês.** Elas usam kana que agora viram acentos:
  - `b1.026` (`[$AF][$AE][$93][$A9][$B3][$A4]`) apareceria como `?? ? Õ â Á`;
  - também há `b0.004`, `b1.030` e `b2.006`, com códigos fora da tabela de acentos ou fora de `0xA1–0xBC`.

  Parecem não usadas. Se aparecerem em jogo, viram lixo de qualquer jeito (o kana já não tinha sentido para o jogador). Convém traduzir ou esvaziar.
- **Animação de tiles por objeto (`0x6F72`).** Escreve no endereço do objeto. Não vi nenhum em `0xA0–0xFF`, mas não percorri todos os objetos do jogo. Ao testar a ROM traduzida, vale olhar lojas/estalagem/quiz/créditos com `vram_cenas`.
- **Cenas `0x701C`/`0x1B796`** (fonte com kana no bloco 4): os acentos continuam em `0xA0–0xBF`, então também aparecem certo ali.
- **Tabela de blocos**: o bloco do HUD é `0x235` (565). A tabela em `0x41000` tem 768 entradas (`0x41000–0x41BFF`, com buracos `FFFFFFFF`); `TOTAL_BLOCOS` era 405 e foi corrigido para 768 na Tarefa 4 (`ler_entrada(rom, 0x235)` funciona).
