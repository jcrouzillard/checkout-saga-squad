# Checklist QA — D18 ambiente e versão do Squad Control (`b72a6bd8caf3`)

Contrato: `docs/contracts/ui-ambiente-e-versao.md` (CA1–CA20) · ressalvas: `docs/squad/gates/G2-D18.json` (QA-1..QA-3).
Código validado: `feature/D18-ambiente-e-versao-no-squad-control` @ `97495c5` (servidor do worktree na porta 7288, dados
copiados para o scratchpad; nada no :7070 nem no log real). Data: 2026-09-24.

## Evidências
| Item | Arquivo | Resultado |
|---|---|---|
| Unitários + contrato HTTP | `tests/squad/test_instancia_d18.py` (porte de `scratchpad/d18/test_instance.py` + classe `ContratoHTTP`) | 18/18 OK |
| Navegador (CA15–CA19) | `tests/ui/d18-ambiente-versao.js` → `tests/ui/d18-ambiente-versao-result.json`, capturas `tests/ui/d18-*.png` | 28/28 OK; axe 0 violações em 14 execuções |
| QA-1 (d14 instável) | `tests/squad/test_alertas_d14.py`: `SQUAD_TESTENV_PROBE=0` e `SQUAD_TESTENV_SPAWN=0` no topo do módulo (como as suítes D15) | 20/20 OK em 5 execuções seguidas (antes: 1 falha em 3/3) |
| Regressão `tests/squad/` (uma a uma) | d14 20 · d15 41 · d16_qa 18 · d16 38 · e2e_compose_seguro_d15 11 · entrega_por_pr (todas PASS) · governanca_d14_qa 19 · instancia_d18 18 | todas verdes |

Causa do QA-1: `version` do `/api/state` e do `/api/live` inclui `repr(TE_PROBE.health)`; a sonda do testenv roda em
segundo plano e terminava entre as duas chamadas, e a criação preguiçosa de `server.INSTANCE` (git) no 1º `/api/state`
alargou a janela. Corrigido só no teste; o produto não mudou.

Navegador: `zenika/alpine-chrome:with-puppeteer` (arm64 nativo; a imagem `ghcr.io/puppeteer/puppeteer` é amd64 e fica
lenta demais emulada), container `--rm`. axe-core de `scratchpad/axe.min.js` montado no container, escopo nos selos e no
painel (fechado, aberto, servidor antigo; claro e escuro; 1440/1280/390).

