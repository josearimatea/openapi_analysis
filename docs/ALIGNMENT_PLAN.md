# Plano — alinhamento dos dois documentos (gerado × oficial)

Estado: **proposta**, 29/out/2026. Revisada no mesmo dia: agrupar ≠ julgar; as
sobras são agrupadas numa chamada com a visão geral do documento, e só depois o
juiz julga cada bloco. Vale para a avaliação 2 (generator). Liga-se à camada 3
(`docs/JUDGE_PLAN.md`) e às duas visões do relatório.

---

## 1. O problema

Hoje `judge/parts.py::diff_documents` percorre os dois documentos **pelo mesmo
endereço**. Se a chave existe só no oficial, é *absent*; se existe só no gerado, é
*extra*. Listas são comparadas por posição, exceto parâmetros (`in` + `name`) e
`enum`/`required` (comparados como conjunto). Ninguém procura o correspondente em
outro lugar.

Por isso, o mesmo conteúdo em outro endereço vira **duas** coisas: um *faltando* no
oficial e um *extra* no gerado. As duas são julgadas separadamente, sem que o juiz
saiba que são a mesma, e às vezes recebem vereditos contraditórios. Medido com
`scratchpad/relocations.py`: valor igual, mesmas 3 últimas chaves, outro endereço.

| documento        | valores só no oficial | reaparecem em outro lugar | valores só no gerado |
|------------------|----------------------:|--------------------------:|---------------------:|
| ProvMnS 28/08    | 139 | 36 (26%) | 228 |
| ProvMnS 20/09    | 145 | 60 (41%) | 365 |
| PerfMnS 23/08    |   4 |  1 (25%) |  20 |

Padrões vistos:

- **parâmetro mudou de nível**: path → operação e operação → path;
- **chave renomeada**:
  - media type (`application/json-patch+json` → `application/vnd.3gpp.json-patch+json`);
  - nome do callback;
  - expressão do callback (`{$request.body#/notificationRecipientAddress}` →
    `{notificationTarget}`);
  - `default` → `4XX`/`5XX`;
- **composição reorganizada**: `type: object` subiu de dentro do `allOf`, e membros
  de `allOf`/`oneOf` foram reordenados;
- **cópia fora do lugar**: schemas dentro de `callbacks.components` do PUT;
- **path duplicado** com o prefixo do `servers`: em ProvMnS 28/08,
  `/{MnSRoot}/ProvMnS/{MnSVersion}/{URI-LDN-first-part}/{className}={id}` repete
  `/{className}={id}`. São 62 valores, julgados como "melhoria" porque o juiz não via
  o `servers` nem os outros paths.

A escala do efeito: em ProvMnS 28/08, dos 148 extras julgados OK, cerca de 63 eram
relocações e cerca de 70 eram lixo mal julgado.

## 2. Princípio: agrupar não é julgar

São duas fases, feitas por partes diferentes do instrumento, **nesta ordem**:

1. **Agrupar** responde *"qual bloco do gerado corresponde a qual bloco do
   oficial?"*. Serve para que o mesmo conteúdo seja olhado **uma vez, junto**, e não
   como um faltando mais um extra. Termina **antes** de qualquer julgamento.
2. **Julgar** responde *"essa correspondência está certa?"*, para cada grupo e
   cada sobra. É sempre o juiz, com a spec 3GPP e a referência OpenAPI. O juiz não
   agrupa.

O agrupamento **nunca decide** que algo está certo. Um parâmetro levado do path para
a operação, um schema com o mesmo nome em `callbacks.components`, um path que repete
outro via `servers`, um media type com outro nome e o mesmo schema: todos formam um
grupo, mas a mudança vira uma **diferença do grupo** (`moved`, `renamed`, `level`,
`duplicate`). Essa diferença vai ao juiz, que pode achar equivalente, erro (o
`$ref` não acha a cópia; query no path é o §3.22; outro media type muda o contrato)
ou melhoria.

**A única coisa que vira "igual" sem consulta** é uma diferença que a própria
especificação OpenAPI / JSON Schema diz que não tem significado. Na prática, só a
**ordem**:

- a ordem das chaves de um mapa (`paths`, `properties`, `responses`…);
- a ordem dos membros de `allOf`, `anyOf` e `oneOf` (`allOf` exige todos, e
  `anyOf`/`oneOf` testam cada um, então a ordem não muda o resultado);
