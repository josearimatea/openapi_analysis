# Documento de Rastreio — OpenAPI Analysis

Caderno de bordo do projeto, no mesmo espírito dos `RASTREIO.md` do
`openapi_rulesbank` e do `openapi_generator`: registrar, em texto corrido, as ideias que
motivaram cada etapa, o que foi de fato implementado, o que mudou e por quê, e o que foi
testado — como matéria-prima para a dissertação. Não é documentação técnica (isso está
no README, no `docs/RULES.md`, no `docs/VALIDATION.md` e no código); conta a *história*
das decisões. A cada mudança relevante, acrescente um parágrafo novo em vez de
reescrever o que já está aqui.

Registro de atualizações:
- 2026-09-28 — repositório criado com o extrator de alvos do YAML oficial (113 alvos).
- 2026-09-29 — estrutura em camadas, dados copiados dos irmãos com manifesto, e as
  primeiras divergências de definição de regra entre os repos.
- 2026-10-01 — as duas avaliações construídas e travadas; quatro erros do próprio
  instrumento achados na auditoria dos números.
- 2026-10-01 — relatórios legíveis: duplicatas no rulesbank, divergências por operação e
  por schema no generator, timestamps da avaliação.
- 2026-10-05 — concordância não é correção: as três camadas; a camada 2 (validade
  OpenAPI 3.0) entra no pipeline.

---

## Por que este repositório existe

O `openapi_rulesbank` extrai regras OpenAPI de especificações 3GPP, e o
`openapi_generator` monta um documento OpenAPI a partir dessas regras. Para saber se os
dois estavam melhorando, era preciso medir o que produziam contra o YAML oficial. Essas
medições vinham sendo feitas de forma ad-hoc, em scripts soltos, e **erraram pelo menos
três vezes**: uma contagem de "31 refs externos" vinha do log inteiro, não do campo das
regras; um "98% de cobertura" vinha de um extrator de alvos que não descia em
`oneOf`/`allOf` e achou 54 alvos onde havia muito mais; e um "0 regras sumiram" vinha de
indexar regras por uma chave que podia repetir, de modo que duas colidiram e uma
sobrescreveu a outra sem aviso.

A lição virou a regra deste repositório: o instrumento de medição precisa ser
versionado e travado por testes, ou o número engana. E uma regra de ouro, herdada do
trabalho: *quando dois indicadores da mesma medição se contradizem, suspeite do
instrumento, não do sistema.* Ela foi aplicada várias vezes abaixo.

---

## Duas avaliações, não uma

A primeira estrutura que propus tratava tudo como uma avaliação só: extrair regras do
YAML oficial **e** do YAML gerado, e comparar banco com banco. Estava errado. São duas
avaliações de natureza diferente:

1. **rulesbank** — o banco de regras é comparado com as regras **extraídas do YAML
   oficial**, no mesmo formato do banco, regra a regra.
2. **generator** — o YAML gerado é comparado **diretamente** com o YAML oficial,
   documento contra documento. Não se extraem regras do YAML gerado.

A extração de regras existe só na avaliação 1, e só a partir do YAML oficial.

## A estrutura do código

A estrutura seguiu os irmãos de propósito — `config/`, `schemas/`, `services/`,
`api/routes|schemas`, `data/inputs|outputs` — em vez de um padrão de livro. Cheguei a
propor um `domain/` e um `repositories/`; ficaram de fora porque os irmãos não os têm e,
num pacote deste tamanho, a separação que importa (lógica pura sem I/O) se consegue sem
mais um nível de pasta. Consistência entre os quatro repos que a mesma pessoa mantém
pesou mais.

Também foi descartado um `loader` que convertia o JSON do banco para classes próprias:
criava uma segunda representação da regra, que é exatamente onde contagens divergem. A
regra tem **um** formato — o do banco — e **uma** função de chave, `rule_key`.

