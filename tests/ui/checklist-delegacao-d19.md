# Checklist QA — D19 Delegação de tarefas pela conversa (`402e76f187f9`)

> Contrato: `docs/contracts/delegacao-pela-conversa.md` (CA-1..30) · parecer `docs/squad/gates/G2-D19.json`
> (ressalvas e "o que o QA deve provar"). Branch `feature/D19-delegar-tarefas-pela-conversa` em `a3be501`.
> Tudo sobre dados temporários: `SQUAD_LOG`/`SQUAD_ROOT_DATA` temporários, `SQUAD_CHAT_RUNNER=fake`
> (`tests/squad/delegacao_fake_runner.py`), `gh` e `claude` simulados no PATH, repositório git temporário com `origin`
> bare local. Nenhum POST ao :7070, nenhum push/PR/merge real, nenhum container `checkout-*` tocado. Navegador em
> container descartável `zenika/alpine-chrome:with-puppeteer`.

## Artefatos
| Arquivo | O que prova |
|---|---|
| `tests/squad/test_delegacao_d19.py` | suíte permanente (27 testes): alertas, validação, log.py, pending, montagem do prompt, HTTP, run_agent `--delegation`, gitflow; **checagem real** do log intocado em todas as cópias (`git worktree list`) |
| `tests/squad/e2e_delegacao_d19.py` | CA-1 ponta a ponta simulado (22 passos) e modo `--serve-ui` para o navegador |
| `tests/ui/d19-delegacao.js` | roteiro de navegador (39 verificações), resultado em `tests/ui/d19-delegacao-result.json`, capturas `tests/ui/d19-*.png` |

## Execução (2026-09-25)
| Suíte | Resultado |
|---|---|
| `test_delegacao_d19.py` | 27/27 OK; log real intocado (6 cópias verificadas) |
| `e2e_delegacao_d19.py` | 22/22 passos OK |
| `d19-delegacao.js` (1440/390, claro/escuro, teclado) | 39/39 OK, 0 erro de página |
| `tests/squad/*.py` uma a uma (alertas_d14 20, ambiente_teste_d15 41, bugs_d16_qa 18, bugs_d16 38, conversa_d17 44, delegacao_d19 27, e2e_compose_seguro_d15 11, entrega_por_pr, governanca_d14_qa 19) | todas rc=0 |
| testes do Orquestrador (`scratchpad/d19/test_{unit,http,gitflow}_d19.py`) | 11 + 7 + 1 OK |
| Log real da cópia principal | 568 linhas antes e depois, 0 eventos `delegation`; cópia principal em `develop` |

