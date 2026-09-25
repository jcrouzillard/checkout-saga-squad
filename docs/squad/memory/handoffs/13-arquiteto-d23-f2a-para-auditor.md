# Handoff 13 — Arquiteto → Auditor/Orquestrador: D23 (F2a) contrato ajustado às ressalvas do G1

Demanda: D23 `6450aecde7f9` · worktree `plankton-d23` (branch da D23) · parecer de origem: `docs/squad/gates/G1-D23.json`.

## O que foi feito
- `docs/contracts/f2a-resolvedor-de-produto.md` ajustado às 5 ressalvas do G1 (APPROVE com ressalvas, 0,87):
  1. **7º cálculo posicional**: `squad-control/index.html:1919` (`demandInfo`, `D${index + 1}` → `info.code`) entra no
     §4.4 (agora 7 cálculos), no §4.6 e no escopo do Frontend (§1: `demandCode`, `findDemand`, `demandInfo`); CA-13 cobre lista/rota/alertas.
  2. **D24 já existe** (`cf7a120591b0`): tabela congela **D1–D24** (§4.3, `lastTaskId`, `--until cf7a120591b0`);
     primeira demanda nova = **D25** (§4.2 exemplo, CA-6: D25/D26, consequência 2).
  3. **Branch em voo**: cabeçalho corrigido — D24 `feature/D24-publicar-squad-control` (worktree `plankton-d24`) em voo;
     cita a decisão do Orquestrador `31400c3b82d1` (quem integrar por último traz a develop). Risco novo no §9.
  4. **Apelidos**: `tests/ui/checklist-cancelar-d7.md` e `tests/ui/checklist-entrega-por-pr-d8.md` nas `sources`; varredura inclui `tests/**/*.md`.
  5. Este brief.
- Respostas-padrão do Auditor registradas no contrato: tabela gerada no worktree sobre cópia do log e **regenerada
  antes do PR** com o último id informado no PR (§4.5); varredura de transcrições de **todos os worktrees** com cache
  30 s (§6); **P1** como restrição da F5 (§9); **sem apelidos no painel** nesta fase (§4.6/§7).
- Errata do ADR-024 §11 E3: congelamento passa a D1–D24.

## Onde está
- `docs/contracts/f2a-resolvedor-de-produto.md`, `docs/adr/024-plataforma-multiproduto.md` (§11 E3) — no worktree, não commitados.

## O que falta
- Orquestrador: commitar no worktree e seguir para a implementação (Orquestrador/Frontend/QA conforme §1).
- `freeze-codes` deve ser refeito antes do `feature-finish` se houver D25+ na janela.

## Riscos
- Conflito com a D24 em `server.py`/`index.html` (mitigado pela ordem de integração).
- A citação da resposta Q2 no cabeçalho diz "D1–D23" (texto do humano); a nota de congelamento logo abaixo esclarece D1–D24.
