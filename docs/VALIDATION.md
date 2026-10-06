# Camada 2 — validade OpenAPI 3.0

Referência do que a camada 2 da avaliação do generator verifica, do que ela **não**
verifica, e de como ela é montada. Código: `src/openapi_analysis/openapi/validation.py`.
Verificado lendo o código da biblioteca instalada, `openapi-spec-validator` **0.9.0**.

## 1. A pergunta que ela responde

**"O documento é um OpenAPI 3.0 válido?"** — e só isso. É uma verificação de *sintaxe*:
o documento segue o formato que a especificação OpenAPI 3.0 fixa (quais campos existem
em cada lugar, obrigatórios, tipos, padrões de nome)?

Ela **não** diz se uma escolha válida é a certa. `4XX`/`5XX` e `default` são ambos
válidos, então os dois passam; decidir qual cabe ali exige ler a referência OpenAPI e a
spec 3GPP — isso é a camada 3 (julgamento com LLM). Por isso a camada 2 serve de **piso**:
o que é inválido está errado em qualquer contexto e nem precisa ir ao juiz.

## 2. Versão da especificação e versão da ferramenta

São duas coisas diferentes:

| | Valor | Onde |
|---|---|---|
| Ferramenta | `openapi-spec-validator` 0.9.0 (gravada no relatório, campo `validator`) | `pyproject.toml` |
| Especificação conferida | **OpenAPI 3.0** (`OpenAPIV30SpecValidator`, `schema_v30`) | `validation.py`, imports |

A biblioteca traz um validador por versão da especificação — `OpenAPIV2SpecValidator`
(Swagger 2.0), `OpenAPIV30SpecValidator`, `OpenAPIV31SpecValidator`,
`OpenAPIV32SpecValidator`. Usamos a **3.0** porque todos os YAMLs 3GPP declaram
`openapi: 3.0.1`; as versões 3.0.0 a 3.0.3 compartilham o mesmo formato.

**Limite conhecido:** a versão está fixa. Um documento gerado que declarasse `3.1.0`
seria validado como 3.0 mesmo assim.

## 3. Como a biblioteca valida — duas etapas

`openapi_spec_validator/validation/validators.py`, `SpecValidator.iter_errors`:

```python
yield from self.schema_validator.iter_errors(self.schema)   # etapa A
yield from self.root_validator(self.schema_path)            # etapa B
```

### Etapa A — o documento contra o JSON Schema oficial do OpenAPI 3.0

Arquivo: `openapi_spec_validator/resources/schemas/v3.0/schema.json`. Identifica-se
como `https://spec.openapis.org/oas/3.0/schema/2021-09-28` — *"as defined by
https://spec.openapis.org/oas/v3.0.3"* — o schema publicado pela **OpenAPI Initiative**,
em JSON Schema Draft 4, com **39 definições**, uma por tipo de objeto (`PathItem`,
`Operation`, `RequestBody`, `Response`, `Parameter`, `Schema`, `Components`,
`Callback`, `Reference`, `MediaType`, `SecurityScheme`, …).

Percorre **o documento inteiro**, nó a nó, e para cada objeto confere:

- **campos permitidos** — qualquer outro só se começar com `x-`;
- **campos obrigatórios** — ex.: `description` numa response; `info`, `paths` na raiz;
- **tipo** de cada campo — string, booleano, objeto, lista;
- **padrões de nome** — path começa com `/`; código de resposta é `200`, `4XX` ou `default`;
- **exclusões mútuas** — `example` *ou* `examples`; `schema` *ou* `content` num parâmetro;
- **objeto ou `$ref`** — cada lugar aceita o objeto ou uma referência.

**Não segue `$ref`**: só confere que a referência tem o formato certo.

### Etapa B — regras que o JSON Schema não consegue expressar

Arquivo: `openapi_spec_validator/validation/keywords.py`. Percorre raiz → `paths` → cada
path item → cada operação, mais `components.schemas` e `tags`, **seguindo os `$ref`**:

