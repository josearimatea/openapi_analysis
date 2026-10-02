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
- **Keyword-coleção = uma regra** (`enum`, `required`, `oneOf`...), valor = a coleção
  inteira (§3.27). Um banco que emite uma regra por item fica com o 1º item no
  endereço e o resto vira "endereço compartilhado".
- **Chave repetida** (mesmo nome de propriedade em dois níveis de um schema) é uma
  regra só; vale o valor da primeira ocorrência.
- **Parâmetros `in: header` / `cookie`** não são extraídos: nenhum rule_type os cobre
  (StreamingDataMnS tem 5).
- `additionalProperties: true/false` (booleano) não é regra.

Contagem por YAML oficial: ProvMnS 17.5.0 = 103, 17.7.0 = 112, **18.2.0 = 113**;
PerfMnS 17.1.0 = 15, **18.1.0 = 15**; FaultMnS 17.2.0 = 260; FileDataReportingMnS
17.1.0 = 40; HeartbeatNtf 17.1.0 = 3; StreamingDataMnS 17.1.0 = 74.

## 4. Decisões de comparação de valor (travadas em `tests/rulesbank/test_comparison.py`)

Endereço e valor são medidos **separados** (§3.19b): cobertura = endereço presente;
fidelidade = valor certo onde dá para conferir.

- **`$ref`**: compara o CONJUNTO de schemas referenciados (arquivo + nome), lido de
  `references[]` e de qualquer `$ref` escrito no `openapi_value`. Mesmo nome sem o
  arquivo externo = **§3.23** (nota explícita no relatório).
- **Referências rasas**: uma regra referencia o `$ref` do próprio nó, ou dos membros
  de uma composição, ou do elemento de um array (`array of X`). Um `$ref` mais fundo
  pertence à regra que endereça aquele elemento — senão uma falta reprovaria duas
  regras.
- **`enum` / `required`**: conjunto de itens, ordem ignorada. Se o banco escreve os
  itens com prosa, confere-se só a presença de cada item oficial.
- **Tipo**: o tipo JSON com que o valor do banco começa (`string (date-time)` = string).
- **path_operation**: o método. **callback**: a expressão (sem `{}` e `$`).
  **request_body**: o media type é o próprio endereço — igual por definição.
- **Sem o que comparar** (resposta sem corpo, propriedade sem tipo): `not_comparable`.

## 5. Decisões em aberto

- [ ] **Referência dos bancos `i00`** (spec V18.0.0): não há YAML de versão
      correspondente; hoje são medidos contra o rel18 (`settings.OFFICIAL_REFERENCE`).
- [ ] **Parâmetros de header**: viram regra (novo rule_type) ou ficam fora do escopo?
- [ ] **O que do YAML não é regra**: `info`, `servers`, `externalDocs`, `summary`/
      `description`, atributos internos de propriedades (`format`, `pattern`...).
- [ ] **`security_scheme`**: nenhum YAML atual tem `components/securitySchemes`.
- [ ] **Valor de resposta prosa** ("Resource or array(Resource)"): hoje conta como
      `different` por não trazer `$ref`; o contrato pede `$ref: '...'`.

## 6. Pendências no gerador (registradas lá como prioridade, 01/out/2026)

1. O validator trata media types diferentes do mesmo request_body como duplicata.
2. A dedup do builder inclui o valor em todos os tipos — duplicatas de endereço sobrevivem.
3. `rules_check` aceita field aninhado (`properties.x.description`).
4. A descrição do `OpenAPIMapping` (vai ao LLM) contradiz o contrato.
5. O planner do rulesbank fala em 7 tipos, sem `callback`.
6. `rules_check` não valida o `openapi_object` de request_body/response.
