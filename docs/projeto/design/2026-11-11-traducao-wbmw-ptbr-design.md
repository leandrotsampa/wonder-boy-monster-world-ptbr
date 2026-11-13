# Tradução PT-BR de Wonder Boy in Monster World: design do projeto

Data: 2026-11-11
Status: rascunho para aprovação

## 1. Intenção

Traduzir 100% de *Wonder Boy in Monster World (UE) [!]* (Mega Drive) para português do Brasil, com resultado completamente jogável em emulador.

O projeto é um repositório git que funciona como uma "fábrica" da tradução. Qualquer pessoa que tenha o repositório e a sua própria cópia da ROM original deve conseguir:

1. **extrair** textos e gráficos da ROM para arquivos editáveis versionados;
2. **editar** a tradução (texto) e os tiles (imagens) no próprio repositório;
3. **verificar** que as edições não quebram o jogo, com falha no build em vez de falha no jogo;
4. **aplicar** tudo na ROM, gerando a ROM traduzida localmente e o patch IPS para distribuição.

### Por quê

- A distribuição é só por patch IPS. ROMs nunca entram no git, por causa dos direitos autorais.
- O projeto precisa ser editável e reprodutível por outras pessoas, e não ser um trabalho feito uma vez com editor hexadecimal.

## 2. Objetivos, não-objetivos e anti-objetivos

### Objetivos
- Todo texto visível traduzido: diálogos, menus, inventário, nomes de itens, equipamentos e magias, lojas, mensagens de sistema, telas de título, créditos e finais.
- Gráficos com texto traduzidos (logotipo/título, telas com texto desenhado, rótulos de HUD), quando houver.
- Fonte com os caracteres do português (á à â ã é ê í ó ô õ ú ç, maiúsculas onde houver espaço e necessidade).
- Pipeline reprodutível: ROM original + repositório → ROM traduzida idêntica byte a byte em qualquer máquina.
- Patch IPS gerado pelo build.
- Documentação técnica dos formatos descobertos (texto, ponteiros, fonte, compressão, mapa da ROM).

### Não-objetivos
- Funcionar em console real ou flashcart. O alvo é emulador (ver §4). Mesmo assim, o design evita truques que sabidamente só funcionam em emulador.
- Interface gráfica de edição. Só ferramentas de linha de comando.
- Traduzir outras versões ou regiões do jogo.
- Formatos de patch além de IPS (BPS e outros podem vir depois, mas não fazem parte deste escopo).

### Anti-objetivos (falha mesmo que "funcione")
- Qualquer ROM comercial versionada no git.
- Qualquer mudança que altere a história, os personagens ou a identidade visual do Wonder Boy.
- Uma edição de texto que ultrapassa limites e só aparece como bug ou travamento dentro do jogo. Isso tem que ser pego pelo `verificar`.
- Build não determinístico, ou que dependa de passos manuais em editor hexadecimal.
- Nomes de pessoas ou monstros traduzidos (ver §5).

## 3. As ROMs

Nenhuma é versionada. Ficam em `rom/` (ignorado pelo git).

| ROM | Papel | Usada pelo build? |
|---|---|---|
| Wonder Boy in Monster World (UE) [!] | **Base.** Todo build parte dela. O hash é validado antes de qualquer operação. | Sim, obrigatória |

A tradução é feita a partir do texto original em inglês. As descobertas técnicas ficam em `docs/tecnico/`; o que o projeto desenha (fonte, telas) fica em `graficos/` como arquivos do projeto.

## 4. Restrições

- **Plataforma de teste:** emulador. Referências (minha escolha): **BlastEm** (preciso) e **Genesis Plus GX** (via RetroArch). O patch tem que funcionar nos dois.
- **Linguagem:** Python 3 (3.11+), linha de comando, multiplataforma (o autor usa Windows). Poucas dependências, todas via `pip` (`requirements.txt`). Previsão: Pillow (PNG) e PyYAML (texto), mais pytest.
- **Sem dependência de ferramentas externas** de romhacking (Atlas, Cartographer etc.). Tudo é implementado em Python no repositório. Ferramentas externas podem aparecer na documentação como referência.
- **ROM de saída válida:** checksum do cabeçalho do Mega Drive recalculado, campo de tamanho/fim da ROM coerente, e tamanho final em potência de 2 se houver expansão.
- **IPS:** o build gera IPS a partir da ROM original. Se a ROM for expandida, o IPS escreve além do fim original (é suportado). O IPS tem limite de 16 MB de offset, mais do que suficiente.

