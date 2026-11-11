# Problemas do instrumento (openapi_analysis)

Defeitos do **próprio instrumento** — extração, camada 1, partes, prompt do juiz — achados ao
conferir os resultados. Os defeitos do banco de regras ficam no `openapi_rulesbank`; aqui só o
que faz este repo medir ou julgar errado. Numeração `A.x`, nunca reaproveitada. Quando este
documento ficar grande, congele-o como `PROBLEMS_LEGACY_ate_<data>.md` e continue num novo, com
a mesma numeração. A solução de cada item está em [FIX_PLAN.md](FIX_PLAN.md).

Estados: `[ABERTO]` achado e conferido, sem conserto · `[PLANEJADO]` com solução no plano ·
`[FEITO]` conserto feito e travado em teste.

## Origem: revisão dos 33 julgamentos do banco de 09/nov/2026

Banco `rules_bank_28532-i20_full_20261109_102214.json` × oficial ProvMnS v18.2.0, relatório
`data/outputs/reports/ProvMnS/rulesbank/2026-11-09_20-17-07.txt` (juiz `judge-v24`, 33
partes, US$ 0,15). Revisão feita em 09–10/nov contra a TS 28.532 i20, a TS 28.623 i40 e o
OpenAPI 3.0.1, com os critérios decididos em 10/nov (tabela das respostas de erro, abaixo).

**O juiz acertou 15 e errou 18.** Dos 18 erros, 16 vêm do instrumento (o que chegou ao juiz
estava incompleto ou falso, ou a parte estava recortada errado) e 2 do julgamento do LLM
(A.6).

| Regra do banco | Juiz deu | Correto | Problema |
|---|---|---|---|
| `default` do PUT | indeciso | errado (sobra; e `$ref` local) | A.1, A.5 |
| `4XX`, `5XX` do PUT | melhor | melhoria | — (certo) |
| `default` do PATCH | errado | errado (`$ref` local) | — (certo) |
| `4XX`, `5XX` do PATCH | melhor | errado (o `default` é específico) | A.1 |
| `default` do GET | indeciso | errado (`$ref` local) | A.5 |
| `4XX` do GET | errado | errado (`$ref` local; o valor contradiz a tabela do método) | — (certo) |
| `5XX` do GET | melhor | errado (idem) | A.1, A.5 |
| `default` do DELETE | indeciso | errado (`$ref` local) | A.5 |
| `204` do PUT, do PATCH e de 5 callbacks | melhor (5) / útil (2) | igual | A.3 |
| `NotifyEvent.specificProblem` | indeciso | errado (`$ref` local) | A.5 |
| `NotifyMoiAttributeValueChanges.additionalText` | indeciso | errado (a tabela do tipo diz `string`) | A.5 |
| `PatchItem.value` (`{}`) | melhor | diferente, mas certo | A.4 |
| `className`, `id` repetidos no DELETE | melhor | extra errado (redundante) | A.6 |
| `MoiChange.value`, `.oldValue` (`object`) | errado | errado | — (certo) |
| `Scope.required`, `PatchItem.required` | errado | errado | — (certo) |
| `Resource` `oneOf`, `anyOf` | errado (faltando) | faltando | — (certo) |
| DELETE `200 array(Uri)`, `204`, `scope`, `filter` | melhor | melhoria | — (certo) |
| `MoiChange.path` (`string` × `$ref Uri`) | equivalente | equivalente | — (certo) |

Fora dos 33: os `4XX` + `5XX` dos 5 callbacks nem chegaram ao juiz (A.2).

### Critério das respostas de erro (decidido em 10/nov/2026)

Por operação, conforme o que o banco declara nela:

| No banco, na mesma operação | `default` | `4XX` / `5XX` |
|---|---|---|
| só `default` | certo | — |
| só `4XX` + `5XX` | — | melhoria |
| `4XX` + `5XX` + `default` genérico | errado (sobra) | melhoria |
| `4XX` + `5XX` + `default` específico | certo | errados (perdem o tipo específico) |
| `default` + um só range | certo | o range: errado |
| um só range, sem `default` | faltando | o range: errado |

Um `oneOf` num `default` é uma regra só. Em qualquer caso, um `$ref` local que não resolve é
errado. **Sem nomes de tipo no instrumento:** o caso sai da estrutura (quais chaves a
operação tem); se o `default` é genérico ou específico, o juiz decide pela spec.

**Revisto em 10/nov (híbrido).** A tabela decide a **forma** da operação, não o valor:

- Cinco situações se decidem só pela estrutura: só `default`; só `4XX` + `5XX`; `4XX` +
  `5XX` + `default` com o **mesmo valor** (o `default` não acrescenta nada: sobra, e os
  ranges são melhoria); `default` + um só range; um só range sem `default`.
