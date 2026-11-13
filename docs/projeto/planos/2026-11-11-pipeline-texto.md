# Pipeline de texto (scripts, extração, montagem, realocação): plano de implementação

**Goal:** extrair todo o texto da ROM (diálogos, bancos de strings e strings inline) para YAML editável e reinseri-lo realocado em `0xA4C80+`, com os saltos do script recalculados. O teste central é o de ida e volta: extrair e reinserir sem alterações gera uma ROM idêntica byte a byte (spec §6.5.1).

**Architecture:** um subpacote `ferramentas/script/` com quatro peças: tabela de opcodes, desmontador (bytes → instruções com rótulos), segmentador (instruções → esqueleto + trechos de texto traduzíveis) e montador (esqueleto + textos → bytes, com rótulos resolvidos). O esqueleto gerado é versionado em `dados/scripts/` e os textos em `traducao/textos/`. O `construir` passa a ter duas etapas em `ETAPAS`: texto realocado e strings inline.

**Tech Stack:** Python 3.11+, PyYAML, pytest e capstone (só para auditoria; vai para `requirements-dev.txt`).

**Spec:** `docs/projeto/design/2026-11-11-traducao-wbmw-ptbr-design.md`. Referência técnica obrigatória: `docs/tecnico/mapa-rom.md` (endereços, opcodes, tabelas).

**Escopo:** este plano não cobre a fonte com acentos, o emulador, os gráficos da tela de título nem a tradução em si. Esses itens ficam nos Planos 3 e 4. Até o Plano 3 a tabela só tem ASCII, então textos `pt` com acento vão falhar no `verificar`, como esperado.

## Global Constraints

- Tudo da fundação continua valendo: UTF-8 explícito, build determinístico e nenhuma ROM no git.
- Testes que precisam da ROM real usam a fixture `rom_base` (Task 1), que dá **skip** quando `rom/` não tem a ROM com o sha1 de `config/rom.yaml`. A suíte tem que passar sem ROM nenhuma.
- Endereços pinados (vêm de `mapa-rom.md`): tabela global `0x1CC00`, ponteiro de diálogos `0x1CC14`, ponteiro da mestra `0x1CC10` → mestra `0x211CA` (4 × u32), tabela de diálogos `0x1DD94` (131 × 3 bytes), região de destino `0xA4C80–0xBFFFF` (preenchida com `FF`).
- Offsets das tabelas são **words BE com sinal**. Todo alvo tem que ficar a −0x8000..+0x7FFF da base da sua tabela. Se não couber, é erro no `verificar`/`construir`, nunca truncamento.
- Semântica de salto (spec §5 do mapa): o destino = endereço do 1º byte do campo de 2 bytes + valor com sinal. Vale para `06` e para os subops condicionais de `0B`.
- O formato de exibição do `en` expande as palavras do dicionário (banco 0, índices `0x3F–0xE7`). Os bytes originais de cada trecho ficam no esqueleto (`bruto`). Quando `pt` está vazio, o build usa `bruto`, e isso garante a ida e volta idêntica.
- `pt` é sempre escrito por extenso: o build nunca gera `0C xx` de dicionário.

## Review Focus

1. **Saltos que cruzam entradas:** um script pode saltar para dentro de outra entrada ou cair nela por continuidade (fall-through). A montagem realocada tem que manter esses destinos. Teste na Task 5 (equivalência semântica sobre a ROM real).
2. **Texto PT maior que o original:** quando um trecho cresce, os saltos posteriores e todos os offsets das tabelas têm que mudar. Teste sintético na Task 5, com um trecho triplicado e saltos antes e depois dele.
3. **Estouro de região ou de offset:** com texto demais, o build falha com uma mensagem que diz quanto passou, sem gravar nada. Teste na Task 5.
4. **Strings inline de tamanho fixo:** `pt` maior que o slot vira erro. Menor é preenchido conforme a política do slot. Teste na Task 6.
5. **Re-extração depois de traduzir:** rodar `extrair` de novo não pode apagar `pt`. Isso usa `mesclar`; teste na Task 4.

---

### Task 1: Fixture da ROM real e auditoria de referências absolutas

**Files:**
- Create: `testes/conftest.py` (acrescentar), `ferramentas/script/__init__.py`, `ferramentas/script/auditoria.py`, `testes/test_auditoria.py`, `requirements-dev.txt` (`capstone>=5`), `config/texto.yaml`

