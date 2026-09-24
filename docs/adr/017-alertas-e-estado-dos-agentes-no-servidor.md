# ADR-017: Bloqueios, avisos e estado dos agentes calculados no servidor, com canal leve ao vivo

**Status**: Proposto (2026-09-24, Arquiteto — D14 `1e3d3c894630`)
**Numeração**: ADR-015 está reservado para a D12 (`feature/D12-evidencias-na-demanda`, PR #104, ainda não integrado);
ADR-016 é a D13. Este é o próximo livre.

## Contexto
O humano pediu (D14) que impedimentos, bloqueios e avisos estejam na primeira tela, que o estado de cada agente e de
cada demanda se atualize sozinho em até **3 s** e que, ao olhar um integrante, se veja o que ele realmente está fazendo e
se há espera de ação — dele, de subagentes ou do humano. Hoje:
- a regra de "precisa de humano" existe duas vezes no cliente, com resultados diferentes (`gateNeedsHuman` × `classify`);
  o 3º ciclo de autocorreção não é calculado (o campo `cycle` só existe nos arquivos de gate);
- não há noção de "agente sem progresso" nem de "quem espera quem"; o Orquestrador é lido só pelas delegações;
- o painel baixa `/api/state` inteiro (1,28 MB, 0,3–0,75 s de montagem) a cada 3 s — o pior caso passa de 3 s.

## Decisão
1. **Regras no servidor.** `tools/squad/server.py` calcula `alerts[]` (bloqueios B1–B4, avisos A1–A3), `agents[]`
   (estado, tarefa, passo, ferramenta atual, arquivos/comandos recentes, espera de ação, subagentes) e o histórico de
   alertas fechados, a partir do log, dos arquivos de gate e das transcrições. A UI só exibe. Regras, limites
   (`stalledSeconds = 600`, justificado pelo p99,9 = 501 s da duração de ferramentas) e esquemas estão em
   [`docs/contracts/ui-governanca-squad-control.md`](../contracts/ui-governanca-squad-control.md) §5, §7, §9.
2. **Nada novo é gravado no log por causa de alertas**: são derivados e reprodutíveis (auditoria por reconstrução).
   Único acréscimo ao log: campo opcional `step` (`log.py --step`) em `progress`/`handoff`.
3. **Canal leve `GET /api/live`** (≤ 64 KB, p95 ≤ 300 ms) consultado a cada 1,5 s; `/api/state` só quando
   `version` muda ou a cada 15 s. Orçamento do fato à tela ≈ 2 s. Sem WebSocket/SSE (stdlib, sem dependência nova,
   `ThreadingHTTPServer` atual).
4. **Conciliação de categorias**: gate com confiança < 70% **sem** decisão humana é bloqueio (AGENTS.md torna a
   intervenção obrigatória — hierarquia de verdade nº 2); **depois** da decisão fica como aviso de risco aceito.
5. **Tema próprio "Grafite"** com tokens claro/escuro de contraste AA medido; severidade e estado sempre com ícone +
   palavra + cor.

## Consequências
- (+) Uma regra auditável, igual para UI, notificações e qualquer consumidor futuro; "quem age" (`owner`) explícito.
- (+) C2 cumprido com folga e menos tráfego (live pequeno; estado pesado só quando muda).
- (+) Detalhe real de cada integrante, incluindo o Orquestrador e suas esperas por subagentes/humano.
- (−) `server.py` cresce (regras + caches por mtime) e precisa de testes unitários por regra com log sintético.
- (−) Heurísticas sobre transcrições não veem prompts de permissão do terminal; o aviso A2 orienta "verificar o terminal".
- (−) Os limites (600 s, 180 s, 70%) viram política: mudá-los exige atualizar o contrato.

## Alternativas consideradas
- **Calcular tudo no cliente** (como hoje): mantém a divergência de regras, exige baixar o estado inteiro e não serve a
  outros consumidores (plantão, `pending.py`). Rejeitada.
- **Gravar eventos `alert-open/alert-close` no log**: auditoria explícita, mas duplica fatos derivados, cria risco de
  divergência e escrita concorrente do servidor no log. Rejeitada; o histórico é reconstruído.
- **SSE/WebSocket**: latência menor, mas sem ganho perceptível sobre 1,5 s e com mais complexidade no servidor stdlib.
  Rejeitada por ora.
- **Polling de `/api/state` a 1 s**: cumpriria C2, mas ~1,3 MB/s e 0,3–0,75 s de CPU por consulta. Rejeitada.
