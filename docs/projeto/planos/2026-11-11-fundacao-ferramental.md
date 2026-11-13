# Fundação e ferramental: plano de implementação

**Goal:** criar o repositório e o ferramental Python que não depende do formato da ROM: validação e checksum de ROM, gerador e aplicador de IPS, tabela de caracteres, modelo YAML dos textos, codec de tiles 4bpp ↔ PNG, framework de verificação e a CLI `checar-rom` / `verificar` / `construir`.

**Architecture:** um pacote Python `ferramentas/` com um módulo por responsabilidade e uma CLI (`python -m ferramentas`) que só orquestra. Todo o ferramental é testado com ROMs e dados sintéticos gerados nos testes, porque nenhuma ROM real entra no repositório nem nos testes. O conhecimento específico do jogo (offsets, ponteiros, regiões) fica para o Plano 2, depois do reconhecimento.

**Tech Stack:** Python 3.11+ (a máquina do autor tem 3.12.2), Pillow, PyYAML, pytest.

**Spec:** `docs/projeto/design/2026-11-11-traducao-wbmw-ptbr-design.md`

**Fora deste plano (vêm no Plano 2, depois do reconhecimento com as ROMs em `rom/`):** mapa da ROM, `extrair`, `importar-tiles`, a fonte com acentos, realocação/expansão, emulador controlável, tradução, gráficos e a distribuição final.

## Global Constraints

- Python 3.11+. Dependências só via `requirements.txt`: Pillow, PyYAML, pytest. Sem ferramentas externas de romhacking.
- Nenhuma ROM comercial no git. `rom/` e `build/` são ignorados, assim como as extensões `*.bin *.md *.gen *.smd *.ips` fora de `docs/`. Atenção: `*.md` é extensão de ROM do Mega Drive, então o `.gitignore` ignora `*.md` só em `rom/` e `build/`. Não ignorar globalmente, senão os docs somem.
- Todo arquivo de texto (YAML, `.tbl`) é lido e gravado em **UTF-8** explícito (`encoding="utf-8"`). O autor usa Windows.
- Build determinístico: a mesma entrada gera bytes idênticos (sem timestamps dentro da ROM ou do IPS).
- Nomes de módulos, comandos e mensagens em português, como no spec (`checar-rom`, `verificar`, `construir`).
- Testes em `testes/`, rodados com `python -m pytest`.

## Review Focus

1. **ROM com cabeçalho SMD de 512 bytes ou entrelaçada (`.smd`):** o usuário pode ter esse formato. O esperado é uma mensagem clara ("ROM em formato SMD; converta para .bin") e não um simples "hash não confere". Teste na Task 2.
2. **ROM errada ou modificada:** com hash divergente, `checar-rom` e `construir` param sem gravar nada em `build/` e mostram o hash esperado e o obtido. Testes nas Tasks 2 e 8.
3. **Registro IPS no offset 0x454F46 ("EOF"):** um registro começando nesse offset seria lido como fim do patch e corromperia o arquivo. O gerador tem que começar o registro 1 byte antes. Teste na Task 3.
4. **Acentos no texto em Windows:** um YAML com "ã", "ç" ou "é" tem que fazer o ciclo carregar/salvar sem virar mojibake, e caractere fora da tabela vira erro com o `id` da entrada. Testes nas Tasks 4, 5 e 7.
5. **Regravar YAML de tradução:** mesclar o original extraído com o arquivo existente nunca apaga nem altera `pt`, `status` ou `nota`. Teste na Task 5.

---

### Task 1: Repositório e esqueleto do pacote

**Files:**
- Create: `.gitignore`, `README.md`, `requirements.txt`, `pyproject.toml` (só configuração do pytest: `testpaths = ["testes"]`), `ferramentas/__init__.py`, `ferramentas/__main__.py`, `testes/test_pacote.py`, `config/rom.yaml`, `rom/.gitkeep`

**Interfaces:**
- Produces: pacote `ferramentas` importável; `ferramentas.__version__ = "0.1.0"`; `config/rom.yaml` com as chaves `nome_arquivo: "Wonder Boy in Monster World (UE) [!].bin"`, `sha1: null`, `crc32: null`, `tamanho: null` (preenchidas no reconhecimento).