**Interfaces:**
- Produces:
  - fixture `rom_base -> bytes` (skip com motivo "ROM base ausente" se não houver ROM válida);
  - `def referencias_absolutas(rom: bytes, inicio: int, fim: int) -> list[tuple[int, int]]`: lista de (endereço do operando, valor) para cada **instrução 68000** decodificada pelo capstone (varredura linear das regiões de código `0x200–0x1C600`) cujo operando absoluto de 32 bits cai em `[inicio, fim)`;
  - `config/texto.yaml` com as chaves `regiao_destino: [0xA4C80, 0xC0000]`, `raizes_extra: []` (endereços de scripts referenciados direto pelo código, que a auditoria preenche) e `inline: []` (Task 6).

- [ ] **Step 1:** escrever `test_auditoria.py`:
  - `test_referencias_sinteticas`: código montado à mão `41F9 0002 1000` (lea $21000,a0) + `4E75` → `referencias_absolutas(..., 0x21000, 0x22000) == [(2, 0x21000)]`.
  - `test_referencias_rom` (com `rom_base`): toda referência encontrada na faixa `0x1DD94–0x22460` tem que estar em `config/texto.yaml: raizes_extra` ou em `referencias_ignoradas` (com uma justificativa por item). Esse teste é o guarda contra texto que escapa da realocação. A tabela global `0x1CC00` é dado, não código, então não aparece aqui: ela é tratada pela Task 5.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar `auditoria.py`.
- [ ] **Step 4:** rodar a auditoria na ROM real. Para cada referência encontrada, ler o código ao redor e classificar: é a raiz de um script (vai para `raizes_extra`) ou não é texto (vai para `referencias_ignoradas`, com o motivo). Registrar o resultado também em `docs/tecnico/mapa-rom.md` §6. As strings inline já conhecidas (`0x1D70`, `0x1FE3`, `0x2B59…`, `0x7BB6…`, `0x84DE`, `0x1ABD9`) vão para a Task 6 e ficam fora desta faixa.
- [ ] **Step 5:** rodar os testes. Esperado: PASS (o de ROM roda localmente e dá skip sem ROM).
- [ ] **Step 6:** commit `feat: auditoria de referências absolutas ao texto`.

### Task 2: Opcodes e desmontador de script

**Files:**
- Create: `ferramentas/script/opcodes.py`, `ferramentas/script/desmontador.py`, `testes/test_desmontador.py`

**Interfaces:**
- Produces:
  - Em `opcodes.py`: tipos de argumento `B` (byte), `R` (salto rel16), `S` (índice de string; o banco vem do opcode) e `W` (word cru). `OPS: dict[int, str]` para `0x00–0x0F` (ex.: `0x01: "B"`, `0x06: "R"`, `0x0C: "S"`) e `SUBOPS_0B: dict[int, str]` para `0x00–0x32` (ex.: `0x11: "BR"`, `0x1A: "BRR"`). Mais `FIM = {0x00}`, `SALTO_INCONDICIONAL = {0x06}` e o conjunto de subops que terminam o fluxo. Caracteres: `0x10–0xFD` ocupam 1 byte; `FE`/`FF` + 1 byte formam um caractere de 2 bytes.
  - `@dataclass(frozen=True) class Instr: end: int; op: int; sub: int | None; args: tuple[int, ...]; alvos: tuple[int, ...]; tam: int`. Caractere: `op = -1`, `args = (byte,)` ou `(prefixo, byte)`.
  - `class ErroScript(Exception)`
  - `def desmontar(rom: bytes, raizes: list[int], limites: tuple[int, int]) -> dict[int, Instr]`: descida recursiva a partir das raízes, seguindo o fluxo contínuo e os alvos de salto. Lança `ErroScript` se uma instrução cair fora dos `limites`, se duas instruções se sobrepuserem ou se aparecer um opcode/subop desconhecido. A mensagem inclui o endereço e a cadeia de raízes.
- Valores conhecidos (de `mapa-rom.md` §5) entram já no código: `00:""`, `01:"B"`, `02:""`, `03:"B"`, `04:"B"`, `05:""`, `06:"R"`, `07:""`, `08:""`, `09:""`, `0A:"B"`, `0B:<sub>`, `0C–0F:"S"`. Os 51 subops são determinados no Step 3 lendo os handlers de `0x15C8` com o capstone. Os handlers que chamam sub-rotinas (`1798`, `183E`, `1C2C`, `2AAE`, `1B7E`…) também precisam ser lidos para contar as leituras de `(a2)+`.

