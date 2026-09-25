# Handoff 17 — Arquiteto → Auditor (D25 `233278d0cfa9`, revisão do ADR-024, gate G1)

**Worktree**: `plankton-d25` (`feature/D25-revisao-adr-024`), sem commit. Só documentação; nada foi implementado nem movido.

## O que foi feito
- **ADR novo** `docs/adr/026-sentido-da-separacao-e-memoria-no-neon.md`. Ele substitui ADR-024 §4.1, §4.3, §4.4.2,
  parte do §4.12 e do §4.13, as linhas F3/F4 do §6 e o item de banco do §8. A escolha de um ADR novo está justificada
  no cabeçalho: evita conflito com a errata §11 da D23 e preserva o texto aprovado no G1-D22.
- `docs/adr/024-plataforma-multiproduto.md`: só avisos de substituição (cabeçalho e títulos §4.1, §4.3, §6 e §7).
- `docs/contracts/plataforma-multiproduto-mapa.md`: destinos revistos, tabela H0 (pontos alterados), H1–H10 (novos) e
  contagem de 84 pontos.
- A simulação de merge com `feature/D23-…` e `feature/D24-…` não deu conflito.

## Decisões recomendadas (a final é do humano, ADR-026 §8)
1. **Sentido B**: o produto sai para `checkout-saga`; o repositório atual vira `squad-platform` (renomeado, nome antigo
   nunca reutilizado). Comparação em 13 critérios no §3.1.
2. **Neon com cache local** (§4): leitura sempre do cache; fila = `mseq > acked`; push `ON CONFLICT (id) DO NOTHING`
   com verificação de hash; pull por `arrival_seq`; tabela de sentido → alerta `sync-conflict` e bloqueio da demanda;
   papel só `SELECT, INSERT` + gatilho; encadeamento por máquina; `psycopg` 3 como exceção isolada; limites do plano
   gratuito marcados "a confirmar" (§4.8).
3. **Exportação congelada** `docs/evidencias/squad/<versão>/` + `verificar.py` stdlib + tag `entrega-desafio-<data>`
   (§5). A tabela dos itens do §14 está no §5.2.

## O que verificar no G1
- Cada ponto tem decisão, alternativas e impacto em F3a/F3b/F3c/F4 (§3.1, §4.11, §5.3, §6).
- Critérios S1–S9 da sincronização (§4.12): offline, sem duplicar, duas máquinas, conflito, integridade, máquina nova,
  segredo, máscara e legado.
- Riscos novos (§7): rede, Neon, segredo, sincronização, mudança do Compose e nome do repositório.
- Nenhuma string de conexão nos arquivos (só o **nome** da variável `SQUAD_MEMORY_URL_<ID>`).

## Riscos e pontos abertos
- Os números do Neon não foram verificados (sem acesso à web). O §4.8 diz como confirmar cada um.
- O limite do segredo está declarado: um runner com Bash consegue ler o `.env` (§4.6, Q-B4).
- Mudar o produtivo do checkout de diretório na F4 exige uma janela do humano (§3.1, §6 F4 (c)).
- O redirecionamento do GitHub após a renomeação está "a confirmar" na documentação dele.
- Perguntas Q-A1…Q-C2 (§8): Q-A1 e Q-B1 bloqueiam F4 e F3b, respectivamente.
