# Camada 3 — o juiz semântico (estratégia de implementação)

Plano para a terceira camada da análise, combinado em 06/out/2026. Ainda **não
implementado**. Quando uma decisão daqui mudar durante a implementação, atualize este
arquivo e registre o porquê no `docs/RASTREIO.md`.

## 1. Por que existe

As camadas 1 e 2 são determinísticas e medem **concordância** com o YAML oficial e
**validade** OpenAPI 3.0. Nenhuma das duas diz se uma divergência é **erro ou melhoria**:
o oficial pode errar ou estar defasado, o banco é extraído do *texto* 3GPP (não do YAML),
e o gerado pode trazer uma escolha melhor. Exemplo: `4XX`/`5XX` × `default` — ambos
válidos; decidir qual cabe exige ler a referência OpenAPI e a spec 3GPP e interpretar.

A camada 3 faz essa leitura. **A LLM julga; não mede.** As camadas 1 e 2 continuam
sendo o instrumento travado; o juiz trabalha sobre a lista de divergências que elas
produzem, e o resultado dele é reportado **à parte**, nunca misturado à concordância.

## 2. O que é julgado

- **Igual ao oficial → ok.** Não vai ao juiz.
- **Diferente → o juiz responde, para aquela parte:**
  1. **por que está diferente** — a causa provável, seja a divergência de valor, de
     **endereço** (nível, lugar) ou de estrutura;
  2. **é erro ou melhoria** — com base no que a spec 3GPP diz e no que a referência
     OpenAPI permite/recomenda;
  3. **qual versão é mais entendível** — a oficial ou a gerada, e por quê.

## 3. A unidade: uma parte por vez

O juiz **nunca** recebe o documento inteiro: a busca precisa ser dirigida pela parte
analisada para trazer trechos que falem dela. Cada parte tem **busca própria e chamada
própria**.

**Rulesbank — uma regra por vez** (do relatório `RulesBankEvaluation`):

| Parte | Origem | O juiz compara |
|---|---|---|
| `different` | `matches` com `value_status == "different"` | valor do banco × valor oficial no mesmo endereço |
| `missing` | `missing` | a regra oficial que o banco não tem — a spec pede isso? |
| `extra` | `extra` | a regra do banco fora de qualquer endereço oficial — é invenção, endereço errado, ou algo que a spec pede e o YAML omitiu? |
| duplicata | `shared_addresses` | as regras do banco no mesmo endereço — qual está certa? |

**Generator — um aspecto de um dono por vez** (do relatório `OpenAPIEvaluation`):

| Aspecto | Origem no relatório | Exemplo |
|---|---|---|
| parâmetros | `OperationScore.params_*`, `params_at_path_level` | GET: query params no path item |
| media types do request body | `media_missing/extra` | PATCH: `json-patch` × `vnd.3gpp.json-patch` |
| respostas | `responses_missing/extra` | PATCH: `{200,204,default}` × `{400,4XX,5XX}` |
| forma do schema | `SchemaScore.shape_*` | NotifyEvent: `allOf[2]` × achatado |
| lugar do schema | `status == "misplaced"`, `found_at` | MoiChange fora de `components.schemas` |
| schema extra | `status == "extra"`, `note` | Uri copiado (externo no oficial) |
| valores divergentes | `details` com `kind == "differing"` agrupados por dono | `$ref` de erro interno × externo |

Partes que a camada 2 já reprovou como **inválidas** (fora do formato OpenAPI 3.0)
entram como `erro` sem chamar a LLM.

## 4. Contexto por RAG, por parte

Repositório compartilhado: `qdrant_3gpp_rag` (o mesmo que o `openapi_rulesbank` usa via
dependência editável). Qdrant em `localhost:6333`, embeddings
`sentence-transformers/all-MiniLM-L6-v2` (dim 384), como nos irmãos.

### 4.1 Regra: nenhum anexo

