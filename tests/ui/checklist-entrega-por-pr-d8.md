# Checklist QA — D8 `349e5b1bf818`: Entrega por PR com revisão humana (ADR-011)

Contrato: `docs/contracts/entrega-por-pr.md` (CA1–CA8). Gates: `docs/squad/gates/G2-D8.json` (ciclo 1, RETURN 0.71)
e `G2-D8-2.json` (ciclo 2, APPROVE 0.96); `G3-D8.json` (APPROVE). Nenhum efeito no GitHub real: repositório git temporário + remote bare
local + `gh`/`mvn` falsos no PATH (suíte `tests/squad/test_entrega_por_pr.py`), e cópia descartável do painel
(porta 7079, log próprio vazio) para os estados visuais. Servidor 7079 encerrado ao final desta rodada.

## Resumo

**Rodada final (após c9c935e):** `python3 tests/squad/test_entrega_por_pr.py` → **45 PASS, 0 FAIL, código de saída 0**.

| # | Critério | Resultado | Evidência |
|---|----------|-----------|-----------|
| CA1 | `feature-finish` sem G3 falha; sem `--force`; `--demand` obrigatório | ✅ | `tests/squad/test_entrega_por_pr.py` — sem G3: código ≠ 0 e stderr "G3 da demanda ainda não aprovado…"; sem `--demand`: argparse recusa; `--force`: "unrecognized arguments" |
| CA2 | Com G3 APPROVE, `feature-finish` abre o PR sem merge e registra **um** `review`; reexecução não duplica | ✅ | 1 único `gh pr create`; evento `review` confirmado **commitado na develop** (`git show develop:...decisions.jsonl`) — o defeito do ciclo 1 do G2-D8 (review perdido ao voltar para develop) está corrigido; reexecução na feature reutiliza a mesma PR (`gh pr list`) e não duplica o evento |
| CA3 | Corpo do PR com as 6 seções (G3, evidências, perguntas/respostas, artefatos, checklist) | ✅ | Corpo capturado do `gh` falso contém "## Pareceres do Auditor", "**G3:**", "## Evidências" com "Testes unitários: pass", "## Perguntas da validação e respostas do humano" com pergunta e resposta do humano, "## Artefatos alterados" com `a.txt`, "## Checklist do revisor"; sem "Refs #" quando a demanda não tem issue (comportamento esperado) |
| CA4 | Nenhum `gh pr merge` em `tools/squad` (nem em release/hotfix) | ✅ | `grep -rnE '"pr",\s*"merge"|pr merge' tools/squad` vazio no código real; nenhuma chamada `pr merge` registrada pelo `gh` falso em todo o teste (feature, review-sync, release, back-merge) |
| CA5 | PR fechado sem merge → `pending.py` lista `revisão recusada:`; `review-sync` → `review-rejected` com comentários; painel "Devolvida pelo revisor" | ✅ | `pending.py` listou `revisão recusada: demanda <id> (PR #1)`; `review-sync` → "devolvida pelo revisor", evento com os comentários do revisor no `detail`; idempotente na 2ª chamada; screenshot `d8-04-card-devolvida-pelo-revisor.png` |
| CA6 | PR integrado → `delivered` com `mergeCommit`; painel "Entregue"; develop local com o merge commit; branch da feature removida | ✅ | Defeito a66b91c8a0d6 **corrigido em c9c935e** e revalidado: `pending.py` lista `revisão integrada`; `review-sync` (MERGED) não quebra mais com conflito de git ao sincronizar a develop (mesmo com o `review` local-only e o merge humano feito à parte no remote); evento `delivered` com `mergeCommit`; branch local da feature removida; idempotente na 2ª chamada. Estado visual: screenshot `d8-03-card-entregue.png` |
| CA7 | `release-finish` só abre PR; `release-publish` recusa sem MERGED; com MERGED cria a tag no merge commit e abre o back-merge como PR | ✅ | `release-finish` abriu PR para `main` sem merge; `release-publish` recusou com PR ainda `OPEN` ("o PR da release ainda não foi integrado…"); após o merge humano (simulado em clone à parte), `release-publish` criou a tag `v9.9.9` apontando exatamente para o merge commit, registrou `delivered` da release e abriu o back-merge (`chore/back-merge-9.9.9` → develop) como **PR**, sem nenhum `gh pr merge` |
| CA8 | Sem regressão: demandas antigas "Concluída", D4/D5/D7, controles e gates inalterados | ⏳ a validar no primeiro PR real | Sem regressão observada no ambiente isolado (checklists de D4/D5/D7 cobrem o resto; `AGENTS.md`/G2-D8-2 confirmam "merge é do humano"). Falta confirmar no **primeiro PR real**: corpo com `Refs #<issue>` quando a demanda tem issue e a passagem **Em revisão → Entregue** refletida na issue do GitHub |

