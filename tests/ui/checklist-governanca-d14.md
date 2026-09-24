# Checklist QA — D14 governança ao vivo, bloqueios/avisos e tema Grafite (`1e3d3c894630`)

Contrato: `docs/contracts/ui-governanca-squad-control.md` (erratas do §16) · ADR-017 · pareceres `G1-D14.json`, `G2-D14.json`.
Branch `feature/D14-tema-e-usabilidade-do-squad-control`, 2026-09-24. Legenda: ✓ passou · ✗ defeito · ~ passou com ressalva.

## Ambiente (nada tocou o log real)
- Servidores do worktree: **7127** = cópia do log/gates/inbox/runs da cópia principal + transcrições reais (só leitura);
  **7128** = cópia temporária + fixtures D15–D19 + transcrições sintéticas (D14); **7129** = cópia cortada antes da D14
  (fixtures da D13 e da D11). Tudo em `$SCRATCH/{real,w13,w14}`; derrubados ao final.
- CA-U3: um vigia no host (`watch7128.sh`) para/sobe o 7128 quando o script grava `stop`/`start` em `/work/ctl/cmd`.
- Puppeteer em Docker (`ghcr.io/puppeteer/puppeteer`, `--platform linux/amd64`), axe-core 4.10.2 injetado por `addScriptTag`.
- Os emojis dos avatares aparecem como "▯" nas capturas porque o container não tem fonte de emoji (não é defeito).

