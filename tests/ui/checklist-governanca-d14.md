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
| S1 abrir/fechar B1–B4, A1–A3 | `test_alertas_d14.py` (17 OK) + `tests/squad/test_governanca_d14_qa.py` (17: 15 OK + 2 falhas esperadas = defeitos): B1 fecha com novo gate/OVERRIDE/cancelar/**delivered**; B2 fecha com decisão (APPROVE/**RETURN**); B3 com decisão/**cancelar**; B4 com clarification/override/cancelar, **`start` sem override não fecha**; A1 fecha com gate ≥ 70% e **cancelar**; A2 fecha com **nova atividade**; A3 com delivered/rejected/**cancelar** | ✓ |
| S2 3º RETURN | B3 `owner: humano`, `returns` volta a 0 depois do `human`; RETURN em outra chave (G3) não soma | ✓ |
| S3 62% B2 → A1 → fecha | ✓. **0,695** é baixa no servidor e no cliente (B2 aberto; 0,700 não abre nada). Texto: "B2 — confiança **70% < 70%**" e título "G2 exige sua decisão · **70%**" (servidor e fallback) | ~ D14-QA-1 |
| S4 601 × 599 s | 601 s ⇒ A2 + `sem-progresso`; 599 s ⇒ nada; ferramenta pendente 200 s ⇒ `current.long` sem A2; **3601 s ⇒ sem A2 e não "trabalhando"** (STALLED_MAX_S); 3590 s ⇒ A2 | ✓ |
| S4b precedência | run externa com pid morto há 11 min ⇒ um único A2 ("interrompido") e estado `interrompido` (não `sem-progresso`) | ✓ |
| S4c G3 APPROVE sem PR | 62% sem decisão ⇒ B2 aberto com a demanda encerrada; decisão fecha o B2. **Mas o A1 do G3 fica aberto para sempre** numa demanda encerrada | ✗ D14-QA-2 |
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
| T5 | D13 `d13-navegacao.js`: 28 rotas × 1440/390 sem erro, menu/título/usage/sem rolagem horizontal; T1–T10, DEF-1..5 e cancelar-polling ✓. D11 `d11-screenshots.js`: `#ai-usage` logo abaixo do cabeçalho (top 56 = fim do header) em 1440; alturas ≤ 72 px ≥ 600 px; foco/texto preservados. **Mas:** a faixa só atualiza a cada 15 s e, em 390 px, flutua a 94 px do topo com o cabeçalho já rolado | ✗ D14-QA-3, D14-QA-4 |

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
| Id | Dono | Severidade | Descrição / reprodução |
|---|---|---|---|
| D14-QA-1 | Orquestrador + Frontend | baixa | Confiança 0,695: `pct()` arredonda (servidor `alerts.py` e fallback `index.html`) e o texto vira "confiança 70% < 70%" / "G2 exige sua decisão · 70%". Mostrar uma casa decimal quando o valor arredondado for 70% (ex.: "69,5% < 70%"). Teste: `test_texto_da_regra_0695_nao_contraditorio` (falha esperada) |
| D14-QA-2 | Orquestrador | média | G3 APPROVE 62% sem PR → humano APPROVE: o A1 do G3 fica aberto numa demanda encerrada (a errata só abre exceção para B2). Teste: `test_g3_approve_baixa_confianca_nada_aberto_apos_decisao` (falha esperada) |
| D14-QA-3 | Orquestrador (ou Frontend) | média | Regressão da D11 CA9: `#ai-usage` atualiza só a cada 15 s. O `version` não inclui `.squad/usage/claude.json` nem os rollouts do Codex, e o `/api/state` só vem com mudança de versão. `d11-screenshots.js` focus-*: API 88% e faixa em 30% por mais de 10 s |
| D14-QA-4 | Frontend | baixa | ≤ 600 px: o cabeçalho deixa de ser sticky, mas `.ai-usage` segue `top: var(--hdr-h)` (94 px). Ao rolar, a faixa flutua a 94 px e o conteúdo aparece por cima dela (`d11-real-execucoes-scroll-390.png`). Sugestão: `top: 0` quando o header não for sticky |

Veredito QA: CA-S, CA-U, CA-I, T1–T4 da D14 cumpridos. 2 defeitos médios (QA-2, QA-3) e 2 baixos. Nenhum é bloqueio de segurança.
