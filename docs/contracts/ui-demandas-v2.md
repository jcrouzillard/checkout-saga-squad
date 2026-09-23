# Contrato — Demandas v2: tipo da demanda + validação agêntica (D4, `1cc732c62a2d`, ADR-008)

> Implementação: **Orquestrador** (`tools/squad/**`, `docs/squad/**`) e **Frontend** (`squad-control/**`).
> Base atual: `squad-control/index.html` (`renderDemandas`, `POST /api/demand`), `tools/squad/server.py`,
> `pending.py`, `log.py`, `github_sync.py`, `docs/squad/prompts/plantao.md`.

## 1. Campo `tipo` (obrigatório)

| Valor (`kind`) | Rótulo no formulário | Ajuda exibida | Exemplos |
|----------------|----------------------|---------------|----------|
| `produto` | **Produto** — muda o checkout | "Altera o que o cliente usa: serviços, APIs, eventos, Saga ou o Console de Checkout." | D1 (listar pedidos), D2 (visual do Console) |
| `operacao` | **Operação / governança** — muda a fábrica | "Altera como a squad trabalha: Squad Control, protocolo, gates, ferramentas de `tools/squad`." | D3 (emojis no painel), D4 (esta) |

- Controle: grupo de 2 botões de opção (`<fieldset><legend>Tipo</legend>`), **sem valor padrão** — o humano escolhe.
- `POST /api/demand` aceita `kind`; ausente ou fora de `produto|operacao` → `400 {"error": "tipo obrigatório: produto | operacao"}`.
  O evento `task` passa a carregar `"kind"`.
- Exibição: tag `produto`/`operação` no card da demanda; label `tipo:produto` / `tipo:operacao` na issue do GitHub.
- **Roteamento** (triagem do plantão, rota "padrao"; rota "direta" continua mandando ao agente escolhido):

| Tipo | Primeiro agente | Caminho |
|------|-----------------|---------|
| `produto` | Arquiteto (contrato/ADR) | Auditor G1 → Backend (`services/**`) e/ou Frontend (`checkout-console/**`) → G2 → QA → G3 |
| `operacao` | Dono do artefato da fábrica: Frontend (`squad-control/**`) ou Orquestrador (`tools/squad/**`, `docs/squad/**`); Arquiteto só se precisar de critérios/ADR | Auditor → QA (smoke do painel/ferramenta) → G3. Mudança em `CLAUDE.md`/`AGENTS.md`/limites de autonomia exige aprovação humana. |

O tipo é **indicativo**: se o Analista achar o tipo incoerente com a descrição, pergunta (ver §2), não altera sozinho.

## 2. Validação agêntica

Fluxo: **Registrar → Em validação → (Validada | Com perguntas → Respondida) → pronta para iniciar → Iniciada → …**

1. `POST /api/demand` grava `task` (com `kind`). A demanda fica **"Em validação"**.
2. `pending.py` lista `validação: <demandId>` para toda demanda humana **com `kind`** sem evento `validation` e sem
   triagem em curso (sem `progress` do `arquiteto` com essa `demand` nos últimos 5 min).
3. O vigia/plantão do Orquestrador delega **imediatamente** (antes da fila de inbox) ao **Arquiteto em modo triagem**:
   `python3 tools/squad/run_agent.py arquiteto @docs/squad/prompts/triagem.md --demand <id>` (prompt novo, curto,
   somente leitura: não cria nem altera arquivos, só registra o evento).
4. O Analista avalia 5 dimensões — **objetivo**, **critério de aceite verificável**, **escopo** (o que entra/o que
   não entra), **restrições** (o que não pode mudar), **tipo coerente** — e registra **um** evento `validation`:
   `status: ok` (nenhuma lacuna que bloqueie quem vai trabalhar) ou `status: perguntas` (1 a 5 perguntas, objetivas,
   cada uma ligada a uma dimensão). Pode sugerir `suggestedKind` se o tipo parecer errado.
5. O painel mostra as perguntas no card; o humano responde (campo por pergunta) → `POST /api/demand/clarify` grava
   `clarification`. Uma rodada só: respostas **não** disparam nova validação; elas são anexadas ao contexto da demanda.
6. **Iniciar** fica habilitado quando: `validation.status = ok`, **ou** existe `clarification` para a última
   `validation`, **ou** o humano marca **"Iniciar mesmo assim"** (override explícito, com nota obrigatória).
   O servidor **reforça** a regra (não só a UI).
7. **Tempo alvo**: perguntas visíveis no painel em **< 1 min** após registrar. Se não houver `validation` em 3 min,
   o card mostra "Validação atrasada" e oferece o override.

Demandas antigas (sem `kind`, anteriores à D4) não passam por validação e mantêm o comportamento atual (status
"Registrada", Iniciar habilitado) — sem regressão.

## 3. Eventos novos no log

`validation` (autor: `arquiteto`):
```json
{ "id": "…", "ts": "…", "agent": "arquiteto", "type": "validation", "demand": "<id da task>", "to": "humano",
  "title": "Validação: 2 perguntas", "status": "perguntas", "suggestedKind": null, "run": "<run id>",
  "questions": [
    { "id": "q1", "dimension": "aceite", "text": "Qual o limite máximo de itens na lista?" },
    { "id": "q2", "dimension": "escopo", "text": "A aba Agentes também deve mudar ou só a faixa?" } ] }
```
`status`: `ok | perguntas`; `dimension`: `objetivo | aceite | escopo | restricoes | tipo`; `questions` vazio se `ok`.