- [ ] **Step 1:** escrever os testes sintéticos:
  - `test_texto_simples`: `b"Hi\x05\x00"` na raiz 0 dá as instruções nos endereços 0,1,2,3 e a última com `op == 0`.
  - `test_salto_incondicional`: `06 00 04 | 41 | 00 | 42 00` (salto em +4 a partir do endereço 1, ou seja, para o 5) → a instrução em 0 tem `alvos == (5,)` e o byte 3 (`41`) **não** é decodificado (é inalcançável).
  - `test_salto_condicional_0b`: com um subop do tipo `"BR"`, os dois caminhos são decodificados.
  - `test_char_2bytes`: `FE D6 00` gera uma instrução de caractere com `tam == 2`.
  - `test_sobreposicao`: um salto para o meio de uma instrução lança `ErroScript`.
  - `test_fora_dos_limites`: lança `ErroScript`.
- [ ] **Step 2:** escrever `test_cobertura_rom` (com `rom_base`), com as raízes = os 131 alvos da tabela `0x1DD94` + todas as entradas não nulas dos 4 bancos + `raizes_extra`, e os limites `0x1DF1D–0x22460`:
  - `desmontar` não lança erro;
  - toda instrução de salto tem alvos que são inícios de instrução;
  - os bytes **não cobertos** dentro de `0x1DF1D–0x211CA` e `0x213AA–0x22460` são no máximo os da lista `config/texto.yaml: lacunas_conhecidas` (cada uma com justificativa; o esperado é vazio, ou só padding).
- [ ] **Step 3:** rodar e iterar sobre `SUBOPS_0B` até `test_cobertura_rom` passar. Cada subop definido ganha um comentário com o endereço do handler. Esta é a tarefa de engenharia reversa: o critério de pronto é o teste de cobertura.
- [ ] **Step 4:** rodar `python -m pytest testes/test_desmontador.py`. Esperado: PASS.
- [ ] **Step 5:** documentar a tabela final de subops em `docs/tecnico/mapa-rom.md` §5.
- [ ] **Step 6:** commit `feat: desmontador de script com tabela completa de opcodes`.

### Task 3: Segmentação em esqueleto + trechos e codec de texto

**Files:**
- Create: `ferramentas/script/segmentos.py`, `testes/test_segmentos.py`, `traducao/tabela.tbl`
- Modify: `ferramentas/verificacao.py` (`CODIGOS_LIVRES`)

**Interfaces:**
- Consumes: `Instr` e `desmontar` (Task 2), `Tabela` (fundação).
- Produces:
  - Um **trecho** é uma sequência máxima de instruções "de texto": caracteres, `01 xx`, `02`, `03 xx`, `04 xx`, `05`, `09`, `0A xx` e `0C–0F xx`. Um trecho **sempre termina** antes de qualquer outra instrução e antes de qualquer endereço que seja alvo de salto ou raiz, porque um rótulo nunca cai no meio de um trecho.
  - `@dataclass class Trecho: id: str; end: int; bruto: bytes`
  - Esqueleto: `list[dict]`, com um item por instrução estrutural (`{"rotulo": "L_1df1d", "op": 6, "sub": None, "args": [...], "alvos": ["L_..."]}`) ou por trecho (`{"rotulo": ..., "trecho": "<id>"}`). Todo endereço que é raiz ou alvo ganha um `rotulo` `L_<hex>`.
  - `def segmentar(instrs: dict[int, Instr], raizes: dict[str, int]) -> tuple[list[dict], list[Trecho]]`, onde `raizes` mapeia o nome lógico para o endereço (`dialogo.000`, `b0.03F`, `b1.000`, `b2.000`, `b3.000`, `extra.<hex>`).
  - `def exibir_en(bruto: bytes, tabela: Tabela, dicionario: list[str]) -> str`: decodifica com a tabela e troca `[s0:XX]` (XX ≥ 0x3F) pela palavra do dicionário.
  - IDs dos trechos: `<raiz>.t<NN>`, onde a raiz é a primeira raiz que alcança o trecho na ordem de endereço e `NN` conta a partir de 00 dentro dela. Os IDs têm que ser estáveis entre extrações da mesma ROM.
