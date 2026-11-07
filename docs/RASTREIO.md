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
- 2026-10-06 — camada 3, etapa 1 (infra): o juiz lê a spec por RAG, sem anexo nenhum;
  o cliente Qdrant fica preso à versão do servidor, com a atualização do servidor
  pendente.
- 2026-10-06 — camada 3, etapas 2 e 3: as partes, e a busca dirigida por parte (título
  que define o assunto, cláusula da regra, similaridade — tudo dentro do serviço).
- 2026-10-07 a 2026-10-18 — o juiz rodando: partes com o dono inteiro como contexto, um
  veredito por diferença, o contexto citável (judge-v4), a coleção compartilhada por
  seção; o relatório final com o resultado primeiro, um relatório por execução.
- 2026-10-29 e 30 — o alinhamento dos dois documentos: agrupar antes de julgar (só o
  exato no determinístico, o resto com um LLM sobre os documentos inteiros); o juiz
  julga grupos e sobras; o relatório em duas visões, cada uma na sua base; prosa só é
  erro quando é falsa (judge-v6).
- 2026-11-01 — a spec como entrada obrigatória: cada documento só é comparado na sua
  versão; os números anteriores eram de versões trocadas. Prosa nunca conta; sem a
  segunda passada; stubs julgados contra a definição externa; `allOf` achatado comparado
  campo a campo (judge-v15).

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

## Camada 3 — o plano e a infraestrutura

As perguntas acima foram fechadas e o plano está em `docs/JUDGE_PLAN.md`. O critério do
juiz: o que está **igual** ao oficial está ok; o que está **diferente** é julgado —
por que difere (valor, endereço ou estrutura), se é erro ou melhoria, e qual versão é
mais entendível — lendo a spec 3GPP e a referência OpenAPI. O modelo é o
`gpt-5.6-luna`, o mesmo dos irmãos (via OpenRouter). O contexto vem por RAG, e a análise
é **por partes**: cada regra divergente do banco, cada aspecto divergente de um dono no
YAML gerado, com busca e chamada próprias — o documento inteiro de uma vez faria a
busca trazer trechos genéricos, que não falam de parte nenhuma.

Uma regra se impôs na implementação: **nenhum anexo de spec entra**, nem na análise,
nem como referência, nem no RAG. O anexo A da TS 28.532 é o próprio YAML oficial; lido
pelo juiz, ele "leria a spec" e acharia o gabarito, e o veredito ficaria circular. Os
irmãos já tratavam disso — o generator corta todo o texto a partir do primeiro anexo
(`normative_only`), o rulesbank descarta o anexo do YAML — e a indexação daqui faz o
mesmo corte, com um teste que trava a regra na spec real. Daí uma decisão de fonte: o
corpus compartilhado do `qdrant_3gpp_rag` (`3gpp_rel18_*`) indexa as specs inteiras,
anexos incluídos, sem metadado que permita filtrá-los — então o juiz **não** busca nele;
as specs de que precisa são indexadas por nós, uma coleção fixa por versão
(`analysis_spec_28532_i20`, 392 trechos, só texto normativo). Por ora só a versão i20.

Ao preparar o ambiente, dois ajustes de infraestrutura. O `torch` do extra `[judge]` é a
versão só para CPU: o juiz só gera embeddings de consultas curtas e indexa cada spec uma
vez, e a versão com CUDA custava vários GB de download. E o cliente Qdrant mais novo
(1.19) avisou incompatibilidade com o servidor compartilhado (1.16.3) — o recomendado é
no máximo uma versão menor de diferença.

**Pendência — atualizar o servidor Qdrant.** Por ora o cliente deste repo está preso à
série do servidor (`qdrant-client>=1.16,<1.17`, no `pyproject.toml`). O certo é
atualizar o servidor (container `qdrant-local`, dados em `~/qdrant_storage`) e soltar o
cliente. Como o servidor é compartilhado com os irmãos, a atualização precisa de: backup
de `~/qdrant_storage` com o container parado; subir **uma versão menor por vez**
(1.16 → 1.17 → 1.18 → 1.19), porque o Qdrant só garante a migração do armazenamento a
partir da versão menor anterior; conferir a cada passo que as coleções e o número de
pontos de cada uma não mudaram; e verificar o `qdrant-client` instalado no chatUI, que
declara `>=1.15.1`.

