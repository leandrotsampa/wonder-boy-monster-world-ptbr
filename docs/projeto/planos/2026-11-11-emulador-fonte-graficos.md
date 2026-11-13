# Emulador, fonte com acentos e tela inicial: plano de implementação

**Goal:** (1) ter um emulador controlável por script para capturar telas e ler a memória de vídeo; (2) extrair a fonte do jogo para PNG editável e reinseri-la com as letras acentuadas do PT-BR; (3) traduzir os tiles da tela inicial; (4) ver o texto realocado rodando no jogo e confirmar a largura real da janela.

**Architecture:** um frontend libretro mínimo em Python (`ctypes`) carrega o core **Genesis Plus GX**. Ele roda roteiros YAML (botões + espera + captura) e lê RAM e VRAM. É ferramenta de desenvolvimento: o build não depende dele, e os testes que o usam dão skip sem o core. A fonte e os gráficos viram PNG indexados em `graficos/` e entram no build como novas etapas em `ETAPAS`, com (re)compressão no formato do jogo e realocação se não couberem no lugar.

**Tech Stack:** Python 3.11+, ctypes, Pillow, PyYAML, pytest; core libretro `genesis_plus_gx_libretro.dll` (Windows x64). O core **não** vai para o git: fica em `emu/` (ignorado) e o README explica de onde baixar.

**Spec:** `docs/projeto/design/2026-11-11-traducao-wbmw-ptbr-design.md`. Referências: `docs/tecnico/mapa-rom.md` (§8 fonte e gráficos) e `docs/tecnico/pendencias.md` (itens "a confirmar no emulador").

## Global Constraints

- Nenhuma ROM nem o core do emulador vão para o git (`emu/` entra no `.gitignore`). **Baixar o core exige aprovação explícita do autor** no momento da execução. A fonte proposta é o buildbot oficial do libretro: `https://buildbot.libretro.com/nightly/windows/x86_64/latest/genesis_plus_gx_libretro.dll.zip`.
- Testes que precisam do core usam a fixture `emulador` (skip com "core libretro ausente" se `emu/genesis_plus_gx_libretro.dll` não existir). Testes que precisam da ROM continuam usando `rom_base`. A suíte passa sem os dois.
- A origem de cada glifo e de cada parte gráfica nova fica registrada nos metadados do PNG. Nada de sprites, roteiro ou gráficos de personagens novos.
- Na tela inicial só mudam os tiles do texto ("APERTE START", "NOVO JOGO", "CONTINUAR"), por decisão do autor.
- O logo "Wonder Boy in Monster World" **não** muda.
- Determinismo: o mesmo PNG gera os mesmos bytes, e o compressor é determinístico.
- O build continua falhando sem gravar nada se um gráfico não couber, se o PNG for inválido ou se faltar um glifo para um caractere usado no texto.

## Review Focus

1. **Glifo faltando:** se um `pt` usa "ã" e a tabela não tem "ã", o `verificar` tem que dar erro com o id. Isso já existe. Falta garantir que **todo** caractere da tabela tenha tile na fonte inserida. Teste na Task 4.
2. **Tiles da fonte colidindo com outros gráficos no VRAM:** os códigos escolhidos para os acentos não podem ocupar tiles que o jogo usa em outra cena (borda da janela, HUD, inventário). Verificação com capturas na Task 3 e teste na Task 4.
3. **Fonte maior que o blob original:** o recomprimido não cabe no lugar. Precisa realocar e repontar, com erro claro se nem isso der. Teste na Task 4.
4. **PNG editado com cor fora da paleta ou dimensões erradas:** erro com o nome do arquivo (já coberto por `tiles.py`). O teste de integração está na Task 4.
5. **Emulador não determinístico:** o mesmo roteiro tem que gerar as mesmas capturas, senão os testes visuais ficam frágeis. Teste na Task 1.

---

### Task 1: Frontend libretro e roteiros de captura

**Files:**
- Create: `ferramentas/emulador/__init__.py`, `ferramentas/emulador/libretro.py`, `ferramentas/emulador/roteiro.py`, `ferramentas/emulador/__main__.py`, `testes/test_emulador.py`, `roteiros/boot.yaml`
- Modify: `.gitignore` (`emu/`), `testes/conftest.py` (fixture `emulador`), `README.md` (seção "Emulador para testes": de onde baixar o core e onde colocá-lo)

