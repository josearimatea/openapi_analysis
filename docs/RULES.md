# Definição das regras

Este documento fixa **o que é uma regra** e **como ela deve estar no banco**, para a
avaliação do rules bank (avaliação 1). É a fonte das decisões; o código que as
aplica é `src/openapi_analysis/rulesbank/rule_types.py` (definição),
`extraction.py` (YAML oficial → regras) e `comparison.py` (regra a regra), e cada
decisão é travada por teste.

Objetivo: uma única definição, para que a contagem de regras extraídas do YAML
oficial e a contagem de regras do banco gerado **não possam divergir**.

## 1. Formato

Uma regra tem um único formato — o do banco gerado pelo `openapi_rulesbank`:

```json
{
  "rule_type": "...",
  "openapi_mapping": {
    "openapi_object": "...",
    "openapi_field": "...",
    "openapi_value": "...",
    "references": [{"file": "...", "schema_name": "..."}]
  }
}
```

As regras do YAML oficial são extraídas **neste mesmo formato** (`openapi-analysis
extract <yaml>` grava esse documento), e a comparação é regra a regra pela chave
`rule_key`: `(rule_type, openapi_object, openapi_field, openapi_value se fizer parte
da identidade)` — hoje só o `request_body` tem o valor (media type) na identidade.

## 2. Endereço por tipo (alinhado aos dois irmãos em 01/out/2026)

| rule_type       | openapi_object                                  | openapi_field                    | openapi_value |
|-----------------|-------------------------------------------------|----------------------------------|---------------|
| path_operation  | `paths.<path>`                                  | `<método>`                       | método em maiúsculas |
| path_parameter  | `paths.<path>` **ou** `paths.<path>.<método>` — o nível que o YAML declara | `parameters[in=path,name=<n>]` | tipo ou `$ref: '<ref>'` |
| query_parameter | `paths.<path>.<método>` — **sempre** a operação | `parameters[in=query,name=<n>]`  | tipo ou `$ref: '<ref>'` |
| request_body    | `paths.<path>.<método>.requestBody`             | `content`                        | media type (**identidade**) |
| response        | `paths.<path>.<método>.responses`               | código / `1XX`–`5XX` / `default` | schema do corpo; vazio se não há corpo |
| callback        | `paths.<path>.<método registrador>.callbacks.<nome>` | método de **entrega**       | expressão `{...}` |
| schema_property | `components/schemas/<Raiz>`                     | `properties.<n>` ou keyword      | tipo, `$ref`, ou a coleção inteira |
| security_scheme | `components/securitySchemes/<Nome>`             | `type`                           | oauth2/http/apiKey/openIdConnect |

Dentro de um callback, o corpo e as respostas continuam a âncora:
`…callbacks.<nome>.<método de entrega>.requestBody` / `.responses`.

Métodos aceitos: `get, put, post, delete, patch` (os mesmos nos três repos).

## 3. Decisões de contagem (travadas em `tests/rulesbank/test_extraction.py`)

- **Descida em schemas** por `oneOf/anyOf/allOf/properties/items/additionalProperties`,
  sempre endereçada pelo schema RAIZ. Um `$ref` é folha (§3.10).
- **O `items` de uma propriedade array é parte do valor dela**, não uma regra própria:
  `properties.<x>` leva o array e o `$ref` do elemento. A spec dá ao atributo um tipo só
  (`array(X)`), e os YAMLs oficiais escrevem `type` e `items` juntos na propriedade (25 de
  25). Antes (até 07/nov/2026), esse `items` saía como uma regra `items` na raiz do schema,
  um endereço que nenhuma regra do banco pode ter. O `items` de um schema que é ele mesmo
  um array na raiz (como `CorrelatedNotifications`) continua sendo regra: é palavra-chave do
  próprio schema.
- **O valor de um `additionalProperties` da raiz (um mapa) é parte dessa regra** (desde
  08/nov/2026; A VERIFICAR antes de rodar as análises — ver RASTREIO). O `Resource` da
  ProvMnS tem `additionalProperties: {type: array, items: {type: object}}`: uma regra
  `additionalProperties` com valor `array`, sem a regra `Resource · items`, que dizia que o
  próprio `Resource` é um array. A spec dá uma linha, um tipo (`n/a | map(array(object))`).
