# Plano de solução — problemas A.1–A.6

Solução, neste repo, de cada problema de [PROBLEMS.md](PROBLEMS.md). Nada aqui mexe nos
repos irmãos. Cada passo é descrito ao usuário antes de mudar código; quando um passo mudar
durante a implementação, atualize este arquivo e registre o porquê no `RASTREIO.md`.

Princípios que valem para todos os passos:

- **Sem nomes de tipo.** Nenhuma regra, prompt ou teste cita um esquema da spec. O
  instrumento decide pela **estrutura** da regra (`rule_type`, `openapi_object`,
  `openapi_field`, presença de `$ref` / `type` / composição); o que depende de
  **significado** fica com o juiz, que lê os nomes nas regras e a spec no RAG.
- **Código decide fato; LLM decide significado.** Um veredito sai do código só quando é
  consequência de um fato estrutural (dois valores idênticos, uma chave ausente, um `$ref`
  sem alvo). Isso dá o mesmo resultado para a mesma entrada; não torna o fato mais certo do
  que a entrada. O relatório diz de onde saiu cada veredito: `rule` ou o juiz.
- **Camada 1 só separa o que é igual.** Os vereditos de regra são da camada 3, como os do juiz.
- **Toda contagem nova travada em teste**, com o detalhamento.

## Resumo: o que é código e o que é LLM

| Problema | O que resolver | Código | LLM |
|---|---|---|---|
| A.3 `204` sem corpo | o oficial sem `content` deixa de ser "sem valor"; `204` sem esquema no banco = igual | tudo | — |
| A.4 schema sem tipo | `{}` e `nullable: true` chegam com o que dizem | a extração e a igualdade | só o que continuar diferente (ex.: `{}` × `nullable`) — julgamento normal |
| A.5 `$ref` local sem alvo | o banco não define X e diz que nunca completou → errado | tudo | — |
| A.6 parâmetro repetido | mesmo `in`, `name` e valor no path e na operação → extra errado | tudo | — |
| A.1 / A.2 respostas de erro | agrupar por operação e aplicar a tabela | agrupar; o caso; o `$ref` antes; as 5 situações estruturais | só `default` × ranges com **valores diferentes**; `4XX` ≠ `5XX`; `default` que pode não ser de erro |
| todos | o valor de cada regra contra o oficial | igual → camada 1 | diferente → juiz, como hoje |

No banco de 09/nov, a LLM das respostas de erro seria chamada em **2 grupos** (PUT e PATCH).
GET (três valores idênticos), DELETE (só `default`) e os 5 callbacks (só ranges) saem do código.

## Ordem

| Passo | Resolve | Onde | Muda números travados? |
|---|---|---|---|
| 1 | A.3, A.4 | extração + camada 1 | sim (`test_results.py`) |
| 2 | A.5 | partes: veredito de regra antes do juiz | sim (`test_parts.py`) |
| 3 | A.6 | partes: veredito de regra antes do juiz | sim (`test_parts.py`) |
| 4 | A.1, A.2 | partes + prompt do juiz | sim (`test_parts.py`) |
| 5 | — | run completo do banco de 09/nov, conferido contra PROBLEMS.md | — |

O passo 1 vem primeiro porque muda o que é "igual"; o 2 antes do 4 porque o `$ref` é
conferido antes da tabela.

---

## Passo 1 — o que o oficial escreve chega inteiro (A.3, A.4) · código · FEITO 10/nov