- a ordem de `enum`, de `required` e da lista de `parameters` (identificados por
  `in` + `name`).

Ou seja, um grupo é **igual** só se os dois lados estão no **mesmo endereço** e são
idênticos a menos dessa ordem. Todo o resto é julgado.

## 3. A ideia

Percorrer o oficial em blocos e procurar no gerado o correspondente de cada um:

- o que corresponde com certeza é agrupado de forma determinística;
- o que é apenas *parecido* dentro de uma área, o LLM agrupa;
- o que ainda sobra vai a **uma chamada com a visão geral do documento**, que liga
  o que as etapas anteriores deixaram passar (algo que corresponde a um bloco já
  agrupado, ou a algo que parece faltando em outro lugar).

Só então o juiz julga **cada bloco**: cada grupo e cada sobra que ficou de um lado
só.

```
 AGRUPAR (nunca julga)                                  JULGAR (nunca agrupa)
 ─────────────────────                                  ─────────────────────
 1. mesmo endereço ──┐
 2. chave equivalente├─ grupos certos ─┐
 3. conteúdo sem ordem┘                │
 4. candidatos ─ 5. LLM agrupa (área) ─┼─ grupos ──────── 7. diff de cada grupo
                                       │                  8. juiz julga cada grupo
 sobras de todas as áreas ─ 6. LLM revê│com visão geral      e cada sobra
                            liga → grupo┘                 9. duas visões
                            não liga → sobra ───────────┘
```

## 4. Os blocos

Um **bloco** é a unidade de agrupamento. Os blocos são hierárquicos, e o
alinhamento desce de cima para baixo: primeiro as operações; depois, **dentro** de
um grupo de operações, os blocos dela.

Um **grupo** liga um ou mais blocos do oficial a um ou mais do gerado (1 para 1,
1 para n, n para 1). Uma **sobra** é um bloco que terminou o agrupamento sem grupo:
um faltando (só no oficial) ou um extra (só no gerado).

| tipo                | onde está                                     | identidade (etapa 1)  | chave de correspondência (etapa 2) |
|---------------------|-----------------------------------------------|-----------------------|------------------------------------|
| operação            | `paths.<p>.<método>`                          | path + método         | método + path com os nomes de template apagados (R2); ou `operationId` (R3) |
| parâmetro           | `paths.<p>.parameters` ou `.<método>.parameters` | nível + `in` + `name` | operação + `in` + `name`, **em qualquer nível** (parâmetro efetivo); `$ref` local resolvido; header sem diferenciar maiúsculas |
| request body (media type) | `….requestBody.content.<mt>`            | media type            | — (renomeado → candidatos) |
| resposta            | `….responses.<código>`                        | código                | — (`default` × `4XX` → candidatos) |
| callback            | `….callbacks.<nome>`                          | nome                  | a entrega (método + `$ref` do corpo), só entre callbacks e só se for única no oficial; callback × operação em `paths` fica para o LLM |
| schema              | `components.schemas.<N>` ou cópia fora do lugar | endereço            | **nome**, em qualquer lugar do documento |
| outro componente    | `components.<seção>.<N>`                      | endereço              | seção + nome |
| cabeçalho           | `info`, `servers`, `tags`, `x-*` …             | endereço              | — (não pontua; e **nunca** é usado para alinhar outra coisa) |

As chaves da etapa 2 vêm da semântica OpenAPI. Elas dizem **o que corresponde**, e
**não** que está certo:

- **Parâmetro efetivo.** Um parâmetro no nível do path vale para todas as operações
  dele, e o da operação sobrepõe o do path com o mesmo `in` + `name` (OAS 3.0,
  *Path Item Object*). O `id` no path do oficial e o `id` em cada uma das 4
  operações do gerado formam **um grupo 1 para n**, com a diferença `level`. O juiz
  decide se essa diferença é equivalente ou erro (o §3.22 é exatamente esse caso).
- **Só o exato é determinístico** (decidido em 29/out/2026). O que precisa de
  interpretação e pode errar às vezes vai para o LLM, nas sobras:
  - um path que repete o prefixo do `servers` (o `servers` é cabeçalho e não entra);
  - `default` × `4XX`/`5XX` (decidir que um código "é de erro" é interpretação);
  - um media type renomeado;
  - um callback de um lado e uma operação em `paths` do outro com a mesma entrega
    (a API pode receber de verdade o que um callback envia);
  - uma chave que dois blocos do oficial compartilham (qual dos dois?);
  - o mesmo conteúdo sob outra chave: dois códigos com o mesmo corpo são duas
    respostas, dois media types com o mesmo schema são duas representações (R9).
  O conteúdo igual aparece ao LLM como candidato com similaridade 1,0.