- [ ] **Step 1:** `git init` na raiz e `git branch -M main`.
- [ ] **Step 2:** criar o `.gitignore` com `rom/*`, `!rom/.gitkeep`, `build/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.venv/`, e por segurança `*.bin`, `*.gen`, `*.smd`, `*.ips` (de novo: **não** ignorar `*.md` globalmente).
- [ ] **Step 3:** criar o teste `testes/test_pacote.py::test_versao` com `import ferramentas; assert ferramentas.__version__ == "0.1.0"`.
- [ ] **Step 4:** rodar `python -m pytest` e confirmar que FALHA (o módulo não existe).
- [ ] **Step 5:** criar `ferramentas/__init__.py` e um `__main__.py` vazio que delega para `ferramentas.cli.main` (a Task 8 cria o `cli`; até lá o `__main__` só faz `print("em construção")`). Criar também `requirements.txt` (`Pillow>=10`, `PyYAML>=6`, `pytest>=8`), `pyproject.toml`, `config/rom.yaml` e `README.md` (o que é o projeto, que a ROM não vem junto, onde colocá-la e como instalar com `pip install -r requirements.txt`).
- [ ] **Step 6:** `pip install -r requirements.txt` e depois `python -m pytest`. Esperado: PASS.
- [ ] **Step 7:** commit de todos os arquivos, incluindo `docs/projeto/design/` e `docs/projeto/planos/`: `chore: estrutura inicial do repositório`.

### Task 2: ROM — carga, hash, validação e checksum do cabeçalho

**Files:**
- Create: `ferramentas/rom.py`, `testes/test_rom.py`, `testes/conftest.py`

**Interfaces:**
- Produces:
  - `class ErroRom(Exception)`
  - `def hashes(dados: bytes) -> dict[str, str]`, que retorna `{"sha1": hex minúsculo, "crc32": "%08x"}`
  - `def carregar_rom(caminho: Path, esperado: dict | None) -> bytearray`. Lança `ErroRom` para formato SMD, para hash diferente de `esperado["sha1"]` (quando não for `None`) e para arquivo inexistente.
  - `def calcular_checksum(rom: bytes) -> int`: soma de palavras big-endian de 16 bits do offset `0x200` até o fim, `& 0xFFFF` (se o tamanho for ímpar, o último byte é tratado como byte alto).
  - `def corrigir_cabecalho(rom: bytearray) -> None`: grava o checksum em `0x18E` (big-endian, 2 bytes) e o fim da ROM `len(rom) - 1` em `0x1A4` (big-endian, 4 bytes).
- Em `conftest.py`, a fixture `rom_sintetica` (bytearray de 0x8000 bytes, com `"SEGA MEGA DRIVE "` em `0x100`, bytes pseudoaleatórios de semente fixa a partir de `0x200` e cabeçalho corrigido).

- [ ] **Step 1:** escrever os testes:
  - `test_checksum_conhecido`: ROM de 0x204 bytes com `00 01 00 02` a partir de 0x200 → `calcular_checksum == 0x0003`.
  - `test_corrigir_cabecalho`: em `rom_sintetica` com 0x18E zerado, depois de `corrigir_cabecalho` vale `int.from_bytes(rom[0x18E:0x190],"big") == calcular_checksum(rom)` e `int.from_bytes(rom[0x1A4:0x1A8],"big") == len(rom)-1`.
  - `test_hash_divergente`: `carregar_rom(arquivo, {"sha1":"00"*20})` lança `ErroRom` com os textos "esperado" e o sha1 obtido na mensagem.
  - `test_formato_smd`: arquivo com 512 bytes extras no início (com `len % 0x4000 == 512`) e sem `"SEGA"` em 0x100 → `ErroRom` com "SMD" na mensagem.
  - `test_esperado_none_aceita`: `esperado=None` carrega sem validar hash.
- [ ] **Step 2:** rodar `python -m pytest testes/test_rom.py`. Esperado: FAIL (falta o módulo).
- [ ] **Step 3:** implementar `ferramentas/rom.py` com as assinaturas acima. A detecção de SMD usa `len(dados) % 0x4000 == 512` e a ausência de `b"SEGA"` em `0x100`.
- [ ] **Step 4:** rodar os testes. Esperado: PASS.
- [ ] **Step 5:** commit `feat: carga, validação e checksum de ROM`.

