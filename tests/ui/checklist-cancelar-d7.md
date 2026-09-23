# Checklist QA — D7 `e31bdfb73679`: Cancelar demanda durante a validação

Contrato: `docs/contracts/ui-cancelar-demanda.md`. Gates: `docs/squad/gates/G2-D7.json` (ciclo 1, RETURN) e
`G2-D7-2.json` (ciclo 2, APPROVE 0.88). Ambiente: cópia descartável do painel/servidor (porta 7078, log próprio
vazio, sem afetar o log real nem o servidor 7070). Servidor encerrado ao final desta rodada.

## Resumo

| # | Critério | Resultado | Evidência |
|---|----------|-----------|-----------|
| CA1 | Botão "Cancelar demanda" nos 5 estados pré-início; 1º clique abre confirmação com "Motivo (opcional)" + "Confirmar cancelamento"/"Voltar"; só o 2º clique envia `control cancel` com `note` | ✅ | `d7-02-card-em-validacao-botao-cancelar.png` (card D5 "Com perguntas" mostra "Cancelar demanda"; código em `squad-control/index.html` `preCancelHtml`/`preStartHtml` confirma fluxo de 2 cliques, foco no campo motivo ao abrir — `document.getElementById('cn-'+id)?.focus()`) |
| CA2 | Após cancelar: card "Cancelada" (+ motivo), sem nenhuma ação; item saído do Backlog aparece na lista geral como Cancelada | ✅ | `d7-03-card-cancelada-com-motivo.png` (D1, motivo "motivo de teste QA", sem botões), `d7-05-card-cancelada-vinda-do-backlog.png` (D2, era backlog, motivo "nao preciso mais") e `d7-01-demandas-geral.png` mostra "Backlog (0)" — D2 não está mais lá, aparece em "Demandas registradas" |
| CA3 | `pending.py` não lista `validação:` para a cancelada; validação/perguntas que cheguem depois do cancelamento não aparecem; card continua "Cancelada"; `triage.py` na cancelada não roda/grava | ✅ | `curl`/CLI abaixo: `pending.py` listou só `cancelamento: 79def696f690` (não `validação:`); `triage.py 79def696f690` → "demanda cancelada: triagem não executada" e decisions.jsonl não cresceu; `d7-04-card-cancelada-validacao-tardia.png` (D4: evento `validation` com `perguntas` gravado *depois* do `control cancel` — card mostra só "Cancelada", sem o bloco de perguntas) |
| CA4 | `start`/`clarify`/`edit` em cancelada → 409 `{"error":"demanda cancelada"}`; `control cancel` → 404 se não existe, 409 "já concluída" se G3 APPROVE, 409 "já cancelada" se repetido | ✅ | ver tabela de `curl` abaixo — todos os códigos e mensagens batem com o contrato, inclusive `start` com `override:true` (bloqueio ocorre antes do desvio de override no código) |
| CA5 | Issue fechada "not planned" com comentário do motivo, Status "Cancelado" (ou risco aceito) e label `cancelada` | ⚠️ verificado no código | `tools/squad/github_sync.py` linhas 301-310: `on_control cancel` cria/aplica label `cancelada`, fecha com `gh issue close --reason "not planned"` e comentário "Demanda cancelada pelo humano. Motivo: …", cria label `status:cancelado` e chama `status_label(issue, "Cancelado")` (que também remove as demais `status:*`, inclusive `status:concluido`). **Não executado contra o GitHub real** (instrução explícita para não gerar issues de teste). Corresponde ao que os gates G2-D7 (devolução) e G2-D7-2 (correção aceita) já registraram; risco aceito documentado na decisão `02a3ae767bb3`: o campo Status do Project não ganha a opção "Cancelado" (evita recriar ids e zerar o Status de todos os cards) — a fonte de verdade passa a ser a label `status:cancelado` + issue fechada `not planned`. QA de 1ª execução real deve confirmar com `gh issue view` |
| CA6 | Sem regressão: pausar/retomar/repriorizar/cancelar de iniciadas, D4 (validação), D5 (backlog/editar/mover), fila | ✅ | Smoke visual em `d7-01-demandas-geral.png`: Fila (0), Backlog (0), demanda D3 pré-início com "Iniciar"/"Iniciar mesmo assim" intactos, D5 com fluxo de perguntas/"Enviar respostas" intacto; nenhuma mudança de comportamento fora do escopo de cancelamento observada; controles de demandas iniciadas (`controlsHtml`) inalterados no código |