| Regra | Onde (keywords.py) |
|---|---|
| `operationId` repetido no documento | 501-511 |
| parâmetro repetido (mesmo `name` + `in`) na mesma lista | 395-405 |
| todo `{x}` do path tem um parâmetro `in: path` (na operação ou no path), e todo `in: path` aparece no path | 525-541 |
| cada **Schema Object** é um schema OpenAPI 3.0 válido, descendo em `allOf`/`anyOf`/`oneOf`/`not`/`items`/`properties` | 135-217 |
| `required` citando propriedade inexistente (só quando o schema usa `allOf`) | 219-235 |
| valor `default` compatível com o schema | 237-243 |
| nome de `tag` repetido | 645-654 |

Os Schema Objects visitados são os de `components.schemas`, dos parâmetros e do
`content` das **respostas**.

## 4. O que a biblioteca NÃO verifica

Pelo registro de validadores da 3.0 (`validators.py`, `OpenAPIV30SpecValidator`):

- **schemas do `requestBody`** — a etapa B não entra neles (só a etapa A passa por ali);
- **callbacks** — a etapa B percorre só os métodos do path item, não as operações
  dentro de um callback. Os YAMLs 3GPP usam callback para as notificações;
- **`example` / `examples`** — não confere se batem com o schema;
- **`security`** — não confere se o nome usado numa operação existe em `securitySchemes`;
- **as recomendações (SHOULD)** do texto da especificação;
- **qualidade e semântica** — nada; isso é a camada 3.

Ou seja: *válido* = "passa no formato oficial do OpenAPI 3.0 e nas checagens desta
biblioteca", não "segue todas as normas da especificação".

## 5. Como usamos a biblioteca

`validate_document(doc)` roda três checagens, nesta ordem:

| Checagem | O que é | Por quê |
|---|---|---|
| `schema` | a **etapa A** sozinha (`Draft4Validator(schema_v30)`) | lista **todos** os erros de estrutura |
| `local_ref` | código nosso: todo `$ref` interno (`#/...`) aponta para algo que existe | a etapa B aborta no **primeiro** `$ref` que não consegue seguir; aqui saem todos |
| `semantics` | a biblioteca completa (**A + B**) | só roda se as duas anteriores passaram |

**`$ref` externos.** Os YAMLs 3GPP referenciam arquivos de outras specs
(`TS28623_ComDefs.yaml#/components/schemas/Uri`), que não estão em `data/inputs`.
Resolvê-los fazia **todo** documento — inclusive os oficiais — abortar no primeiro
`$ref` externo (testado: os 12 documentos, `Unresolvable`). Por isso um arquivo externo
é resolvido para um *stub* em que qualquer schema existe e aceita qualquer coisa: o
documento em si é validado; os arquivos que ele importa, não.

**Mensagens.** Uma falha em `oneOf`/`anyOf` do JSON Schema reporta o objeto inteiro;
usamos o `best_match` do `jsonschema` para mostrar o sub-erro específico (ex.:
`'responses' does not match any of the regexes: '^x-'` = "`responses` não é permitido
aqui"). A localização usa a mesma notação do resto do relatório
(`paths./{className}={id}.patch.requestBody`).

Gerado **e** oficial são validados; o relatório mostra os dois.

## 6. Resultado nos insumos atuais (06/out/2026)

| Documento | Válido? |
|---|---|
| os 9 YAMLs oficiais | todos válidos |
| `provmns_20260920_194130` | **inválido — 18**: 11 `schema` + 7 `local_ref` |
| `provmns_20260828_232853` | válido |
| `perfmns_20260823_031421` | válido |

Travado em `tests/services/test_results.py` e `tests/openapi/test_validation.py`.

## 7. Em aberto

- Cobrir os buracos da etapa B que importam aos 3GPP — **callbacks** e **requestBody** —
  aplicando a mesma validação de Schema Object a esses lugares.
- Escolher o validador pela versão declarada em `openapi` e acusar quando o gerado
  declara uma versão diferente da do oficial.
- Trazer os arquivos dependentes (`TS28623_ComDefs.yaml`, …) do 3GPP Forge para validar
  também que cada `$ref` externo aponta para algo que existe (útil ao §3.23).