## Defeito encontrado e corrigido (a66b91c8a0d6)

**`review-sync` (caminho MERGED) falhava com conflito de git ao sincronizar a develop** quando o merge humano
chegava antes do próximo `sync_develop`: o commit local-only do evento `review` (feito por `feature-finish`) e o
merge da PR no remote mexiam no fim de `docs/squad/memory/decisions.jsonl`, e o `git pull --rebase` entrava em
conflito, saindo com código ≠ 0 sem gravar `delivered`.

**Status: corrigido em `c9c935e`** ("review-sync sem conflito após o merge humano"). A asserção
`CA6 [DEFEITO]: review-sync (MERGED) não quebra com conflito de git ao sincronizar a develop` agora passa, assim
como `delivered` com `mergeCommit`, remoção da branch local e idempotência. Evidência registrada com
`--demand 349e5b1bf818` ("CA6 review-sync MERGED=pass").

## Ambiente de teste

- **CA1–CA7 (gitflow.py/pending.py)**: `tests/squad/test_entrega_por_pr.py` — repositório git temporário
  (`tempfile.mkdtemp`), remote bare local (`git init --bare`), `gh` e `mvn` **falsos** no `PATH` (registram
  todas as chamadas e nunca tocam o GitHub real). O merge humano é sempre simulado num **clone separado** do
  remote bare (nunca no checkout do "orquestrador"), para reproduzir fielmente o que o GitHub faz server-side.
  Rodar: `python3 tests/squad/test_entrega_por_pr.py` (sai com código 0 só se tudo passar). Resultado após
  c9c935e: **45 PASS, 0 FAIL, código 0**. O script mantém a recuperação automática (`git rebase --abort` +
  `reset --hard origin/develop`) caso o conflito de CA6 volte a ocorrer, para seguir testando CA7.
- **Painel (CA5/CA6, estados visuais)**: cópia descartável de `tools/`, `squad-control/`,
  `docs/squad/project.json`, `docs/squad/prompts/`, com `docs/squad/memory/decisions.jsonl` vazio; servidor
  `python3 tools/squad/server.py --port 7079` (encerrado ao final). Três demandas de teste com eventos `review`/
  `delivered`/`review-rejected` injetados diretamente no log da cópia (via `tools/squad/log.py` da própria
  cópia): "Em revisão" (com `start` para aparecer também em Execuções), "Entregue" e "Devolvida pelo revisor".

## Screenshots (1440px, Puppeteer `ghcr.io/puppeteer/puppeteer:latest`)

- `d8-01-demandas-geral.png` — aba Demandas com as 3 demandas de teste.
- `d8-02-card-em-revisao.png` — card "Em revisão · PR #101" com o link "Revisar no GitHub".
- `d8-03-card-entregue.png` — card "Entregue · PR #102 · commit abcdef1".
- `d8-04-card-devolvida-pelo-revisor.png` — card "Devolvida pelo revisor · PR #103" com os comentários do revisor.
- `d8-05-execucoes-em-revisao.png` — tela **Execuções** com a demanda ativa mostrando o mesmo estado
  "D1 · EM REVISÃO · PR #101" e "Aguardando sua revisão · PR #101 · Revisar no GitHub" no cabeçalho.

Nota: para a demanda "Em revisão" aparecer também em Execuções, foi injetado um evento `start` (sem essa etapa a
demanda fica "pré-início" e não é considerada "ativa" pela tela de Execuções) — não é um defeito, é só o motivo
de os cards "Entregue" e "Devolvida" (que não passaram por essa injeção) mostrarem os controles de pré-início
("Iniciar") ao lado do rótulo no `d8-01`.

## Outras observações (não bloqueantes)

- O contrato (§2.1) menciona reabrir um PR fechado da mesma branch com `gh pr reopen`, mas o código atual
  (`gitflow.py:pr()`) só faz `gh pr list` (PRs abertas) + `gh pr create`; após um `review-rejected`, uma nova
  `feature-finish` abriria uma **PR nova**, não reaproveitaria/reabriria a antiga. Isso é explicitamente aceito
  pelo próprio diagrama de estados do contrato ("PR reaberto **ou novo**"), então não é tratado como defeito.
