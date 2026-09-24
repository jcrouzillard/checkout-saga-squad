# Checklist QA — D16 demandas de bug (`841f9a27e64a`)

Contrato `docs/contracts/demandas-de-bug.md` (§13), ADR-019, G2-D16-3 (prioridades do QA). Worktree
`feature/D16-demandas-de-bug` @ `9abadb7`. Tudo isolado: servidor do worktree na porta 7161 com `SQUAD_ROOT_DATA`/
`SQUAD_LOG` em uma cópia temporária, Jaeger/Grafana/Prometheus e `docker compose logs` simulados
(`tests/ui/d16_simulados.py`, `tests/ui/d16-docker-simulado`). Nenhum POST ao :7070 nem ao log real; nenhum container
tocado (só `docker logs` para ler o formato real, sem gravar dados reais). Servidores derrubados ao fim.

## Execução
| Suíte | Resultado |
|---|---|
| `tests/squad/test_bugs_d16.py` (assumida pelo QA) | 38 OK |
| `tests/squad/test_bugs_d16_qa.py` (nova) | 14 testes: 9 OK + 5 `expectedFailure` = defeitos QA-D16-1..4 (viram "unexpected success" quando corrigidos) |
| `test_alertas_d14` 20 OK · `test_governanca_d14_qa` 19 OK · `test_ambiente_teste_d15` 41 OK · `test_e2e_compose_seguro_d15` 11 OK · `test_entrega_por_pr` OK | sem regressão |
| `tests/ui/d16-bugs.js` (Puppeteer em Docker) | 16/16 cenários `ok` (`tests/ui/d16-bugs-result.json`) |