**Interfaces:**
- Produces:
  - `class Emulador` em `libretro.py`:
    - `__init__(self, caminho_core: Path, caminho_rom: Path)`
    - `avancar(self, quadros: int, botoes: set[str] = frozenset()) -> None`, com botões `{"cima","baixo","esq","dir","a","b","c","start"}` mapeados para o RetroPad (`B→A`, `A→B`, `Y→C` ou o mapeamento que o core usar; registrar o mapeamento no código)
    - `quadro_png(self, caminho: Path) -> None`
    - `ram(self) -> bytes` (64 KB da RAM do 68000)
    - `vram(self) -> bytes` (64 KB)
    - `salvar_estado(self) -> bytes` e `carregar_estado(self, dados: bytes) -> None`
    - `fechar(self) -> None`
  - `vram()`: primeiro tentar `retro_get_memory_data(RETRO_MEMORY_VIDEO_RAM)`. Se o core não expuser, usar os memory maps (`RETRO_ENVIRONMENT_SET_MEMORY_MAPS`). Se nada disso der, extrair do save state (localizar o offset do VRAM no formato de estado do GPGX e documentar). Registrar como ruling qual caminho funcionou.
  - Roteiro YAML: lista de passos `{"esperar": N}`, `{"apertar": ["start"], "quadros": 2}`, `{"capturar": "nome"}`, `{"vram": "nome"}`, `{"estado_salvar": "nome"}` e `{"estado_carregar": "nome"}`. `python -m ferramentas.emulador <roteiro.yaml> [--rom CAMINHO]` grava as saídas em `build/capturas/<roteiro>/`.
- [ ] **Step 1:** pedir ao autor a aprovação para baixar o core (nome, origem e tamanho). Sem aprovação, parar a tarefa com BLOCKED.
- [ ] **Step 2:** escrever os testes (fixture `emulador` + `rom_base`):
  - `test_boot_mostra_imagem`: depois de 600 quadros, a captura não é toda de uma cor só.
  - `test_deterministico`: duas execuções do mesmo roteiro dão PNGs idênticos byte a byte.
  - `test_vram_tamanho`: `len(vram()) == 0x10000` e não é toda zero depois do boot.
  - `test_estado_ida_e_volta`: salvar, avançar 60, carregar e avançar 60 de novo dá a mesma captura.
- [ ] **Step 3:** rodar. Esperado: FAIL.
- [ ] **Step 4:** implementar `libretro.py` (callbacks de vídeo RGB565/XRGB8888 → PNG, input, environment com `SET_PIXEL_FORMAT`, `GET_SYSTEM_DIRECTORY`, `SET_MEMORY_MAPS`) e `roteiro.py`.
- [ ] **Step 5:** escrever `roteiros/boot.yaml` (boot → tela de título → captura) e rodá-lo na ROM base. Conferir a captura visualmente.
- [ ] **Step 6:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 7:** commit `feat: emulador libretro controlável por roteiro`.

### Task 2: Localizar a fonte e o formato de compressão

**Files:**
- Create: `ferramentas/compressao.py`, `testes/test_compressao.py`, `roteiros/dialogo.yaml`
- Modify: `docs/tecnico/mapa-rom.md` §8

**Interfaces:**
- Produces:
  - `def descomprimir(rom: bytes, end: int) -> tuple[bytes, int]`, que devolve (dados, bytes consumidos);
  - `def comprimir(dados: bytes) -> bytes`, determinístico, com `descomprimir(comprimir(x)) == x` (não precisa ser idêntico ao original);
  - um registro do formato em `mapa-rom.md` §8 (cabeçalho, códigos, rotina do 68000 que descomprime, endereço do blob da fonte, ponteiro que aponta para ele, destino no VRAM).
- Método:
  1. O roteiro `dialogo.yaml` (novo jogo → primeira fala) captura a tela e o VRAM com a janela de diálogo aberta.
  2. Pelo VRAM, identificar os tiles da fonte. O código do caractere é o índice do tile (mais um offset a descobrir; ver o mapa §5: "cada caractere ocupa 2 linhas de tiles").
  3. Achar a rotina que grava esses tiles (busca no código por comandos de escrita do VDP para o endereço VRAM correspondente, ou pela tabela de blocos e pelos blobs da fonte: `0x41020–0x417C4`, `0x42019–0x4213E`, `0x4214F–0x42274`).
  4. Ler o descompressor com o capstone e reimplementá-lo em Python.
