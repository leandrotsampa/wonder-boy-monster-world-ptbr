# MOEDAS, menus e nomes de itens: plano de implementação

**Objetivo:** deixar prontos, antes da tradução em lotes, todos os pontos que definem
nomes e rótulos usados no resto do jogo: MOEDAS no HUD e nos textos de tamanho fixo,
menus e magias como decididos pelo autor e os nomes de itens (completo nos diálogos,
curto no menu quando o contexto deixa claro).

**Arquitetura:** o mesmo pipeline dos planos anteriores. Gráficos entram como itens de
`config/graficos.yaml` (PNG editável, recompressão, realocação via tabela `0x41000`).
Mudanças de código entram como patches conferidos em `config/patches.yaml` (bytes
originais checados antes de gravar). Textos entram nos YAML de `traducao/textos/`.
Cada mudança visível tem teste com captura no emulador.

**Design:** `docs/projeto/design/2026-11-11-traducao-wbmw-ptbr-design.md`. Regras de
tradução: `docs/projeto/guia-traducao.md`. Referências técnicas: `docs/tecnico/mapa-rom.md`,
`docs/tecnico/vram.md`, `docs/tecnico/pendencias.md`.

**Ponto de parada:** ao fim da Task 5 o trabalho **para** para revisão do autor. A
tradução em lotes, a revisão jogando e a distribuição ficam num plano seguinte, que só
começa depois do aval do autor.

## Restrições globais

- Nada de ROM nem do core no git; testes com ROM usam `rom_base` e com emulador usam o
  core (skip sem eles). A suíte passa sem os dois.
- Mensagens de commit simples, sem linhas de coautoria.
- Nada que mude a história do Wonder Boy; a origem do material gráfico é registrada
  nos metadados.
