# ADR-022: Delegação de tarefas pela conversa — evento no log, execução pelo plantão na branch da demanda, mesmo PR

**Status**: Proposto (2026-09-25, Arquiteto — D19 `402e76f187f9`)
**Numeração**: 020 = conversa (D17); 021 = ambiente e versão (D18, em PR). Este é o próximo livre.
**Contrato**: [`docs/contracts/delegacao-pela-conversa.md`](../contracts/delegacao-pela-conversa.md).
**Estende**: ADR-020 (conversa e destravar). **Respeita**: ADR-011 (merge humano), ADR-017 (alertas derivados do
log), ADR-018 (produtivo inquebrável; ambiente de teste só por pedido do humano).

## Contexto
Quando surge um impedimento fora do fluxo (ex.: PR #171 da D18 ficou em conflito com a `develop`), o humano só tem
duas saídas: fechar o PR ou abrir uma demanda nova. Ele quer pedir, **pela conversa com o Orquestrador**, uma tarefa
pontual **para uma demanda existente**, confirmar num cartão e ver a squad resolver no fluxo normal, atualizando o
**mesmo PR**. Respostas do humano na triagem: (1) só tarefas sobre a demanda existente, sem gerar demanda nova;
(2) no caso "ambiente de teste com erro", a operação do ambiente continua com ele; (3) "pendência de outro agente" =
(a) handoff sem continuidade, (b) change-request aberto, fechado por um `decision` ligado ao id, (c) agente parado
(A2), com **uma** nova tentativa e depois volta ao humano.

Fatos verificados no código:
- A conversa (ADR-020) é somente leitura por construção; o único efeito é a confirmação humana de uma proposta, que o
  servidor revalida e grava pela mesma função das rotas existentes (`record_human_decision`/`record_control`).
- O servidor não tem poder de escrita no repositório nem faz push (ADR-011 §2b). Quem executa é o plantão
  (`pending.py` → prompt `plantao.md`), que já trata eventos `control`/`human` do log.
- `pending.py` já consulta cada PR em revisão com `gh pr view` no máximo a cada 30 s (cache `.squad/pr-state.json`);
  o campo `mergeable` sai da mesma chamada, sem custo extra.
- `gitflow.pr()` reutiliza o PR existente da branch (`gh pr list --head`); `open_review` não duplica `review`.
  `align_memory` já faz merge da `develop` na feature e aborta em conflito de código.
- `alerts.py` reconstrói alertas só a partir do log e dos gates (sem rede). `change-request` existe em `log.py`, mas
  nenhum evento o fecha. Não há alerta para handoff sem continuidade.
- Cada demanda trabalha num worktree irmão (`plankton-d<n>`); a cópia principal `plankton/` fica em `develop` e é a
  origem do produtivo (ADR-018).
- `log.py` (linha 20) e `gitflow.py` (`ROOT`, linhas 26-27) resolvem o log e o repositório **a partir do próprio
  caminho do script**: rodados de dentro de um worktree, gravam no `decisions.jsonl` do worktree, que o
  `pending.py`/`alerts.py` (cópia principal) não leem, e a memória vazaria para o PR (defeito `a66b91c8a0d6`).
  `align_memory` faz `switch` na própria cópia principal.
- `run_agent.py` gera um `runId` novo a cada execução: A2 `agent-stalled:<runId>` muda de alvo a cada run.

## Decisão
1. **A conversa propõe; o servidor valida; o humano confirma; o log registra; o plantão executa.** O modelo do chat
   continua sem ferramenta de escrita. Um novo bloco estruturado ` ```delegar ` (ao lado do ` ```destravar `) vira
   proposta; na confirmação o servidor grava **um** evento `delegation` (`agent: humano`, `via: conversa`) no log.
   O plantão lista `delegação: <id>` via `pending.py` e conduz a tarefa. Nada de processo disparado pelo servidor.
2. **Tipo em lista fechada + tarefa em texto livre ancorada numa demanda existente.** Tipos: `conflito-develop`,
   `gate-travado`, `teste-quebrado`, `ambiente-teste` (só diagnóstico e correção na branch), `pendencia-handoff`,
   `pendencia-change-request`, `pendencia-agente-parado` e `ajuste-pontual` (texto livre dentro do escopo da demanda,
   para honrar a resposta 1). O servidor recusa demanda inexistente, cancelada ou entregue, tipo fora da lista, alvo
   que não existe ou não pertence à demanda, e as ações reservadas ao humano (merge, cancelar, pausar, repriorizar,
   operar o ambiente de teste ou o produtivo, abrir demanda). O **agente** e o **piso de risco** são definidos pelo
   servidor a partir do tipo e do dono do diretório (single-writer), não pelo modelo.
3. **Execução no fluxo normal**: worktree da demanda (recriado se removido), branch da própria demanda, dono do
   diretório, QA se mudar código, Auditor no gate do estágio (G3 se a demanda já está em revisão). Conflito com a
   `develop` é resolvido por **merge** da `origin/develop` na feature (sem rebase, sem `--force`); o PR é atualizado
   por push na mesma branch (`gitflow.py review-update`), **nunca** um PR novo nem um `review` novo.
   **Onde roda**: todo `log.py` e `gitflow.py` da delegação é o da **cópia principal**, chamado pelo caminho absoluto
   (o log é um só); os comandos git novos do `gitflow.py` recebem o worktree da demanda como diretório de trabalho e
   **nunca** fazem `switch` na cópia principal. O worktree não commita `docs/squad/memory/**` (`STATE`), e o
   `review-update` **recusa** o push se o diff da branch contra a `origin/develop` tocar `STATE` (verificar, não
   realinhar: ver contrato §9.4).