### Task 3: IPS — gerar e aplicar

**Files:**
- Create: `ferramentas/ips.py`, `testes/test_ips.py`

**Interfaces:**
- Produces:
  - `def gerar_ips(original: bytes, modificado: bytes) -> bytes`
  - `def aplicar_ips(original: bytes, patch: bytes) -> bytes`
  - `class ErroIps(Exception)`
- Formato: `b"PATCH"`, registros com offset de 3 bytes + tamanho de 2 bytes + dados (tamanho ≤ 0xFFFF; regiões maiores são quebradas em vários registros) e `b"EOF"`. Sem RLE (decisão de simplicidade). Se `modificado` for maior, a diferença vira registros além do fim do original. Se for menor, `ErroIps` ("IPS não suporta reduzir a ROM").

- [ ] **Step 1:** escrever os testes:
  - `test_ida_e_volta`: com A = `rom_sintetica` e B = A com 3 regiões alteradas, `aplicar_ips(A, gerar_ips(A,B)) == B`.
  - `test_sem_diferencas`: `gerar_ips(A,A) == b"PATCHEOF"`.
  - `test_expansao`: com B = A + 0x10000 bytes `0xFF`, a ida e volta dá B.
  - `test_regiao_maior_que_ffff`: 0x20000 bytes alterados seguidos, e a ida e volta dá B.
  - `test_offset_eof`: original de 0x460000 bytes zerados, modificado com `byte[0x454F46] = 1` → a ida e volta dá B, e nenhum registro no patch começa no offset 0x454F46 (verificar percorrendo os registros).
  - `test_patch_invalido`: `aplicar_ips(A, b"XXXX")` lança `ErroIps`.
  - `test_reducao`: `gerar_ips(A, A[:-2])` lança `ErroIps`.
- [ ] **Step 2:** rodar os testes. Esperado: FAIL.
- [ ] **Step 3:** implementar. Agrupar bytes diferentes em trechos contínuos. Se um trecho começar em `0x454F46`, começar em `0x454F45`, incluindo esse byte com o valor do modificado.
- [ ] **Step 4:** rodar os testes. Esperado: PASS.
- [ ] **Step 5:** commit `feat: geração e aplicação de patch IPS`.

### Task 4: Tabela de caracteres (`.tbl`)

**Files:**
- Create: `ferramentas/tabela.py`, `testes/test_tabela.py`

**Interfaces:**
- Produces:
  - `class ErroTabela(Exception)`
  - `class Tabela` com:
    - `@classmethod carregar(cls, caminho: Path) -> Tabela`
    - `@classmethod de_texto(cls, texto: str) -> Tabela`
    - `def decodificar(self, dados: bytes) -> str`
    - `def codificar(self, texto: str, id_entrada: str = "?") -> bytes`
    - `def caracteres(self) -> set[str]`
- Formato (estilo Thingy), uma linha por entrada: `HEX=valor`, onde HEX tem 1 ou mais bytes (ex.: `41=A`, `F001=[nome]`). Valores entre colchetes são códigos de controle. Linhas vazias e linhas começando com `#` são ignoradas. O valor pode conter `=` (só a primeira ocorrência separa a chave). HEX duplicado lança `ErroTabela`.
- `decodificar`: casamento do maior prefixo de bytes. Byte desconhecido vira `[$XX]`.
- `codificar`: casamento do maior prefixo de texto, e `[$XX]` vira o byte literal. Um caractere sem mapeamento lança `ErroTabela` com `id_entrada`, o caractere e a posição na mensagem.

- [ ] **Step 1:** escrever os testes com a tabela `"41=A\n42=B\n80=ã\nE0=á\nF0=[quebra]\nF001=[nome]\nFF=[fim]"`:
  - `test_decodificar`: `bytes([0x41,0x80,0xF0,0x42,0xF0,0x01,0xFF]) → "Aã[quebra]B[nome][fim]"`.
  - `test_codificar_ida_e_volta`: `codificar(decodificar(x)) == x` para o mesmo x.
  - `test_byte_desconhecido`: `decodificar(b"\x10") == "[$10]"` e `codificar("[$10]") == b"\x10"`.
  - `test_caractere_ausente`: `codificar("Aç", "vila.npc1")` lança `ErroTabela` contendo `"vila.npc1"` e `"ç"`.
  - `test_carregar_utf8`: grava a tabela num arquivo temporário em UTF-8 e `carregar` decodifica "ã" corretamente.
  - `test_hex_duplicado`: `"41=A\n41=B"` lança `ErroTabela`.
