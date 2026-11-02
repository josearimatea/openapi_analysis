# Plano — corrigir a classificação, o juiz, a busca e o relatório

Estado em 02/nov/2026: **quase tudo aplicado, ainda sem commit**. Cada item da seção 3 está
marcado como `[feito]`, `[parcial]` ou `[falta]`, e o que falta está reunido na seção 8.
Substitui o plano de alinhamento de 29/out, já
implementado. A versão anterior, com as etapas 1–9 citadas nos docstrings do código, está
no histórico do Git (`git show 0d9487a:docs/ALIGNMENT_PLAN.md`). A história das decisões
fica em `docs/RASTREIO.md`.

## 1. De onde vem este plano

Revisei as 137 diferenças das últimas rodadas, cada uma contra os YAMLs e as fontes:

| Documento | Spec / oficial | Prompt | Diferenças | Iguais | Só muda o rótulo | Muda certo/errado |
|---|---|---|---|---|---|---|
| ProvMnS 28/08 | i00 / v17.5.0 | `judge-v15` | 120 | 107 | 6 | 7 |
| PerfMnS 23/08 | i00 / v17.1.0 | `judge-v13` | 17 | 15 | 2 | 0 |

A revisão está em `data/outputs/reviews/2026-11-02_revisao_vereditos.md` (pasta ignorada
pelo Git) e ainda é provisória: só vira gabarito depois da revisão humana.

A auditoria da evidência mostrou que o problema principal é o prompt, não a busca: nos
erros de `required`, o trecho decisivo chegou ao juiz e ele parou no `M`.

## 2. Regras decididas

**Classificação, pelo lugar da diferença:**

| Onde está | Vereditos possíveis |
|---|---|
| Nos dois, mas diferente | equivalente, melhoria ou errado |
| Só no gerado | melhoria, extra útil ou extra errado |
| Só no oficial | faltando |

- Melhoria exige que a spec ou a referência peça o que o gerado fez. A OpenAPI permitir algo
  só mostra que é válido.
- Prosa nunca é erro nem melhoria. Prosa só no oficial é contada à parte, fora da
  porcentagem; o resto do bloco é julgado normalmente.
- **`required` a mais:** é erro quando rejeita uma mensagem que a spec aceita. Quando não
  rejeita nada que ela aceite, é extra útil. `M` sozinho não decide: é requisito de suporte
  para o produtor (TS 32.156 cl. 6; TS 32.160 6.1.10).

## 3. O que mudar

### A. Classificação (juiz e contagem)

- **A1.** `[feito]` Nova opção `useful`. O que só existe no gerado nunca é equivalente.
- **A2.** `[feito]` Melhoria em extra conta como melhoria, não como extra útil (ex.: 204 e
  `scope` do DELETE).
- **A3.** `[feito]` Prosa só no oficial ganha contagem separada, abaixo da visão do oficial.
- **A4.** `[feito]` Prosa só no gerado é extra útil.

### B. Comparador

- **B1.** `[feito]` `Resource.oneOf`: comparar o ramo genérico com a raiz, campo a campo. Eram
  17 faltando, e só os 9 `$ref` de NRM faltam de fato.
- **B2.** `[feito]` Callback × path: comparar a operação do callback com a do path. Eram 5
  faltando, e 4 existem no path.
- **B3.** `[feito]` `responses` desse path: com o B2, os campos contam nas linhas de dentro do
  bloco. O veredito da linha do bloco ainda varia, sem efeito na nota (seção 8).
- **B4.** `[feito]` `$ref` trocado por `type` no mesmo campo é uma única diferença, não
  "faltando" mais "extra" (ex.: `MoiChange.path`).

### C. Prompt do juiz

- **C1.** `[feito]` Regra fixa do `M` e do `required` (seção 2).
- **C2.** `[feito]` Regra: permitido não é melhor. Corrige os `operationId`, também por regra
  no código.
- **C3.** `[feito]` Cobertura se mede pelos códigos que a spec lista para o método, não por
  códigos que ninguém declarou. Corrige `4XX`/`5XX` do GET. No `judge-v24`, `default` trocado
  pelos códigos que a spec nomeia é melhoria.
- **C4.** `[feito]` Regras fixas da OpenAPI 3.0.1: chaves ao lado de `$ref`, parâmetro no path,
  `allOf`, `servers`. O `nullable` saiu do prompt e virou caso decidido (seção 4).
- **C5.** `[feito]` Citar a linha inteira, sem `...`, e ler a descrição antes da coluna `S`.
- **C6.** `[parcial]` Quando trechos divergem, apontar o conflito e dizer qual decide (ex.:
  `scope` no DELETE é `n/a` em uma tabela e `O` em outra). O juiz já aponta a divergência dentro
  da TS 28.532, mas não cita a TS 32.158 (seção 8).

### D. Busca

- **D1.** `[feito]` Um bloco que mudou de lugar também busca pelos nomes do path gerado.
- **D2.** `[parcial]` TS 32.158: indexada no `qdrant_3gpp_rag`, e as referências no texto já
  são consultadas, não só as de `$ref`. Reconferidos os vereditos de patch e `Scope`; no `scope`
  do DELETE, a busca não traz a 6.1.2: os trechos lidos nessa parte não citam essa cláusula
  (seção 8).
- **D3.** `[feito]` Trecho externo de Release posterior não entra, e trecho de Release anterior
  entra com aviso no relatório.

Nada do que o juiz lê é cortado; essa regra continua valendo.

### E. Relatório