## 5. Regras de tradução

- **Mantidos como no original:** nomes de pessoas, personagens e monstros (Shion, Purapril, Eleanora, Myconid etc.).
- **Traduzidos:** todo o resto que for traduzível, como diálogos, menus, itens, equipamentos, magias, lugares genéricos e mensagens.
- **Casos cinzentos** (ex.: nomes de lugar que também são palavras comuns) são decididos e registrados em `traducao/glossario.yaml`. O `verificar` avisa quando um termo do glossário aparece traduzido de formas diferentes.
- **Título do jogo:** mantido como "Wonder Boy in Monster World". O logo não é redesenhado. Só os textos ao redor (ex.: "APERTE START", menu inicial) são traduzidos.
- **Registro:** português do Brasil, natural, sem ser arcaico. O tom acompanha o original (leve e de aventura).

### 5.1 Quem faz o quê

- **Tradução:** quem implementa escreve todo o texto `pt` em lotes, por bloco, e decide os casos cinzentos do glossário, deixando a decisão registrada. Uma entrada escrita fica com `status: traduzido`.
- **Revisão:** o autor do projeto revisa jogando. Correções viram edições no YAML, e o que foi validado no jogo passa a `status: revisado`.
- **Testes no jogo por quem implementa:** além do `verificar`, dá para rodar um emulador controlável por script para testar trechos específicos (abrir uma caixa de diálogo, ver um menu, tirar capturas de tela). Escolher e configurar esse emulador faz parte do plano. A jogatina completa de validação é do autor.

## 6. Decisões de "como" já tomadas

### 6.1 Estrutura do repositório (proposta, pode ser refinada no plano)

```
/
├── README.md               # o que é, como usar, créditos
├── requirements.txt
├── .gitignore              # rom/, build/, *.bin, *.md, *.gen, *.smd etc.
├── config/
│   └── rom.yaml            # hashes esperados da ROM base, tamanho alvo, regiões livres
├── rom/                    # (ignorado) ROMs do usuário
├── build/                  # (ignorado) ROM traduzida, IPS, relatórios
├── traducao/
│   ├── tabela.tbl          # tabela de caracteres (byte ↔ caractere / códigos de controle)
│   ├── glossario.yaml
│   └── textos/*.yaml       # um arquivo por bloco lógico (diálogos de cidade X, itens, menus…)
├── graficos/
│   ├── fonte/*.png         # fonte (PNG indexado)
│   └── telas/*.png         # tiles/telas com texto (PNG indexado + metadados)
├── ferramentas/            # pacote Python (CLI)
├── testes/                 # pytest
└── docs/
    ├── tecnico/            # mapa da ROM, formatos, notas técnicas
    └── projeto/design/     # este documento
```

### 6.2 CLI

Um único ponto de entrada, por exemplo `python -m ferramentas <comando>`:

| Comando | Faz |
|---|---|
| `checar-rom` | valida o hash da ROM base |
| `extrair` | ROM original → `traducao/textos/*.yaml` (campo `en`) e `graficos/**/*.png` |
| `importar-tiles` | extrai, uma única vez, tiles de uma ROM (a base) para `graficos/` como PNG, registrando a origem. Não importa texto. |
| `verificar` | todas as checagens da §6.5, sem gerar ROM |
| `construir` | `verificar` + inserção + correção de checksum → `build/` (ROM + IPS + relatório) |

O comando `extrair` nunca sobrescreve traduções já existentes. Ele só atualiza o original (`en`) e adiciona entradas novas.

### 6.3 Formato do texto

YAML, uma entrada por string, com ID estável:

```yaml
- id: vila_purapril.npc_03.fala_01
  en: "Welcome to Purapril!"
  pt: "Bem-vindo a Purapril!"
  status: traduzido        # pendente | traduzido | revisado
  nota: ""                 # opcional
```

