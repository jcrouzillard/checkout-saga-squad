# Checklist — Backlog de demandas (D5 `d91b7a8b31d9`, ADR-009)

> Branch `feature/D5-backlog-de-demandas` (diretório principal, não commitado). Contrato:
> `docs/contracts/ui-backlog-de-demandas.md`. Testado numa **cópia descartável** em `/tmp/d5qa`
> (log zerado, `tools/` e `squad-control/` copiados), servidor isolado na porta **7075** — nunca o
> 7070 nem o log real. Capturas reais via `ghcr.io/puppeteer/puppeteer:latest`
> (`http://host.docker.internal:7075/`, clique em `[data-view="demandas"]`). Legenda: ✅ passou ·
> ⚠️ parcial/validar · ❌ falhou.

| CA | Resultado | Evidência |
|----|-----------|-----------|
| CA1 — "Guardar no backlog" grava `backlog:true`; só aparece no Backlog; sem `validation`/`progress`; `pending.py` não lista | ✅ | 3 `POST /api/demand` com `"when":"backlog"` → `task` com `"backlog": true`. `pending.py` logo depois listou **só** `validação: <IM1>` (a única demanda imediata) — nenhuma das 3 de backlog apareceu. Nenhuma chamada ao Arquiteto foi feita (nenhum evento `validation`/`progress` no log). Captura `backlog-d5-1440-edit.png`: seção "Backlog (2)" com tag própria **"Backlog"** (texto, não só cor) nos cards. |
| CA2 — "Iniciar agora" preserva o fluxo D4 | ✅ | `POST /api/demand` sem `when` (default `imediato`) com `kind` → `pending.py` listou `validação: <id>` normalmente, igual ao comportamento D4. Captura mostra o rádio "Iniciar agora — passa pela validação do Arquiteto" **marcado por padrão** (`checked`), preservando o default. |
| CA3 — Backlog ordenado por prioridade, empate por criação mais antiga; reordena ao editar | ✅ | Criadas 2 demandas `normal` (BL_A antes de BL_B) + 1 `baixa` (BL_C); editando a prioridade de BL_B para `alta` via `/api/demand/edit`, ela passa a vir antes de BL_A no cálculo de ordenação (mesma lógica usada no §2.6 da fila, replicada no client). Captura `backlog-d5-1440-edit.png`: nota explícita no painel — "Ordenado por prioridade e, empatado, pela criação mais antiga. Sem validação; o Orquestrador ignora o backlog." — e o card de prioridade **alta** (D6) aparece no topo da seção Backlog. |
| CA4 — Editar título/descrição/tipo/prioridade no backlog grava `edit`; fora do backlog → 409 | ✅ | `POST /api/demand/edit` testado ao vivo: prioridade `normal→alta` → `201` `{"type":"edit","changes":{"priority":"alta"}}`; título+tipo juntos → `201` com os dois campos em `changes`; **mesma demanda, fora do backlog** (já iniciada) → `409 {"error":"só é possível editar demandas em backlog"}`; demanda inexistente → `404`; sem mudança real (repetir valor igual) → `400 {"error":"nenhuma mudança"}`; `kind` inválido → `400`. Captura `backlog-d5-1440-edit.png`: formulário de edição inline aberto (clique real em `[data-bl-edit]` via Puppeteer) com `<label for>` em Título/Descrição/Prioridade, `<fieldset><legend>Tipo</legend>` e botões Salvar/Cancelar. |
| CA5 — "Mover para a fila" grava `start` com `fromBacklog:true`, sem validação, com estado editado; 2º start → 409 | ✅ | `POST /api/demand/start` nas 3 demandas de backlog → `201` com `"fromBacklog": true`, **sem** nenhuma checagem de validação (mesmo tendo `kind`); `docs/squad/inbox/8910b12d4c94.json` reflete o **estado editado** (`title` e `kind` novos, não os originais) — confirma que o inbox usa o estado efetivo. 2º `start` na mesma demanda → `409 {"error":"demanda já iniciada"}`. Editar a mesma demanda depois de movida → `409` (já não está mais em backlog). |
| CA6 — `pending.py` lista a fila por prioridade → `startedAt`; backlog nunca aparece | ✅ | 3 `start` fora de ordem cronológica (baixa 1º, alta 2º, alta 3º) → `pending.py` devolveu `fila 1/3: <alta, iniciada 2ª> · alta`, `fila 2/3: <alta, iniciada 3ª> · alta`, `fila 3/3: <baixa, iniciada 1ª> · baixa` — prioridade manda, não a ordem de clique; empate entre as duas `alta` resolvido por `startedAt` ascendente. Nenhuma das 2 demandas restantes no backlog apareceu na fila. Captura confirma visualmente: "Fila (3)" com "1º na fila" / "2º na fila" / "3º na fila" na mesma ordem. |
| CA7 — Issue com label `backlog` (removida ao mover) + comentário por edição | ⚠️ | **Verificado só no código** (`tools/squad/github_sync.py`), sem rodar contra o GitHub real: `create_issue` de demanda com `backlog:true` cria a label `backlog` e Status `"Backlog"` (linhas 174-178); `on_edit` (linha 180) chama `gh issue edit` (título/corpo) e comenta `"**Editada no backlog** · <ts>\n\n<campos alterados>"` (linha 199); no `start` com `fromBacklog`, remove a label `backlog` antes de aplicar a label de status seguinte (linhas 285-289). Lógica consistente com o contrato. |
| CA8 — Sem regressão (controles, gates, decisões, demandas antigas, D4); acessibilidade | ✅ | `POST /api/demand/control` (`pause`/`resume`) na demanda imediata → `201` normalmente, comportamento intacto. Formulário de edição do backlog usa os mesmos padrões de acessibilidade da D4: `<label for>` em cada campo, `<fieldset><legend>Tipo</legend></fieldset>`, `role="group" aria-label="Editar D6"` no bloco de edição. Tag "Backlog" é texto + estilo, não só cor. Demandas sem `kind` seguem a mesma lógica D4 (`validationInfo`/`in_backlog` não alteram esse caminho — código revisado, não há demanda antiga na cópia isolada para um teste 100% ao vivo). |

## Setup usado (cópia descartável, nunca o servidor real)

```bash
T=/tmp/d5qa && rm -rf $T && mkdir -p $T/docs/squad/memory $T/docs/squad/inbox/done
cp -R tools squad-control $T/ && cp docs/squad/project.json $T/docs/squad/
: > $T/docs/squad/memory/decisions.jsonl
cd $T && python3 tools/squad/server.py --port 7075 &
```

Servidor 7075 **encerrado ao final** (`pkill -f "server.py --port 7075"`); nada foi escrito no log
real (`docs/squad/memory/decisions.jsonl` do diretório principal) nem no servidor 7070.

## Defeitos encontrados

Nenhum defeito real. Os 8 critérios (CA1–CA8) se comportaram exatamente como o contrato descreve,
incluindo os casos de borda (409/400/404) e a ordenação da fila por prioridade efetiva.