## Resultado por CA
| CA | Como | Resultado |
|---|---|---|
| CA1 | `test_ca1_produtivo` (principal em develop, 7070, dados próprios → produtivo/inferido) | PASSA |
| CA2 | `test_ca2_*` (worktree em 7070 e 7281 → teste; `reason` cita worktree e porta) + HTTP: servidor do worktree em porta efêmera → `teste`, `reason` com a porta real; tela: "worktree plankton-d18, porta 7288" | PASSA |
| CA3 | `test_ca3_*` (principal em outra porta; `SQUAD_ROOT_DATA` ou `SQUAD_LOG` de fora → teste) | PASSA |
| CA4 | `test_ca4_squad_env` (" produtivo " aparado → produtivo/SQUAD_ENV; "xyz" e "Produtivo" → desconhecido, `valor inválido: xyz`) | PASSA |
| CA5 | `test_ca5_sem_git` (fora de repositório e PATH sem git → desconhecido/indeterminado; display "sem tag · 1.1.0-SNAPSHOT · commit ?") | PASSA |
| CA6 | `test_ca6_r4_*` (dados ou log na principal → `dataIsMain`) + tela `estado-dadosprod` ("dados do produtivo" no selo, no aria-label e no painel) | PASSA |
| CA7 | `test_ca7_8_9_versao` (v1.2.0 fora da história, sem rc), `test_ca7_sem_tags_e_destacado`, `test_r6_so_prerelease`, repositório real (v1.0.0) | PASSA |
| CA8 | pom sintético com `<parent>` 3.4.5 → 1.1.0-SNAPSHOT; repositório real idem | PASSA |
| CA9 | `display` exato com U+00B7; tela mostra `v1.0.0 · 1.1.0-SNAPSHOT · 97495c5` | PASSA |
| CA10 | commit só em `docs/squad/memory` → `atual`, `changedPaths=0` | PASSA |
| CA11 | commit em `squad-control/` → `desatualizado`, `changedPaths ≥ 1`; tela `estado-stale`: texto de reinício no rodapé, "⚠" no compacto, aria "Desatualizado, reinicie" | PASSA |
| CA12 | modificado em `squad-control/` → `dirty` e " +alterações"; só em memória → `dirty=false`; tela `estado-dirty` | PASSA |
| CA13 | HTTP: 5× `/api/live` → **0 subprocessos** (qualquer comando, Popen espionado); chaves e headers do `/api/live` iguais aos anteriores; `/api/live` não cria `INSTANCE`; 5× `/api/instance` na janela → 0 git; `test_ca13_r2_*`: 1 `rev-parse` + 1 `status` por janela de 30 s, `diff` só em HEAD novo. Navegador: 0 chamadas a `/api/instance` em 6 s (fora do ciclo de 1,5 s) | PASSA (ver obs. 1) |
| CA14 | HTTP: chaves de `/api/state` = anteriores (`now, log, gates, runs, handoffs, github, usage, version, thresholds, summary, alerts, alertsHistory, agents, serverMs, testEnv`) + `instance`; `version` igual à do `/api/live`; `/api/instance` 200, `application/json`, `Cache-Control: no-store`, igual ao `instance` do state | PASSA |
| CA15 | 1440×900 e 1280×720, `#/auditoria` (~49 000 px) rolada até o fim, claro e escuro: selo inteiro na janela no topo e no fim, acima da autoria | PASSA |
| CA16 | 390×844, claro e escuro: sem rolagem horizontal (painel, squad, auditoria, execuções, demandas); sino visível; selo compacto fixo no canto inferior esquerdo (R5, aceito no G2); 3 toasts não cobertos; controle mais baixo de 4 páginas roladas ao fim não fica sob o selo | PASSA (ver obs. 2) |
| CA17 | 1440 (`#inst-side`) e 390 (`#inst-c`), claro e escuro: Enter abre `role=dialog`, `aria-expanded=true`, foco no painel; campos da §4 todos presentes + Copiar/Fechar; Esc fecha e devolve o foco; clique fora fecha; "Fechar" devolve o foco; `aria-label` = "Ambiente: Teste. Versão v1.0.0 · 1.1.0-SNAPSHOT · 97495c5"; `title` com o display; axe sem violações | PASSA |
| CA18 | axe (inclui `color-contrast`) 0 violações nos dois temas, fechado e aberto; estado sempre por texto (TESTE/PRODUTIVO/AMBIENTE DESCONHECIDO, "⚠", frases) | PASSA |
| CA19 | `/api/instance` 404 e `/api/state` sem `instance`, 1440 e 390, claro e escuro: "AMBIENTE DESCONHECIDO · versão indisponível · ⚠ Servidor sem suporte à versão — reinicie (make squad)"; aria "…reinicie"; título `[?] `; 0 erros de JS (o console só tem o "Failed to load resource 404" do próprio navegador) | PASSA |
| CA20 | `git` que dorme 10 s no PATH → `Instance` responde em < 5 s como desconhecido | PASSA |
| Título | `[TESTE] ` em todas as rotas, sem duplicar ao navegar; produtivo sem prefixo; desconhecido `[?] ` | PASSA |
| 800 / 700 | compacto no cabeçalho; 800 mostra `TESTE 97495c5`; 700 oculta o commit (fica no aria-label e no detalhe); sino visível; sem rolagem horizontal | PASSA (desvio 4 do G2, humano confirma) |

## Defeitos e observações
- **QA-D18-1 (menor, dono: frontend)** — com `freshness.state = "indeterminado"` e dados presentes, o `aria-label` do selo
  fica "Ambiente: Teste. Versão v1.0.0 · 1.1.0-SNAPSHOT · 97495c5", sem "Não foi possível verificar a versão". O texto
  aparece no rodapé (≥ 900 px) e no painel, mas não no aria-label, e no selo compacto (< 900 px) não há indicação visível
  (nem "⚠"). Reproduzir: `/api/instance` e `state.instance` com `freshness.state="indeterminado"` →
  `tests/ui/d18-estado-indet-{1440,390}.png`, `results["estado-indet-1440"].ariaDizIndeterminado = false`. Causa:
  `instView()` em `squad-control/index.html` só acrescenta ". Desatualizado, reinicie" quando `stale`. O roteiro
  registra o campo sem reprovar.
- Obs. 1 — o contrato §3 diz "até 1 comando git extra por janela"; o código roda `rev-parse` + `status` (R3, aceito no
  G2; o Arquiteto vai atualizar o §3). O teste fixa esse comportamento (2 por janela, `diff` só em HEAD novo).
- Obs. 2 — o contrato §5/CA16 diz "compacto no cabeçalho" a 390; o selo fica fixo no canto inferior esquerdo (R5, aceito no
  G2). Com o painel aberto a 390, ele ocupa quase toda a altura (rolagem interna até Copiar/Fechar), como esperado num diálogo.
