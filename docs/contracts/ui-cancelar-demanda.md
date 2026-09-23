# Contrato — Cancelar demanda antes do início (D7, `e31bdfb73679`, tipo operação)

> Implementação: **Frontend** (`squad-control/**`) e **Orquestrador** (`tools/squad/**`). Complementa D4
> (`ui-demandas-v2.md`) e D5 (`ui-backlog-de-demandas.md`). Reutiliza o controle existente
> `POST /api/demand/control {id, action: "cancel", note}` → evento `control` `cancel`; **nenhum evento novo**.

## Escopo
Oferecer "Cancelar demanda" também nos estados **pré-início**: *Em validação*, *Com perguntas*, *Validação atrasada*,
*Registrada · pronta para iniciar* (inclui *Validada*/*Respondida*) e *Backlog*. Nos estados já iniciados o botão
existente continua igual. Fora de escopo: desfazer cancelamento, excluir a demanda do log.

## Situação atual verificada
- `server.py` aceita `cancel` para qualquer `id` (inclusive inexistente, concluída ou já cancelada) → precisa de ajuste.
- `pending.py` já não pede validação para demanda cancelada e lista `cancelamento: <id>` até o Orquestrador registrar
  a decisão "…cancelada…" → cobre também pré-início.
- `github_sync.py` `on_control cancel` comenta (com a nota) e fecha a issue, mas move o Status para **"Backlog"** e
  fecha sem motivo → ajustar.
- Painel: `controlsHtml` retorna vazio quando `info.preStart` → ajustar; a precedência de status já põe "Cancelada"
  acima de validação (linha do `status` em `demandInfo`).

## Critérios de aceite

| # | Critério | Verificação |
|---|----------|-------------|
| CA1 | Nos 5 estados pré-início o card mostra **"Cancelar demanda"**. 1º clique abre confirmação inline: campo **Motivo (opcional)** com `label` + botões "Confirmar cancelamento" e "Voltar"; só o 2º clique ("Confirmar") envia `control cancel` com `note` = motivo. Operável por teclado; foco vai para o campo motivo ao abrir. | Painel em cada estado |
| CA2 | Após cancelar, o card mostra **"Cancelada"** (+ motivo, se houver) e **nenhuma ação** (sem Iniciar, responder perguntas, editar, mover para a fila, override); no Backlog ele sai da seção Backlog e aparece na lista geral como Cancelada. | Painel após refresh |
| CA3 | Nenhuma validação depois do cancelamento: `pending.py` não lista `validação:` para ela; se uma triagem estava em curso e gravar `validation` depois, o card **continua "Cancelada"** e as perguntas **não** são exibidas; o plantão, ao tratar `cancelamento:`, interrompe a triagem em execução da demanda (se houver) e registra a decisão "Demanda cancelada pelo humano". | Cancelar durante "Em validação"; `pending.py` 2× |
| CA4 | Servidor recusa ações sobre demanda cancelada: `start`, `clarify` e `edit` → **409** `{"error":"demanda cancelada"}`. `control cancel` → **404** se a demanda não existe, **409** `{"error":"demanda já concluída"}` se houver G3 APPROVE, **409** `{"error":"demanda já cancelada"}` se já cancelada. | `curl` |
| CA5 | A issue do GitHub recebe comentário "Controle humano · cancel" com o motivo e é **fechada como "not planned"** (`gh issue close --reason "not planned"`), com Status do Project **"Cancelado"** (criar a opção se não existir; não usar "Backlog") e label `cancelada`. | `gh issue view` |
| CA6 | Sem regressão: pausar/retomar/repriorizar/cancelar de demandas iniciadas, fluxo D4 (validação), D5 (backlog/editar/mover) e fila funcionam como antes. | Smoke da aba Demandas |

## O que muda, por arquivo e dono

| Dono | Arquivo | Mudança |
|------|---------|---------|
| Frontend | `squad-control/index.html` | `controlsHtml`: nos estados pré-início renderizar só o bloco "Cancelar demanda" (com a confirmação de CA1); estado "Cancelada" sem ações; perguntas de `validation` ocultas se cancelada; tratar 404/409 do servidor com a mensagem. |
| Orquestrador | `tools/squad/server.py` | Validações de CA4 em `/api/demand/control` (só para `cancel`) e bloqueio de `start`/`clarify`/`edit` de demanda cancelada. |
| Orquestrador | `tools/squad/github_sync.py` | `on_control cancel`: Status "Cancelado", `close --reason "not planned"`, label `cancelada`; não comentar `validation` que chegue depois do cancelamento (opcional, recomendado). |
| Orquestrador | `docs/squad/prompts/plantao.md` | Em A) `cancel`: se houver triagem/execução em curso da demanda, interrompê-la; se não iniciada, só registrar a decisão. |
| — | `pending.py`, `log.py`, contratos de produto | Sem mudança. |

## Plano de teste
1. `curl` CA4 (404, 409 concluída, 409 já cancelada, 409 em start/clarify/edit após cancelar).
2. Painel: cancelar uma demanda em cada estado pré-início (CA1, CA2), uma delas durante a triagem (CA3).
3. `github_sync.py` uma vez → issue fechada "not planned", Status "Cancelado", comentário com motivo (CA5).
4. Smoke de regressão (CA6). Evidências com `--demand e31bdfb73679`.