## Camada 3 — as partes e a busca por parte

As **partes** saem dos relatórios das camadas 1 e 2, sem LLM. No generator, uma por
aspecto de cada dono (as respostas de uma operação, os parâmetros, cada notificação de
callback, a definição ou o lugar de um schema); no rulesbank, uma por regra divergente.
O documento mais novo do ProvMnS rende 37 partes — 13 já inválidas pela camada 2, que
viram erro sem chamar a LLM — e o banco i20 rende 91. Montá-las expôs mais da corrupção
daquele documento: dentro dos callbacks do PUT há `applied`, `removed` e `components`,
e no PUT há `skipped` — o relatório que o Patcher faz do próprio trabalho, vazado para
o YAML, e os schemas que ele não conseguiu devolver na raiz da correção. Registrado no
`openapi_generator/docs/PROBLEMS.md` como P10; a execução avaliada (`…194130`) é
posterior à de referência de lá (`…184338`) e reabre defeitos dados como resolvidos.

A **busca** precisou de três ajustes, todos achados conferindo os resultados à mão. A
similaridade pura trazia cláusulas de outros serviços (o `HTTP GET` do Streaming para
uma parte do ProvMnS): cada trecho passou a carregar o serviço, lido dos títulos da
própria spec, e a busca filtra por ele. Ela também perdia o assunto quando o nome era
parecido com outros (`NotifyEvent` trazia os demais `Notify*`): uma passada anterior
busca as seções cujo título **define** o assunto — o formato 3GPP `Type X`,
`Notification X`, `Operation X` — e, quando esse título não tem texto próprio, as
subcláusulas. E casar o nome por palavra solta confundia o schema `Resource` com
"Resource structure on the MnS producer": só o título que define conta.

Dois achados que não são do instrumento. A própria spec é inconsistente num ponto: a
cláusula 12.1.1.4.1a.10 tem título "Type NotifyMoiEvent" sobre a tabela "Definition of
type NotifyEvent" — e nem é marcada como título no markdown; nenhuma busca por título
acha esse tipo. E os `$ref` externos ficaram sem fonte: a TS 28.623 define os tipos que
o ProvMnS importa (`Uri`, `NotificationHeader`, `ErrorResponse`…) só no anexo C, que é o
próprio `TS28623_ComDefs.yaml`; com a regra de nenhum anexo, não há texto de spec sobre
eles — decisão em aberto no plano.

## Camada 3 — o juiz em uso e o relatório final (07 a 18/out/2026)

Com a busca pronta, as partes do generator mudaram de forma: cada uma passou a levar o
**dono inteiro** — a operação, o callback, o schema — dos dois lados, como contexto, e a
lista exata de diferenças como foco, com um veredito por diferença. Nenhuma linha que
diverge fica de fora, e um teste trava isso. O contexto passou a ser citável (C1 o
oficial, C2 o gerado, no judge-v4): o juiz pode concluir "equivalente" só lendo os dois
lados — duas frases que dizem a mesma coisa não precisam da spec —, enquanto melhoria
continua exigindo a spec ou a referência OpenAPI. Antes disso, as partes sem evidência
viravam "indeciso" sem consultar ninguém, e o PerfMnS, praticamente igual ao oficial,
saía com muitos indecisos.

A busca falhava por motivos que só apareceram olhando os trechos: tabelas cortadas,
janelas de 2 000 caracteres que partiam a seção, o limite de 256 tokens do modelo de
embeddings. A correção foi no repositório compartilhado (`qdrant_3gpp_rag`): trechos por
seção, sem anexo, metadados de cláusula, busca híbrida (densa + BM25) e um modelo maior
— e as coleções foram reindexadas. O juiz passou a ler a coleção compartilhada da série
28, em vez de uma coleção própria.