Os insumos são **copiados** dos irmãos para `data/inputs/` por `scripts/sync_data.py`,
com um `manifest.json` (origem, sha256). Dois achados vieram daí: os YAMLs "oficiais"
tinham nomes ambíguos entre os repos (três "ProvMnS" que eram as versões 17.5.0, 17.7.0
e 18.2.0), então foram renomeados por serviço + `info.version`; e cada YAML gerado traz
no cabeçalho `x-ai-generation` a data do banco que o produziu, o que permite parear
gerado → banco de forma exata, sem adivinhar por nome.

---

## A definição de regra, e as divergências entre os repos

O objetivo declarado foi definir "de uma vez por todas" o que é uma regra e como ela
deve estar no banco, para que as contagens não divirjam. Comparando as fontes da
definição — o `rules_check.py` e os prompts do rulesbank, o `rule_types.py` e o planner
do generator — apareceram divergências **entre os dois irmãos**: o nível dos parâmetros
(o gerador dizia "sempre no path", o YAML oficial põe os query params no `.get`), o
endereço do callback (duas formas aceitas pelo consumidor, uma pelo produtor), o
conjunto de keywords de schema (7 × 5), o `openapi_field` do request body e a lista de
métodos HTTP. Foram corrigidas nos irmãos.

Uma segunda varredura, lendo o código inteiro e não só os diffs, achou mais: o
validator do rulesbank chama de duplicata dois media types do mesmo request body; a
deduplicação do builder inclui o valor em todos os tipos, deixando passar duplicatas de
endereço; o `rules_check` aceita field aninhado (`properties.x.description`); e a
descrição do `OpenAPIMapping`, que chega ao LLM via structured output, dá exemplos que o
próprio `rules_check` rejeita. A raiz comum: cada lugar define "mesma regra" do seu
jeito. Ficaram registradas como prioridade no rulesbank.

O que é regra, o endereço por tipo e cada decisão de contagem estão em `docs/RULES.md`.

---

## Os erros do próprio instrumento

Ao rodar as avaliações sobre os dados reais, segui a regra de ouro e auditei cada
número estranho antes de aceitá-lo. Quatro eram do instrumento, não dos geradores:

1. **Referências aninhadas.** A regra `allOf` reprovava porque eu contava nas referências
   esperadas os `$ref` de propriedades *dentro* dos membros inline — que são regras
   próprias. As referências passaram a ser rasas.
2. **Enum com prosa.** O banco escreve itens com descrição (`A — significa…`); separar
   por vírgula gerava itens falsos. Com prosa, confere-se só a presença de cada item.
3. **Parâmetros por posição.** Herdado do comparador do generator: `parameters[0]`, de
   modo que reordenar parâmetros parecia erro. Passaram a ser identificados por
   `(in, name)`, como o próprio OpenAPI faz.
4. **Chaves com ponto.** O caminho de cada folha era uma string separada por `.`, mas
   media types (`application/vnd.3gpp...`), expressões de callback e as chaves
   malformadas do gerado têm ponto. O caminho virou tupla de chaves.

Cada correção ficou travada por teste. As diferenças que restaram foram conferidas uma
a uma e são defeitos reais.

---

## Os resultados

Banco i20 do ProvMnS contra o YAML oficial 18.2.0: **81 de 113 regras com endereço
(71,7%)**, **53 de 72 valores certos (73,6%)**, 39 regras do banco fora de qualquer
endereço oficial, 2 endereços com duplicata, 5 casos do §3.23 (`$ref` externo que perdeu
o arquivo). Os 5 query params estão no path (§3.22) — o banco é anterior à correção. Os
5 callbacks estão no endereço certo com a expressão errada (`{notificationTarget}`).

No generator, o documento mais novo do ProvMnS (20/set) concorda **menos** com o
oficial (22,5% do contrato) que o anterior (28/ago, 36,7%). O relatório por operação e
por schema mostrou por quê: schemas criados fora de `components.schemas`, composições
`allOf` achatadas, query params declarados no path item, cinco schemas externos
copiados para dentro do documento, e uma estrutura corrompida (um path chamado
`components`, callbacks com `components`/`applied`/`skipped` dentro).

