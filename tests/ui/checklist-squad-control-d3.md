# Checklist — Emojis por papel no Squad Control (D3 `62f458c8038b`, prioridade alta)

> Branch `feature/D3-emojis-nos-agentes` (não alterada). Contrato:
> `docs/contracts/ui-squad-control-agentes.md`. Painel em `http://localhost:7070/`. Evidência via
> `grep`/leitura de código em `squad-control/index.html` e capturas reais com Chrome headless
> (`zenika/alpine-chrome`, `--network host`, `http://host.docker.internal:7070/`).
> Legenda: ✅ passou · ⚠️ parcial/validar · ❌ falhou.

| CA | Resultado | Evidência |
|----|-----------|-----------|
| CA1 — Emoji exato por papel, um por papel, sem repetição | ✅ | `AGENTS` (index.html) tem exatamente o mapa do contrato: 🎼 orquestrador, 📐 arquiteto, ⚙️ devops, 🔭 observabilidade, 🧩 backend, 🎨 frontend, 🧪 qa, 🛡️ auditor, 👤 humano — 9 emojis distintos, sem repetição. `tests/ui/squad-control-d3.png` (1440px) mostra os 8 cards da faixa "Squad ao vivo" com os emojis corretos. |
| CA2 — Mesmo emoji nos 3 lugares (card, gaveta, aba Agentes) | ⚠️ | Confirmado **por código**: `av()` (única função) é chamada nos 3 pontos — `renderSquadStrip()` (linha 264), `renderAgentes()` (linha 367) e `renderDrawer()` (linha 469) — todos lendo `AGENTS[a].emoji`, fonte única. **Sem captura**: gaveta e aba Agentes não abrem sem clique (headless não interagiu); marcado ⚠️ por falta de evidência visual, não por defeito. |
| CA3 — Emoji em elemento `aria-hidden="true"`, nome como texto, tooltips inalterados | ✅ | `av()`: `<span aria-hidden="true">${m.emoji}</span>`; nome do agente segue em `<span class="name">`/`<b>` fora do avatar nos 3 usos. `title="Ver o que X está fazendo"` no card da faixa (linha 262) e `title="${st}"` no dot preservados, sem alteração no diff. |
| CA4 — Papel desconhecido cai no fallback, sem `undefined` | ✅ | `const av = a => { const m = AGENTS[a] \|\| { ini: "?", color: "#555" }; return m.emoji ? ... : ...m.ini \|\| "?"... }` — cobre tanto chave inexistente em `AGENTS` quanto entrada sem `emoji`/`ini`; nunca produz `undefined` (revisão de código; não injetado evento `agent:"xyz"` no console ao vivo por falta de interação no headless). |
| CA5 — Layout preservado a 1440 (8 cards, nome, dot, tamanho do avatar) e sem transbordo a 390 | ✅ | `tests/ui/squad-control-d3.png` (1440px): 8 cards com nome (reticências em "Observabi…"), dot de status e avatar de tamanho uniforme. `tests/ui/squad-control-d3-390-tall.png` (390×2200, para não cortar o conteúdo): cards em grade 2 colunas, sem texto/emoji cortado horizontalmente. CSS nova é só `.av.emo` com caixa fixa (22px/32px, `overflow:hidden`) — não toca `.squad`/`.agents-grid`/media queries de 900px (confirmado no diff). Observação à parte: a página mostra uma barra de rolagem horizontal mais abaixo (seção "Evidências usadas"/feed), mas o diff do D3 não mexeu em nenhuma regra de largura — não é causado por este código (não é um defeito de D3; registrar como observação, não como defeito). |
| CA6 — Sem lib/imagem/fonte externa nova; emoji com fonte de sistema | ✅ | `git diff develop -- squad-control/index.html`: única CSS nova é `.av.emo{...font-family:"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif...}` (fontes de sistema, não carregadas via rede); nenhum `<script src>`/`<link>` novo no diff. |
| CA7 — Diff restrito a `squad-control/index.html`; resto funciona como antes | ✅ | `git diff develop --stat -- . ':!docs' ':!tests'` mostra 4 arquivos, mas só `squad-control/index.html` (+28/−14) é código de produto tocado pela implementação do D3; `.claude/agents/frontend.md`, `AGENTS.md` e `tools/squad/gitflow.py` vêm de commits **anteriores** de governança (`2900401`/`b855118`, dando ao Frontend a propriedade de `squad-control/**`), não do commit de implementação. `git show --stat c58414a` (commit "D3: emojis por papel…") confirma: só `squad-control/index.html` + `docs/squad/memory/*` (log) + a própria captura `tests/ui/squad-control-d3.png` — nenhuma API, servidor, `tools/squad/log.py` ou `decisions.jsonl` (formato) alterados. Abas/gaveta/gates continuam presentes no HTML (não há remoção de handlers). |
| CA8 — Campo `ini` mantido | ✅ | `grep -n "ini:"` mostra `ini` em todas as 9 entradas de `AGENTS`; `av()` usa `m.ini` no fallback; `ini` também usado na linha do tempo (`AGENTS[e.to]?.ini`, `AGENTS[e.agent]?.ini`, linhas 281/284) — nada removido. |

## Escopo (item extra da tarefa)

`git diff develop --stat -- . ':!docs' ':!tests'` → `squad-control/index.html` (28 linhas), mais 3 arquivos de
governança de commits anteriores ao da implementação (ver CA7). Nenhuma mudança em `services/**`, API,
`docker-compose.yml` ou `tools/squad/log.py`.

## Defeitos encontrados

Nenhum defeito real. Duas ressalvas registradas (não bloqueantes): CA2 sem captura visual (gaveta/aba não
abertas por interação) e a barra de rolagem horizontal pré-existente mais abaixo na página (não introduzida
pelo diff do D3).