O relatório final foi reescrito a pedido, para ser lido por alguém de fora: o resultado
primeiro (validade, depois cada valor por veredito, e a porcentagem correta, com as
melhorias destacadas), depois o detalhe. Um relatório por execução, com a data no nome,
nunca sobrescrito, em `data/outputs/reports/<Serviço>/{generator,rulesbank}/`, para
comparar antes e depois.

## Camada 3 — alinhar os documentos antes de julgar (29 e 30/out/2026)

**O problema.** Ao separar a cobertura do oficial da correção do gerado, a conta não
fechava: o gerado tinha 58% "certo", mas só 48% do oficial estava coberto, e havia 148
"extras aprovados". A causa estava no instrumento: o diff percorria os dois documentos
pelo **mesmo endereço**. O mesmo conteúdo em outro lugar — o parâmetro levado do path
para cada operação, o `default` trocado por `4XX`/`5XX`, um schema copiado para dentro de
um callback — virava um "faltando" de um lado e um "extra" do outro, julgados em
separado, às vezes com vereditos contraditórios. Medido: 26% dos valores "faltando" do
ProvMnS de 28/08 reaparecem em outro endereço do gerado, e 41% no de 20/09. A base dos
números também misturava os dois documentos (os 423 valores eram a união dos dois).

**A ideia: agrupar não é julgar.** Antes de julgar, cada bloco do oficial (operação,
parâmetro, media type, resposta, callback, schema) é ligado ao bloco do gerado que faz o
mesmo papel. O agrupamento nunca diz que algo está certo: a mudança de lugar ou de forma
vira uma diferença do grupo, e o juiz decide. O plano está em `docs/ALIGNMENT_PLAN.md`.

**Só o exato é determinístico.** A primeira versão agrupava também pelo `servers` (a URL
completa), por conteúdo igual e pela entrega de um callback contra uma operação. Os
testes mostraram que tudo isso podia errar: conteúdo igual juntou `default` e `4XX` só
porque os dois tinham `{description: Error}`, e cinco schemas vazios
(`{type: object}`) entraram no grupo do `Resource`. A regra decidida foi: no
determinístico fica só a igualdade exata definida pela OpenAPI — o mesmo endereço, o
mesmo path com outros nomes de template, o mesmo `operationId`, o mesmo nome de schema
(inclusive as cópias fora do lugar), o mesmo parâmetro (`in` + `name`) em qualquer
nível, o callback renomeado com a mesma entrega —, e uma chave que dois blocos do
oficial compartilham não decide nada. O `servers` é cabeçalho e nunca serve para
alinhar. O que pede interpretação vai para o LLM. Cada valor de cada documento pertence
a exatamente um bloco, e isso é travado em teste. O teste de generalidade, sem outra
spec à mão: um documento contra ele mesmo dá tudo por endereço; o ProvMnS v17.5 contra o
v18.2 sobra exatamente o que a v18.2 acrescentou (`dataNodeSelector`, o callback
`notifyEvent`, o schema `NotifyEvent`).

**O LLM que agrupa.** Um agrupador separado do juiz, que só diz o que corresponde. Ele
não usa RAG: as 17 regras de identidade da OpenAPI 3.0.1 (R1–R17, cada uma com a seção
de onde saiu) foram extraídas uma vez e fixadas no prompt, e o agrupador cita a regra em
cada decisão. O formato chegou à versão 8 depois de testes reais, e cada erro virou uma
mudança: por área, ele decidia cedo com visão parcial e não podia rever; com só pedaços
dos documentos, inventava conteúdo ("o PUT gerado contém esses callbacks" — não
continha); numa chamada só com tudo, a mensagem ficava 3 vezes maior que os próprios
documentos. A forma final: uma chamada por família de bloco (endpoints, parâmetros,
corpos e respostas, schemas e cabeçalho), em ordem, cada uma com **os dois YAMLs
inteiros** como base. As regras estruturais não ficaram no prompt, ficaram em checagens
de código — o LLM tentou duas vezes juntar dois media types num grupo, apesar do prompt
proibir: um tipo só de cada lado do grupo, um media type por lado, operação × callback só
em lados opostos. Uma resposta recusada não agrupa nada. No ProvMnS de 28/08, todas as
decisões da versão final conferiram com os documentos: o `default` com `4XX`/`5XX`, o
path duplicado com o prefixo do `servers`, o DELETE de URL quebrada, o callback
declarado como path; e as sobras que ficaram (13 faltando, 6 extras) são reais.

