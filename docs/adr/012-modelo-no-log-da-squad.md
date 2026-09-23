# ADR-012: Modelo de IA registrado por execução e por evento da squad

**Status**: Aceito (2026-09-23, Arquiteto) — demanda D9 (`174084ec85d0`). Contrato: `docs/contracts/ui-modelo-por-agente.md`.
(ADR-010 já está reservado pela D6 em outra branch.)

## Contexto
O humano quer ver, na demanda, o ID exato do modelo (e o fornecedor) usado por cada agente, em execuções, resumo e
linha do tempo. Hoje o log (`decisions.jsonl`) não tem modelo; `.squad/runs/*.json` só tem o runner, que o servidor
expõe como `model` (errado); subagentes Claude Code saem com `model` vazio, embora a transcrição traga
`message.model`. A squad é multi-fornecedor (Claude Code, Codex), então o mecanismo não pode depender de um só.

## Decisão
1. Novo campo **opcional** `model` (ID exato) nos eventos do log, via `log.py --model`, com herança de
   `SQUAD_MODEL`; `--run` herda de `SQUAD_RUN`. Aditivo: nenhum consumidor existente quebra.
2. `run_agent.py` registra o modelo **efetivo** (não o alias) lendo-o do que rodou: cabeçalho da saída do Codex;
   transcrição do `claude -p` identificada por `--session-id`. Exporta `SQUAD_RUN`/`SQUAD_MODEL` ao filho.
3. O servidor é a camada de **reconstrução**: preenche modelo de runs/eventos antigos a partir de transcrições e
   runs (somente leitura; o log continua append-only), marcando a origem (`modelSource`). O que não se reconstrói
   aparece como "não registrado".
4. Fornecedor é derivado (hint do runtime > prefixo do ID > runner), não gravado como verdade no log.

## Consequências
- (+) Rastreabilidade de qual modelo produziu cada handoff/parecer, útil para auditoria e comparação de fornecedores.
- (+) Retroativo para quase todo o histórico Claude Code e para o run Codex existente.
- (−) Casamento evento↔transcrição é heurístico (agente + título + janela de 120 s); exposto como `modelSource`.
- (−) `runs[].model` muda de semântica (runner → ID); único consumidor (`feedHtml`) é ajustado na mesma demanda.

## Alternativas
- Pedir ao agente que informe o próprio modelo no prompt: não confiável (o modelo pode errar o próprio ID).
- Gravar só o alias do frontmatter: não é o ID exato e não cobre Codex.
- Reescrever o log com o modelo: viola append-only.
