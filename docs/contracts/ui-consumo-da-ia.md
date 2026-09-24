# Contrato — Consumo da IA no Squad Control (D11, `642a73cb38e5`, tipo operação)

> Decisão: [ADR-014](../adr/014-consumo-da-ia-por-fonte-real.md). Implementação: **Orquestrador**
> (`tools/squad/server.py`, novo `tools/squad/statusline_usage.py`) e **Frontend** (`squad-control/index.html`).
> Respostas do humano: provedores **separados** (sem soma); **só fonte real** (sem estimativa por tokens);
> atualiza a cada polling; se indisponível, **último valor + alerta + hora da coleta**.

## 1. Fontes reais (verificadas nesta máquina em 2026-09-23)

| Provedor | Onde | Campos lidos | Quando se renova |
|---|---|---|---|
| Codex | `$CODEX_HOME/sessions/**/rollout-*.jsonl` (padrão `~/.codex/sessions`) — linha `{"timestamp", "type":"event_msg", "payload":{"type":"token_count","rate_limits":{…}}}` | `rate_limits.limit_id` (=`"codex"`), `primary.used_percent`, `primary.window_minutes` (=300), `primary.resets_at` (epoch s), `secondary.used_percent`, `secondary.window_minutes` (=10080), `secondary.resets_at`, `plan_type`; hora da coleta = `timestamp` da linha | a cada turno de qualquer sessão Codex (interativa ou `codex exec`) |
| Claude Code | stdin JSON da **statusline** → snapshot `<DATA_ROOT>/.squad/usage/claude.json` (gravado pelo tee, §2) | `rate_limits.five_hour.used_percentage`, `.five_hour.resets_at` (epoch s), `.seven_day.used_percentage`, `.seven_day.resets_at` | a cada redesenho da statusline de uma sessão **interativa** (`claude -p` não aciona) |

Não existe outra fonte real local para o Claude Code (transcrições sem `rate_limits`, sem cache de cabeçalhos, sem
comando de status). Codex não tem comando não interativo de status. **Nenhum** valor pode ser derivado de tokens.

Regras de leitura do Codex: considerar os 5 rollouts de maior `mtime`; em cada um, a **última** linha `token_count`
com `rate_limits` não nulo e `limit_id == "codex"` (se não houver `limit_id`, aceitar); escolher a de maior
`timestamp`. Ler só o final do arquivo (≤ 512 KiB) e cachear por `(caminho, mtime, tamanho)` — o polling é de 3 s.
Se `window_minutes` ≠ 300 / ≠ 10080, publicar mesmo assim com `windowMinutes` real (a UI rotula pela duração).

## 2. Tee de statusline do Claude Code (`tools/squad/statusline_usage.py`)
- Uso: `python3 <repo>/tools/squad/statusline_usage.py [--next "<comando da statusline do usuário>"]`.
- Lê todo o stdin; grava **atomicamente** (tmp + `rename`) em `<DATA_ROOT>/.squad/usage/claude.json`
  (`DATA_ROOT` = `$SQUAD_ROOT_DATA` ou a raiz do repo do próprio script) somente:
  `{"collectedAt": <ISO UTC>, "fiveHour": {"usedPercent", "resetsAt"}, "sevenDay": {"usedPercent", "resetsAt"}}`.
  Se o JSON não tiver `rate_limits`, **não** sobrescreve o snapshot anterior.
- Depois executa `--next` com o **mesmo stdin** e escreve a saída dele sem alteração; sem `--next`, não imprime nada
  além de uma linha vazia. Qualquer erro do tee é engolido (a statusline do usuário nunca quebra); timeout de 1 s
  para a parte do tee.
- Instalação: `--install` lê `statusLine.command` atual de `~/.claude/settings.json`, faz backup e grava
  `statusLine.command = "python3 <abs>/tools/squad/statusline_usage.py --next '<comando anterior>'"`;
  `--uninstall` restaura o anterior. Por mexer em configuração do usuário fora do repo, **só o humano** executa
  (ou autoriza) o `--install`. Idempotente: não encadeia a si mesmo duas vezes.
- Nunca grava tokens, e-mail, `session_id`, caminhos ou qualquer outro campo do JSON de entrada.