- Só quando o `default` e os ranges têm **valores diferentes** é preciso ler a spec: o tipo do
  `default` traz algo que a spec restringe à operação (ou a uma condição dela) e que os
  ranges não têm? "Sim" → `default` certo, ranges errados; "não, é o mesmo conceito" →
  ranges melhoria, `default` sobra; "sem evidência" → indeciso.
- Fora da tabela, também para ler: `4XX` e `5XX` com valores diferentes entre si; um
  `default` que não é de erro.
- O **valor** de cada regra contra o oficial segue à parte (igual na camada 1, ou julgado).
- O `$ref` é conferido **antes** da tabela.

Consequência para o GET: os três (`default`, `4XX`, `5XX`) têm o mesmo valor, então pela
forma os ranges seriam melhoria e o `default` sobraria — não "`default` específico". Os três
continuam errados, mas pelo valor: `$ref` local que não resolve, e o tipo dos ranges
contradiz a tabela do método (`ErrorResponse 4xx/5xx`).

---

## A.1 `[FEITO 10/nov]` Respostas de erro julgadas uma a uma, sem o caso da operação

Cada `default`, `4XX` e `5XX` do banco vira uma parte separada (`judge/parts.py`,
`_rulesbank_items`). O juiz não sabe o que mais a operação declara, e o prompt não tem o
critério acima: a única regra de respostas de erro (`judge/prompts.py`, "When one official
block corresponds to several generated blocks...") manda decidir pelos **códigos** que a spec
lista, não pelo **tipo** do `default`.

Efeitos no banco de 09/nov: `4XX` do GET "errado" e `5XX` do GET "melhor" com o mesmo valor;
`4XX`/`5XX` do PATCH "melhor" quando o `default` é específico; `default` do PUT "indeciso"
quando sobra.

## A.2 `[FEITO 10/nov]` A camada 1 marca como igual 4XX + 5XX que fazem o papel do default

Pela regra de 07/nov (`rulesbank/comparison.py`, `_ranges_of` / `_compare_ranges`), um par
`4XX` + `5XX` do banco cobre o `default` oficial da mesma operação; com o mesmo valor, o par é
"igual" e não vai ao juiz. Pelo critério de 10/nov, "só 4XX + 5XX" é **melhoria**, um
veredito: não pode sair da camada 1, que só separa o que é igual.

Efeito: as regras 51–60 do banco (os `4XX`/`5XX` dos 5 callbacks do PUT) contam como "igual".

## A.3 `[FEITO 10/nov]` 204 sem corpo comparado como texto

O `204` oficial não tem `content`; a extração escreve o valor `""`
(`rulesbank/extraction.py`, `_response_value`). O banco escreve "No response body" (ou "no
response body"). A comparação vê textos diferentes, o resumo da parte diz ao juiz que "the
official holds no value at this address" (`judge/parts.py`, `_NOT_COMPARED`) e o juiz julga o
que é, de fato, igual.

Efeito: 7 falsos "diferente" (PUT, PATCH e 5 callbacks), com vereditos melhor (5) e útil (2).

## A.4 `[FEITO 10/nov]` A extração apaga o que o oficial escreve num schema sem tipo

`_schema_value` (`rulesbank/extraction.py`) devolve `""` para todo schema sem `$ref`, `type`
ou composição. Assim `{}` (qualquer tipo) e `{nullable: true}` (qualquer tipo, e `null`)
viram "sem valor", e o juiz recebe a frase falsa de A.3.

Efeito: `PatchItem.value` (oficial `nullable: true`) julgado "melhor" contra um oficial "sem
valor"; `MoiChange.value` / `.oldValue` (oficial `{}`) acertaram, mas com a mesma entrada falsa.

## A.5 `[FEITO 10/nov]` `$ref` local que não resolve: o juiz não recebe o fato

O banco declara em `metadata.rules_never_completed` os `$ref` que nunca completou ("no section
stated whether X is local or imported"), e não define esses alvos. O juiz não recebe nenhum
dos dois fatos; vê só o nome e procura no RAG.

Efeito: os mesmos defeitos com vereditos diferentes — `default` do PATCH "errado"; `default`
de GET, PUT, DELETE, `specificProblem` e `additionalText` "indeciso".

## A.6 `[FEITO 10/nov]` Parâmetro repetido na operação julgado melhoria

O banco declara `className` e `id` no nível do path e de novo no DELETE, com o mesmo `in`,
`name` e schema. O juiz deu "melhor"; o decidido em 10/nov é **extra errado** (redundante: o
parâmetro do path já vale para a operação — OpenAPI 3.0.1, Path Item Object).

---

## Em aberto de antes

Os itens de [RULES.md](RULES.md) §5 (comparar `style`/`explode`; mostrar
`metadata.unresolved_missing`; o que do YAML não é regra) continuam lá.