- **O `oneOf`/`anyOf`/`allOf` de uma propriedade também é parte do valor dela** (desde
  07/nov/2026), pelo mesmo motivo e pelo contrato do gerador (`rules_check.py`: a palavra-chave
  vale para o schema inteiro; o que está dentro de uma propriedade vai no `openapi_value`).
  Antes, saía como regra `oneOf` na raiz do schema: o endereço não dizia de qual propriedade era,
  e duas propriedades com `oneOf` caíam na mesma chave, de modo que a segunda sumia
  (`streamInfo-Type.streamId` e `.additionalInfo`, StreamingDataMnS). A composição do próprio
  schema (`Resource`, `PerfMetricValue`, o `allOf` dos `NotifyMoi*`) continua sendo regra.
- **Keyword-coleção = uma regra** (`enum`, `required`, `oneOf`...), valor = a coleção
  inteira (§3.27). Um banco que emite uma regra por item fica com o 1º item no
  endereço e o resto vira "endereço compartilhado".
- **Chave repetida** (mesmo nome de propriedade em dois níveis de um schema) é uma
  regra só; vale o valor da primeira ocorrência.
- **Parâmetros `in: header` / `cookie`** não são extraídos: nenhum rule_type os cobre
  (StreamingDataMnS tem 5).
- `additionalProperties: true/false` (booleano) não é regra.

Contagem por YAML oficial (desde 07/nov/2026): ProvMnS 17.5.0 = 97, 17.7.0 = 106,
**18.2.0 = 107**; PerfMnS 17.1.0 = 15, **18.1.0 = 15**; FaultMnS 17.2.0 = 258;
FileDataReportingMnS 17.1.0 = 38; HeartbeatNtf 17.1.0 = 3; StreamingDataMnS 17.1.0 = 69.
Antes: 103, 112, 113, 15, 15, 260, 40, 3 e 74. A diferença é o `items` de propriedade e, na
FaultMnS e na StreamingDataMnS, mais 1 cada pelo `oneOf` de propriedade.
Desde 08/nov/2026: ProvMnS 17.5.0 = 96, 17.7.0 = 105, **18.2.0 = 106** (o `items` do
`additionalProperties` da raiz de `Resource` é parte do valor dele); os demais não mudam.

## 4. Decisões de comparação de valor (travadas em `tests/rulesbank/test_comparison.py`)

Endereço e valor são medidos **separados** (§3.19b): cobertura = endereço presente;
fidelidade = valor certo onde dá para conferir.

- **`$ref`**: compara o CONJUNTO de schemas referenciados (arquivo + nome), lido de
  `references[]` e de qualquer `$ref` escrito no `openapi_value`. Mesmo nome sem o
  arquivo externo = **§3.23** (nota explícita no relatório).
- **Referências rasas**: uma regra referencia o `$ref` do próprio nó, ou dos membros
  de uma composição, ou do elemento de um array (`array of X`). Um `$ref` mais fundo
  pertence à regra que endereça aquele elemento — senão uma falta reprovaria duas
  regras. Um schema que é ele mesmo uma composição (o corpo de uma resposta, uma
  propriedade) referencia os membros, como o banco escreve (`oneOf: [$ref: A, $ref: B]`);
  isso faltava até 07/nov/2026, e o `default` do PATCH da ProvMnS 18.2.0 saía sem
  referências. Na regra de uma palavra-chave de composição, um membro que é outra
  composição não é aberto: ele tem a sua própria regra (o `anyOf` dentro do `oneOf` do
  `Resource`).
- **`enum` / `required`**: conjunto de itens, ordem ignorada. Se o banco escreve os
  itens com prosa, confere-se só a presença de cada item oficial.
- **Tipo**: o tipo JSON com que o valor do banco começa (`string (date-time)` = string).
- **path_operation**: o método. **callback**: a expressão (sem `{}` e `$`).
  **request_body**: o media type é o próprio endereço — igual por definição.