**Nenhum anexo de spec 3GPP entra** — nem na análise da spec, nem como referência, nem
no RAG. Os anexos de uma spec 3GPP trazem os documentos OpenAPI prontos (o anexo A da
TS 28.532 é o próprio YAML oficial): lidos pelo juiz, ele "leria a spec" e encontraria
o gabarito contra o qual está julgando — o veredito ficaria circular. É a mesma regra
dos irmãos: o generator corta todo o texto a partir do primeiro anexo
(`utils/parsers.normative_only`), o rulesbank descarta o anexo do YAML.

Consequências:
- toda spec indexada passa por `normative_only` (sem sumário, sem anexo) antes de ser
  cortada em seções; um filtro extra descarta qualquer seção com linha `openapi: <n>`;
- o **corpus compartilhado** (`3gpp_rel18_*`, do `qdrant_3gpp_rag`) **não é usado**:
  ele indexa as specs inteiras, anexos incluídos, e seus chunks não têm metadado que
  permita filtrar o anexo. As specs referenciadas por `$ref` externo são indexadas por
  nós, com a mesma regra;
- uma citação de cláusula de anexo (`A.x`) é rejeitada → veredito `incerto`;
- um teste trava: nenhum trecho indexado vem de anexo.

### 4.2 Fontes

| Fonte | Coleção | Filtro | Para quê |
|---|---|---|---|
| **spec principal** (a spec de onde o insumo veio) | **fixa por versão**, ex. `analysis_spec_28532_i20` — indexada uma vez por seção, só texto normativo, metadados `spec`, `code`, `clause`, `title` | `clause` (rulesbank) ou nenhum (generator, só similaridade) | o que a spec diz daquela parte |
| **specs referenciadas** (`$ref` externo) | fixas por versão, mesma construção — ex. `analysis_spec_28623_i40` | — | tipos importados (ErrorResponse, Uri, NotificationHeader…) |
| **referência OpenAPI** | `openapi_reference` (OpenAPI 3.0.1) | — | o que o formato permite/recomenda |

Por ora só a spec **i20** é indexada (os bancos i00 ficam fora do juiz).

A coleção da spec principal é **fixa por versão** (não temporária por execução): mais
rápida, e a mesma pergunta sempre busca no mesmo índice — reprodutível. O markdown da
spec é copiado para `data/inputs/specs/` por `scripts/sync_data.py`, mantendo a regra de
que a análise não lê os irmãos.

### 4.3 Qual spec é a referenciada

- **spec principal:** do próprio insumo — banco: `metadata.source_document`
  (`28532-i20.md`); YAML gerado: `x-ai-generation.rules-bank.source-document`. A versão
  (`i20`, `i00`) escolhe a coleção.
- **spec de um `$ref` externo:** do nome do arquivo — `TS28623_ComDefs.yaml#/...` →
  spec `28623` → a coleção daquela spec (indexada por nós, sem anexo).

### 4.4 A consulta de cada parte

Montada a partir **daquela** parte, nunca genérica:

- **rulesbank:** filtro pela cláusula da regra (`section_id`) + similaridade com o
  `rule_text`/endereço; para `missing` (sem cláusula), similaridade com o endereço
  (operação/schema/campo).