- `traducao/tabela.tbl`: `20–7E` em ASCII. Controles: `01A0=[cor]`, `0180=[/cor]`, `02=[quebra2]`, `05=[espera]`, `09=[linha]`. Códigos de string gerados: `0C00..0CE7=[s0:XX]`, `0D00..0D40=[item:XX]`, `0E00..0E2A=[nome:XX]`, `0F00..0F08=[s3:XX]`. Os demais (`03 xx`, `04 xx`, `0A xx`, `01 xx`) caem no fallback `[$XX]` da Tabela. **Nada em `0x80–0xFD`** por enquanto (Plano 3).
- `CODIGOS_LIVRES` passa a ser `{"[quebra2]", "[linha]", "[espera]", "[cor]", "[/cor]"}`. Quem traduz pode mover quebras, esperas e destaques; variáveis e strings inseridas continuam obrigatórias.

- [ ] **Step 1:** escrever os testes:
  - `test_trecho_quebrado_por_rotulo`: o texto `Hello World\x00` com um salto apontando para o `W` gera 2 trechos (`Hello `, `World`).
  - `test_estrutural_separa`: `Hi\x0b\x19\x05Yo\x00` (com `0B 19` = `"B"`) gera trecho, estrutural, trecho e fim.
  - `test_exibir_dicionario`: `bruto = b"\x0c\x54 was"`, com dicionário em que `0x54 - 0x3F` = "Monster", dá `"Monster was"`.
  - `test_ids_estaveis`: segmentar duas vezes produz os mesmos IDs.
  - `test_tabela_ida_e_volta_rom` (com `rom_base`): para todo trecho da ROM, `tabela.codificar(tabela.decodificar(bruto)) == bruto`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar `segmentos.py` e `tabela.tbl` e ajustar `CODIGOS_LIVRES`. O teste antigo `test_quebra_livre` usa `[quebra]`: atualizar para `[linha]` e registrar como ruling.
- [ ] **Step 4:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 5:** commit `feat: segmentação de scripts e tabela ASCII`.

### Task 4: Comando `extrair`

**Files:**
- Create: `ferramentas/script/extracao.py`, `testes/test_extracao.py`
- Modify: `ferramentas/cli.py` (subcomando `extrair`)

**Interfaces:**
- Consumes: as Tasks 1 a 3, `mesclar`/`salvar_textos`/`carregar_textos` (fundação).
- Produces:
  - `def extrair_texto(rom: bytes, cfg: dict) -> tuple[dict, dict[str, list[Entrada]]]`, que devolve o esqueleto completo (`{"raizes": {nome: rotulo}, "instrucoes": [...], "trechos": {id: hex_bruto}}`) e as entradas agrupadas por arquivo: `dialogos`, `banco0_sistema` (índices 0x00–0x3E), `banco1_itens`, `banco2_nomes`, `banco3_lojas` e `extras`. O dicionário (banco 0, 0x3F–0xE7) **não** vira entrada traduzível: ele só é lido para exibição.
  - CLI `extrair [--rom]`: grava `dados/scripts/esqueleto.json` (JSON indentado, `sort_keys`, UTF-8, LF) e mescla cada `traducao/textos/<arquivo>.yaml` com `mesclar`.

- [ ] **Step 1:** escrever os testes (com `rom_base`):
  - `test_extrair_contagens`: `dialogos` tem pelo menos 131 entradas, e os ids `b1.*` cobrem as 65 entradas do banco 1.
  - `test_en_legivel`: alguma entrada de `dialogos` contém o texto `"was once a peaceful"` (expansão do dicionário funcionando).
  - `test_reextrair_preserva_pt`: depois de `extrair`, editar um `pt`, rodar `extrair` de novo e confirmar que o `pt` continua lá.
  - `test_esqueleto_deterministico`: duas extrações dão um `esqueleto.json` idêntico byte a byte.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar `python -m ferramentas extrair` na ROM real e conferir a contagem total de trechos e uma amostra de 5 entradas lidas no YAML.
- [ ] **Step 5:** rodar os testes. Esperado: PASS.
- [ ] **Step 6:** commit dos fontes **e** do `dados/scripts/esqueleto.json` + `traducao/textos/*.yaml` gerados: `feat: comando extrair`.

### Task 5: Montador, realocação e etapa de build