- [ ] **Step 1:** escrever os testes:
  - `test_descomprime_fonte_bate_com_vram` (com `rom_base` + `emulador`): `descomprimir(rom, END_FONTE)` é igual aos bytes do VRAM na região da fonte capturada.
  - `test_comprimir_ida_e_volta`: para dados sintéticos (zeros, aleatórios com semente fixa, tiles repetidos) e para a fonte real, `descomprimir(comprimir(x)) == x`.
  - `test_comprimir_deterministico`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** investigar e implementar até os testes passarem. Se o formato for algum conhecido do Mega Drive (Nemesis, Kosinski, Enigma, LZSS próprio), dizer qual e citar a evidência.
- [ ] **Step 4:** documentar em `mapa-rom.md` §8.
- [ ] **Step 5:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 6:** commit `feat: descompressor e compressor de gráficos`.

### Task 3: Mapa de tiles livres e escolha dos códigos dos acentos

**Files:**
- Create: `roteiros/cenas.yaml`, `docs/tecnico/vram.md`
- Modify: `config/texto.yaml` (`acentos:`)

**Interfaces:**
- Produces:
  - `docs/tecnico/vram.md`: quais faixas de tiles cada cena usa (título, campo, diálogo, loja, inventário/status, menu de magias, créditos, se der) e quais ficam livres enquanto a janela de texto está aberta.
  - `config/texto.yaml: acentos:` com o mapa caractere → código (byte) para no mínimo `á à â ã é ê í ó ô õ ú ç Á À Â Ã É Ê Í Ó Ô Õ Ú Ç`. Os códigos ficam em `0x80–0xFD`, fora dos usados pelo jogo e dos que o script reserva (`FE`/`FF` são prefixo). Confirmar que os tiles escolhidos estão livres no VRAM em todas as cenas com texto.
- [ ] **Step 1:** escrever `cenas.yaml`, que visita cada cena com texto e despeja o VRAM, e rodar na ROM base.
- [ ] **Step 2:** analisar (script auxiliar em `ferramentas/emulador/`, se útil) e escrever `vram.md`.
- [ ] **Step 3:** escolher os códigos e registrar em `config/texto.yaml`, cada um com justificativa em `vram.md`. Se não houver 24 códigos livres, registrar a solução adotada (ex.: maiúsculas acentuadas só onde necessário, ou acento no tile superior via prefixo `FE`/`FF` com os tiles `0xBE`/`0xBF`) como ruling.
- [ ] **Step 4:** commit `docs: mapa de VRAM e códigos dos acentos`.

### Task 4: Fonte editável em PNG e etapa de build

**Files:**
- Create: `ferramentas/fonte.py`, `testes/test_fonte.py`, `graficos/fonte/fonte.png`, `graficos/fonte/fonte.yaml` (metadados: origem, endereço do blob, ponteiro, quantidade de tiles, paleta usada para exibição e a origem de cada glifo novo)
- Modify: `ferramentas/cli.py` (`extrair` também gera a fonte se o PNG não existir; `etapa_fonte` em `ETAPAS`), `traducao/tabela.tbl` (entradas dos acentos), `ferramentas/verificacao.py` (checagem `checar_glifos`), `README.md` (como editar a fonte)

**Interfaces:**
- Consumes: `descomprimir`/`comprimir` (Task 2), `tiles_para_png`/`png_para_tiles` (fundação), `acentos` (Task 3), `Layout`/região livre (Plano 2: a fonte vai **depois** do texto em `0xA4C80+` se precisar realocar; o espaço é calculado em conjunto).
- Produces:
  - `def extrair_fonte(rom: bytes, cfg: dict, destino: Path) -> None`
  - `def etapa_fonte(rom: bytearray, projeto: Projeto) -> None`: lê o PNG, comprime, grava no lugar se couber; se não couber, grava na região livre e reponta. Erro esperado se não houver espaço.
  - `checar_glifos(ctx)`: todo caractere de `tabela.caracteres()` tem que ter tile não vazio na fonte (exceto o espaço), senão é erro.
