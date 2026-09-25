# Handoff — Arquiteto → Auditor · D24 (cf7a120591b0) · ADR-025 publicação do Squad Control

**Feito**: `docs/adr/025-publicacao-do-squad-control.md` (Proposto) e `docs/contracts/publicacao-do-squad-control.md`
(22 CAs) na branch `feature/D24-publicar-squad-control`. Log: decisão `58e53a667638`, handoff `a6f81716402c`.

**Decisões**: supervisor `tools/squad/publisher.py` (stdlib, trava de arquivo, logs em `.squad/squad-control/`);
gatilhos: merge detectado pelo próprio supervisor (consulta à develop remota a cada 15 s, só fast-forward, só reinicia
se mudar `tools/squad/` ou `squad-control/`), botão "Publicar Squad Control" (pedido em arquivo) e subida do supervisor;
travas do ADR-018; candidato em outra porta com dados sintéticos antes da troca; saúde pós-troca (commit novo em 20 s,
estável por 10 s); rollback pelo worktree `plankton-squad-prev`; ponto seguro pelo `busy` de `/api/conversas`
(automático espera 20 s com contagem; botão oferece "agora" ou "quando terminar", até 10 min); resposta em andamento
vira "interrompida pela publicação" com "Reenviar"; a tela recarrega sozinha se não houver rascunho; eventos
`squad-publish-requested`, `squad-updated`, `squad-update-failed`, `squad-server-crashed`; `/api/squad-control/publication`
e `publication` no `/api/live`.

**Descoberta**: o `review-sync` do plantão (ciclo de 180 s + LLM) não cumpre o prazo de 1 min; por isso o supervisor
detecta o merge. O `review-sync` segue registrando o `delivered`.

**Sobreposição com a D23**: sem mudanças em `gitflow.py`/`run_agent.py`; três pontos pequenos em `server.py` que
delegam a `publication.py`.

**Pendências**: change-request ao DevOps para o `Makefile` (`make squad` sobe o supervisor; `make squad-primeiro-plano`
mantém o modo antigo) — registrado pelo Orquestrador.

**Perguntas ao humano** (padrão sugerido entre parênteses): (1) limite de 20 s do ponto seguro (sim);
(2) recarga automática sem rascunho (sim); (3) supervisor encerrar o servidor atual não supervisionado na 1ª adoção
(pedir confirmação no botão); (4) sem volta automática após reboot nesta demanda (sim); (5) publicador avançar a develop
antes do `delivered` (sim).