**O juiz sobre grupos (judge-v5).** Cada grupo que difere vira uma parte; cada sobra,
outra. Um bloco é comparado só pelo que é dele — a operação sem os parâmetros e as
respostas, que têm parte própria —, para nada ser julgado duas vezes; o juiz continua
vendo a operação inteira como contexto. Um bloco em outro lugar vira uma diferença
"moved", julgada uma vez. O juiz pode marcar que um grupo está errado. Ao rodar o
PerfMnS, apareceu que a busca do juiz ainda lia os rótulos das partes antigas: a
consulta do schema saía vazia e o `required` do `NotifyThresholdCrossing`, antes
melhoria pela tabela da spec, virou indeciso. Corrigida a busca, voltou a melhoria.

**O relatório em duas visões.** Cada documento na sua base, sem mistura: quanto do
oficial o gerado reproduz (igual, diferente mas certo, melhor, errado, faltando,
indeciso) e quanto do gerado está certo (os mesmos, com extra útil e extra errado). Um
campo que só mudou de lugar conta uma vez, no seu grupo. O cabeçalho fica à parte. Os
termos foram escolhidos para serem entendidos sem explicação — "changed", "equivalent" e
"values" confundiam.

**Prosa só é erro quando é falsa (judge-v6).** No PerfMnS, o veredito sobre a
`description` da operação oscilou entre duas rodadas: erro numa, equivalente na outra. O
texto gerado é verdadeiro, só mais genérico (não cita `notifyThresholdCrossing`). A
decisão: menos claro não é erro. Prosa só é erro quando diz algo falso; mais curta ou
menos precisa é "diferente, mas certo", e o que perdeu vai só na comparação de clareza.
É o mesmo princípio da camada 1, onde prosa nunca conta como defeito. Na rodada do
judge-v5 com a busca corrigida, o PerfMnS ficou em 100% nas duas visões — o gerado
reproduz todo o oficial, e o que muda (`4XX`/`5XX` no lugar do `default`, o `required`
explícito, o `operationId`) foi julgado melhoria com evidência; a regra do judge-v6
tira a oscilação que dava esse resultado ou 95,5% conforme a rodada. A rodada com o
judge-v6 ainda está por fazer.

**Duplicatas, o corte escondido e a busca medida (30/out a 01/nov/2026).** A primeira
rodada completa do ProvMnS deu 86,9% do gerado "certo", com 140 extras úteis: as
duplicatas (o PUT e o DELETE do path longo) entravam no grupo da operação oficial e cada
resposta delas era julgada sozinha. Passaram a ser marcadas e julgadas inteiras, e uma
duplicata nunca sai melhoria nem equivalente. O juiz também julgava melhoria o path
longo porque não via o `servers` do oficial; o cabeçalho dos dois documentos passou a ir
como contexto, e os paths são comparados como escritos. Com isso, o gerado certo foi a
55,7%.

Restava a mesma mudança (`default` → `4XX`/`5XX`) julgada diferente em cada operação.
Primeiro culpei a busca; a medida sobre 16 partes reais, com a cláusula esperada de cada
uma, mostrou que ela já achava 15. Depois culpei o juiz. A causa era minha: cada trecho
de evidência era cortado em 2.500 caracteres antes de ir a ele, e o `4xx` estava no
caractere 2.982 da tabela do DELETE e no 2.521 da do PATCH. No PUT, no 278; no GET, no
1.247. Sem o corte, a mudança saiu melhoria nas quatro. Um teste agora garante que nada
do que o juiz lê é cortado. A lição é a do início deste caderno: quando dois números se
contradizem, o instrumento é o suspeito — vale também para o que ele mostra ao LLM.