- Glifos novos: desenhados no PNG, nos códigos escolhidos, no estilo da fonte original. A origem de cada glifo fica registrada em `fonte.yaml`.
- [ ] **Step 1:** escrever os testes:
  - `test_fonte_ida_e_volta` (com `rom_base`): extrair o PNG e reinserir sem mudanças reproduz o mesmo conteúdo descomprimido. Se o blob recomprimido for idêntico, melhor ainda; senão, a equivalência descomprimida basta.
  - `test_fonte_maior_realoca` (sintético) e `test_fonte_sem_espaco_erro`.
  - `test_glifo_faltando_erro`.
  - `test_acentos_codificam`: `tabela.codificar("ação")` dá os bytes dos códigos escolhidos.
  - `test_jogo_mostra_acento` (com `rom_base` + `emulador`): build com um `pt` de teste contendo "ÁÉÍÓÚ ãõç" na primeira fala, rodar `dialogo.yaml` e comparar a região da janela da captura com uma imagem de referência gerada a partir dos tiles do PNG (ou, no mínimo, confirmar que os tiles dos códigos de acento estão no VRAM com o conteúdo do PNG).
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar, extrair a fonte, compor os glifos e atualizar a tabela.
- [ ] **Step 4:** olhar as capturas do `test_jogo_mostra_acento` e registrar no relatório.
- [ ] **Step 5:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 6:** commit `feat: fonte editável com acentos do PT-BR`.

### Task 5: Tiles traduzidos da tela inicial

**Files:**
- Create: `ferramentas/graficos.py`, `testes/test_graficos.py`, `graficos/telas/titulo.png`, `graficos/telas/titulo.yaml`
- Modify: `ferramentas/cli.py` (`importar-tiles` e `etapa_graficos`), `config/texto.yaml` ou `config/graficos.yaml`

**Interfaces:**
- Produces:
  - `importar-tiles --origem <ROM> --item <nome>`: localiza, descomprime e grava o PNG + metadados (origem e endereço).
  - `etapa_graficos(rom, projeto)`: insere cada item de `config/graficos.yaml` (PNG → tiles → compressão no formato do item → no lugar ou realocado com repoint).
- Método: rodar `boot.yaml` na ROM base, localizar no VRAM da tela de título e da tela de menu (NOVO JOGO / CONTINUAR) os tiles do texto e o bloco comprimido de origem com o ponteiro correspondente. Se o tilemap da tela precisar mudar (posição/tamanho do texto), ele entra como um item à parte.
- [ ] **Step 1:** escrever os testes:
  - `test_titulo_importado_ida_e_volta`: o PNG reinserido na base gera o VRAM de título esperado nas faixas do texto.
  - `test_titulo_no_jogo` (com `emulador`): a captura da tela de título do build mostra o PNG na região do texto e é igual à da base fora dela (o logo não muda).
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 5:** commit `feat: tela inicial traduzida`.

### Task 6: Primeira validação no jogo e ajuste das regras de largura

**Files:**
- Create: `roteiros/validacao.yaml`, `testes/test_validacao_jogo.py`
- Modify: `config/texto.yaml` (`largura_linha`, `linhas_por_caixa` se houver), `ferramentas/verificacao.py` (regras confirmadas ou corrigidas), `docs/tecnico/mapa-rom.md` ("Largura de linha"), `docs/tecnico/pendencias.md`

**Interfaces:**
- Para cada item "A confirmar no emulador" de `pendencias.md`/`mapa-rom.md`: montar um `pt` de teste que exercita o caso (linha com exatamente N caracteres, N+1, `[$04]` depois de texto, string do banco 3 seguida de texto, nome de item longo inserido, muitas linhas numa caixa), rodar no emulador, capturar e decidir.
- [ ] **Step 1:** escrever `test_validacao_jogo` (com `rom_base` + `emulador`): para cada caso, build com o `pt` de teste, roteiro até a fala e captura. Cada asserção compara a captura com o comportamento decidido (ex.: o caractere da coluna N aparece e o N+1 quebra/corta, verificado pelos pixels da região da janela).
- [ ] **Step 2:** rodar, olhar as capturas e decidir cada item. Atualizar `largura_linha`, as heurísticas e o limite de linhas por caixa (nova checagem `checar_linhas` se o jogo tiver limite). Cada decisão vira ruling com a captura de referência citada.
- [ ] **Step 3:** atualizar `pendencias.md` (marcar resolvidos) e `mapa-rom.md`.
- [ ] **Step 4:** rodar a suíte inteira. Esperado: PASS.
- [ ] **Step 5:** commit `feat: regras de largura confirmadas no jogo`.

---

## Depois deste plano

**Plano 4:** tradução em lotes (diálogos, sistema, itens, lojas, inline), glossário, ocarina (repoint se precisar), revisão jogável pelo autor e distribuição (IPS final + README com instruções e créditos).
