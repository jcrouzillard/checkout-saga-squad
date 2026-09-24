# ADR-018: Ambiente de teste compartilhado em projeto Compose isolado e atualização incremental do produtivo local

**Status**: Proposto (2026-09-24, Arquiteto — D15 `518f89f27ae8`)
**Numeração**: ADR-015 está reservado para a D12 (PR aberto); 016 é a D13 e 017 a D14. Este é o próximo livre.
**Contrato**: [`docs/contracts/ambiente-de-teste.md`](../contracts/ambiente-de-teste.md).

## Contexto
O humano quer testar cada demanda antes de aprovar o PR (D15) e que, aprovado o PR, o "produtivo local" seja
atualizado. Respostas: **um** ambiente de teste compartilhado com fila; publicação **a pedido do humano**; isolamento
**total** (Kafka, Postgres, observabilidade); produtivo **inalterado e inquebrável**; portas do teste diferentes como
**regra forte**; dados do teste persistem; produtivo roda a `develop`.

Fatos do código que condicionam a decisão:
- `docker-compose.yml` fixa `name: checkout-saga`, todas as portas do host e as tags de imagem
  `checkout-saga/<svc>:local`. Qualquer `docker compose up` em qualquer worktree atinge o produtivo, e um build do
  teste reescreveria as imagens do produtivo (recriadas no próximo `up`).
- Arquivos de override do Compose **somam** listas de `ports`; não servem para trocar portas.
- `tests/e2e/run.sh` já aceita URLs por variável, mas o cenário de reinício chama `docker compose kill` sem `-p` —
  hoje sempre no produtivo.
- O schema é Flyway (migrações só para frente): rollback de imagem após migração nova não é seguro.
- A atualização do produtivo após merge é manual (`docker compose up -d --build` na cópia principal).

## Decisão
1. **Um compose, parametrizado**: portas do host e namespace das imagens viram variáveis com default igual ao valor
   atual (o `config` do produtivo não muda). O teste é o projeto **`checkout-teste`** com
   `--env-file infra/teste/teste.env`, **portas = produtivo + 10 000** (18080-18084, 18090, 15432, 39092, 26686,
   14317/14318, 19090, 13001) e imagens `checkout-teste/*`. Rede e volume ficam separados pelo nome do projeto.
2. **Origem fixa**: worktree dedicado `plankton-teste/` em HEAD destacado no commit do PR; o commit publicado é
   registrado e comparado ao head do PR ("desatualizado").
3. **Uma vaga, fila FIFO, só humano pede**: `tools/squad/testenv.py` (publish/release/reset-data/down/reconcile), com
   guard que valida projeto, portas, imagens e volumes **antes** de qualquer `up`; o Squad Control grava o pedido
   (`test-env-request`, agent `humano`) e dispara o `reconcile`. Liberação automática em `delivered`/`review-rejected`/
   cancelamento publica o próximo da fila. Apagar dados só com confirmação digitada.
4. **Estados**: "Pronto para testar" (PR aberto + publicado e saudável) entra entre "Revisão (PR)" e "Entregue";
   "Na fila do teste", "Publicando", "Falha ao publicar" como status; o ambiente tem `livre/publicando/ocupado/
   falhou/divergente`. Oito tipos de evento novos, só acréscimo.
5. **Produtivo atualizado automaticamente após o merge**, por `tools/squad/prod.py update` chamado depois do
   `delivered`: rebuild e recriação **só dos serviços alterados** (`--no-deps`), build antes de tocar containers,
   espera de `healthy`, rollback por retag da imagem anterior quando não há migração nova, e lista fechada de comandos
   proibidos (`down`, `-v`, `prune`, `--force-recreate` de infraestrutura, `--remove-orphans`).

## Consequências
- (+) Produtivo e teste coexistem sem colisão de porta, imagem, volume ou rede; o isolamento é **verificável** por
  impressão digital do produtivo (ids, `StartedAt`, volumes, hashes de config) antes/depois.
- (+) O humano testa exatamente o commit do PR; a rastreabilidade demanda → PR → commit testado → merge → commit
  implantado fica no log.
- (+) Corrige um risco existente: `docker compose` sem `-p` e o e2e de reinício deixam de poder atingir o produtivo.
- (−) Dobra o consumo de memória com os dois ambientes no ar; mitigado por aviso e por `teste-derrubar`.
- (−) Dados persistentes do teste podem conflitar com migrações de outra demanda (Flyway); a falha é detectada e o
  humano decide apagar.
- (−) Automatizar a atualização do produtivo cria um caminho de escrita nele; mitigado pelos guards, lock, diff por
  caminho e rollback — com migração nova, a falha escala para o humano (B5) em vez de reverter.
- (−) Mudança em quatro donos (DevOps, Orquestrador, Frontend, QA), sequencial: compose/`teste.env` primeiro.

## Alternativas consideradas
- **Override `docker-compose.teste.yml`**: listas de `ports` se somam (o teste herdaria 8080…); exigiria `!override`
  em cada serviço e ainda deixaria as tags de imagem colidindo. Rejeitada.
- **Um ambiente por PR** (portas por slot): contraria a resposta 1 e multiplica memória. Rejeitada.
- **Subir o teste a partir do worktree da feature**: alvo móvel (agentes editando, console em bind mount). Rejeitada.
- **Publicação automática ao abrir o PR**: contraria a resposta 3 (o humano escolhe). Rejeitada.
- **Produtivo só por comando manual**: mais simples, mas contraria "quando aprovado o PR, é atualizado"; mantido como
  alternativa (`make prod-atualizar`, `SQUAD_PROD_AUTOUPDATE=0`).
- **`docker compose up -d --build` completo no produtivo**: recria tudo a cada merge e não tem ponto de retorno.
  Rejeitada.
- **Portas por faixa própria (ex. 28080…)** em vez de +10 000: funciona, mas a regra "+10 000" é memorizável,
  verificável por fórmula e não colide com nada ocupado hoje (checado: 13001-39092 livres, 3000/4009/5439 são de
  outros projetos). Escolhida a +10 000.
