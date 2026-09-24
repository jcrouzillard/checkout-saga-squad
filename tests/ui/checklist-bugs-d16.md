# Checklist QA — D16 demandas de bug (`841f9a27e64a`)

Contrato `docs/contracts/demandas-de-bug.md` (§13), ADR-019, G2-D16-3 (prioridades do QA). Worktree
`feature/D16-demandas-de-bug` @ `9abadb7` (revalidação @ `e565020`). Tudo isolado: servidor do worktree na porta 7161 com `SQUAD_ROOT_DATA`/
`SQUAD_LOG` em uma cópia temporária, Jaeger/Grafana/Prometheus e `docker compose logs` simulados
(`tests/ui/d16_simulados.py`, `tests/ui/d16-docker-simulado`). Nenhum POST ao :7070 nem ao log real; nenhum container
tocado (só `docker logs` para ler o formato real, sem gravar dados reais). Servidores derrubados ao fim.

## Execução
| Suíte | Resultado |
|---|---|
| `tests/squad/test_bugs_d16.py` (assumida pelo QA) | 38 OK |
| `tests/squad/test_bugs_d16_qa.py` (nova) | 18 OK na revalidação (antes: 9 OK + 5 `expectedFailure` = QA-D16-1..4) |
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
| Id | Dono | Sev. | Resumo | Teste | Situação |
|---|---|---|---|---|---|
| QA-D16-1 | orquestrador | alta | `extracted.errorSpans[].exceptionMessage`/`statusDescription` gravados em `bug.json` (git público) sem máscara | `Q06…resumo_extraido…`, `Q07…painel_e_alerta…` | **corrigido** (e565020) |
| QA-D16-2 | orquestrador | média | regex quadráticas (`chave_valor`, `_REC_START`); prévia prendia `bugs.LOCK` | `Q03…barras…`, `Q03…pontos…`, `Q07…1mb` | **corrigido** (e565020) |
| QA-D16-3 | orquestrador | média | `cardCvv`, `cardPin`, `pinCode`, `otpCode`, `pwd`, `auth` sem máscara | `Q04…camel_case…`, `Q07…camel_case…` | **corrigido** (e565020) |
| QA-D16-4 | orquestrador | baixa | `customerName=\"…\"` consumia o fim da string JSON | `Q01…nome_sem_aspas…`, `Q01…linhas_json…` (sem exceção de linha) | **corrigido** (e565020) |
| QA-D16-5 | frontend | média | UI não comunicava máscara por padrão; prévia truncada sem aviso/link | `d16-bugs.js` (`produto-*`, `operacao`, `acrescentar-*`) | **corrigido** (6ec999a) |
| QA-D16-6 | frontend | baixa | 409 no Registrar bug dizia "acrescentar" | `d16-bugs.js` (`409-*`) | **corrigido** (6ec999a) |
| QA-D16-7 | orquestrador | baixa | chaves `pass`, `passcode`, `db.pass`, `mysqlPass` e `"auth":{"pass":…,"key":…}` não são mascaradas (fora do mínimo do §8.2; o aviso da UI cobre) | reval (scratchpad) | novo, aberto |
| QA-D16-8 | frontend | baixa (recomendação) | com prévia truncada, o botão habilita só com as 2 caixas, sem abrir o arquivo inteiro; sugerido exigir abrir "Ver o arquivo inteiro" antes | `d16-bugs.js` (`exigeLeitura`) | recomendação, aberto |

## Revalidação após as correções (e565020 Orquestrador, 6ec999a Frontend)
| Item | Resultado | Evidência |
|---|---|---|
| Suítes `tests/squad/` | PASS | `test_bugs_d16_qa` 18 OK (5 `expectedFailure` removidos + 4 novos em `Q07`), `test_bugs_d16` 38 OK, `test_alertas_d14` 20, `test_governanca_d14_qa` 19, `test_ambiente_teste_d15` 41, `test_e2e_compose_seguro_d15` 11, `test_entrega_por_pr` OK |
| QA-D16-1 | PASS | trace com e-mail/token no `operationName`, `customerName=` numa tag de correlação, e-mail+senha no `status_description`, `Address[...]`+CPF+senha+e-mail na exceção: nada sobra na resposta do rascunho, `bug.json`, `GET /api/bug/<id>`, evidências e log; painel (título/expr) e alerta (título/expr) também mascarados |
| QA-D16-2 | PASS | `mask_text`: `\` 20 KB 0,01 s / 1 MB 0,5 s; `.` 40 KB 0,01 s / 1 MB 0,35 s; `1.1.` 1 MB 0,31 s; domínio 1 MB 0,29 s; `Address[` 1 MB 0,42 s; `\"`, `customerName=\"`, `{"auth":` 1 MB ≤ 0,6 s. Concorrência: rascunho com trace lento (3 s) + log de 1 MB (3,5 s no total) e, durante ele, 3 rascunhos pequenos + GET do arquivo em ≤ 0,02 s; outro rascunho durante a confirmação de 1 MB em 0,25 s |
| QA-D16-3 | PASS | `cardCvv`/`cardPin`/`pinCode`/`otpCode`/`pwd`/`userPwd`/`DB_PWD`/`auth`/`x-auth`/`spring.auth`/`cvv_number` mascarados; `spin`/`author`/`authorId`/`authority`/`authType`/`oauth2Client`/`PWD=/home/app`/`OLDPWD=/tmp`/`pinCount`/`authenticated`/`otpauth`/`checkpoint` preservados |
| QA-D16-4 | PASS | as 10 linhas do corpus continuam JSON válido após a máscara |
| Efeitos colaterais | aceitáveis | `"auth":{...}`: campos internos com palavra-chave são mascarados e o JSON continua válido — mas `pass`/`key` internos passam (QA-D16-7, baixa, não é regressão: antes `auth` não era chave); `mapPin=1`/`dropPin=5` mascarados a mais (lado seguro). Ressalva: `pwd`/`userPwd` com valor começando por `/` não são mascarados (troca consciente por `PWD=/caminho`) |
| QA-D16-5 | PASS | UI 1440/390: aviso "A máscara é automática e reconhece apenas padrões conhecidos…" na prévia; contagem "Nenhum padrão conhecido encontrado — revise o conteúdo" quando nada é mascarado; log de 501 linhas → "Mostrando 200 de 501 linhas…", "Ver o arquivo inteiro (mascarado, 501 linhas)" com a linha 501 `senha=[MASCARADO:segredo]` idêntica ao servidor, e link "Abrir o arquivo inteiro (mascarado)" (`d16-acrescentar-previa-*.png`) |
| QA-D16-6 | PASS | 409: "Não foi possível registrar o bug (409): o tipo informado (operacao) diverge do rascunho (produto): gere a prévia de novo com o tipo correto." (`d16-409-tipo-*.png`) |
| Corpus completo | PASS | enviado e gerado do link (01-trace + 02-logs): arquivo gravado == rascunho (bytes e sha256), prévia == 200 primeiras linhas, 0 de 17 valores sensíveis no arquivo, `bug.json` e log; diagnóstico preservado |
| Fluxo de UI | 16/16 `ok`, 0 erros JS | `tests/ui/d16-bugs-result.json` (condições de QA-D16-5/6 agora exigidas no `ok`) |

## Como rodar
`python3 tests/squad/test_bugs_d16.py && python3 tests/squad/test_bugs_d16_qa.py`; fluxo de UI: cabeçalho de
`tests/ui/d16-bugs.js`.
