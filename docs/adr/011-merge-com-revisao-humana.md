# ADR-011: Entrega por PR com merge exclusivamente humano

**Status**: Aceito (2026-09-23, Arquiteto) — demanda D8 (`349e5b1bf818`). Contrato: `docs/contracts/entrega-por-pr.md`.
Altera o comportamento de `gitflow.py feature-finish`/`release-finish` descrito em `docs/squad/git-flow.md`.

## Contexto
Hoje, com G3 APPROVE, o Orquestrador abre o PR **e faz o merge** automaticamente (também em releases). O humano
quer revisar antes: "pronta" = PR aberto para revisão humana com o parecer G3; "entregue" = PR integrado; nada sem
G3; sem `--force`.

## Decisão
1. Ferramentas da squad **nunca** fazem merge: `feature-finish` e `release-finish`/`hotfix-finish` só abrem (ou
   reabrem/atualizam) o PR e registram `review`. `--force` é removido.
2. O merge é feito pelo humano **no GitHub**, não por botão no painel. Motivos: (a) a revisão só tem valor vendo o
   diff, os checks e os comentários, que estão no GitHub; (b) o servidor do painel continua sem poder de escrita no
   repositório (menor superfície, coerente com os limites de autonomia); (c) evita duas portas de merge com regras
   divergentes. Um botão "Aprovar e integrar" fica como evolução, condicionado a proteção de branch.
3. A integração é **detectada** consultando o PR (`gh pr view`): `pending.py` só lista mudanças de estado (merge ou
   fechamento), e o plantão registra `delivered` ou `review-rejected` via `gitflow.py review-sync`. PR fechado sem
   merge é devolução, com o mesmo ciclo de correção e reauditoria.
4. Releases seguem a mesma regra; tag, GitHub Release e back-merge acontecem em `release-publish`, depois do merge
   humano, com a tag no merge commit.
5. A issue da demanda deixa de fechar no G3 APPROVE e passa a fechar em `delivered`.

## Consequências
- (+) Controle humano explícito sobre o que entra em `develop`/`main`; rastreabilidade G3 → PR → merge commit no log.
- (+) Estados "Em revisão", "Entregue" e "Devolvida pelo revisor" visíveis no painel e na issue.
- (−) Entrega depende da disponibilidade do revisor (lead time maior).
- (−) Detecção por consulta ao GitHub (latência de um ciclo do plantão; depende de `gh` autenticado).
- (−) Mudança de comportamento em `gitflow.py` exige atualizar `git-flow.md` e `AGENTS.md`.

## Alternativas consideradas
- **Botão de merge no painel** (`gh pr merge` pelo servidor): um clique a menos, mas merge sem ver o diff e servidor com poder de escrita.
- **Branch protection com aprovação obrigatória**: o PR é aberto pela conta do próprio humano, que não pode aprovar o próprio PR; ficaria bloqueado.
- **Webhook do GitHub para detectar merge**: exige endpoint público; desproporcional ao ambiente local.
- **Manter merge automático com notificação**: contraria a definição de "entregue" dada pelo humano.