- **E1.** `[feito]` Trocar `S2`, `C1` etc. pela cláusula e listar as citações em cada parte.
- **E2.** `[feito]` Corrigir o rodapé, que promete YAMLs e evidência que não estão lá.
- **E3.** `[feito]` Listas separadas de melhorias e extras úteis, com a unidade escrita
  (diferenças ou campos).
- **E4.** `[feito]` Mostrar o resumo da parte, como "1 certa, 1 errada", em vez de um rótulo
  único.
- **E5.** `[falta]` Trocar o aviso "uncalibrated" pelo acerto medido contra o gabarito. Depende
  do F1.

### F. Medição

- **F1.** `[falta]` Levar o gabarito revisado para um arquivo versionado e travá-lo em teste.
  Depende da revisão humana.
- **F2.** `[feito]` Medir a variação real do juiz, repetindo a mesma entrada. Medida com 3
  repetições na ProvMnS, com o `judge-v24`: 1,6% das diferenças variam e a nota não muda (RASTREIO).
- **F3.** `[falta]` Corrigir no RASTREIO os vereditos que foram dados como conferidos e não
  estavam certos (`PatchItem`, `required`).

## 4. Casos decididos

Três casos em que as fontes não fecham. Decisão de 02/nov/2026: **erro** nos casos 2 e 3 e
**equivalente** no caso 1.

1. **`PatchItem.value` sem `nullable`:** a OpenAPI 3.0.1 diz que `nullable` tem padrão `false`,
   mas o esquema da TS 32.158 (6.3.3) escreve `"value": {}`, igual ao gerado. Equivalente.
2. **Chaves ao lado de `$ref`** (200 do GET): a OpenAPI manda ignorá-las, então o contrato não
   muda, mas o objeto não pode ter outras chaves.
3. **Notificação como path:** neste documento o oficial usa callback e o alvo fica no
   consumidor, mas o oficial da PerfMnS usa path (`/notificationSink`).

## 5. Ordem

1. **A** — classificação e contagem, sem LLM.
2. **B** — comparador, sem LLM.
3. **C e D** — prompt e busca.
4. **E** — relatório.
5. **Teste só das partes afetadas**, contra a revisão, antes de qualquer rodada completa.
6. **F** — gabarito, rodada completa da ProvMnS, repetição sem cache e RASTREIO.

A PerfMnS só roda de novo se o teste de partes afetadas mudar algum veredito dela.

Cada etapa só avança com os testes passando. Toda contagem nova é travada em teste.

## 6. Efeito esperado (estimativas, a confirmar na rodada)

| Visão | Última rodada | Com a revisão e o comparador corrigido |
|---|---|---|
| ProvMnS, oficial | 116/177 (65,5%) | cerca de 111/164 (67,7%), sem a prosa só no oficial |
| ProvMnS, gerado | 160/291 (55,0%) | cerca de 159/291 (54,6%) |
| PerfMnS, nas duas visões | 100% | 100% |

## 7. Fora deste plano

- A ProvMnS de 20/09 (i20), até ser pedida.
- Apagar os vereditos antigos em `data/judgements/`, até haver confirmação.
- Registrar os defeitos do gerador no repositório `openapi_generator`.

## 8. O que falta na análise de YAML (a verificar depois)

Medido no `judge-v24` (RASTREIO, "variação do LLM"): ProvMnS 111/163 (68,1%) no oficial e
159/291 (54,6%) no gerado. O último relatório, `2026-11-02_18-58-59`, é do `judge-v23` e ainda
mostra 112/163.

**Decisão pendente**

- **DELETE com `scope` e corpo no `200` (9 campos):** melhoria ou indeciso. A tabela do método
  na TS 28.532 pede esses campos; a de mapeamento diz `n/a`, e a TS 32.158 diz o contrário em
  5.4, 6.1.2 e A.4.2. Como indeciso, o gerado cai para 150/291 (51,5%).

**Problemas conhecidos do juiz, sem efeito na nota**

- O juiz não cita a TS 32.158 no `scope` do DELETE, e a busca não traz a 6.1.2 para essa parte.
- `/{notificationTarget}.post.responses` varia entre erro e melhoria; o esperado é equivalente.
- O resumo de um bloco é texto livre: o aviso contra "invalid" reduz o problema, não o garante.

**A fazer**

- **F1 e E5:** gabarito versionado e travado em teste, depois da revisão humana. A revisão em
  `data/outputs/reviews/` já tem as 125 linhas atuais da ProvMnS; a PerfMnS não foi remapeada.
- **F3:** corrigir o RASTREIO.
- **Rodada completa da ProvMnS com o `judge-v24`,** quando for preciso um relatório novo.
- **PerfMnS com o `judge-v24`:** não foi repetida; só o `NotifyThresholdCrossing` foi testado,
  no `judge-v23`.
- **Travar em teste** os números finais.
- **Atualizar** `README`, `JUDGE_PLAN` (rótulo `useful`) e `CLAUDE.md`.
- **Decidir** o destino dos vereditos antigos, sem commit, em `data/judgements/`.
- **Commit** de tudo o que está aplicado, quando for pedido.

**Limites a declarar na dissertação**

- O instrumento só vê o que difere do oficial: o que falta nos dois fica invisível (ex.: `filter`
  no DELETE, que está na tabela da spec e em nenhum dos dois documentos).
- A variação foi medida com 3 repetições em um documento: não mostra casos raros (`scope` no
  DELETE variou em 1 de 5 tentativas) e não dá margem estatística.
- A TS 32.158 h60 é da Release 17 e entra com aviso: não confirmei se há versão na Release 18.
  Também não confirmei se a TS 28.623 i40 é a última da Release 18.