A busca ficou com o que a medida sustentou: filtro no servidor (sem anexo, dentro do
escopo) e as seções que definem o assunto primeiro. Achou as mesmas 15 de 16, com cerca
de 20% menos trechos. Aumentar o k para 8 ou 10 só trouxe ruído, e os anexos também, na
medida possível (as cláusulas esperadas são todas do corpo da spec). A parte que falta é
o `notifyEvent`: a coleção indexava a i00, onde essa cláusula não existe, e na i20 o
título dela está sem estilo de título no próprio Word da 3GPP. A troca para a i20 e o
reconhecimento desses títulos ficaram com o `qdrant_3gpp_rag`.

Para a variação que sobra, o juiz recebeu regras (o trecho da spec que trata desta
operação decide antes do argumento genérico da OpenAPI) e uma segunda passada: cada
parte é julgada sozinha, e só onde o mesmo tipo de mudança recebeu vereditos diferentes
elas são julgadas de novo, vendo todos os vereditos e motivos. Isso evita que um erro
inicial se propague, porque qualquer uma pode mudar. No teste, a segunda passada
corrigiu o `$ref` do PUT, mas também mudou o que ninguém disputava (o `oneOf` perdido do
PATCH, de erro para indeciso). Por isso só valem dela os vereditos das diferenças em
conflito. Onde todas concordam no erro, ela não corrige; isso segue para a revisão humana.

## Camada 3 — a versão errada, e a correção do juiz (01/nov/2026)

**O erro de medição.** O ProvMnS de 28/08 e o PerfMnS vêm da i00, mas vinham sendo
comparados com os oficiais v18.2.0 e v18.1.0 e com a spec i20. Os números da seção
anterior medidos assim (86,9%, 55,7%) e os 57,4% / 55,7% do judge-v13 não medem o
gerador: parte das "faltas" era diferença entre versões. Pior, atribuí à reindexação uma
solução que não existia, e isso custou uma troca de coleção à toa. A correção é
estrutural: a spec passou a ser **entrada obrigatória** (`--spec`), a versão do documento
e do oficial é conferida contra ela e a divergência é erro, salvo com
`--allow-other-version`, que fica registrado no relatório. Se nenhuma coleção tem aquela
versão exata, ela é indexada na hora (`analysis_spec_28532_i00`). O oficial de cada
versão fica em `OFFICIAL_BY_SPEC`, conferido nos anexos: i00 → ProvMnS 17.5.0 e PerfMnS
17.1.0; i20 → 18.2.0 e 18.1.0.

**Decisões que substituem as anteriores.** Prosa (`description`, `summary`, `title`)
nunca é erro nem melhoria, nem quando parece falsa: não faz parte do contrato, e há um
piso em código. A cópia de um bloco é erro; a original é julgada normalmente. Nada do que
o juiz lê é cortado (retorno do RAG, YAMLs, diferenças); só os termos de busca têm
limite, porque viram uma consulta só. O `x-*` da raiz saiu do contexto: o registro de
como o documento foi gerado não diz nada da API e poderia influenciar o veredito.

**A busca não era reproduzível.** Na busca híbrida, empates da fusão RRF mudavam a ordem
entre execuções: a densa repetia em 39/39 consultas, a híbrida só em 6/39. Eu havia
tratado uma variação de 14 para 15 como ruído. A correção foi no `qdrant_3gpp_rag`
(commit `3c7403b`). Depois dela, com cada documento na sua versão, a evidência veio
idêntica em 4 repetições nas 119 partes, e 14 de 14 cláusulas esperadas ficaram no top 3
(das 16 medidas antes, duas partes não existem na v17.5.0).

**Primeira rodada com as versões certas (judge-v13).** PerfMnS × i00 / v17.1.0: 22/22 do
oficial e 26/26 do gerado. ProvMnS 28/08 × i00 / v17.5.0: 118/177 (66,7%) e 163/291
(56,0%). Conferidos nos documentos: os erros de enum, `PatchItem`, PATCH sem 2xx e media
types faltando, e as melhorias do `attributes` opcional e do DELETE (`scope`, 204,
`array(Uri)`), que estão na spec e faltam no oficial. A rodada também mostrou os três
problemas abaixo.