## 5. Agrupar (etapas 1–6)

### Etapa 1 — mesmo endereço (determinística)

A mesma chave nos dois lados forma um grupo, como hoje.

### Etapa 2 — mesma chave de correspondência (determinística)

Para os blocos sem grupo na etapa 1, aplicar a chave da tabela da §4. O grupo pode
ser 1 para 1 (um schema com o mesmo nome em outro lugar), 1 para n (um parâmetro do
path casado com o mesmo parâmetro em cada operação) ou n para 1. O grupo registra
**como** foi formado, e a mudança de endereço vira a diferença `moved` ou `level`.

### Etapa 3 — mesmo conteúdo (retirada)

Retirada em 29/out/2026: conteúdo igual sob outra chave não é correspondência exata
(ver §4). As cópias de um schema continuam no grupo dele pela etapa 2 (o nome).

### Etapa 4 — candidatos (determinística, só ordena)

Para cada bloco ainda sem grupo, listar os candidatos **do mesmo tipo** no outro
lado, primeiro no mesmo pai (a mesma operação, o mesmo schema). Cada candidato
recebe uma pontuação de semelhança:

- fração de folhas iguais (caminho relativo + valor);
- `$ref`s em comum;
- chaves em comum.

A pontuação **não agrupa nada**. Ela só ordena e corta: no máximo K candidatos por
bloco (K = 5), e os de pontuação zero são descartados.

### Etapa 5 — o LLM agrupa os parecidos, por área

Uma chamada **por área com sobras**: a operação, o callback, ou a seção de schemas.
O LLM de agrupamento é **separado** do juiz. Ele só diz o que corresponde a quê; não
diz se está certo, e o prompt diz isso explicitamente.

**Entrada:**

- os blocos do oficial sem grupo, cada um com id (`A1`, `A2` …), endereço e
  conteúdo;
- os candidatos do gerado (`B1`, `B2` …), com endereço, conteúdo e pontuação;
- o contexto mínimo da área: a identidade da operação e o `servers`.

**Saída estruturada (`GroupingAnswer`):**

```
groups:     [{official: [A1], generated: [B2, B3], reason: "…"}]
ungrouped:  {official: [A4], generated: [B1]}       # com o motivo de cada
```

### Etapa 6 — o LLM revê as sobras com a visão geral

As etapas 1–5 olham **por área**, então o que mudou de dono escapa: um schema
copiado dentro de um callback, um path duplicado, um parâmetro que foi parar em
outra operação. Esta etapa é **uma** chamada (ou poucas, se não couber) com **todas**
as sobras do documento, dos dois lados, e uma visão geral de tudo.

**Entrada:**

- **as sobras**, inteiras: os faltando do oficial (`A…`) e os extras do gerado
  (`B…`), cada uma com tipo, endereço e conteúdo;
- **o índice dos dois documentos**: todos os blocos, inclusive os já agrupados, cada
  um com tipo, endereço, identidade (método + path + `operationId`, nome do schema,
  código, media type, nome do callback) e o grupo a que pertence. É curto: sem o
  conteúdo, só o suficiente para reconhecer;
- o `servers` dos dois documentos.

**Saída:** a mesma forma da etapa 5, mais uma opção: uma sobra pode ser **acrescentada
a um grupo que já existe** (`join: {block: B7, group: G12, reason}`). É o caso de uma
segunda cópia de um schema já agrupado, ou de um path que duplica uma operação já
agrupada.

O que esta etapa não liga é sobra de verdade e vai assim ao juiz.

### O prompt do agrupador (etapas 5 e 6)

O agrupador **não usa RAG**. O que a OpenAPI diz sobre a identidade de cada objeto
foi extraído uma vez da referência OpenAPI 3.0.1, a mesma que alimenta a coleção
`openapi_reference`, e fixado em `judge/grouping_prompts.py`. São 17 regras (R1–R17),
cada uma com a seção da referência de onde veio:

- endpoints: URL efetiva = `servers` + path, com `/` quando não há `servers`;
  templates com nomes diferentes são o mesmo path; `operationId` é único;