**Files:**
- Create: `ferramentas/script/montador.py`, `testes/test_montador.py`
- Modify: `ferramentas/cli.py` (registrar a etapa em `ETAPAS`; o `construir` passa a carregar o esqueleto), `ferramentas/verificacao.py` (checagem `checar_espaco`, que usa `ctx.extra["montagem"]`)

**Interfaces:**
- Consumes: o esqueleto (Task 4), `Tabela`, os textos.
- Produces:
  - `class ErroMontagem(Exception)` (entra em `ERROS_ESPERADOS`)
  - `def montar_bloco(instrucoes: list[dict], bytes_trecho: Callable[[str], bytes], base: int) -> tuple[bytes, dict[str, int]]`: duas passadas (tamanhos → endereços dos rótulos → bytes) que devolvem o bloco e o mapa rótulo→endereço. Um salto com destino fora de ±0x8000 lança `ErroMontagem`.
  - `def montar_texto(esqueleto: dict, textos: dict[str, list[Entrada]], tabela: Tabela, destino: int, limite: int, modo: str = "traducao") -> Layout`, com `@dataclass class Layout: blocos: list[tuple[int, bytes]]; ponteiros: list[tuple[int, int]]  # (endereço, valor u32)`. Com `modo="original"`, todo trecho usa `bruto`. Com `modo="traducao"`, usa `tabela.codificar(pt)` quando `pt` não está vazio e `bruto` quando está.
  - Layout em `destino`: [tabela de diálogos 131×3 + scripts de diálogo] [tabela banco 0 + strings] [banco 1] [banco 2] [banco 3], com cada tabela imediatamente antes das suas strings. Os ponteiros atualizados são `0x1CC14` ← tabela de diálogos, `0x211CA..0x211D9` ← as 4 bases de banco, e cada endereço de `raizes_extra` ← o novo endereço do seu rótulo. Para preservar alvos e fall-through que cruzam bancos, os rótulos compartilhados entre blocos são resolvidos globalmente (um único mapa).
  - Etapa `etapa_texto(rom: bytearray, projeto: Projeto) -> None`: aplica o `Layout` (offsets de tabela recalculados com sinal) e falha se passar de `regiao_destino`.
  - Função auxiliar `montar_no_lugar(...)` (modo original, base = endereços originais), usada só pelo teste de identidade.
- Observação: o byte `flag` de cada diálogo vem do esqueleto (o extrator precisa guardá-lo; se a Task 4 não guardou, incluir aqui como ruling).

- [ ] **Step 1:** escrever os testes sintéticos:
  - `test_rotulos_resolvidos`: esqueleto com `06 → L_x` antes e depois de um trecho que cresce de 2 para 6 bytes; os alvos recalculados apontam para os rótulos certos.
  - `test_salto_fora_de_alcance`: lança `ErroMontagem`.
  - `test_estouro_regiao`: `limite` pequeno lança `ErroMontagem` com "excede" e o número de bytes na mensagem.
- [ ] **Step 2:** escrever os testes com a ROM real:
  - `test_identidade_no_lugar` (spec §6.5.1): `montar_no_lugar` com o esqueleto extraído reproduz **exatamente** os bytes `0x1DD94–0x22460` da ROM.
  - `test_realocado_equivalente`: aplica `etapa_texto` em modo original sobre a ROM, desmonta a ROM resultante a partir das novas tabelas e confirma que a sequência de trechos `bruto` por raiz é igual à da ROM original e que todo salto aponta para o rótulo equivalente.
  - `test_build_cli_com_texto`: com a ROM real, `construir` retorna 0, a ROM gerada tem os ponteiros novos e o IPS só toca `0x1CC14`, `0x211CA–0x211D9`, `raizes_extra`, `0xA4C80+` e o cabeçalho (`0x18E`, `0x1A4`).
- [ ] **Step 3:** rodar. Esperado: FAIL.
- [ ] **Step 4:** implementar e registrar `etapa_texto` em `ETAPAS`.
- [ ] **Step 5:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 6:** commit `feat: montador de scripts e realocação do texto`.

### Task 6: Strings inline de tamanho fixo

**Files:**
- Create: `ferramentas/inline.py`, `testes/test_inline.py`
- Modify: `config/texto.yaml` (`inline:`), `ferramentas/script/extracao.py` (gerar `traducao/textos/inline.yaml`), `ferramentas/cli.py` (segunda etapa em `ETAPAS`)