`clarification` (autor: `humano`, via servidor):
```json
{ "id": "…", "ts": "…", "agent": "humano", "type": "clarification", "demand": "<id>", "to": "orquestrador",
  "validation": "<id do evento validation>", "title": "Respostas à validação",
  "answers": [ { "id": "q1", "text": "Máximo 50." }, { "id": "q2", "text": "Só a faixa." } ] }
```
Evento `start` ganha os campos opcionais `override: true` e (no inbox) `kind` e `clarifications`.

## 4. Mudanças por arquivo

| Arquivo (dono) | Mudança |
|----------------|---------|
| `tools/squad/log.py` (Orquestrador) | `TYPES` += `validation`, `clarification`; args `--status {ok,perguntas}`, `--question "dimensão::texto"` (repetível → `questions[]` com ids `q1..qn`), `--suggested-kind {produto,operacao}`, `--kind`. |
| `tools/squad/server.py` (Orquestrador) | `POST /api/demand`: exige `kind`. Novo `POST /api/demand/clarify` `{id, validation, answers[]}` → 400 se respostas vazias, 404 se demanda/validação não existe. `POST /api/demand/start`: 409 `{"error":"demanda aguardando validação"}` se a regra do §2.6 não for satisfeita e `override` ≠ true; com `override` exige `note`; inbox recebe `kind` e `clarifications` (perguntas + respostas). |
| `tools/squad/pending.py` (Orquestrador) | Lista `validação: <id>` (regra §2.2), antes dos demais itens. |
| `docs/squad/prompts/triagem.md` (Orquestrador, novo) e `plantao.md` | Prompt de triagem (§2.4, somente leitura, 1 evento, ≤ 5 perguntas, português) e item "0) validações pendentes" no plantão; triagem da fila usa `kind` (§1). |
| `tools/squad/github_sync.py` (Orquestrador) | `create_issue` da demanda humana com label `tipo:<kind>`; handler `validation` → comentário "Validação agêntica" com checklist das perguntas + label `validacao:ok`/`validacao:perguntas`; handler `clarification` → comentário com pergunta ↔ resposta. Não duplicar no comentário genérico de `on_demand_event`. |
| `squad-control/index.html` (Frontend) | Campo tipo (§1); estados e cores: Em validação (`validate`, com "analisando…"), Com perguntas (`fail`/destaque, lista de perguntas + campos de resposta + "Enviar respostas"), Validada / Respondida → "Registrada · pronta para iniciar" (`muted`), Validação atrasada; tag do tipo e sugestão de tipo; botão Iniciar desabilitado com motivo (`aria-describedby`) até a regra §2.6; checkbox "Iniciar mesmo assim" + nota. Tratar 400/409 do servidor com a mensagem. |

## 5. Critérios de aceite

| # | Critério | Verificação |
|---|----------|-------------|
| CA1 | Formulário exige tipo (sem padrão); sem tipo não registra (validação no front e `400` no servidor). | UI + `curl -XPOST /api/demand -d '{"title":"x"}'` → 400 |
| CA2 | Evento `task` tem `kind`; card mostra a tag do tipo; issue recebe label `tipo:<kind>`. | Log + card + `gh issue view` |
| CA3 | Após registrar, card mostra "Em validação" e, em **< 60 s**, "Validada" ou "Com perguntas" (medir `validation.ts − task.ts`). | Log/cronômetro, 3 demandas |
| CA4 | Demanda vaga (ex.: "melhorar o visual") gera `status: perguntas` com 1–5 perguntas, cada uma com `dimension`; demanda completa (ex.: texto da D1) gera `ok`. | 2 demandas de controle |
| CA5 | Perguntas aparecem no card e como comentário na issue; respostas geram `clarification` e comentário pergunta ↔ resposta. | Painel + issue |
| CA6 | Iniciar bloqueado (UI desabilitada **e** servidor 409) enquanto "Em validação"/"Com perguntas"; liberado após `ok` ou respostas; override exige nota e registra `start` com `override: true`. | `curl /api/demand/start` antes/depois |
| CA7 | O inbox da demanda iniciada contém `kind` e `clarifications`; o plantão roteia pelo tipo conforme §1. | `docs/squad/inbox/done/<id>.json` + log `task` do Orquestrador |
| CA8 | O Analista não altera arquivos (somente o evento `validation`); `pending.py` não relista uma demanda já validada nem em triagem. | `git status` limpo após triagem; rodar `pending.py` 2× |
| CA9 | Sem regressão: demandas antigas (sem `kind`) continuam "Registrada" e iniciáveis; pausar/retomar/cancelar/repriorizar, gates e decisões humanas funcionam como antes. | Smoke das abas + D1–D3 no painel |
| CA10 | Acessibilidade: `fieldset/legend` no tipo, `label` em cada resposta, estado anunciado via `aria-live`, motivo do botão desabilitado legível. | Teclado + leitor de tela |

## 6. Plano de teste (QA)
1. **API** (`curl` no `server.py`): CA1, CA6 (409/201/override sem nota → 400), `clarify` 400/404.
2. **Log/pending**: registrar demanda → `pending.py` lista `validação:`; após `validation`, não lista mais (CA8).
3. **Ponta a ponta com o vigia ativo**: demanda vaga e demanda completa; medir CA3; conferir painel e issue (CA2, CA4, CA5).
4. **Início**: responder perguntas → Iniciar → conferir inbox e roteamento (CA7).
5. **Regressão**: demanda antiga, controles, gates, aba Execuções (CA9); checklist de acessibilidade (CA10).
Evidências: `log.py --type evidence --demand 1cc732c62a2d --evidence "<CA>=pass|fail"`.