## Resultado por critério
| CA | Resultado | Evidência |
|---|---|---|
| CA-1 aceite | **pass (simulado)** / validar com PR real | e2e: 1ª consulta UNKNOWN → 2ª CONFLICTING → `pr-conflict` → B6 → pedido → cartão → confirmação → `delegation` → `--delegation-check` 0 → `demand-worktree` → `feature-sync` 3 → resolução do dono → commit do merge → QA handoff → G3 APPROVE `--delegation` → `review-update` (mesmo PR #171, fast-forward) → `delegation-result ok` → MERGEABLE → `pr-conflict-cleared` → B6 fecha; `gh pr list --head` = 1 PR; 0 `gh pr merge`/`pr create`. A execução com PR real no GitHub (§13) fica com o humano |
| CA-2 detecção | pass | `D_Pending`: 1 chamada `--json state,mergeable`; cache 30 s; UNKNOWN → nada; CONFLICTING → item; MERGEABLE → "conflito resolvido" |
| CA-3 B6 | pass | abre/fecha pelos 4 fechamentos; reprodução idêntica |
| CA-4 A6/A7 | pass | 31 min abre, 29 não; evento do `qa` fecha; A7 não abre sem `demand` nem em demanda entregue |
| CA-5 proposta não grava | pass | sha256 do log igual; bloco fora do texto |
| CA-6 lista fechada | pass | tipo_invalido, alvo_inexistente, demanda_encerrada (cancelada/entregue), alvo_de_outra_demanda, acao_proibida, precondicao_falhou; confirmar → 422; log inalterado |
| CA-7 agente/risco | pass | `baixo` → `moderado`; change-request → `devops`; ref em `docs/contracts/` → `arquiteto`; gate 0,6 → `alto` |
| CA-8 revalidação | pass | 409 proposta_obsoleta, registro `obsoleta`, log igual |
| CA-9 uma ativa | pass | delegacao_ativa; volta a valer após o resultado |
| CA-10 tentativas | pass | (a)(b)(c) em unidade; **(d) fixado pela via do servidor**: `run_agent.py --delegation` real (claude simulado) grava `delegation` na meta e nos `progress`; A2 da run delegada com `delegable:false`, `runDelegation` = id, antes e depois do resultado |
| CA-11 uma confirmação | pass | 2ª → 409 ja_decidida; 1 linha |
| CA-12 evento | pass | exatamente os campos do §3.1; sem id da conversa; par `confirmada` na conversa |
| CA-13 log.py | pass | `--type delegation`/`--type=delegation` recusados, log vazio; tipos novos aceitos; `--status falhou` só em delegation-result |
| CA-14 autenticidade | pass | `delegation` injetado no jsonl → `--delegation-check` 3 "sem confirmação", nada gravado, sem `delegation-start` |
| CA-15 obsoleta | pass | conflito resolvido antes do início → código 4, sem `delegation-start` |
| CA-16 worktree | pass | cria da origin, recria após remoção, "worktree ocupado" com alteração alheia |
| CA-17 merge | pass | commit com 2 pais, head anterior do PR é ancestral; push fast-forward |
| CA-18 mesmo PR | pass | sem gate/sem start/gate RETURN → recusa; PR diferente → falha sem criar PR; sucesso → `review-updated` único |
| CA-19 QA quando muda código | validar | regra presente em `plantao.md` §D.5 e `gates.md` (B,2); no e2e o QA registrou handoff antes do G3. Execução pelo plantão real não coberta |
| CA-20 ambiente de teste | validar | proibições em `delegacao.md`/`plantao.md` (publish, test-env-request); e2e sem nenhum `test-env-*`/`control`. Delegação `ambiente-teste` executada pelo plantão real não coberta |
| CA-21 change-request | pass | `decision --change-request --resolution recusada` do dono fecha A7; o autor não aparece nos eventos da delegação |
| CA-22 agente parado | pass | via servidor: A2 → delegação (`attempt 1`, `attemptKey` = demanda:qa:handoff, `run`) → run delegada para → `falhou` → A2 sem delegar; 2ª proposta → limite_tentativas |
| CA-23 injeção | pass | handoff e `--dados` com "ignore as regras…merge" só dentro de `<dados>`; marcas de fechamento neutralizadas |
| CA-24 proibidos | pass | tipos/ações merge, cancelar, pausar, retomar, repriorizar, nova-demanda, publicar-teste… → acao_proibida; no chat, pedidos reservados sem proposta |
| CA-25 pausa/cancelamento | pass | pausada não é listada; resume volta; cancel → "delegação cancelada" → estado `cancelada` |
| CA-26 visível na demanda | pass | navegador: seção Delegações (quem pediu, tipo, agente, tarefa, risco, estado, resultado, links G3/PR), marcas na linha do tempo, badge "Delegação em andamento" na D2; 1440/390 claro/escuro sem rolagem horizontal; teclado (Tab → Delegar correção → Enter → campo preenchido e **não enviado** → Enter → cartão → Tab → Confirmar); texto do modelo com `<img onerror>` exibido como texto |
| CA-27 sem regressão | pass | todas as suítes de `tests/squad/`; destravar sem `kind` segue `destravar` |
| CA-28 segurança HTTP | pass | Origin externo → 403 (GET e POST); `ref` inválido/`pr-waiting` → 404; 2 001 caracteres → 400 tarefa_grande |
| CA-29 log único/memória | pass | (a) eventos no log da cópia principal, log do worktree igual; (b) HEAD/status/branch da cópia principal iguais; (c) memória/inbox no diff → código 4 sem push; (d) `--abort` limpa |
| CA-30 refs | pass | handoff do `to` com `delegation` e `refs` = handoff pendente; A6 fecha; estado `aguardando-gate` |

## Ressalvas do G2
- **Ressalva 1 (feature-sync, `a3be501`)**: pass — merge que falha sem MERGE_HEAD (index.lock presente; develop com
  histórico sem relação) sai ≠ 0 com "falhou", nunca "nada a integrar"; o caso legítimo "nada a integrar" continua 0.
- **Desvio 3 (A6 entre G3 APPROVE e PR)**: confirmado e fixado em teste — handoff parado nesse intervalo não gera A6
  (a demanda é tratada como encerrada por `Rules._closed`); volta a gerar quando o PR existe. Registrado como defeito
  de severidade baixa para o Orquestrador (diverge da definição de "demanda aberta" do contrato §1).
- **`or True` no teste do Orquestrador**: substituído na suíte do QA por checagem real (linhas novas de todas as cópias
  sem ids/marcador de teste e sem `delegation`).