## Critérios de aceite
| CA | Resultado | Evidência |
|---|---|---|
| CA-1 Compatibilidade | PASS | test_bugs_d16 T01 (byte a byte + log real copiado); na UI, demandas comuns sem mudança além do botão |
| CA-2 Evidência obrigatória | PASS | T02; UI: botão desabilitado com "gere a prévia mascarada" |
| CA-3 Produto e operação | PASS | UI: bug de produto (link + log + imagem) e de operação (só arquivos, `declaração humana`) → 201, página do bug, pastas `produto/bugs` e `operacao/bugs` (`d16-pagina-bug-*.png`) |
| CA-4 A partir de trace | PASS | UI com Jaeger simulado: serviços, spans com erro, `IllegalStateException`, `verifiedBy=jaeger-produtivo`, `01-trace` + `02-logs` gerados (`d16-previa-produto-*.png`) |
| CA-5 Só produtivo | PASS | T06 (26686/13001 → 422, host externo sem requisição) |
| CA-6 Máscara | PASS no mínimo do contrato, **com defeitos** | corpus realista `tests/squad/d16_corpus.py` (ECS 8.11 do Spring Boot, payload do outbox escapado 1x, ConsumerRecord com envelope escapado 2x, stack trace com `Address[...]`, SQL e toString com aspas simples, ProducerConfig, JDBC com credencial): 0 de 17 valores sensíveis sobram, diagnóstico (orderId, sagaId, trace_id, SKU, frames) preservado, idempotente. Defeitos QA-D16-1 (resumo extraído sem máscara no `bug.json`), QA-D16-3 (camelCase `cardCvv`/`pinCode`), QA-D16-4 (JSON inválido) |
| CA-6 prévia = arquivo gravado | PASS | API e UI: bytes do rascunho == `evidencias/<arquivo>` == servido por `/api/bug/<id>/file/…`; `preview` == 200 primeiras linhas do arquivo; sha256 confere |
| CA-7 Snapshot sem PII de rede | PASS | T06; UI: snapshot sem `client.address`/query |
| CA-8 Tipos e limites | PASS | T04 |
| CA-9 Grafana | PASS | T07 (painel e alerta simulados) |
| CA-10 Metadados de imagem | PASS | T03; UI: "metadados da imagem 1" no PNG com `tEXt` |
| CA-11 Confirmação | PASS | UI: desabilitado sem prévia, com 1 caixa e habilitado só com as 2 (`s0/s1/s2` no resultado) |
| CA-12 Nada fora do lugar | PASS | T02; log da cópia sem nenhum valor sensível do corpus |
| CA-13 Commit automático | PASS (real) | Q05: clone temporário com origin nu temporário; `gitflow.py feature-start` (CLI) com `bugs/` não rastreado → commit "Sincronização da memória da squad" com a pasta, push na develop do origin temporário; `align_memory` sem pasta `operacao/bugs` (tolerado) e depois com bug novo na develop → chega à feature |
| CA-14 GitHub | PASS | T09 (labels, sem duplicar) |
| CA-15 Triagem | PASS | T09 |
| CA-16 Reprodução antes da correção | N/A nesta demanda | processo para bugs futuros (checagem do Auditor) |
| CA-17 UI | PASS | selo BUG textual (cor `#A4262C` sobre `#FBEDED`) na lista, página e filtro `f=bugs` (`d16-filtro-bugs-*.png`); "Abrir bug a partir deste trace/painel" em Produto › Jaeger/Grafana leva a `kind=produto` com o link em foco e ausente no cartão do teste (`d16-produto-jaeger-*`, `d16-a-partir-do-trace-*`); `<img onerror>` no log e na mensagem da exceção exibidos como texto (`window.__xss` nulo) |
| CA-18 Acrescentar evidência | PASS | UI: `bug-evidence` 201, `bug.json` com item a mais e antigos idênticos (`d16-acrescentar-*`); demanda comum → 409 `nao_e_bug` |
| CA-19 Sem nova dimensão | PASS | T01 |
| 422 `segredo_no_texto` na UI | PASS | mensagem clara, fica no formulário (`d16-422-segredo-*.png`) |
| 409 `tipo_divergente` na UI | PASS com ressalva | mensagem pede nova prévia, mas diz "Não foi possível **acrescentar**" no formulário de registro (QA-D16-6) (`d16-409-tipo-*.png`) |
| Máscara por padrão comunicada ao humano | **FAIL** | a UI não diz que a máscara cobre só padrões conhecidos; `pwd`/`auth` em claro aparecem como "Nada precisou ser mascarado"; prévia de log cortada em 200 linhas sem aviso nem link para o arquivo inteiro (a linha 501 com segredo vai ao git sem ser vista) — QA-D16-5 (`d16-previa-operacao-chave-desconhecida-1440.png`, `d16-acrescentar-previa-*.png`) |
| Tempo da prévia (1 MB, linha base64) | PASS | 0,42 s pelo servidor (limite 3 s); e-mail sem retrocesso (1 MB < 1,5 s). Defeito QA-D16-2: ainda quadrático em sequência de `\` (20 KB ≈ 22 s) e de `.`/`1.1.`/domínio longo (40 KB ≈ 4–9 s) |
| Adendo pin/otp/cvv/cvc/passphrase | PASS | chave inteira, `card_pin`, `x-otp`, JSON, JSON escapado, aspas simples; `spin`, `pinned`, `otpEnabled`, `cvvRequired` preservados |
| D14 "sem-F1" falso positivo | CORRIGIDO | `tests/ui/d14-governanca.js`: `uiOnlyBad` ignora ocorrências cujo contexto está em strings de `/api/state`; na cópia do log real o regex antigo acusava `#/auditoria/eventos` (8 literais), o novo acusa 0 e detecta um `undefined`/`NaN` injetado |

## Defeitos
| Id | Dono | Sev. | Resumo | Teste |
|---|---|---|---|---|
| QA-D16-1 | orquestrador | alta | `extracted.errorSpans[].exceptionMessage`/`statusDescription` gravados em `bug.json` (git público) sem máscara | `Q06…test_resumo_extraido_no_bug_json_mascarado` |
| QA-D16-2 | orquestrador | média | regex quadráticas: `chave_valor` (`\\*` inicial sem âncora) e `_REC_START` (`(?<![\w$])[\w$.]*`); prévia prende `bugs.LOCK` | `Q03…barras…`, `Q03…pontos…` |
| QA-D16-3 | orquestrador | média | `cardCvv`, `cardPin`, `pinCode`, `otpCode` (camelCase) sem máscara; `pwd`, `auth` também | `Q04…camel_case…` |
| QA-D16-4 | orquestrador | baixa | `customerName=\"…\"` sem aspas consome o fim da string JSON (JSON inválido, sem vazamento) | `Q01…nome_sem_aspas…` |
| QA-D16-5 | frontend | média | UI não comunica máscara por padrão; prévia de log truncada em 200 linhas sem aviso/link | `d16-bugs.js` (`clarity`, `previaLonga`) |
| QA-D16-6 | frontend | baixa | 409 no Registrar bug diz "acrescentar" | `d16-bugs.js` (`verboAcrescentar`) |

## Como rodar
`python3 tests/squad/test_bugs_d16.py && python3 tests/squad/test_bugs_d16_qa.py`; fluxo de UI: cabeçalho de
`tests/ui/d16-bugs.js`.