**Interfaces:**
- Produces:
  - Item de config: `{id: "quiz.tempo", end: 0x1D70, tam: 10, preencher: "espaco"}`, onde `preencher` vale `espaco` (completa com `0x20`) ou `nulo` (completa com `0x00`). O `tam` não inclui o terminador `00`, que já existe na ROM e não é tocado.
  - `def extrair_inline(rom: bytes, itens: list[dict], tabela: Tabela) -> list[Entrada]`
  - `def etapa_inline(rom: bytearray, projeto: Projeto) -> None`: um `pt` codificado maior que `tam` lança `ErroMontagem` com o id. O `pt` vazio mantém o original.
  - Checagem `checar_inline` no `verificar` (mesmo erro, antes do build).
- Itens iniciais (confirmar o tamanho exato de cada um lendo a ROM e registrar em `config/texto.yaml`): `0x1D70` "Time's up.", "Incorrect.", "Correct." · `0x1FE3` "Found the ", "Found ", " GOLD." · `0x7BB6–0x7C42` nomes de magia (cada nome é um item; os bytes de coordenada entre eles não são tocados) · `0x84DE` "AP", "DP", "SP", "GOLD" · `0x1ABD9–0x1AD5D` títulos dos créditos (só os títulos de função; nomes de pessoas não são traduzidos). Os mini-scripts da ocarina (`0x2B59–0x2C05`) **não** são inline de tamanho fixo: eles entram como `raizes_extra` da Task 1 se a auditoria confirmar referência absoluta; se não, entram aqui com `tam` fixo e ruling.

- [ ] **Step 1:** escrever os testes:
  - `test_inline_cabe_preenche`: `tam=10`, `pt="Acabou!"` → bytes `b"Acabou!   "`.
  - `test_inline_estoura`: lança `ErroMontagem` contendo o id.
  - `test_inline_pt_vazio_mantem` mantém o original.
  - `test_inline_rom` (com `rom_base`): os `en` extraídos batem com os textos listados acima.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 5:** commit `feat: strings inline de tamanho fixo`.

### Task 7: Checagem de largura de linha e relatório

**Files:**
- Modify: `ferramentas/verificacao.py`, `ferramentas/cli.py`, `config/texto.yaml`
- Test: `testes/test_largura.py`

**Interfaces:**
- Produces:
  - `config/texto.yaml: largura_linha: <N>`. N é calculado no Step 3 como a maior largura de linha observada nos `en` dos diálogos, contando caracteres entre `[linha]`/`[quebra2]`/início com as palavras do dicionário expandidas. O valor medido e o método ficam registrados em `mapa-rom.md`.
  - `checar_largura(ctx)`: para cada `pt` não vazio, uma linha mais larga que N vira **erro**. Os códigos `[s0:XX]`, `[item:XX]`, `[nome:XX]` e `[s3:XX]` contam pelo comprimento da maior string possível do banco correspondente. Para `[s0:XX]` com XX < 0x3F conta o tamanho daquela entrada; para variáveis cujo valor só se conhece em tempo de execução (nome de item escolhido), conta o maior nome do banco 1.
  - O relatório do `construir` ganha a linha `Espaço: N bytes usados de M em 0xA4C80–0xC0000`.

- [ ] **Step 1:** escrever os testes: `test_linha_longa_erro`, `test_variavel_conta_maior_nome` e `test_en_original_passa` (com `rom_base`: aplicar a checagem com `pt = en` exibido em todas as entradas não pode dar erro, o que valida N).
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** medir N na ROM, gravar na config e implementar.
- [ ] **Step 4:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 5:** atualizar o README (seção "Uso": `extrair`, onde editar os textos e o significado das tags `[linha]`, `[espera]`, `[cor]`, `[item:XX]` etc.).
- [ ] **Step 6:** commit `feat: checagem de largura de linha e relatório de espaço`.

---

## Depois deste plano

- **Plano 3:** emulador controlável (escolha + automação de capturas), localização e descompressão da fonte (via VRAM), letras acentuadas em `0x80–0xFD`, entradas novas na `tabela.tbl`, tiles traduzidos da tela inicial e o primeiro teste visual do texto realocado no jogo.
- **Plano 4:** tradução em lotes por arquivo YAML, glossário, revisão jogável e distribuição (IPS final + README).