- [ ] **Step 2:** rodar os testes. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar os testes. Esperado: PASS.
- [ ] **Step 5:** commit `feat: tabela de caracteres`.

### Task 5: Modelo de textos (YAML)

**Files:**
- Create: `ferramentas/textos.py`, `testes/test_textos.py`

**Interfaces:**
- Produces:
  - `STATUS = ("pendente", "traduzido", "revisado")`
  - `@dataclass class Entrada: id: str; en: str; pt: str = ""; status: str = "pendente"; nota: str = ""`
  - `class ErroTextos(Exception)`
  - `def carregar_textos(caminho: Path) -> list[Entrada]`, que lança `ErroTextos` para id duplicado, status inválido, campo `id`/`en` ausente, ou `status != "pendente"` com `pt` vazio. A mensagem inclui o arquivo e o id.
  - `def salvar_textos(caminho: Path, entradas: list[Entrada]) -> None`: YAML em UTF-8, `allow_unicode=True`, `sort_keys=False`, chaves na ordem `id, en, pt, status, nota`, sem gravar `nota` vazia.
  - `def mesclar(existentes: list[Entrada], extraidas: list[Entrada]) -> list[Entrada]`: segue a ordem de `extraidas`. Para um id existente, mantém `pt/status/nota` e atualiza `en`. Se `en` mudou e havia `pt`, volta `status` para `"pendente"` e acrescenta à `nota` o texto `"[original mudou]"`. Ids novos entram como pendentes. Ids que sumiram ficam no fim, com `nota` acrescida de `"[órfão]"`.
  - `def carregar_todos(pasta: Path) -> dict[str, list[Entrada]]`, com uma chave por arquivo `*.yaml` (nome sem extensão) e id duplicado **entre arquivos** gerando `ErroTextos`.

- [ ] **Step 1:** escrever os testes:
  - `test_salvar_carregar_acentos`: ida e volta de uma `Entrada(id="a", en="Hi", pt="Olá, ação!", status="traduzido")`, preservando "Olá, ação!" e com o arquivo contendo os bytes UTF-8 de "ã" literalmente (sem `\u` escapado).
  - `test_id_duplicado`, `test_status_invalido`, `test_traduzido_sem_pt` lançam `ErroTextos` com o id na mensagem.
  - `test_mesclar_preserva_traducao`: um existente traduzido com o mesmo `en` mantém `pt` e `status`.
  - `test_mesclar_original_mudou`: o status vira `pendente`, o `pt` é mantido e a nota contém `"[original mudou]"`.
  - `test_mesclar_novo_e_orfao`: um id novo entra pendente e um id que sumiu vai para o fim com `"[órfão]"`.
  - `test_duplicado_entre_arquivos`: dois YAML com o mesmo id fazem `carregar_todos` lançar `ErroTextos`.
- [ ] **Step 2:** rodar os testes. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar os testes. Esperado: PASS.
- [ ] **Step 5:** commit `feat: modelo YAML de textos`.

### Task 6: Tiles 4bpp do Mega Drive ↔ PNG indexado

**Files:**
- Create: `ferramentas/tiles.py`, `testes/test_tiles.py`

**Interfaces:**
- Produces:
  - `def cor_md_para_rgb(palavra: int) -> tuple[int,int,int]`: formato `0000 BBB0 GGG0 RRR0`, onde cada componente de 3 bits `c` vira `c * 36` (0..252).
  - `def rgb_para_cor_md(rgb: tuple[int,int,int]) -> int`: arredonda para o nível de 3 bits mais próximo.
  - `def paleta_de_bytes(dados: bytes) -> list[tuple[int,int,int]]`: 16 cores a partir de 32 bytes big-endian.
  - `def tiles_para_png(dados: bytes, largura_tiles: int, paleta: list[tuple[int,int,int]], caminho: Path) -> None`: cada tile tem 32 bytes, 8 linhas de 4 bytes, 2 pixels por byte, nibble alto = pixel da esquerda. Os tiles vão da esquerda para a direita e de cima para baixo. Se faltarem tiles para completar a última linha, ela é preenchida com o índice 0 (registrar a quantidade real nos metadados é tarefa de quem chama).
  - `def png_para_tiles(caminho: Path, quantidade: int | None = None) -> bytes`: exige PNG modo `"P"` com largura e altura múltiplas de 8. Pixel com índice > 15 lança `ErroTiles`. `quantidade` corta o resultado.
  - `class ErroTiles(Exception)`