## 3. API (`tools/squad/server.py`)
Campo novo `usage` em `GET /api/state` e o mesmo objeto em `GET /api/usage`:
```json
{
  "usage": {
    "providers": [
      { "id": "claude", "label": "Claude Code", "source": "statusline", "status": "fresh",
        "available": true, "collectedAt": "2026-09-23T21:24:49Z", "reason": null,
        "fiveHour": { "usedPercent": 9.0, "remainingPercent": 91.0, "resetsAt": "2026-09-24T00:15:11Z", "windowMinutes": 300 },
        "week":     { "usedPercent": 22.0, "remainingPercent": 78.0, "resetsAt": "2026-09-27T01:39:51Z", "windowMinutes": 10080 } },
      { "id": "codex", "label": "Codex", "source": "codex-rollout", "status": "stale", "available": false,
        "collectedAt": "…", "reason": "Coleta com mais de 15 min", "plan": "plus", "fiveHour": {…}, "week": {…} }
    ]
  }
}
```
- Ordem fixa: `claude`, `codex`. Horários em ISO-8601 UTC (`resets_at` epoch → ISO). `remainingPercent = max(0, 100 − usedPercent)`.
- `status`: `fresh` (coleta há ≤ 15 min e nenhum `resetsAt` já passou) → `available: true`;
  `stale` (há valor, mas coleta > 15 min **ou** algum `resetsAt` < agora) → `available: false`, números = último valor;
  `none` (sem fonte/arquivo/campo) → `available: false`, `fiveHour`/`week`/`collectedAt` = `null`.
  `reason` curto em português explica `stale`/`none` (ex.: "Statusline não instalada", "Janela de 5 h renovada às 21:15").
- Erro de leitura de um provedor nunca derruba `/api/state` (vira `status: none`).

## 4. Tela (`squad-control/index.html`)
- Faixa `#ai-usage` no topo de `<main>`, `position: sticky; top: 0`, visível nas visões de **Operação**
  (`execucoes`, `decisoes`, `evidencias`) e **Governança** (`politicas`, `agentes`, `demandas`); **não** aparece em
  Produto (`observabilidade`). Renderizada a cada `refresh()` (3 s), inclusive quando a visão está em edição
  (atualiza só a faixa, sem re-render do resto).
- Um bloco por provedor, **lado a lado** (≥ 600 px) e **empilhados** (< 600 px); nada soma os dois.
  Cada bloco: nome · **5 h**: barra + "9% usado · falta 91% · renova em 2h51 (00:15)" · **Semana**: idem com
  dia/hora ("renova sex 01:39"). Barra com `role="meter"`, `aria-valuenow`, `aria-valuemin=0`, `aria-valuemax=100`, `aria-label`.
- Faixas de cor com texto (não só cor): < 80% neutro; 80–94% atenção; ≥ 95% crítico. Paleta/tipografia do painel.
- `stale`: mantém os números (esmaecidos) + ícone de alerta com texto **"Indisponível · coletado às HH:MM"**
  (+ `title`/tooltip com `reason`). `none`: "Indisponível — sem fonte real" + `reason`, **sem números**.
- Sem `aria-live` na faixa (o polling não pode ser anunciado a cada 3 s). Altura ≤ 72 px em desktop; a 390 px sem
  rolagem horizontal nem texto cortado (quebra de linha permitida).

## 5. Critérios de aceite

| # | Critério | Verificação |
|---|----------|-------------|
| CA1 | `GET /api/usage` e `/api/state.usage` retornam `providers` = [`claude`, `codex`] no formato do §3; valores **separados**. | `curl` |
| CA2 | Codex: com um rollout real, `fiveHour.usedPercent`/`week.usedPercent`/`resetsAt` batem com `primary`/`secondary` do último `token_count` (maior `timestamp` entre os 5 rollouts mais recentes). | Comparar com `grep token_count` do arquivo |
| CA3 | Claude: com o tee instalado, após uma interação numa sessão interativa, `.squad/usage/claude.json` contém só as chaves do §2 e a API reflete `five_hour`/`seven_day`. | Inspeção do arquivo + `curl` |
| CA4 | Tee preserva a statusline do usuário: saída com `--next` é idêntica à do comando original para o mesmo stdin; stdin sem `rate_limits` ou JSON inválido não altera o snapshot e não gera erro visível. | Teste com fixture |
| CA5 | Nenhum segredo: snapshot e resposta da API não contêm tokens, e-mail, `session_id` nem caminhos. | `grep` nas saídas |
| CA6 | Sem fonte (sem `~/.codex/sessions` ou sem snapshot): `status: none`, números `null`, UI mostra "Indisponível — sem fonte real". Nenhuma estimativa. | `CODEX_HOME=/vazio` / remover snapshot |
| CA7 | Coleta > 15 min ou `resetsAt` vencido: `status: stale`; UI mostra último valor + ícone de alerta + "Indisponível · coletado às HH:MM". | Fixture com `timestamp` antigo |
| CA8 | Faixa fixa (sticky) visível ao rolar em Execuções, Decisões, Evidências, Políticas, Agentes e Demandas; ausente em Observabilidade. | Painel |
| CA9 | Atualiza a cada polling (3 s) sem recarregar a página, também durante edição de formulário. | Painel |
| CA10 | A 390 px: blocos empilhados, sem rolagem horizontal; barras com `role="meter"` e texto além da cor. | DevTools 390 px |
| CA11 | Falha de leitura de um provedor não quebra `/api/state` nem o outro provedor. | Arquivo corrompido |
