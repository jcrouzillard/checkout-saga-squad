# Handoff 12 — Arquiteto → Auditor/Orquestrador (D22 fase 1, `b26da7851764`)

## O que foi feito
- ADR-024 (plataforma multiproduto) e mapa de acoplamento, ajustados às ressalvas do G1-D22 ciclo 1
  (APPROVE com ressalvas, 0,75) **sem novo ciclo de gate**.
- Worktree `plankton-d22`, branch `feature/D22-plataforma-multiproduto` — alterações **commitadas na branch da D22** (commit é do
  Orquestrador).

## Onde está
- `plankton-d22/docs/adr/024-plataforma-multiproduto.md` — §10 lista cada ressalva e a seção que a trata.
- `plankton-d22/docs/contracts/plataforma-multiproduto-mapa.md` — 74 pontos (67 + A10, B16, C16–C18, F5, G7);
  PLAT 30 / CFG 22 / MEM 15 / PROD 7; fases F2a 4, F2b 25, F3 17, F4 20, F5 7, sem mudança 1.
- Parecer de origem: `docs/squad/gates/G1-D22.json`.

## Principais mudanças
1. Conversas e anexos (ADR-020/023) ficam em `run:` (fora do git); ADR-020 e ADR-023 **sem mudança** (§4.3).
2. ADR-015/D12 incluído (§3, E2); regra para branches em voo D12/D21 durante F2–F4 (§4.11).
3. Links `blob/…/docs/squad/…` do `github_sync.py` mapeados (F5) com destino por `memory.link_base` (§4.12).
4. `git filter-repo`: pré-requisito do host só em F3/F4, com alternativa só git (fast-export/fast-import) (§4.13).
5. `[env.prod] kind = "compose" | "process" | "none"`; a plataforma é `process` na 7070 (§3).
6. Isolamento: negação gerada dos outros produtos (claude); limitação declarada + opção explícita (codex);
   teste F6 nos dois runners (§4.9).
7. Constituição chega a Codex/Copilot/Devin por bloco **gerado** no `AGENTS.md` do produto (§4.5).
8. F2 dividida em F2a (resolvedor, `code`, `SQUAD_LOG`, transcrições) e F2b (valores para o cadastro) (§6).
9. §9: **Q2 bloqueia a F2**; **Q4 antes do G1 da F3**.

## O que falta
- Humano: aceitar o ADR e responder o §9 (Q2 primeiro; Q3 junto; Q4 antes da F3).
- Orquestrador: commitar na branch da D22 e abrir a F2a como demanda após a Q2.

## Riscos
- Os dois exemplos TOML do §3 foram validados com `tomllib`; campos definitivos só no contrato da F2a/F2b.
- Com codex, a leitura entre produtos continua possível — é limitação declarada, não resolvida.