## CA-S — regras e servidor (log sintético)
| CA | Evidência | Status |
|---|---|---|
| S1 abrir/fechar B1–B4, A1–A3 | `test_alertas_d14.py` (revalidação: 20 OK) + `tests/squad/test_governanca_d14_qa.py` (revalidação: 19 = 18 OK + 1 falha esperada, D14-QA-5): B1 fecha com novo gate/OVERRIDE/cancelar/**delivered**; B2 fecha com decisão (APPROVE/**RETURN**); B3 com decisão/**cancelar**; B4 com clarification/override/cancelar, **`start` sem override não fecha**; A1 fecha com gate ≥ 70% e **cancelar**; A2 fecha com **nova atividade**; A3 com delivered/rejected/**cancelar** | ✓ |
| S2 3º RETURN | B3 `owner: humano`, `returns` volta a 0 depois do `human`; RETURN em outra chave (G3) não soma | ✓ |
| S3 62% B2 → A1 → fecha | ✓. **0,695** é baixa no servidor e no cliente (B2 aberto; 0,700 não abre nada). Revalidação: "B2 — confiança **69,5% < 70%**" e "G2 exige sua decisão · **69,5%**" no live e no modo sem F1; 62%, 70%, 90% seguem inteiros. Borda 0,6996 agora lê "69,9" no servidor, igual ao cliente | ✓ QA-1 · ✓ QA-5 |
| S4 601 × 599 s | 601 s ⇒ A2 + `sem-progresso`; 599 s ⇒ nada; ferramenta pendente 200 s ⇒ `current.long` sem A2; **3601 s ⇒ sem A2 e não "trabalhando"** (STALLED_MAX_S); 3590 s ⇒ A2 | ✓ |
| S4b precedência | run externa com pid morto há 11 min ⇒ um único A2 ("interrompido") e estado `interrompido` (não `sem-progresso`) | ✓ |
| S4c G3 APPROVE sem PR | 62% sem decisão ⇒ B2 aberto com a demanda encerrada; decisão fecha o B2 e, na revalidação, **nada fica aberto** (A1 fecha com a demanda encerrada) | ✓ QA-2 |
| S5 esperas do Orquestrador | `test_orquestrador_espera_subagente_e_humano` ✓; no navegador (7128): cartão "Aguarda: Você, Backend, Frontend — Decidir G2 (D15)" e gaveta lista cada subagente | ✓ |
| S6 desempenho/compatibilidade | 7127 (dados reais), 20 GETs `/api/live`: p50 3,0 ms, **p95 3,6 ms**, máx 15 ms, 19.675 B (≤ 64 KB), `serverMs` ≤ 5. `/api/state` mantém `now,log,gates,runs,handoffs,github,usage` + chaves novas; `log.py` sem `--step` grava o mesmo formato (teste); `thresholds.stalledMaxSeconds = 3600` em live e state | ✓ |
| S7 segredos | `ghp_…`, `sk-…`, `password=`, `token=`, `Bearer` mascarados em `recentCommands`, em `/api/live` e em `/api/state` (corpo HTTP inteiro) | ✓ |
| S8 histórico real / sem bloqueios herdados | Real: **0 bloqueios**, 1 aviso (A3 PR #104 da D12). D13 real: gates G1–G3 ≥ 77% não geram item (correto); histórico tem B4 (fechado pelo humano) e A3 PR #118 (aberto 13:46, fechado 14:01 pelo orquestrador). 21 itens no histórico, todos com `openedAt/closedAt/closedBy` | ✓ |
| Regressão | `test_entrega_por_pr.py`: todas as verificações passaram | ✓ |

## CA-U — primeira tela e tempo real (`tests/ui/d14-governanca.js`, 7128)
| CA | Evidência | Status |
|---|---|---|
| U1 (C1) | 9 rotas × 1440/390: indicador ao vivo + 3 contadores no viewport sem rolar. Painel 1440: "Sua próxima ação" (208–299 px), 2 bloqueios e 2 avisos acima de 900 px; 390: próxima ação + 1º bloqueio. `d14-primeira-tela-*.png` | ✓ |
| U2 (C2) | 10 repetições × 4 fatos, do `write` no disco até o seletor: gate RETURN → item na central **149–1.574 ms**; ferramenta começa na transcrição → "▶ Executando" no cartão **1.162–1.214 ms**; ferramenta termina → some **1.549–1.572 ms**; `progress --step` → passo no cartão **1.554–1.622 ms**. **Máximo 1.622 ms** (≤ 3 s). Caminho: 44 `/api/live`, 31 `/api/state` (só por mudança de versão) | ✓ |
| U3 | Servidor parado de verdade: "Atrasado" em **5,60 s**, "Sem conexão desde hh:mm:ss" em **15,19 s**, `#srv-down` com o que fazer, leitor de tela "Sem conexão com o servidor"; botões de decisão `disabled` com título "Sem dados atuais — reconectando". Servidor religado: "Ao vivo" em **0,18 s**, botões religados, sem recarregar | ✓ |
| U4 | Mantido pelos cenários da D13 (T9, CA-11, cancelar-polling) sob o novo polling | ✓ |
| Sem F1 | `/api/live` → 404 interceptado: modo compatível (`/api/state` a cada 3 s, 1 tentativa no live), título do indicador "modo compatível"; contadores (3 bloqueios, 3 avisos, Você 5), listas e estados dos 8 cartões **iguais** ao modo live; 10 rotas sem `undefined/NaN/[object Object]`. `d14-sem-f1-1440.png` | ✓ |

## CA-I — integrante
| CA | Evidência | Status |
|---|---|---|
| I1 | 8 cartões com estado (ícone+texto), idade, demanda·passo, ferramenta natural ("Executando: subir o order-service · 15 min · comando longo"), espera, modelo | ✓ |
| I2 | Gaveta com as 7 seções na ordem (Agora, Espera de ação, O que o humano precisa fazer, Arquivos, Comandos, Linha do tempo, Execuções anteriores); botões levam a `#/demandas/D15/gates` etc. | ✓ |
| I3 | Com B2 humano na D15: Orquestrador, Backend e Frontend com "Aguarda: Você — Decidir G2" e borda `--danger` (`d14-painel-1440.png`, `d14-demanda-1440.png`) | ✓ |

## CA-T — tema e acessibilidade
| CA | Evidência | Status |
|---|---|---|
| T1 | axe-core (wcag2a/aa/21aa/22aa) em 8 telas × claro/escuro × 1440/390 = 32 páginas: **0 violações** (inclusive `color-contrast`) | ✓ |
| T2 | "Sistema" segue `prefers-color-scheme: dark`; clique → "Claro"; após F5 o tema já é `light` no `DOMContentLoaded` (sem flash) e `sc-theme=light` | ✓ |
| T3 | Toda `.sev` tem SVG + palavra; todo `.state` tem ícone + rótulo; `prefers-reduced-motion` zera animações (l.443) | ✓ |
| T4 | Sem `#EC7000`, sem "Itaú"; paleta = tokens do contrato (o `color: "#1F3A5F"` de `AGENTS` no JS não é usado) | ✓ |
| T5 | D13 `d13-navegacao.js`: 28 rotas × 1440/390 sem erro, menu/título/usage/sem rolagem horizontal; T1–T10, DEF-1..5 e cancelar-polling ✓. D11 `d11-screenshots.js`: `#ai-usage` logo abaixo do cabeçalho (top 56 = fim do header) em 1440; alturas ≤ 72 px ≥ 600 px; foco/texto preservados. Revalidação: faixa atualiza em ≤ 1,6 s e, a 390 px rolada, fica em top 0 sem conteúdo acima | ✓ QA-3, QA-4 |

Ajustes de teste (premissas mudaram por contrato, não defeitos): `d13-navegacao.js` T9 e cancelar-polling contam
`/api/live` (12 polls em 10,5 s); T4 aceita rótulo em maiúsculas; a volta do navegador usa a 1ª demanda listada (a D13 real
já foi entregue). `d11-screenshots.js` mede `belowHeader` (top da faixa = `--hdr-h` e fim do cabeçalho fixo).

## Tarefas de usabilidade (1440 e 390; iguais nas duas larguras)
| T | Resultado | Meta | Status |
|---|---|---|---|
| T1 bloqueado? quem age? | 0 cliques; contadores + próxima ação visíveis em 1,19 s (1440) / 1,18 s (390); "Quem age: Você" em cada item | ≤ 5 s, 0 | ✓ |
| T2 o que o Backend faz? | 1 clique (cartão) → "Agora": ferramenta, alvo, 15 min, "comando longo", "Verifique o terminal" | ≤ 1 | ✓ |
| T3 Orquestrador espera? | 0 cliques (cartão já mostra "Aguarda"), 1 na gaveta (subagentes com idade) | ≤ 1 | ✓ |
| T4 decidir o gate | de `#/auditoria/eventos`: contador bloqueios → "Decidir G2" = **2 cliques até os botões**; decidir = 3º clique | ≤ 2 | ~ (2 para chegar; a decisão é o 3º) |
| T5 agente sem progresso | aviso "Backend sem progresso há 15 min" → "Ver integrante" = 1 clique; gaveta diz o que verificar | ≤ 1 | ✓ |
| T6 quem fechou o bloqueio de G2 | a D13 real nunca teve bloqueio de G2 (todos APPROVE ≥ 77%); feito com a D6: Auditoria → Alertas → filtro D6 = 3 → "B1 G2 aberto 23/09 18:38:40, fechado 20:44:56 por Auditor, evento e55853885a5c" | ≤ 3 | ✓ |

## Heurísticas de Nielsen por tela (capturas `tests/ui/d14-*-1440.png` / `-390.png`)
| Tela (captura) | H1 | H2 | H3 | H4 | H5 | H6 | H7 | H8 | H9 | H10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Barra global (`barra-global`, `sem-conexao`) | ✓ ao vivo + 3 contadores | ✓ | ✓ links `?alerta=` | ✓ mesmos ícones | — | ✓ posição fixa | ✓ | ✓ | ✓ "Rode make squad…" | ✓ legenda |
| Painel (`painel`, `painel-claro/escuro`) | ✓ | ✓ frases naturais | ✓ "Visto" (3) | ✓ `.sev`/`.state` | ✓ U3 | ✓ quem age + desde | ✓ filtro | ✓ 1 destaque | ✓ "Por quê?" (6) | ~ regra "70% < 70%" (QA-1) |
| Demanda (`demanda`) | ✓ faixa da demanda | ✓ | ✓ trilha | ✓ | ✓ nota + "Seguir mesmo assim" outline | ✓ cartões ativos | ✓ âncoras | ✓ | ✓ parecer | ✓ |
| Squad + gaveta (`squad`, `gaveta-*`) | ✓ | ✓ rótulos naturais | ✓ Fechar/Esc (D13 T10) | ✓ mesmo cartão | — | ✓ | ✓ esperas | ✓ | ✓ "comando longo"/verificar terminal | ✓ link p/ legenda |
| Demandas (`demandas`) | ✓ chip de aviso | ✓ | ✓ filtros na URL | — | — | ✓ Dn + título | ✓ | — | ✓ | — |
| Auditoria + Alertas (`auditoria-alertas`, `politicas-legenda`) | ✓ aberto/fechado | ✓ regra por extenso | ✓ URL | — | — | ✓ por quem | ✓ 3 filtros | ~ corta em 300 linhas, sem paginação | ✓ evento de origem | ✓ legenda + limites |
| Nova demanda (`nova-demanda`) | ✓ | ✓ tipos | ✓ | — | ✓ obrigatórios | — | — | — | ✓ | ✓ |

## Defeitos
| Id | Dono | Severidade | Descrição / reprodução | Situação |
|---|---|---|---|---|
| D14-QA-1 | Orquestrador + Frontend | baixa | Confiança 0,695 aparecia como "70% < 70%" | **corrigido** (e33a092 + 608aeaf) |
| D14-QA-2 | Orquestrador | média | A1 do G3 ficava aberto numa demanda encerrada | **corrigido** (e33a092) |
| D14-QA-3 | Orquestrador | média | `#ai-usage` só atualizava a cada 15 s | **corrigido** (e33a092: consumo na `version`) |
| D14-QA-4 | Frontend | baixa | A 390 px a faixa flutuava a 94 px com conteúdo por cima | **corrigido** (608aeaf: `--hdr-stick: 0px`) |
| D14-QA-5 | Orquestrador | baixa | `alerts.pct_text` usa `:.1f` (arredonda): 0,6996 lê "confiança 70,0% < 70%" no servidor, enquanto o front trunca e mostra "69,9%". Só afeta [0,6995; 0,7). Trocar por truncamento como no front. Teste: `test_pct_text_06996_nao_vira_70` | **corrigido** (0e31c1c: trunca, 0,6996 → "69,9") |
| D14-QA-6 | Frontend | média | Regressão do 608aeaf: `recoHtml` usa o texto de `pct()` (que já traz "%") no estilo da barra: `style="width:62%%"` é CSS inválido e a barra "RECOMENDAÇÃO DO AUDITOR" fica **cheia (100%) para qualquer confiança** (62% e 69,5% medidos). Usar o número (`g.confidence * 100`) na largura. `d14-governanca.js` cenário `pct-reco`; `d14-reco-barra-1440.png` | **corrigido** (66344b6: largura pelo número) |

## Revalidação (2026-09-24, após e33a092 e 608aeaf)
Ambiente limpo em `$SCRATCH/rv14`: **7141** = cópia do log/gates/inbox/runs da cópia principal (só leitura, POSTs abortados);
**7142** = cópia + fixtures D15–D19 da D14 (vigia de stop/start para CA-U3); **7143** = cópia reaproveitada da D13/D11
(`w13`, snapshot do Claude e rollout do Codex de teste); **7144** = cópia cortada antes da D14 real para o `d13-navegacao.js`
(a `w13` já tinha as fixtures D17/OVERRIDE consumidas pela rodada anterior, o que fazia T2-sino-390 e T6-1440 não acharem o botão:
estado da cópia, não defeito). Todos derrubados ao final; 7070 intocado.

| Defeito | Evidência | Status |
|---|---|---|
| QA-1 | Servidor: regra "B2 — confiança 69,5% < 70% …", título "G2 exige sua decisão · 69,5%"; `pct_text` inteiro para 0,62/0,70/0,90/0,694. Navegador (live e sem F1, D17): mesmas frases; gates "69,5% confiança"; D15 "62%" | ✓ |
| QA-2 | `test_g3_approve_baixa_confianca_nada_aberto_apos_decisao` passa sem `expectedFailure` (nada aberto após G3 APPROVE 62% + decisão humana) | ✓ |
| QA-3 | `/api/live` 7143: `version` estável sem mudança, estável quando só `collectedAt` muda, muda quando o percentual muda. Navegador (`d11-screenshots.js` foco-*): do write do snapshot até o medidor do Claude mostrar o valor: **772 / 1.568 / 1.535 ms** (1440) e **796 / 1.586 / 1.545 ms** (390) — ≤ 3 s; foco e texto digitado preservados | ✓ |
| QA-4 | `d11-screenshots.js` real × 6 telas roladas: 390 px ⇒ faixa em top 0 (`--hdr-stick` 0), `contentAbove` vazio; 1440 ⇒ top 56 = fim do cabeçalho fixo, `contentAbove` vazio; sem rolagem horizontal (`d11-real-*-scroll-390.png`) | ✓ |
| Suítes | `test_governanca_d14_qa.py` 19 (18 OK + 1 falha esperada QA-5), `test_alertas_d14.py` 20 OK, `test_entrega_por_pr.py` tudo OK. `d14-governanca.js`: CA-U1 1440/390 ✓, CA-U2 máx **1.618 ms** ✓, CA-U3 atrasado 5,1 s / sem conexão 15,1 s ✓, sem F1 ✓, axe 32 páginas 0 violações ✓, T1–T6 ✓. `d13-navegacao.js` (7144): 25 cenários sem erro, T1–T10 ✓, DEF-1..5 e cancelar-polling ✓, 28 rotas × 2 larguras ✓. `d11-screenshots.js`: alturas 68–69 px ≥ 600 px ✓ | ✓ |
| Novo | `pct-reco` (novo cenário do `d14-governanca.js`): barra da recomendação com `width:62%%` e 100% de largura | ✗ D14-QA-6 |

Capturas regeneradas: `d14-*`, `d13-*`, `d11-*` e a nova `d14-reco-barra-1440.png`.

Veredito QA (revalidação): QA-1..QA-4 corrigidos e verificados; sem regressão nas suítes D11/D13/D14. Dois defeitos novos:
D14-QA-6 (média, Frontend — barra de confiança sempre cheia, regressão do 608aeaf) e D14-QA-5 (baixa, Orquestrador — borda 0,6996).
Nenhum é de segurança.

## Checagem final (2026-09-24, após 0e31c1c e 66344b6)
Ambiente: `$SCRATCH/rv14c`, **7151** = cópia nova do log/gates/inbox/runs da cópia principal + fixtures da D14 + transcrições
sintéticas, com vigia de stop/start para CA-U3; derrubado ao final; 7070 intocado. O `d14-governanca.js` agora **resolve o código
Dn de cada fixture pela ordem dos `task` do humano** (mesma regra de `demand_codes`), em vez de fixar D15/D17 nas rotas e na
regra de 69,5% — a cópia do log pode ter mais ou menos demandas reais (resultado `codigos` na saída).

| Defeito / suíte | Evidência | Status |
|---|---|---|
| QA-5 | `test_pct_text_06996_nao_vira_70` passa **sem** `expectedFailure` (`pct_text(0.6996)` ≠ "70"/"70,0"); 0,62/0,70/0,694/0,695 sem mudança | ✓ |
| QA-6 | `pct-reco`: D15 `style="width:62%"`, largura medida **62,0%**, texto "62% confiança"; D17 `style="width:69.5%"`, largura **69,5%**, texto "69,5% confiança". `d14-reco-barra-1440.png` regenerada (barra parcial) | ✓ |
| Python | `test_governanca_d14_qa.py` **19 OK** (sem falhas esperadas), `test_alertas_d14.py` **20 OK**, `test_entrega_por_pr.py` tudo OK | ✓ |
| `d14-governanca.js` completo | 0 erros de console; CA-U1 1440/390 ✓; CA-U2 máx **1.620 ms** (43 `/api/live`, 31 `/api/state`) ✓; CA-U3 atrasado 5,64 s / sem conexão 15,27 s / volta 0,46 s ✓; sem F1 ✓ (regra "B2 — confiança 69,5% < 70%"); axe 32 páginas 0 violações, tema T2 ✓; T1–T6 iguais em 1440/390 (T2 1, T3 1, T4 2, T5 1, T6 3 cliques); `.sev`/`.state` sem cor pura ✓ | ✓ |

Capturas `d14-*` regeneradas. Veredito QA final: D14-QA-1..QA-6 corrigidos e verificados; sem regressão; nenhum defeito aberto.