4. **Resultado e estados no log**: `delegation` → `delegation-start` → (trabalho, handoffs, gate) →
   `delegation-result` (`ok | falhou | obsoleta | recusada | cancelada`). Uma delegação ativa por demanda.
   **Tentativas** com chave estável (independente de `runId`/id de evento que muda a cada ocorrência):
   `pendencia-agente-parado` → no máximo **1** delegação por `(demanda, agente, passo)` (a run que parou é a
   original; a delegação é a única nova tentativa; se falhar, volta ao humano), e uma run iniciada por delegação que
   parar não oferece delegar de novo; `conflito-develop` → no máximo 2 por `(demanda, tipo, PR)`; demais tipos → no
   máximo 2 por `(demanda, tipo, alvo)` (original + uma nova). O fechamento de
   change-request passa a ser um `decision` com `changeRequest: <id>` e `resolution: aceita|recusada`.
5. **Detecção de conflito no plantão**: `pending.py` lê `mergeable` na consulta que já faz; transição para
   `CONFLICTING` vira `pr-conflict` no log (e `pr-conflict-cleared` na volta); `alerts.py` abre **B6** "PR em
   conflito" com a ação "Delegar correção", que abre a conversa com o pedido pré-preenchido. Novos avisos derivados
   do log: **A6** handoff sem continuidade e **A7** change-request aberto em demanda ativa.
6. **Segurança**: o texto da tarefa é instrução só porque o humano o confirmou no cartão; todo o resto (log,
   evidências, gates, handoffs, diffs) chega ao executor como **dado**. `log.py` **não** aceita `--type delegation`
   (só o servidor grava); o plantão confere que o evento tem par `confirmada` na conversa e revalida a pré-condição
   antes de começar. Merge, cancelar e repriorizar continuam só do humano.

7. **Decisões provisórias** (padrões recomendados pelo Auditor no G1; o humano pode rever no PR): (i) `ajuste-pontual`
   fica, com piso `moderado` e gate; (ii) latência de até um ciclo do plantão (≈ 3 min) é aceitável, com "aguardando o
   plantão" na UI; (iii) A6 com limiar de 30 min, ajustável por `SQUAD_HANDOFF_STALLED_S`; (iv) o botão do alerta abre
   a conversa com o pedido **preenchido e sem enviar**.

## Consequências
- (+) Um único caminho para impedimentos pontuais, sem demanda nova e sem fechar PR; tudo rastreável no log.
- (+) O servidor continua sem poder de escrita no repositório; a conversa continua somente leitura.
- (+) Reaproveita o que existe: validação/revalidação/cartão do ADR-020, `pr()` idempotente, `align_memory`, gates.
- (−) Latência de até um ciclo do plantão (≈ 3 min) entre confirmar e começar; a UI mostra "aguardando o plantão".
- (−) `ajuste-pontual` abre espaço para mudança de escopo; mitigado pelo gate (o Auditor devolve o que for escopo
  novo, que então vira demanda pelo humano) e por piso de risco `moderado`.
- (−) Três regras novas (B6, A6, A7) e sete tipos de evento novos; exige atualizar `alerts.py`, `pending.py`,
  `log.py`, `gitflow.py`, prompts e a tela da demanda.
- (−) A2 some após `STALLED_MAX_S` (1 h, `alerts.py:14`); depois disso o agente parado deixa de ser delegável e
  volta a ser só do humano.
- (−) Autenticidade do `delegation` é defendida por convenção (log.py recusa o tipo + par na conversa local), não por
  criptografia: agentes rodam com o mesmo usuário do sistema.

## Alternativas
| Alternativa | Por que não |
|---|---|
| A. Servidor dispara `run_agent.py` na confirmação | dá poder de escrita/push ao servidor (contraria ADR-011 §2b e ADR-020) e cria um segundo orquestrador concorrendo com o plantão |
| B. Criar uma demanda-filha para o impedimento | o humano recusou ("sem gerar demanda nova") |
| C. Só texto livre, sem tipo | não dá para validar pré-condição, agente nem risco no servidor; perde a lista fechada que torna o ADR-020 seguro |
| D. Só a lista fechada dos cinco impedimentos | contraria a resposta 1 ("tarefas relacionadas à demanda existente") e o exemplo do item 1 |
| E. Rebase da feature sobre a `develop` | exige `push --force` (vetado desde ADR-011) e reescreve o histórico já revisado |
| F. Detectar conflito no `alerts.py` chamando o GitHub | `alerts.py` é puro sobre o log (ADR-017); rede nele deixa `/api/live` lento e não reprodutível |
| G. Botão "Delegar correção" grava a delegação direto, sem conversa | seria um segundo caminho de confirmação; o critério de aceite do humano passa pelo chat. A ação abre a conversa com o pedido pré-preenchido |
| H. Confirmação vale como `test-env-request` | o humano decidiu manter a operação do ambiente com ele (resposta 2; ADR-018) |
| I. Assinar o evento com HMAC | a chave ficaria legível pelos agentes (mesmo usuário); custo sem ganho real. Revalidação + par na conversa + gate bastam |
| J. `review-update` realinhar a memória como o `align_memory` | `align_memory` faz `switch` e commit na cópia principal (origem do produtivo); realinhar em silêncio esconderia um agente que gravou no log errado. O realinhamento legítimo já ocorre no `feature-sync`; o `review-update` só verifica e recusa |