- parâmetros: identidade `name` + `in`; os do path valem para todas as operações;
  `schema` × `content`; header;
- request body e respostas: media type e faixa; `default` × `1XX`–`5XX`; o código
  explícito tem precedência;
- callbacks: o nome não tem significado; a expressão de runtime; a correspondência
  pela entrega (método + corpo);
- componentes e schemas: seção + nome; `$ref` = o objeto apontado, resolvido só no
  endereço exato; `allOf` composto ou achatado; `oneOf`/`anyOf`; `enum`/`required`
  como conjunto.

O agrupador cita os ids das regras no `reason` de cada grupo. A regra central do
prompt: agrupar é dizer *qual bloco faz o papel de qual*, e nunca que está certo.
"Parecido" não basta.

O texto é versionado (`GROUPING_VERSION`). Um teste confere que os ids das regras
estão em ordem e que toda regra citada nas instruções existe.

### Checagens, cache e versão (etapas 5 e 6)

**Checagens determinísticas** (`_check`, como no juiz):

- só ids recebidos (de bloco e de grupo);
- grupo só entre blocos do mesmo tipo;
- cada bloco em no máximo um grupo;
- todo id de sobra recebido aparece em `groups`, `join` ou `ungrouped`.

Uma resposta inválida **não forma grupo**: na etapa 5, os blocos seguem para a
etapa 6; na etapa 6, ficam como sobras.

**Cache:** a chave é o conteúdo da entrada + o modelo + `GROUPING_VERSION`, em
`data/judgements/`, ao lado dos vereditos. Mesma entrada, mesmo agrupamento.

Ao fim da etapa 6, o agrupamento está **fechado**: cada bloco de cada documento está
em exatamente um grupo ou é uma sobra. Nada é reagrupado depois.

## 6. Julgar (etapas 7–9)

### Etapa 7 — o diff de cada grupo

Cada grupo é comparado com o `diff_documents` de hoje, aplicado **ao grupo** (os
subárvores dos dois lados) e não mais ao documento, ignorando só a ordem sem
significado da §2. Saem as diferenças internas (*differing*, *absent*, *extra*) e as
do agrupamento (`moved`, `renamed`, `level`, `duplicate`).

Um grupo **sem nenhuma diferença** (mesmo endereço, idêntico a menos da ordem) é
**igual** e não vai ao juiz. Todo grupo com alguma diferença, inclusive só a do
agrupamento, vai.

### Etapa 8 — o juiz julga cada bloco

**Cada grupo com diferença** é uma `Part`:

- o contexto traz o bloco do oficial e **todos** os blocos do gerado do grupo,
  inteiros, cada um com o seu endereço;
- o juiz recebe **como** o grupo foi formado (endereço, chave, conteúdo, LLM por
  área, LLM com visão geral) e o `reason` do agrupamento;
- as diferenças D1..Dn, incluindo as do agrupamento, com um veredito por diferença,
  como hoje.

Se o juiz achar que os blocos **não correspondem**, ele diz isso
(`grouping_wrong: true`, com o motivo). O grupo **não** é refeito, porque o
agrupamento já fechou. Fica registrado e listado no relatório para a revisão humana,
e as diferenças do grupo recebem o veredito que o juiz der.

**Cada sobra** também é uma `Part`:

- o contexto traz a sobra inteira, o `servers` e a identidade das outras operações
  (o que faltava para pegar o path duplicado do ProvMnS);
- um extra pode ser melhoria, erro ou incerto; um faltando é erro ou incerto.

### Etapa 9 — as duas visões (sem mistura)

Cada folha conta **uma vez** em cada visão, pelo grupo a que pertence, com o
veredito do grupo.

| visão              | base                     | categorias |
|--------------------|--------------------------|------------|
| **do gerado**      | só os valores do gerado  | igual · agrupado-aceito · agrupado-errado · extra-aceito · extra-errado · incerto · não julgado |
| **do oficial**     | só os valores do oficial | igual · agrupado-aceito · agrupado-errado · faltando · incerto · não julgado |

- "Aceito" junta `equivalent` e `improvement`; as melhorias continuam destacadas à
  parte.
- Um valor que só mudou de lugar conta no grupo dele, julgado, e nunca como
  faltando + extra.
- A base mista (a união de 423 valores) sai do relatório.

## 7. O que o relatório mostra a mais

