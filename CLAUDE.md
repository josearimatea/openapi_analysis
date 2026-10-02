# openapi_analysis — contexto para o agente

Leia este arquivo antes de mexer no repositório. Ele explica o que este projeto é,
por que existe, o que já foi construído, e como a análise deve funcionar. Foi
escrito para um agente (ou pessoa) que abre este repo sem conhecer o histórico.

---

## 1. O que este projeto é

`openapi_analysis` é um **instrumento de medição** com **duas avaliações separadas**,
ambas contra o **YAML OpenAPI oficial**:

1. **rulesbank** — avalia o *rules bank* do `openapi_rulesbank`. As regras do YAML
   oficial são extraídas aqui, **no mesmo formato do banco**, e comparadas regra a
   regra: cobertura (endereço) e fidelidade (valor).
2. **openapi** — avalia o YAML gerado pelo `openapi_generator`, comparando-o
   **diretamente** com o YAML oficial (documento × documento). Aqui NÃO se extraem
   regras do YAML gerado.

**Este projeto NUNCA gera regras a partir da especificação 3GPP** — isso é o
`openapi_rulesbank`. A única extração que existe aqui é a do YAML OFICIAL (o
gabarito), em `rulesbank/extraction.py`.

## 2. Por que existe (a motivação — importa para não repetir o erro)

O gerador (`openapi_rulesbank`) é uma pipeline multi-agente (LangGraph) que extrai
regras OpenAPI de especificações 3GPP. Para saber se ele está melhorando, era
preciso medir o banco de regras contra o YAML oficial. Essas medições vinham sendo
feitas **de forma ad-hoc, e deram erradas pelo menos três vezes**:

1. "31 refs externos" era contagem no LOG inteiro (linhas de RAG e de raciocínio),
   não no campo real das regras.
2. "43% correto / 98% cobertura" veio de um extrator de alvos que **não descia em
   `oneOf`/`allOf`**: achou 54 alvos onde havia muito mais.
3. "0 regras sumiram" saiu de indexar regras por uma chave que pode repetir; duas
   regras colidiram, uma sobrescreveu a outra silenciosamente.

**A lição:** o instrumento de medição precisa ser confiável, versionado e travado
por testes — senão o número engana. Este repo é essa correção. Regra de ouro
herdada do trabalho: *quando dois indicadores da mesma medição se contradizem,
suspeite do instrumento, não do sistema.*

## 3. O ecossistema (onde os arquivos moram)

Tudo fica em `workspace/`, como pastas irmãs:

```
workspace/
  openapi_rulesbank/     # o GERADOR (pipeline LangGraph). Fonte da verdade do contrato de regra.
    data/inputs/yamls/   # os YAMLs OFICIAIS (ground truth). Ex.: rel18_TS28532_ProvMnS.yaml
    data/outputs/rules_bank/<MnS>/Final_rules/*.json   # os BANCOS DE REGRAS gerados
    src/openapi_rulesbank/utils/rules_check.py         # O CONTRATO que este repo espelha
    Problems_ProvMnS.txt                               # defeitos ABERTOS (numeração §x.y)
    Problems_ProvMnS_LEGACY_ate_20260920.txt           # histórico, mesma numeração
  openapi_generator/     # gera o YAML OpenAPI a partir do banco
    src/openapi_generator/schemas/rule_types.py        # como o CONSUMIDOR lê cada regra
    data/outputs/test_pipeline/**/*.yaml               # os YAMLs gerados
  openapi_analysis/      # ESTE repo
```

**A análise não lê os irmãos.** Os insumos são COPIADOS para `data/inputs/` por
`scripts/sync_data.py`, que grava `data/inputs/manifest.json` (origem, sha256 e o
pareamento YAML gerado → banco que o produziu, lido do cabeçalho
`x-ai-generation`). Assim um número travado não muda porque um arquivo mudou em
outro repo. Os YAMLs oficiais são renomeados por serviço + `info.version`
(`data/inputs/reference/ProvMnS/TS28532_ProvMnS_v18.2.0.yaml`). Para acompanhar uma
rodada nova: adicione-a em `RULES_BANKS`/`GENERATED` no script e rode-o.

## 4. As duas estruturas de dados

### 4.1 Uma regra no banco (o que analisamos)

Cada item de `rules[]` no JSON tem:

```
section_id, section_title, rule_type, source_name, rule_text,
openapi_mapping { openapi_object, openapi_field, openapi_value,
                  references[] { file, schema_name } },
reflector_score, reflection_reasoning, reflection_flagged,
split_suggestion, discard_suggestion,
validation_notes, validation_passed
```

O `metadata.usage` traz `llm_calls`, tokens e `cost_usd` (ainda sem tempo de
execução — é uma lacuna aberta, §3.20).

### 4.2 Uma regra do YAML oficial (o que esperamos que exista)

É uma regra **no mesmo formato do banco** (`rule_type` + `openapi_mapping` com
valor e `references[]`), extraída do YAML oficial por `rulesbank/extraction.py`.
As duas são casadas por UMA função, `rule_types.rule_key` — nada mais pode montar
chave de regra, ou as contagens divergem. A definição completa e cada decisão
estão em `docs/RULES.md`.

## 5. O CONTRATO que espelhamos (não invente granularidade)

**Princípio inegociável:** a enumeração de alvos espelha o contrato de endereçamento
do gerador (`openapi_rulesbank/utils/rules_check.py`). O que conta como "uma regra"
é decidido lá, no fluxo e na geração — este repo apenas mede contra isso. Se o
gerador emite uma regra por media type, o alvo é por media type; se ele trata `enum`
como um campo único, o alvo é um só. Nunca imponha aqui uma contagem própria.