**Sem a segunda passada.** Ela consumiu 19 das 66 chamadas da ProvMnS (cerca de 29%) e só
alinhou dois vereditos do PUT, sem mudar a nota. Também não enxergava a incoerência que
importava, porque só compara diferenças do mesmo tipo. Foi removida. O preço é que
`default` → `4XX`/`5XX` pode variar entre equivalente e melhoria, e os dois contam como
certo.

**Stubs locais.** O oficial cita `TS28623_ComDefs.yaml#/components/schemas/ErrorResponse`;
o gerado cria um `ErrorResponse: {type: object}` local. A mesma troca saía erro nas
respostas, melhoria na definição do stub e equivalente nos `NotifyMoi*`: a parte do
schema extra não sabia que ele substituía uma definição externa. Agora, quando o nome é
exatamente o de uma definição externa do oficial, a parte recebe essa ligação e busca a
definição, e o juiz compara: perde contrato é erro, preserva é equivalente, melhoria
nunca. Com nome diferente não há ligação, de propósito: agrupar errado é pior do que
deixar de ligar. No teste das partes afetadas, os stubs viraram erro e `Filter` saiu de
indeciso para erro (`string` × `object`). O `400` junto de `4XX`/`5XX` deixou de ser erro
com outra regra: um bloco oficial que vira vários é avaliado pela cobertura do conjunto.

**`allOf` achatado.** Com os stubs certos, um `$ref` errado marcava os 5 campos de
`properties` como errados, porque o gerado escreveu na raiz o que o oficial tem em
`allOf[1]` e a diferença virava um bloco só. E as visões se contradiziam: o oficial dizia
"diferente mas certo", o gerado "errado". Pela regra deste caderno, o suspeito era o
instrumento. Como `allOf` combina seus membros, as duas formas são o mesmo schema: agora
são comparadas campo a campo, nos dois sentidos, e só o `$ref` trocado conta como erro.

**Definição externa de outra versão.** Os stubs são julgados contra a TS 28.623 i40, e o
documento vem da TS 28.532 i00. Não é o erro de versão acima: a cláusula de referências da
própria spec diz que uma referência sem versão vale pela última versão da mesma Release,
e as duas são da Release 18. Não verifiquei se a i40 é a última da Release 18.

Ainda sem rodada completa com o judge-v15: os números acima são do judge-v13, e o efeito
estimado na ProvMnS é de cerca de 65,0% e 53,3%. As partes afetadas foram testadas em
separado.

## Camada 3 — variação do LLM para a mesma entrada (02/nov/2026)

Medição isolada, sem relatório: ProvMnS 28/08 contra a v17.5.0, spec 28532-i00, judge-v24,
`gpt-5.6-luna` com temperatura 0 e sem semente. O mesmo modelo, prompt, parte e evidência
foram enviados 3 vezes. A busca rodou uma vez e, conferida, devolveu o mesmo nas 47 partes.
Dados em `data/outputs/reviews/2026-11-02_variacao_llm_judge-v24.json`.

| Etapa | Repetições | Variou |
|---|---:|---|
| Agrupador | 3 (12 chamadas, US$ 0,029) | 0: os mesmos 47 grupos |
| Juiz, resposta do LLM | 3 × 47 partes (141 chamadas, US$ 0,364) | 3 de 125 diferenças (2,4%) |
| Juiz, depois das regras do código | idem | 2 de 125 diferenças (1,6%) |
| Nota do oficial | 3 | 0: 111/163 (68,1%) nas 3 |
| Nota do gerado | 3 | 0: 159/291 (54,6%) nas 3, com `/eventListener` separado |

As 3 diferenças que variaram, nenhuma com efeito na nota:

| Diferença | Vereditos | Observação |
|---|---|---|
| `/{notificationTarget}.post.responses` | erro, erro, melhoria | Os campos contam nas linhas de dentro do bloco |
| `...default.description` | equivalente, equivalente, melhoria | Prosa: o código fixa em equivalente, e por isso não varia no final |
| `/eventListener.post` | melhoria, indeciso, indeciso | Nas 3 o juiz diz que não pertence ao grupo |

O `/eventListener`, separado do grupo como faz o fluxo real, saiu erro nas 3 repetições. A
medição não refaz esse passo: sem ele, uma das repetições conta 167/291, o que não é nota.