- [ ] **Step 1:** escrever os testes:
  - `test_cor`: `cor_md_para_rgb(0x0EEE) == (252,252,252)`, `cor_md_para_rgb(0x000E) == (252,0,0)` e `rgb_para_cor_md((250,0,0)) == 0x000E`.
  - `test_tile_conhecido`: um tile com o primeiro byte `0x12` gera o pixel (0,0) com índice 1 e o (1,0) com índice 2.
  - `test_ida_e_volta`: 10 tiles pseudoaleatórios, `largura_tiles=4`, e `png_para_tiles(png, 10) == dados`.
  - `test_png_nao_indexado`: um PNG RGB lança `ErroTiles`.
  - `test_indice_maior_que_15`: um PNG "P" com um pixel de índice 16 lança `ErroTiles`.
- [ ] **Step 2:** rodar os testes. Esperado: FAIL.
- [ ] **Step 3:** implementar com Pillow (`Image.new("P", ...)`, `putpalette` preenchendo até 256 cores, `putdata`/`getdata`).
- [ ] **Step 4:** rodar os testes. Esperado: PASS.
- [ ] **Step 5:** commit `feat: codec de tiles 4bpp e paletas`.

### Task 7: Framework de verificação e checagens genéricas

**Files:**
- Create: `ferramentas/verificacao.py`, `testes/test_verificacao.py`, `traducao/glossario.yaml` (lista vazia `[]` com um comentário mostrando o formato)

**Interfaces:**
- Consumes: `Tabela` (Task 4) e `Entrada` (Task 5).
- Produces:
  - `@dataclass class Achado: nivel: str  # "erro" | "aviso"; checagem: str; local: str; mensagem: str`
  - `Checagem = Callable[[Contexto], list[Achado]]`
  - `@dataclass class Contexto: tabela: Tabela; textos: dict[str, list[Entrada]]; glossario: list[dict]; extra: dict = field(default_factory=dict)`. O campo `extra` serve para as checagens do Plano 2 (ROM, ponteiros, regiões livres).
  - `def rodar(ctx: Contexto, checagens: list[Checagem]) -> list[Achado]`
  - `def tem_erros(achados: list[Achado]) -> bool`
  - `def formatar(achados: list[Achado]) -> str`, com uma linha por achado: `ERRO [checagem] local: mensagem`, terminando com um resumo `N erro(s), M aviso(s)`.
  - Checagens: `checar_caracteres` (cada `pt` não vazio codifica na tabela, e uma falha vira erro com o id), `checar_controles` (o `pt` tem a mesma sequência de códigos `[...]` do `en`, ignorando `[quebra]`; diferença vira erro) e `checar_glossario` (para cada item `{en: "Dragon Castle", pt: "Castelo do Dragão"}`, se o `en` da entrada contém o termo e o `pt` traduzido não contém o termo pt, vira aviso).
  - `CHECAGENS_PADRAO = [checar_caracteres, checar_controles, checar_glossario]`

- [ ] **Step 1:** escrever os testes (tabela de teste com A–Z, a–z, espaço, "ã", "[quebra]", "[nome]", "[fim]"):
  - `test_caractere_fora_da_tabela`: `pt="Olá"` (sem "á" na tabela) gera 1 erro com o id no `local`.
  - `test_controle_faltando`: `en="Hi [nome]"` com `pt="Oi"` gera 1 erro.
  - `test_quebra_livre`: `en="Hi there"` com `pt="Oi[quebra]você"` (com "ê" incluído na tabela desse teste) não gera erro.
  - `test_glossario_inconsistente`: gera 1 aviso, e `tem_erros` é False.
  - `test_pendente_ignorado`: entrada pendente com `pt` vazio gera 0 achados.
  - `test_formatar_resumo`: a saída termina com `"1 erro(s), 1 aviso(s)"`.