O contrato (resumido de `rules_check.py`):

| rule_type       | openapi_object                             | openapi_field                    | observação |
|-----------------|--------------------------------------------|----------------------------------|-----------|
| path_operation  | `paths.<path>`                             | `<método>`                       | um por método |
| path_parameter  | `paths.<path>` **ou** `.<método>`          | `parameters[in=path,name=<n>]`   | nível que o YAML declara |
| query_parameter | `paths.<path>.<método>` (sempre)           | `parameters[in=query,name=<n>]`  | `rules_check` exige o método |
| request_body    | `paths.<path>.<método>.requestBody`        | `content`                        | media type vai no **value** |
| response        | `paths.<path>.<método>.responses`          | `<código>`                       | 200/4XX/default... |
| callback        | `paths.<path>.<método>.callbacks.<nome>`   | `<método de entrega>`            | + insides |
| schema_property | `components/schemas/<Nome>`                | `properties.<n>` ou keyword      | keyword: enum/required/oneOf/anyOf/allOf/items/additionalProperties |

Pontos que já foram fonte de bug e estão resolvidos em `rulesbank/extraction.py`:

- **Nível do parâmetro.** Parâmetro no nível do PATH vale para todos os métodos; no
  nível da OPERAÇÃO só para aquele. Os dois são modelados, porque pôr um parâmetro
  de operação no nível do path é o defeito §3.22, e a cobertura só o detecta se o
  alvo estiver no nível certo.
- **Media type na identidade do request_body.** O gerador usa sempre
  `field="content"` e põe o media type no `openapi_value`. Logo o media type faz
  parte da IDENTIDADE do alvo (4 media types = 4 alvos); para os outros rule_types,
  o value é conteúdo a conferir, não identidade (`RuleTypeSpec.value_in_identity`).
- **Descida recursiva.** Em schemas, descer por `oneOf`/`anyOf`/`allOf`/
  `properties`/`items`. Um `$ref` (interno ou externo) é uma FOLHA: a referência é
  o alvo, o interior dela não é enumerado (não abrimos o outro arquivo YAML). Não
  descer no `oneOf` foi o bug que contou 54 alvos a menos.
- **Keyword-coleção = um alvo.** `enum`, `required`, `oneOf` etc. são um alvo cada
  (o valor é a coleção inteira), nunca um por item.

## 6. O que JÁ existe (estado em 01/out/2026)

```
src/openapi_analysis/
  config/        paths, settings (OFFICIAL_REFERENCE por serviço), logging
  rulesbank/     avaliação 1: rule_types.py (A DEFINIÇÃO + rule_key), extraction.py,
                 comparison.py (cobertura + fidelidade regra a regra)
  openapi/       avaliação 2: comparison.py (folhas contract/metadata/prose)
  schemas/       os relatórios (Pydantic) — contrato com quem chama
  services/      o que irmãos / chatUI / CLI chamam (aceitam dict ou caminho)
  reporting/     texto
  api/           FastAPI opcional — só docstrings, ainda não construído
  cli.py         openapi-analysis rulesbank | openapi | extract | all
tests/           61 testes; tests/services/test_results.py TRAVA todo número publicado
```

O padrão de pastas segue os irmãos (`config/`, `schemas/`, `services/`,
`api/routes|schemas`, `data/inputs|outputs`) — de propósito, sem `domain/`.

**Resultados travados** (`uv run openapi-analysis all` → `data/outputs/<Serviço>/`):
banco i20 ProvMnS × v18.2.0 = **81/113 cobertos (71,7%)**, fidelidade **53/72 (73,6%)**,
39 regras do banco fora de qualquer endereço oficial, 5 casos de §3.23 medidos.
Query params: 0/5 (todos no path — §3.22, banco anterior à correção do rulesbank).

Rodar:
```bash
uv sync && uv run pytest
uv run openapi-analysis all
```

## 7. O que FALTA (roteiro)

1. Decisões em aberto de `docs/RULES.md` §5 (referência dos bancos i00, header,
   o que do YAML não é regra).
2. Catálogo de defeitos além do §3.23 já medido: §3.22 explícito (query no path),
   §3.27 (endereço compartilhado já listado), §2.1 (`validation_passed=False` já
   contado).
3. `api/` — rotas FastAPI para o chatUI (`app.include_router`).
4. Relatório HTML (opcional).

## 8. Convenções e cuidados

- **Espelhe o gerador, não o contrário.** Antes de decidir o que conta como alvo,
  confira `rules_check.py`. Divergência entre os dois é bug do instrumento.
- **Trave números novos em teste.** Toda contagem que você passar a reportar deve
  ter um teste que a fixe, com o detalhamento por tipo. É o que impede o erro de
  medição de voltar.
- **Ao medir, se dois números se contradizem, o instrumento é o suspeito.**
- **Commits:** formato `[TAG]` no assunto (ex.: `[FEAT]`, `[FIX]`, `[TEST]`,
  `[INIT]`). **Não** adicionar linha `Co-Authored-By`.
- **Não commitar** os arquivos `Problems_ProvMnS*.txt` do repo gerador — eles são
  notas de trabalho de lá.
- O `Problems_ProvMnS.txt` (aberto) e o `_LEGACY_` (histórico) usam a MESMA
  numeração `§x.y`; um `§3.22` referido aqui é o de lá, continuado. Consulte-os
  para o raciocínio por trás de cada defeito.