Nada interpretado pelo código, nada específico de spec (uma lista de chaves "que não
restringem" foi descartada: o código decidiria o significado).

**Extração** (`rulesbank/extraction.py`):

- `_schema_value`: um schema que não é `$ref`, tipo nem composição é escrito **como está**,
  numa linha (`{}`, `{nullable: true}`).
- `_response_value`: uma resposta sem `content` → `no body` (`rule_types.NO_BODY`), fato da
  estrutura (Response Object).

**Camada 1** (`rulesbank/comparison.py`, `compare_value`):

- oficial `no body` × valor do banco que não nomeia corpo (sem `$ref`, palavra de tipo JSON,
  `oneOf`/`anyOf`/`allOf` ou nome de schema em CamelCase) → igual; na dúvida, diferente.
- schema escrito como está × o banco: igual só ao mesmo schema (lido como YAML).

**Juiz** (`judge/prompts.py`, `judge-v25`): fatos da OpenAPI 3.0.1 — Schema Object `{}` e
`nullable`; Response sem `content`.

**Resultado**: nenhum `not_comparable` sobra em nenhum insumo. Banco de 09/nov: os 7 `204`
iguais; `PatchItem.value`, `MoiChange.value` e `.oldValue` diferentes, com o valor oficial
verdadeiro. Conferido regra a regra em todos os bancos: nenhum igual falso. Testes:
`test_extraction.py`, `test_comparison.py`, `test_results.py`, `test_parts.py`.

---

## Passo 2 — `$ref` local sem alvo (A.5) · código · FEITO 10/nov

Feito em `judge/rules.py` (`BankFacts`, `unresolved_local_ref`, `decide`), com
`judge.rule_verdict` (veredito `decided_by="rule"`, sem evidência, sem LLM, sem cache) e o
`decide` do `_judge` em `services/judge_service.py`. Com só o primeiro fato, a parte vai ao
juiz com ele no resumo (`judge/parts.py`, `ref_fact`). O relatório final conta os vereditos
"by the judge" e "by a rule", e marca cada parte decidida por regra. No banco de 09/nov: as 8
regras esperadas (4 `default`, `4XX`/`5XX` do GET, `specificProblem`, `additionalText`) →
errado, travadas em `tests/judge/test_rules.py`. O que estava planejado:

Para cada `$ref` local (`#/components/schemas/X`) no valor de uma regra do banco:

1. o banco não tem nenhuma regra em `components/schemas/X`; **e**
2. `X` está em `metadata.rules_never_completed` do banco.

Com os dois, a regra é **errada**, sem LLM, com o motivo no relatório. A condição 2 existe
porque o formato do banco não consegue declarar um schema de tipo simples (`schema_property`
só aceita `properties.<n>` e as palavras-chave): só a 1 marcaria errado um `$ref` certo para um
tipo simples. Com só um dos dois, a regra segue para o juiz, com o fato numa linha `known`.

**Mecanismo novo** (vale para os passos 2–4): um veredito de regra (`origin: rule`, com o
motivo) no lugar do veredito do juiz, para a parte ou para uma diferença dela; o relatório
conta à parte quantos vieram de regra. É o único arquivo novo do plano, se o mecanismo não
couber em `judge/parts.py` — a decidir ao implementar, mostrado antes.

**Efeito esperado**: `default` de PUT, PATCH, GET, DELETE, `4XX`/`5XX` do GET,
`specificProblem` e `additionalText` → errado, sem LLM.

---

## Passo 3 — parâmetro repetido na operação (A.6) · código · FEITO 10/nov

Feito em `judge/rules.py` (`repeated_path_parameter`). No banco de 09/nov: `className` e `id`
do DELETE → extra errado; no banco de 15/set, o `filter` do DELETE (também declarado no path,
com o mesmo valor). Travado em `tests/judge/test_rules.py`. O que estava planejado:

Um parâmetro no nível da operação com o mesmo `in`, `name` e valor de um parâmetro do nível do
path do mesmo `paths.<path>` → **extra errado** (redundante: o parâmetro do path já vale para a
operação — OpenAPI 3.0.1, Path Item Object). Com o mesmo `in` e `name` e **outro** valor, é
uma sobrescrita: vai ao juiz.

**Efeito esperado**: `className` e `id` do DELETE → extra errado, sem LLM.

---

## Passo 4 — respostas de erro por operação (A.1, A.2) · código + LLM · FEITO 10/nov

Feito: `judge/rules.py` (`error_plan`: o caso, o que a forma decide, a pergunta;
`error_responses` no `decide`), `judge/parts.py` (`_error_groups`, `_error_items`: uma parte
`error responses` por operação; as visões tomam o veredito de cada regra,
`Verdict.rule_verdicts`), `judge/judge.py` (`with_rule_verdicts`: o que a forma fixou + o
juiz nas diferenças), prompt (a regra das respostas de erro, sem nomes; `judge-v25`). Ficam
fora do grupo: a operação em que o banco só tem `default` (julgada como qualquer regra) e a
em que o oficial declara ele mesmo um range. No banco de 09/nov: GET (três `$ref` sem alvo) e
os 5 callbacks (melhoria) por regra; PUT e PATCH à LLM só nos ranges, com a pergunta das três
respostas. Travado em `tests/judge/test_rules.py` (cada situação, sintética; o banco de 09/nov)
e `test_parts.py`. Conferido com uma LLM falsa: 14 partes à LLM, 11 por regra, cada regra
contada uma vez nas duas visões. O que estava planejado:

**Agrupar** (código): regras com `rule_type == "response"`, o mesmo `openapi_object` (os
`responses` de uma operação ou de um callback) e `openapi_field` igual a `default` ou a uma
faixa `1XX`–`5XX`. O `default` oficial do mesmo `openapi_object` entra junto. Códigos
explícitos (`400`...) ficam fora. É a mesma chave que a camada 1 já usa para casar `4XX` +
`5XX` com o `default` oficial (`_ranges_of`).

**Conferir o `$ref` antes** (passo 2): uma regra errada pelo `$ref` fica errada, e o caso é
decidido com as regras como estão.

**A forma, por código** — as situações que só dependem da estrutura:

| Situação | `default` | `4XX` / `5XX` |
|---|---|---|
| só `default` | certo | — |
| só `4XX` + `5XX` (mesmo valor) | — | melhoria |
| `4XX` + `5XX` + `default`, **mesmo valor** nos três | errado (sobra) | melhoria |
| `default` + um só range | certo | o range: errado |
| um só range, sem `default` | faltando | o range: errado |

**A forma, pela LLM** — só o que pede leitura:

- `4XX` + `5XX` + `default` com **valores diferentes**: uma parte por operação, com as três
  regras e o `default` oficial. Pergunta, com o RAG: o tipo do `default` traz algo que a spec
  restringe à operação (ou a uma condição dela) e que os ranges não têm? Três respostas:
  - **sim** → `default` certo, ranges errados;
  - **não, é o mesmo conceito** → ranges melhoria, `default` sobra (errado);
  - **sem evidência** → indeciso.
- `4XX` e `5XX` com valores diferentes entre si, e um `default` que pode não ser de erro: a
  tabela não os cobre; vão ao juiz com o grupo inteiro e a pergunta aberta.

O prompt (`judge/prompts.py`) ganha a regra dessa parte, com a pergunta e as três respostas,
sem nomes de tipo; `PROMPT_VERSION` sobe.

**O valor, à parte**: a forma não diz se o valor está certo. O valor de cada regra contra o
oficial segue o caminho de sempre (igual na camada 1, ou julgado). Uma regra "melhoria" na
forma e com o valor errado é errada.

**A.2**: o casamento de `4XX` + `5XX` com o `default` oficial continua contando como
cobertura na camada 1, mas a linha do par na visão final vem da forma (aqui: melhoria), não
de "igual".

**As visões** (`rulesbank_views`): cada regra toma a linha do **seu** veredito (de regra ou da
sua diferença), não o da parte.

**Efeito esperado** no banco de 09/nov:

| Operação | Situação | Quem decide | `default` | `4XX` / `5XX` |
|---|---|---|---|---|
| PUT | 3, valores diferentes | LLM (forma); `$ref` antes | errado (`$ref`) | depende da LLM; esperado: melhoria |
| PATCH | 3, valores diferentes | LLM (forma); `$ref` antes | errado (`$ref`) | depende da LLM; esperado: errados |
| GET | 3, mesmo valor | código | errado (`$ref`) | errados (`$ref`) |
| DELETE | só `default` | código | errado (`$ref`) | — |
| 5 callbacks | só ranges | código | — | melhoria (10 regras) |

**Testes**: `tests/judge/test_parts.py` — o agrupamento, cada situação da tabela com regras
sintéticas, quais grupos vão à LLM, as visões com vereditos por regra.

---

## Passo 5 — conferir · LLM

`uv run openapi-analysis rulesbank <banco de 09/nov> <oficial 18.2.0> --spec 28532-i20`: a
análise completa. Com o prompt novo, as partes que ainda vão ao juiz são julgadas de novo (a
versão do prompt faz parte da chave do cache); menos partes que as 33 de hoje.

O resultado é conferido regra a regra contra a tabela de PROBLEMS.md. Uma regra que o juiz
ainda errar vira um problema novo `A.x`, com a evidência — não um ajuste para o número bater.
Depois: `RULES.md`, `CLAUDE.md` (resultados travados), `RASTREIO.md` (a entrada de cada passo).

**Feito em 10/nov** (relatório `2026-11-10_20-23-44`, 14 chamadas, US$ 0,066): das 33 regras da
revisão, 31 certas, 0 erradas e 2 indecisas (os `4XX`/`5XX` do PUT) — o que levou a A.7.

---

## Passo 6 — default + 4XX + 5XX é escolha do usuário (A.7) · código + LLM

**Forma, por código** (`judge/rules.py`, `error_plan`): no caso `4XX + 5XX + default` (mesmo
valor ou não), o `default` é julgado contra o `default` oficial como qualquer regra (igual → igual;
diferente → o juiz julga o valor) e os ranges recebem `discardable`. O `$ref` sem alvo continua
antes de tudo. Os outros casos não mudam. Sai a pergunta "o tipo do default traz algo...".

**Recomendação, pela LLM**: a parte desse caso vai sempre ao juiz, que responde, além do valor
do `default` quando ele difere, a configuração a usar — `default`, `4XX + 5XX` ou "a spec admite
as duas" —, pelo que a spec traz para a operação (as três regras de PROBLEMS.md A.7), com a
citação. Campo novo na resposta (`JudgeAnswer.recommendation`, `recommendation_why`); fora do
placar. Prompt sem nomes de tipo; `PROMPT_VERSION` sobe.

**Visões e relatório**: linha nova `extra discardable` — "extra, descartável (decisão do
usuário)" — na visão do banco, fora de "certo" e de "errado", na base do banco. O relatório final
lista essas regras com a recomendação da operação.

**Esperado no banco de 09/nov**: PUT — `default` errado (`$ref`), ranges descartáveis,
recomendação "admite as duas"; PATCH — `default` errado (`$ref`), ranges descartáveis,
recomendação `default`; GET — os três errados (`$ref` sem alvo nos três). Testes: cada caso
sintético e o banco de 09/nov em `test_rules.py`; a visão com a linha nova.

## Fora deste plano

- O `default` × `4XX` / `5XX` na avaliação do YAML gerado (`openapi`): o critério de 10/nov foi
  decidido para o banco. Se vale também para o YAML, é uma decisão à parte.
- Os itens de `RULES.md` §5.