## Relatórios legíveis

A primeira versão dos relatórios era correta mas ilegível: no generator, uma lista
plana de 126 folhas ausentes e 270 extras. Duas mudanças: no rulesbank, a conta
`bank = covered + dup + extra` com as duplicatas lado a lado; no generator, a quebra por
dono — cada operação, cada path item, cada schema — com o que falta e sobra em cada um,
o *status* do schema (presente, ausente, **fora do lugar** e onde está), a forma
(`allOf[2]` × `type=object`) e as folhas de um mesmo elemento agrupadas numa linha. O
relatório passou também a registrar quando a avaliação rodou, separado das datas de
geração de cada insumo.

---

## Concordância não é correção — as três camadas

Uma objeção importante: tudo o que foi medido trata o YAML oficial como gabarito
perfeito. Mas o oficial pode errar ou ficar defasado (os bancos `i00` vêm da spec
V18.0.0 e são comparados ao YAML 18.2.0), o banco é extraído do **texto** 3GPP e não do
YAML, e o gerado pode trazer uma melhoria. A comparação determinística mede
**concordância**, não **correção**. O exemplo que deixou isso claro: a especificação
OpenAPI trata de `4XX`/`5XX` e de `default`; os dois são válidos, e decidir qual é o
certo exige ler e interpretar a referência OpenAPI e a spec 3GPP.

Daí as três camadas:

1. **Concordância** — determinística, a que já existia. Gera a lista de divergências.
2. **Validade** — determinística: o documento é OpenAPI 3.0 válido? Só sintaxe. Um piso:
   o inválido está errado em qualquer contexto.
3. **Julgamento** — uma LLM lê a referência OpenAPI e a spec 3GPP e julga **só as
   divergências**: gerado errado, equivalente, gerado melhor, oficial errado, incerto,
   com citação. Vereditos em cache (reprodutíveis), calibrados contra revisão humana, e
   reportados **separados** da concordância.

A LLM entra para julgar, não para medir — se substituísse a camada determinística,
voltaríamos ao problema que motivou o repositório: um número que muda a cada rodada e
que ninguém consegue auditar.

## A camada 2 — validade OpenAPI 3.0

Antes de escolher a ferramenta, confirmamos que validadores existem e se apoiam todos
na mesma base: o JSON Schema oficial do OpenAPI 3.0, publicado pela OpenAPI Initiative.
A escolha foi o `openapi-spec-validator` (Python, local, versão fixa — reprodutível; um
validador online mudaria sem aviso e exigiria enviar os documentos para fora).

O primeiro teste deu errado de um jeito previsto: **os 12 documentos, oficiais
inclusive, abortavam no primeiro `$ref` externo** — os arquivos das outras specs 3GPP
não estão aqui. A saída foi resolver arquivos externos para um *stub*, listar nós mesmos
todos os `$ref` internos quebrados (a biblioteca para no primeiro) e rodar a validação
completa só quando o documento passa nas duas checagens anteriores. O resultado: os 9
oficiais válidos, os 2 gerados antigos válidos, e o gerado mais novo **inválido**, com
18 problemas — o único inválido é também o de menor concordância, sinal de regressão do
gerador entre 28/ago e 20/set. A camada 2 substituiu uma checagem de estrutura que eu
tinha escrito à mão: dois instrumentos medindo a mesma coisa seria o que este repo
existe para evitar.

Lendo o código da biblioteca, ficou claro também o que ela **não** cobre — callbacks e
schemas de request body não são percorridos pela parte semântica, exemplos e `security`
não são checados. O detalhe está em `docs/VALIDATION.md`.

## O que vem a seguir

A camada 3, o juiz com LLM. Em aberto: o modelo (o mesmo dos irmãos, via LangChain, como
dependência opcional?), se o juiz recebe contexto por RAG nas coleções do Qdrant que o
rulesbank já indexa ou só o trecho da spec referenciado, e por qual avaliação começar.