- **Como cada grupo foi formado**: `endereço | chave | conteúdo | LLM por área | LLM
  com visão geral`, com a contagem de cada. Mostra quanto do agrupamento veio de
  decisão do LLM.
- **Os grupos que o juiz achou errados** (`grouping_wrong`), com o motivo. São os
  casos para a revisão humana.
- As duplicatas, mostradas junto do original.

## 8. Onde fica no código

| arquivo                        | o quê |
|--------------------------------|-------|
| `openapi/alignment.py` (novo)  | blocos, etapas 1–4, o índice, `Group` / `Alignment`. Determinístico: é instrumento, como `comparison.py` |
| `judge/grouping.py` (novo)     | etapas 5 e 6: prompts, chamadas, checagens, cache (`GROUPING_VERSION`) |
| `schemas/alignment.py` (novo)  | `Block`, `Group`, `GroupingAnswer` |
| `judge/parts.py`               | `generator_parts` monta as partes a partir dos grupos e das sobras; `official_view` e `leaf_census` viram as duas visões |
| `judge/prompts.py`, `judge.py` | a etapa 8: o grupo no contexto, `grouping_wrong`, o contexto das sobras |
| `reporting/final.py`           | as duas visões e a seção "como foi agrupado" |

A **camada 1** (concordância, `openapi/comparison.py`) **não muda**: continua estrita
por endereço. Ela é a medida "diverge do oficial?" e seus números travados seguem
valendo. O alinhamento alimenta a camada 3 e as visões.

## 9. Testes

- **Documentos sintéticos pequenos, um por caso**, verificando o grupo **e** a
  diferença que ele leva ao juiz:
  - parâmetro path → operação: 1 para n, diferença `level`;
  - schema copiado em `callbacks.components`: `moved`/`duplicate`;
  - media type renomeado com o mesmo schema: `renamed`;
  - `allOf` reordenado no mesmo endereço: **igual**, sem juiz (a única exceção);
  - `type: object` subindo do `allOf`: candidato, vai ao LLM por área;
  - `default` × `4XX`: vai ao LLM por área;
  - path duplicado via `servers`: `duplicate`;
  - um bloco que mudou de dono e escapa da área: chega à etapa 6.
- **Invariantes:**
  - ao fim da etapa 6, cada bloco de cada documento está em exatamente um grupo ou é
    uma sobra;
  - nenhum grupo com diferença e nenhuma sobra fica sem ir ao juiz;
  - visão do gerado: soma = valores do gerado; visão do oficial: soma = valores do
    oficial.
- **Agrupamento LLM** com resposta simulada: ids inválidos, tipos diferentes e bloco
  repetido viram "sem grupo"; `join` num grupo válido acrescenta o bloco; `join` num
  grupo inexistente é recusado.
- **Travar** em `tests/services/test_results.py`: grupos por etapa e sobras por
  documento, para os três documentos.

## 10. Ordem de implementação

1. Os blocos e as etapas 1–3, com os testes sintéticos e os invariantes.
2. A etapa 4, mais um relatório só de contagem: quantas sobras restam por documento
   e por área. **Parar aqui e olhar os números** antes de ligar o LLM.
3. As etapas 5 e 6 (o LLM de agrupamento por área e com visão geral), com cache.
4. As etapas 7–8: as partes vêm dos grupos e das sobras; `grouping_wrong`.
5. A etapa 9 e o relatório. Regerar os três relatórios (precisa do Qdrant) e
   comparar o antes e o depois.
6. Registrar no `docs/RASTREIO.md` e atualizar `CLAUDE.md` / `JUDGE_PLAN.md`.

## 11. Decisões a confirmar

1. **A camada 1 fica estrita** (§8)? Recomendo que sim: ela é a concordância literal,
   e o alinhamento é interpretação.
2. **K = 5 candidatos** por bloco e o LLM chamado por área: dá para ajustar depois de
   ver as sobras no passo 2.
3. **O modelo do agrupamento** é o mesmo do juiz? Recomendo que sim, para começar,
   com cache separado pela versão.
4. **A etapa 5 é necessária**, ou a etapa 6 (visão geral) basta sozinha? Recomendo
   manter as duas: a 5 vê poucos blocos com o conteúdo inteiro e erra menos; a 6 vê
   tudo, mas resumido. Dá para decidir com os números do passo 2: se as sobras forem
   poucas, só a 6 já cabe.