**Limites.** Três repetições não mostram variação rara: no teste das partes afetadas, com o
mesmo prompt, `scope` no DELETE saiu indeciso em 1 de 2 tentativas, e na medição saiu melhoria
nas 3; somando, 1 de 5. Vale para um documento (a ProvMnS), e a amostra não dá margem
estatística.

## Camada 3 — mudança dos vereditos entre versões do prompt (02/nov/2026)

Não é variação do LLM: aqui o prompt também muda. Duas rodadas completas da ProvMnS 28/08
contra a v17.5.0, com a spec 28532-i00 e sem cache do juiz nem do agrupador:
`2026-11-02_17-27-05` (judge-v18) e `2026-11-02_18-58-59` (judge-v23). Têm 124 diferenças em
comum, e 10 mudaram de veredito.

| Causa | Diferenças | Campos | Quais |
|---|---:|---:|---|
| Mudança de propósito (regra ou prompt) | 3 | 3 | `Resource.required`, `PatchItem...nullable`, `delete.operationId` |
| Sem mudança feita para isso | 7 | 15 | abaixo |

As 7 sem mudança feita para isso, de 121 comparáveis (5,8%):

| Diferença | v18 | v23 | Campos | Efeito na nota |
|---|---|---|---:|---|
| `object-tree-hierarchical` no GET 200 | erro | equivalente | 1 | oficial +1 campo certo |
| `/{notificationTarget}.post.parameters` | útil | melhoria | 4 | nenhum |
| PUT `4XX`, PUT `5XX`, PATCH `4XX`, PATCH `5XX` | melhoria | equivalente | 8 | nenhum |
| PATCH `400` | melhoria | equivalente | 2 | nenhum |

Na mesma rodada e com o mesmo prompt, a v23 também diverge consigo mesma: das 8 linhas de
`default` → `4XX`/`5XX`, 4 saíram melhoria (GET, DELETE) e 4 equivalente (PUT, PATCH).

No agrupamento, os 47 grupos da v23 são iguais aos das respostas em cache. A variação foi
no juiz: na v18 ele tirou `/eventListener` do grupo do callback, na v23 não. A nota não
muda, porque os 8 campos são errados nos dois casos, mas as duplicatas passam de 94 para
102.

Em testes menores, repetindo as mesmas partes: no judge-v21, `NotifyThresholdCrossing` deu
útil em uma tentativa e erro na outra; no judge-v23, nada variou (4 partes da ProvMnS
2 vezes, 1 da PerfMnS 3 vezes).

**O que estes números não são.** Entre as duas rodadas o prompt mudou, então os 5,8% não
medem o acaso do LLM; essa medida é a da seção anterior. O único caso com efeito na nota é o
`object-tree-hierarchical`, que no judge-v24 saiu erro nas 3 repetições.

**Correções do judge-v24**, depois destas rodadas: entrada de mapa só no oficial é perdida
mesmo que outra entrada possa levar o conteúdo; `default` trocado pelos códigos que a spec
nomeia é melhoria (as 9 linhas saíram melhoria nas 3 repetições); parâmetro de caminho de um
callback declarado como caminho nunca é melhoria (regra no código). Não virou regra fixa que
"campo só no oficial nunca é equivalente", porque não vale sempre: `style: form` só no oficial
é o valor padrão do OpenAPI.

**Em aberto: DELETE com `scope` e corpo no `200`.** A TS 28.532 i00 diverge de si mesma: a
tabela do método (12.1.1.3.2.1.3.4) lista `scope` e `array(Uri)`, e a de mapeamento
(12.1.1.1.5) diz `n/a`. A TS 32.158 h60 acompanha o mapeamento: 5.4 ("no query", corpo vazio),
6.1.2 (scoping "not supported by any other method") e A.4.2 (a requisição com scope é
inválida). O juiz decide pela tabela do método, como a mais específica, sem citar a TS 32.158.
São 9 campos contados como melhoria; se forem indecisos, o gerado cai para 150/291 (51,5%).

## O `items` de uma propriedade array não é regra própria (07/nov/2026)