- Decisões do autor (vinculantes):
  - GOLD → **MOEDAS** em todo lugar (HUD, baú, tela de status, preços).
  - HUD: "MOEDAS" um pouco mais acima, sem encostar no valor; pode ser dividido entre
    duas linhas de tiles.
  - Menus traduzidos, com a categoria **ARMA** (não PODER).
  - Magias traduzidas, com **TERREMOTO** (não TREMOR DE TERRA).
  - Itens e magias traduzidos; no menu o nome **só encurta quando o contexto deixa o
    sentido claro** (ex.: em BOTAS, "Couro"); nos diálogos, nome completo ("Botas de
    Couro").
- Estilo: linguagem natural e fluida, tom vindo do original e do contexto
  (`guia-traducao.md`).

## Review Focus

1. **HUD com valores grandes:** "MOEDAS" não pode sobrepor o número com o máximo de
   dígitos que o jogo mostra. Teste na Task 1.
2. **Strings repontadas:** o código que lia o texto antigo de tamanho fixo tem de ler
   o novo em todos os pontos que o usam, não só no que foi visto. A auditoria das
   referências fica na Task 2.
3. **Nome curto vazando para diálogo, ou longo para menu:** loja e falas com
   `[s0:02]` mostram o nome completo; inventário e menus mostram o curto. Teste na
   Task 4.
4. **Menus com texto mais largo que o painel:** checagem de largura por painel, com
   erro no `verificar`. Tasks 3 e 4.
5. **Ida e volta:** com os textos vazios, o build continua igual ao original nessas
   áreas (exceto patches declarados). Testes existentes mais os novos.

---

### Task 1: HUD com "MOEDAS"

- Localizar no VRAM, durante o jogo, os tiles e o tilemap do rótulo "GOLD" do HUD e de
  onde vêm (bloco da tabela `0x41000` ou outro). Registrar em `mapa-rom.md` §8.
- Desenhar "MOEDAS" com as letras da fonte nas colunas do rótulo e ajustar: subir a palavra
  alguns pixels para não encostar no valor; se precisar, dividir entre a linha de tiles
  de cima e a de baixo (pode exigir mudar o tilemap do HUD, via item gráfico ou patch
  conferido).
- Testes: captura em jogo mostra "MOEDAS" com pelo menos 1 linha de pixels livre entre
  a palavra e o valor; com o valor máximo (RAM ajustada no emulador) não há
  sobreposição; o resto do HUD é idêntico ao original.

### Task 2: MOEDAS e textos do baú e da tela de status fora dos slots fixos

- Strings hoje de tamanho fixo: `bau.ouro` (" GOLD.", 6 bytes), `status.ouro`
  ("GOLD", 4 bytes) e, juntas com elas, as mensagens do baú `bau.achou_o`/`bau.achou`.
- Auditar todas as instruções que referenciam cada string (endereço PC-relativo ou
  absoluto) e repontar para cópias novas em espaço livre, sem limite do slot antigo
  (patches conferidos em `config/patches.yaml` ou um mecanismo de "inline repontável"
  em `config/texto.yaml`, à escolha de quem implementa, documentado em `mapa-rom.md`).
  Se o deslocamento PC-relativo não alcançar a área livre, usar trampolim ou
  endereçamento absoluto, sem mudar o tamanho do código existente.
- Traduzir: baú com "MOEDAS" e as frases de "achou", com linguagem natural; tela de
  status com "MOEDAS" (cabendo no layout da tela, conferido por captura).
- Testes: abrir um baú de dinheiro e um de item (estado salvo ou truque de
  posicionamento) e capturar; tela de status capturada; ida e volta sem tradução.

### Task 3: Menus e magias

- Descobrir se cabeçalhos e categorias dos menus (SELECT, WEAPON/ARMOR/SHIELD/BOOTS/
  ITEM/MAGIC e afins) são desenho ou texto, e onde ficam.
- Rótulos dos menus: SELECIONAR, ARMA, ARMADURA, ESCUDO, BOTAS, ITEM, MAGIA… (desenhados
  no mesmo estilo se forem gráfico).
- Menu de magias (strings em `0x7C0C…`): "BOLAS DE FOGO", "TERREMOTO", "TROVÕES",
  "SUPER FORÇA", "BLINDAGEM", "VOLTAR".
  Se algum não couber no slot, repontar como na Task 2.
- Status (`status.ap/dp/sp`): PA / PD / PE.
- Testes: captura de cada menu (seleção, cada categoria, magias, status) igual ao
  esperado; checagem de largura dos rótulos.

### Task 4: Nomes de itens (completo nos diálogos, curto no menu)

- Investigar como o inventário e os menus obtêm o nome do item e como os diálogos
  (`[s0:02]`) obtêm o mesmo nome: hoje ambos vêm do banco 1.
- Se viável: criar uma segunda lista de nomes (curtos, para menus) em espaço livre e
  fazer o código dos menus usá-la (patch conferido); os diálogos e a loja continuam no
  banco 1 (completo). Se inviável, registrar o motivo e usar nome único curto,
  coerente (plano B).
- Montar o glossário de itens em `docs/projeto/guia-traducao.md`: para cada item, nome
  completo e nome de menu, aplicando "só encurta quando o contexto deixa o sentido
  claro". Armas como espadas e lanças (não "Poder X"); magias com TERREMOTO.
- Preencher `banco1_itens` (completo) e a lista do menu (curto).
- Testes: inventário mostra o curto em cada categoria; loja e a fala da senhora
  mostram o completo; checagem de largura por painel.

### Task 5: Checksum do cabeçalho e CRC32 iguais aos da ROM original

- Pedido do autor: manter o CRC da ROM intacto quando possível.
- Checksum do cabeçalho (`0x18E`): continuar **válido e igual ao original** (`9D79`),
  ajustando uma palavra de compensação numa área livre que o jogo não lê.
- CRC32 do arquivo inteiro: **igual ao original** (`1592F5B0`), ajustando 4 bytes de
  compensação numa área livre (técnica de "forjar" CRC32), sem desfazer o checksum
  (resolver os dois juntos).
- As áreas de compensação ficam fora de qualquer região usada pelo texto, fonte e
  gráficos (reservadas no alocador) e documentadas em `mapa-rom.md`.
- Limite conhecido: o SHA-256 não pode ser preservado (o ares continua sem gravar o
  save; o patch anti-travamento continua necessário). Documentar no README, incluindo
  que catálogos de ROM vão listar o arquivo traduzido como a ROM original.
- Testes: o build tem `crc32 == 1592f5b0` e checksum `9D79` válido (recalculado);
  determinismo; o IPS aplicado sobre a original reproduz o build.

### Ponto de parada: revisão do autor

- Ao fim da Task 5: build, capturas de todos os pontos alterados (HUD, baú, status,
  cada menu, inventário, loja, senhora) e a lista completa de nomes (completo e curto)
  entregues ao autor.
- **Nada da tradução em lotes começa antes do aval do autor.**