## Ambiente de teste (cópia descartável, NUNCA o servidor 7070 nem o log real)

- Cópia em diretório temporário do scratchpad: `tools/`, `squad-control/`, `docs/squad/project.json`,
  `docs/squad/prompts/`, com `docs/squad/memory/decisions.jsonl` vazio e `docs/squad/inbox/done/` vazio.
- Servidor: `python3 tools/squad/server.py --port 7078` (encerrado ao final desta rodada).
- Demandas de teste criadas via `POST /api/demand` e eventos de fixture via o `log.py` **da cópia**:
  - `79def696f690` (D1) — "Em validação" → cancelada com motivo "motivo de teste QA".
  - `0c2e07a7106c` (D2) — Backlog → cancelada com motivo "nao preciso mais".
  - `6da36ede0890` (D3) — gate `G3 APPROVE` de fixture (simula "concluída") para o teste de 409.
  - `b8709fad41ae` (D4) — cancelada e, **depois**, recebeu evento `validation` com `status: perguntas` (cenário CA3 de validação tardia).
  - `4f479ad461ae` (D5) — "Com perguntas" (não cancelada), usada para fotografar o botão "Cancelar demanda" em CA1.

## Matriz de `curl` (CA4)

```
POST /api/demand/control {id: D1, action: cancel, note: "motivo de teste QA"}      -> 201
POST /api/demand/control {id: D1, action: cancel}                                   -> 409 {"error":"demanda já cancelada"}
POST /api/demand/control {id: "naoexiste123", action: cancel}                       -> 404 {"error":"demanda não encontrada"}
POST /api/demand/control {id: D3 (com gate G3 APPROVE), action: cancel}             -> 409 {"error":"demanda já concluída"}
POST /api/demand/start   {id: D1}                                                    -> 409 {"error":"demanda cancelada"}
POST /api/demand/start   {id: D1, override:true, note:"seguir mesmo assim"}          -> 409 {"error":"demanda cancelada"}
POST /api/demand/clarify {id: D1, validation:<id>, answers:[...]}                    -> 409 {"error":"demanda cancelada"}
POST /api/demand/edit    {id: D1, title:"x"}                                         -> 409 {"error":"demanda cancelada"}
POST /api/demand/control {id: D2 (backlog), action: cancel, note:"nao preciso mais"} -> 201
```

## CLI (CA3)

```
$ python3 tools/squad/pending.py
validação: 6da36ede0890     # D3, sem relação com o cancelamento (fixture sem evento de validação)
cancelamento: 79def696f690  # D1 — nenhuma linha "validação:" para D1
cancelamento: 0c2e07a7106c  # D2

$ python3 tools/squad/triage.py 79def696f690
demanda cancelada: triagem não executada
# decisions.jsonl não cresceu (nenhum evento `validation` gravado)
```

## Screenshots (1440px, Puppeteer `ghcr.io/puppeteer/puppeteer:latest`, `[data-view="demandas"]`)

- `d7-01-demandas-geral.png` — visão geral da aba Demandas com a cópia (Backlog vazio, Fila vazia, 5 demandas de teste).
- `d7-02-card-em-validacao-botao-cancelar.png` — card "Com perguntas" (D5) mostrando "Cancelar demanda".
- `d7-03-card-cancelada-com-motivo.png` — card "Cancelada" com motivo (D1).
- `d7-04-card-cancelada-validacao-tardia.png` — card "Cancelada" (D4) que recebeu `validation` com perguntas *depois* do cancelamento e não exibe o bloco de perguntas.
- `d7-05-card-cancelada-vinda-do-backlog.png` — card "Cancelada" (D2) que era backlog e passou para a lista geral.

## Defeitos encontrados

Nenhum. Todos os critérios de aceite (CA1–CA6) se comportaram conforme o contrato e conforme os pareceres G2-D7 /
G2-D7-2. CA5 permanece com verificação apenas no código (não exercitado contra o GitHub real, por instrução
explícita desta rodada de QA) — recomenda-se conferir com `gh issue view` na primeira demanda cancelada real.