Os códigos de controle do jogo (quebra de linha, espera, nome do jogador, cores etc.) aparecem como marcadores legíveis entre colchetes, por exemplo `[quebra]` e `[espera]`. Os nomes exatos dependem do reconhecimento técnico.

### 6.4 Formato dos gráficos

PNG indexado usando a paleta real do jogo, com extração e inserção ida e volta sem perda. Para cada imagem há metadados (offset, formato, compressão se houver, dimensões em tiles) num YAML ao lado ou em `config/`.

### 6.5 Verificação (o que o `verificar` garante)

1. **Ida e volta neutra:** extrair e reinserir sem nenhuma alteração gera uma ROM idêntica byte a byte à original. Esse é o teste fundamental do pipeline e roda no pytest.
2. Todo caractere usado nos textos `pt` existe na tabela e na fonte.
3. Cada texto cabe no espaço permitido: largura de linha e número de linhas da caixa de diálogo/menu, e limite em bytes quando o texto não for realocado.
4. O texto realocado cabe nas regiões livres declaradas, sem sobreposição.
5. Todos os ponteiros apontam para dentro da ROM e para o início de uma string válida.
6. Códigos de controle estão balanceados e são válidos.
7. As imagens têm as dimensões e a paleta esperadas.
8. O cabeçalho final tem checksum correto e tamanho coerente.
9. Consistência com o glossário (aviso, não erro).

O `construir` também gera um relatório de progresso (porcentagem de strings `pendente/traduzido/revisado` por bloco).

### 6.6 Realocação e expansão

O português é mais longo que o inglês, então os textos serão reescritos numa região nova, com os ponteiros atualizados. A ROM pode ser expandida (provavelmente de 1 MB para 2 MB, a confirmar no reconhecimento). As técnicas adotadas ficam registradas em `docs/tecnico/`.

## 7. Fases (ordem sugerida para o plano)

0. **Repositório:** `git init`, `.gitignore`, README básico, `requirements.txt`. Commit deste documento.
1. **Reconhecimento técnico** (depende das ROMs estarem em `rom/`): hashes, cabeçalho, localização dos textos, codificação/compressão, ponteiros, fonte, gráficos com texto, espaço livre. Pesquisa de documentação existente (Data Crystal, romhacking.net). Resultado: `docs/tecnico/mapa-rom.md` e `traducao/tabela.tbl`.
2. **Pipeline ida e volta:** `checar-rom`, `extrair` e `construir` sem alterações, com o teste de ROM idêntica passando.
3. **Fonte e acentos:** ampliar a tabela e a fonte com os caracteres do PT-BR.
4. **Realocação/expansão:** inserção de texto de tamanho livre, mais as checagens da §6.5.
5. **Emulador de teste:** configurar um emulador controlável por script para testar trechos e capturar telas.
6. **Tela inicial:** os textos da tela inicial traduzidos em PNG editável.
7. **Tradução do texto:** quem implementa preenche todo `pt`, em lotes por bloco, a partir do inglês.
8. **Gráficos restantes:** outras telas com texto desenhado (o logo do título é mantido).
9. **Revisão jogável:** o autor joga do início ao fim nos emuladores de referência e as correções voltam para o YAML.
10. **Distribuição:** IPS final, README com instruções de aplicação e hash da ROM base esperada, créditos.

## 8. Deixado a cargo de quem implementar

- Nomes finais dos comandos, módulos e marcadores de controle.
- Granularidade dos arquivos de texto (como agrupar os blocos).
- Algoritmos de compressão/descompressão, caso o jogo use algum.
- Escolha exata da região de realocação e do tamanho final da ROM, respeitando §4.
- Detalhes do relatório de progresso.
- Qual emulador controlável usar para os testes automatizados (§5.1).

## 9. Decisões tomadas na elaboração deste documento (para o autor conferir)

- Python 3.11+, com Pillow, PyYAML e pytest. Sem ferramentas externas de romhacking.
- Texto em YAML, gráficos em PNG indexado.
- Emuladores de referência: BlastEm e Genesis Plus GX.
- Teste de "ida e volta byte a byte idêntica" como garantia central do pipeline.
- Expansão provável para 2 MB (a confirmar no reconhecimento).
- A tradução sempre parte do inglês.