- **Sem o que comparar** (resposta sem corpo, propriedade sem tipo): `not_comparable`.
- **`default` × 4XX/5XX** (desde 07/nov/2026): uma resposta `default` do oficial sem regra do
  banco no mesmo endereço é coberta pelos `4XX` **e** `5XX` do banco na mesma operação ou no
  mesmo callback, desde que o oficial não os declare ele mesmo. Pela OpenAPI 3.0 (Responses
  Object), `default` documenta "responses other than the ones declared", e `4XX` cobre só de
  400 a 499: só os dois juntos fazem o papel do `default`. O valor do `default` é comparado
  com o de cada um: igual só se os dois forem iguais, de modo que outro `$ref` continua
  diferença (ex.: `ErrorResponseDefault` no oficial, `ErrorResponse` no banco). Esses 4XX/5XX
  deixam de ser extras: o primeiro conta como cobertura e o segundo como `range`, e a soma do
  banco passa a ser cobertura + duplicatas + `range` + extras. Um `default` que o banco também
  declara casa pelo endereço, e os 4XX/5XX continuam extras.
  - **Só um dos dois** (ex.: só `4XX`): o `default` conta como faltando, e o `4XX` como extra,
    os dois com a nota "the bank replaced default by 4XX only: 5XX missing". Se esse extra é
    útil ou melhoria, é o juiz (camada 3) que decide, lendo a nota.
  - **Premissa:** o `default` também cobriria 1xx, 2xx e 3xx não declarados, que `4XX` +
    `5XX` não cobrem. A regra o trata como "todo erro", como nos YAMLs da TS 28.532: a
    descrição dele é "Error case." e a spec lista só 4xx/5xx para os erros.

## 5. Decisões em aberto

- [ ] **Referência dos bancos `i00`** (spec V18.0.0): não há YAML de versão
      correspondente; hoje são medidos contra o rel18 (`settings.OFFICIAL_REFERENCE`).
- [ ] **Parâmetros de header**: viram regra (novo rule_type) ou ficam fora do escopo?
- [ ] **O que do YAML não é regra**: `info`, `servers`, `externalDocs`, `summary`/
      `description`, atributos internos de propriedades (`format`, `pattern`...).
- [ ] **`security_scheme`**: nenhum YAML atual tem `components/securitySchemes`.
- [ ] **Valor de resposta prosa** ("Resource or array(Resource)"): hoje conta como
      `different` por não trazer `$ref`; o contrato pede `$ref: '...'`.
- [ ] **A VERIFICAR E COMMITAR ANTES DE RODAR QUALQUER ANÁLISE (08/nov/2026):** o valor de
      um `additionalProperties` da raiz passou a ser uma regra só (sem `Resource · items`);
      ProvMnS 107 -> 106 regras oficiais. Feito sem commit; ver RASTREIO, seção de 08/nov.
- [ ] **`style`/`explode` dos query params (08/nov/2026):** o rulesbank passou a escrever
      no valor `<schema>; style: <s>; explode: <b>` quando a spec escreve (D.3 lá). A
      comparação de valor olha só o primeiro tipo ou o `$ref`, então nada quebra; o oficial
      tem os dois atributos em `scope`, `attributes` e `fields` do GET. Decidir se o
      instrumento passa a comparar `style`/`explode` (extração: ler do Parameter Object;
      comparação: só quando o oficial os tem).
- [ ] **`metadata.unresolved_missing` (08/nov/2026):** campo novo do banco do rulesbank, com
      as regras que o Validator pediu e o Extractor nunca criou (N.26 lá). Decidir se o
      relatório do instrumento o mostra (é o "pedido e não feito", que hoje só aparece como
      faltante).
- [ ] **Código morto em `judge/spec_index.py`:** `split_sections`, `segments`,
      `normative_only`, `annex_cut`, `corpus_text`, `heading_clause`, `chunk_clauses` e
      `split_by_heading` não são chamados por `src/` (só por `tests/judge/test_spec_index.py`);
      o índice que roda (`index_spec`) já usa o `chunk_spec_sections` do `qdrant_3gpp_rag`,
      o mesmo corte que o rulesbank e o generator passaram a usar (N.29 lá, 08/nov). Remover
      com os testes?

## 6. Pendências no gerador (registradas lá como prioridade, 01/out/2026)

1. O validator trata media types diferentes do mesmo request_body como duplicata.
2. A dedup do builder inclui o valor em todos os tipos — duplicatas de endereço sobrevivem.
3. `rules_check` aceita field aninhado (`properties.x.description`).
4. A descrição do `OpenAPIMapping` (vai ao LLM) contradiz o contrato.
5. O planner do rulesbank fala em 7 tipos, sem `callback`.
6. `rules_check` não valida o `openapi_object` de request_body/response.