- **generator:** termos do dono e do aspecto — URI, método, nome da operação IS quando
  conhecido, nome do schema, o que difere (ex.: "modifyMOIAttributes PATCH response
  error codes").
- **referência OpenAPI:** tipo de objeto + aspecto (ex.: "Responses Object default
  response 4XX range").

Cada veredito guarda **os trechos recuperados** (coleção, filtro, ids/títulos), para que
se possa auditar o que o juiz leu.

## 5. O juiz

- **Modelo:** `gpt-5.6-luna` — o mesmo dos irmãos. Configuração no mesmo esquema
  (`ChatOpenAI` do LangChain; provedor OpenAI ou OpenRouter por variável de ambiente;
  `.env` próprio deste repo). Saída estruturada (Pydantic).
- **Saída por parte:**

  ```
  part           : identificador estável da parte (avaliação, insumo, dono, aspecto)
  official       : o trecho oficial            generated : o trecho gerado / do banco
  why_different  : a causa provável da diferença
  verdict        : erro | melhoria | equivalente | incerto
  spec_3gpp      : o que a cláusula diz        + citação (spec, cláusula)
  openapi        : o que a referência diz      + citação (seção)
  clearer        : oficial | gerado | igual    + por quê
  ```

  `equivalente` = diferente na forma, mesmo significado e mesma clareza.
- **Regras do prompt:** julgar só com base nos trechos recuperados; **sem citação, o
  veredito é `incerto`**; não inferir o que a spec não diz; separar "o oficial está
  errado" de "o gerado está errado".
- **Risco reconhecido:** o mesmo modelo gerou o que julga (viés de autopreferência).
  Mitigação: citação obrigatória e calibração humana (§7).

## 6. Reprodutibilidade

- **Cache por parte**, chave = hash(parte + trechos recuperados + modelo + versão do
  prompt). Rodar de novo não chama a LLM e dá o mesmo resultado; trocar modelo ou prompt
  gera uma medição **nova**, sem sobrescrever a anterior.
- Os vereditos ficam em `data/judgements/` e **são versionados** no git — são dados da
  pesquisa, caros de regenerar.
- Uso registrado: chamadas, tokens, custo (como o `UsageTracker` dos irmãos).

## 7. Calibração

Um arquivo de revisão por amostra de vereditos, em que o revisor marca
concordo/discordo (e o veredito certo, quando discorda). O relatório do juiz mostra a
concordância juiz × humano. **Sem calibração, o número do juiz não é publicado.**

## 8. Relatório

Relatório próprio, em `data/outputs/judge/<avaliação>/<Serviço>/`:
- contagem por veredito, por aspecto/tipo de regra;
- **lado a lado** com a concordância da camada 1, nunca somado a ela;
- seções "melhorias do gerado/banco", "erros", "falhas do oficial", "incertos";
- cada veredito com o porquê, as citações e os trechos lidos.

## 9. Estrutura de código

```
src/openapi_analysis/
  judge/
    parts.py       extrair as partes divergentes dos relatórios das camadas 1 e 2
    retrieval.py   montar consulta e filtro por parte; chamar qdrant_3gpp_rag
    prompts.py     o prompt (versionado)
    judge.py       julgar uma parte: cache → busca → LLM → veredito
  schemas/judge.py       Part, Evidence, Verdict, JudgeReport
  services/judge_service.py   judge_rules_bank(...), judge_openapi(...)
  cli.py                 openapi-analysis judge rulesbank|openapi <insumo>
scripts/index_specs.py   indexa as specs principais nas coleções fixas por versão
```

Dependências num extra opcional **`[judge]`** (`qdrant-3gpp-rag` editável,
`langchain-openai`, `langchain-qdrant`, `langchain-huggingface`, `qdrant-client`), para a
parte determinística continuar leve.

**Testes** sem rede: LLM e busca falsos (injeção), cobrindo a extração das partes, a
montagem de consultas/filtros, o cache e a regra "sem citação → incerto".

## 10. Ordem de execução

1. Infra: extra `[judge]`, configuração do LLM, `index_specs.py`, cópia das specs.
2. `parts.py` + testes — sem LLM, verificável já.
3. `retrieval.py` — conferir à mão que a busca de cada parte traz trechos pertinentes.
4. **Piloto no generator**, ProvMnS de 20/set, 4 partes: respostas do PATCH (4XX/5XX ×
   default), parâmetros do GET, forma do NotifyEvent, lugar do MoiChange. Revisão
   humana dos vereditos.
5. Ajustes; rodar todas as partes do generator.
6. Estender ao rulesbank.
7. Calibração e relatório.

## 11. Em aberto

- Qual versão da TS 28.532 está no corpus permanente — a coleção fixa por versão
  resolve a spec principal, mas os `$ref` externos dependem do corpus.
- Custo por execução completa (estimar no piloto).
- Tamanho da amostra de calibração.