**O que estava errado.** Ao descer no schema, a extração do YAML oficial emitia o `items` de
uma propriedade array como uma regra `items` na raiz do schema (`components/schemas/
CorrelatedNotification · items`). O endereço não diz de qual propriedade é, e nenhuma regra do
banco pode ocupá-lo; por isso essas regras apareciam sempre como faltantes. A propriedade já era
comparada com o `$ref` do elemento (`properties.notificationIds` com `NotificationId`).

**Quem decide a forma.** A spec e o YAML. A spec dá ao atributo um tipo só (`notificationIds |
array(NotificationId)`); os 8 YAMLs oficiais têm 25 propriedades array, todas com `type: array` e
`items` juntos na propriedade. A propriedade é uma regra, com o array e o elemento no valor. O
`openapi_rulesbank` mudou o mesmo contrato do lado dele no mesmo dia.

**Efeito.** Alvos: ProvMnS 18.2.0 113 -> 107 (os 6 `items` de `CorrelatedNotification`,
`MoiChange` e dos quatro `NotifyMoi*`); 17.5.0 103 -> 97; 17.7.0 112 -> 106; FaultMnS 260 -> 259;
FileDataReportingMnS 40 -> 38; StreamingDataMnS 74 -> 70; PerfMnS e HeartbeatNtf sem mudança.
Banco i20 de 15/set: 81/107 (75,7%), antes 81/113 (71,7%) — as 6 faltantes eram do instrumento.
Banco i00 de 28/08 × 17.5.0: 57/97, antes 59/103 — ele escrevia 2 regras `items` na raiz, que
deixam de casar e viram extras. Números travados atualizados em `tests/rulesbank/
test_extraction.py`, `tests/services/test_results.py` e `tests/judge/test_parts.py`.

## Um `default` oficial é coberto pelos 4XX/5XX do banco (07/nov/2026)

**O que estava errado.** A cobertura casa endereço exato. Quando o oficial declara `default` e o
banco declara `4XX` e `5XX` na mesma operação, o `default` saía faltante e os dois saíam extras,
embora digam o mesmo: "todo erro". O número de faltantes e de extras era do instrumento.

**A regra** (genérica, em `rulesbank/comparison.py`; RULES.md §4). O `default` sem regra no
próprio endereço é coberto pelos `4XX`/`5XX` do banco na mesma operação ou callback que o oficial
não declara. O valor é comparado com cada um, e outro `$ref` continua diferença. Para a soma do
banco fechar sem contar o segundo como duplicata, há uma contagem nova, `range`.

**Efeito** (medido nos bancos de `data/inputs`):

| Banco | Coberto | Diferente | Extras | Range |
|---|---|---|---|---|
| ProvMnS i20 15/09 × 18.2.0 | 81 -> 87 de 107 | 19 -> 25 | 39 -> 28 | 5 |
| ProvMnS i00 28/08 × 17.5.0 | 57 -> 59 de 97 | 14 -> 16 | 39 -> 35 | 2 |
| PerfMnS i20 15/09 × 18.1.0 | 14 -> 15 de 15 | 0 -> 1 | 4 -> 2 | 1 |
| PerfMnS i00 26/09 × 17.1.0 | 14 -> 15 de 15 | 0 -> 1 | 8 -> 6 | 1 |
| PerfMnS i00 18/08 × 17.1.0 | 13 -> 14 de 15 | 1 -> 1 (iguais 11 -> 12) | 3 -> 1 | 1 |

Os `default` recém-cobertos saem quase todos como diferentes: o banco perdeu o arquivo do
`ErrorResponse` externo (§3.23), ou trocou o `$ref`. A fidelidade do i20 da ProvMnS cai de 53/72
(73,6%) para 53/78 (67,9%) por isso: são diferenças que antes ficavam escondidas como faltantes.

**Limite que apareceu.** O `default` do PATCH na ProvMnS 18.2.0 é um `oneOf` de dois `$ref`
(`ErrorResponseDefault`, `ErrorResponsePatch`), e a extração grava o valor da resposta só como
`oneOf`, sem as referências. A comparação diz "o banco tem `$ref` onde o YAML não tem": o status
(diferente) está certo, a nota não. Fica para corrigir na extração.