- [ ] **Step 2:** rodar os testes. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar os testes. Esperado: PASS.
- [ ] **Step 5:** commit `feat: framework de verificação`.

### Task 8: CLI — `checar-rom`, `verificar`, `construir`

**Files:**
- Create: `ferramentas/cli.py`, `ferramentas/config.py`, `testes/test_cli.py`
- Modify: `ferramentas/__main__.py` (passa a chamar `cli.main`)

**Interfaces:**
- Consumes: as Tasks 2 a 7.
- Produces:
  - `config.py`: `@dataclass class Projeto: raiz: Path; rom: dict` e `def carregar_projeto(raiz: Path) -> Projeto` (lê `config/rom.yaml`).
  - `cli.py`: `def main(argv: list[str] | None = None) -> int` (argparse), com a opção global `--raiz` (padrão: diretório atual) e os subcomandos:
    - `checar-rom [--rom CAMINHO]`: o padrão é `raiz/rom/<nome_arquivo>`. Imprime sha1/crc32/tamanho. Retorna 0 se bater com a config, ou se a config tiver `sha1: null`, caso em que imprime um aviso sugerindo preencher. Retorna 1 com `ErroRom`.
    - `verificar`: carrega `traducao/tabela.tbl` (se não existir, aviso e tabela vazia), `traducao/textos/` e `traducao/glossario.yaml`, roda `CHECAGENS_PADRAO`, imprime `formatar` e retorna 1 se houver erros.
    - `construir [--rom CAMINHO]`: roda `verificar` (com erro, retorna 1 sem criar nada em `build/`), carrega a ROM, aplica a lista de etapas de inserção (por enquanto vazia: `ETAPAS: list[Callable[[bytearray, Projeto], None]] = []`, que o Plano 2 preenche), roda `corrigir_cabecalho` e grava `build/wbmw-ptbr.bin`, `build/wbmw-ptbr.ips` e `build/relatorio.txt` (resultado do verificar + progresso por arquivo: quantidade de entradas pendente/traduzido/revisado e porcentagem). Retorna 0.
  - Os erros esperados (`ErroRom`, `ErroTabela`, `ErroTextos`, `ErroIps`, `ErroTiles`) viram mensagem em stderr e código 1, sem traceback.

- [ ] **Step 1:** escrever os testes (com `tmp_path` como raiz, gravando `rom_sintetica` em `rom/` e a config com o sha1 dela):
  - `test_checar_rom_ok` → 0. `test_checar_rom_errada` (config com outro sha1) → 1, com "esperado" no stderr (`capsys`).
  - `test_construir_gera_artefatos` → 0. Os três arquivos existem, e `aplicar_ips(original, ips) == bin` gerado.
  - `test_construir_deterministico`: rodar duas vezes gera `.bin` e `.ips` idênticos byte a byte.
  - `test_construir_com_erro_nao_grava`: um YAML com um caractere fora da tabela → 1, e `build/` não existe.
  - `test_construir_rom_errada_nao_grava`: sha1 divergente → 1, e `build/` não existe.
  - `test_relatorio_progresso`: com 1 traduzida e 1 pendente, o relatório contém `"50%"`.
- [ ] **Step 2:** rodar os testes. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar `python -m pytest` (a suíte inteira). Esperado: tudo PASS.
- [ ] **Step 5:** atualizar o `README.md` com a seção "Uso", contendo os três comandos e o que cada um faz.
- [ ] **Step 6:** commit `feat: CLI checar-rom, verificar e construir`.

---

## Próximo plano (Plano 2, depois que as ROMs estiverem em `rom/`)

O reconhecimento técnico do spec (§7, fase 1) produz `docs/tecnico/mapa-rom.md`, `traducao/tabela.tbl` e os hashes em `config/rom.yaml`. A partir dele, o Plano 2 define: `extrair` com o teste de ida e volta byte a byte idêntica (spec §6.5.1), a fonte com acentos, a realocação/expansão com as checagens de ponteiros e de espaço, `importar-tiles`, o emulador controlável, e as fases de tradução, gráficos e distribuição.
