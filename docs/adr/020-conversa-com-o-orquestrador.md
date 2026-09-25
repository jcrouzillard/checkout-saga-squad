# ADR-020: Conversa direta com o Orquestrador — sessão dedicada somente leitura, histórico fora do log e destravar por confirmação humana

**Status**: Proposto (2026-09-24, Arquiteto — D17 `e1d6eae16073`)
**Numeração**: 015 reservado para a D12; 016–019 são D13–D16. Este é o próximo livre.
**Contrato**: [`docs/contracts/conversa-com-o-orquestrador.md`](../contracts/conversa-com-o-orquestrador.md).

## Contexto
O humano quer um **canal direto** com o Orquestrador dentro do Squad Control: uma opção abre um painel de conversa,
ele pergunta e recebe a resposta **na hora**, numa **sessão dedicada** (não pelo plantão). O Orquestrador **só
responde**, sem efeito colateral, com uma exceção: **destravar uma fase devolvida ou travada**. O histórico continua
depois de recarregar e fica num **lugar apartado** (fora de `decisions.jsonl`), **não ligado a demanda**.

Fatos verificados no código:
- `run_agent.py` grava `.squad/runs/*.json` e dois `progress` no log a cada execução; o Squad Control mostra isso como
  trabalho da squad. `triage.py` usa `--read-only` (`claude -p --allowedTools Read Glob Grep` / `codex exec -s read-only`).
- O servidor lê as transcrições de `~/.claude/projects/<slug de DATA_ROOT>/*.jsonl`; uma sessão `claude -p` com cwd na
  raiz do repositório cai nesse diretório e pode ser confundida com execução da squad.
- `claude -p` aceita `--session-id`, `--resume`, `--tools`, `--disallowedTools`, `--add-dir`,
  `--output-format stream-json --include-partial-messages`, `--strict-mcp-config`, `--append-system-prompt`;
  `codex exec` aceita `--json`, `-s read-only` e `codex exec resume <id>`.
- "Destravar" já existe: decisão de gate `POST /api/human` (`type: human`, `APPROVE|RETURN|OVERRIDE`) fecha B1/B2/B3
  (`alerts.Rules._eval_gate`), e `POST /api/demand/control` `resume` tira a demanda de `pause` (plantão §A).
  `/api/human` hoje **não** aplica `_local_ok` (só as rotas de bug aplicam).
- O servidor é `ThreadingHTTPServer` (uma thread por conexão): SSE é viável sem dependências.
- `.squad/` é ignorado pelo git; o repositório é **público**.

## Decisão
1. **Sessão dedicada, processo por mensagem com retomada**: cada pergunta dispara um processo do runner
   (`SQUAD_CHAT_RUNNER`, padrão `SQUAD_RUNNER`) que **retoma a sessão** da conversa (`claude -p --resume <uuid>` /
   `codex exec resume <thread>`), fora do plantão e fora de `run_agent.py`. Um módulo novo `tools/squad/conversa.py`
   monta o comando, o contexto e o armazenamento. O histórico gravado por nós é a fonte da verdade: se a sessão do
   fornecedor se perder, uma nova é aberta com o histórico recente injetado (`sessionReset`).
2. **Streaming por SSE** do servidor para o painel (`text/event-stream`), com leitura incremental da saída
   `stream-json`/`--json` do runner. Um turno ativo por vez em todo o servidor (`409` para o segundo); timeout de turno
   (120 s, `SQUAD_CHAT_TIMEOUT_S`) e cancelamento pelo humano (mata o grupo de processos). Latência medida e gravada
   por resposta (`firstTextMs`, `totalMs`).
3. **Somente leitura por construção**: ferramentas **só** `Read`, `Glob`, `Grep` (Claude: `--tools` + `--disallowedTools`
   de escrita/shell/web/subagente + `--strict-mcp-config` sem MCP; Codex: sandbox `read-only`); cwd dedicado
   `.squad/conversas/.sessao/` (transcrições caem noutro diretório e **não** viram execução da squad) com
   `--add-dir` da raiz; ambiente do filho por **lista de permissão** (sem `GH_TOKEN`, `GITHUB_TOKEN`, `SQUAD_RUN`,
   `SQUAD_MODEL`); nada é gravado em `decisions.jsonl`, `.squad/runs/` nem `docs/squad/inbox/` pela conversa.
4. **Destravar fora do modelo**: o modelo apenas **propõe** (bloco estruturado no fim da resposta). O servidor valida a
   proposta contra o estado atual (lista fechada de estados destraváveis), mostra um cartão com botão **Confirmar**, e
   só na confirmação do humano grava **o mesmo evento** das rotas existentes (`human` ou `control resume`), pela
   **mesma função** do servidor, com o único campo a mais `via: "conversa"`. Destraváveis: gate com último parecer
   sem decisão humana posterior (B1/B2/B3) → as ações que o painel oferece para ele, exceto `RETURN`; demanda com
   último controle `pause` → `resume`. Nada mais.
5. **Armazenamento apartado e local**: `.squad/conversas/<id>.jsonl` (append-only, um arquivo por conversa, **fora do
   git**), várias conversas, sem vínculo a demanda, sem retenção automática. Não passa por `evidence_rules` (não é
   evidência nem vai ao git); o que vai **para o modelo** (estado da squad) é mascarado.
6. **UI**: botão fixo "Conversar com o Orquestrador" no cabeçalho (não é o 6º item do menu do ADR-016: é ferramenta
   transversal), painel lateral não modal aberto por parâmetro de rota `conversa=<id>` (sobrevive a F5 e Voltar), com
   estados explícitos e anúncio acessível só na conclusão.

## Consequências
- (+) Canal direto e imediato, independente do plantão e do fornecedor; o humano vê a resposta chegando.
- (+) Garantia de "sem efeito colateral" verificável por teste (comando montado, hash do log, `git status`, runs).
- (+) O destravar não cria caminho paralelo: mesma função, mesmo evento, mesmas regras; o plantão não muda.
- (+) Conversas livres não vão para um repositório público.
- (−) Processo por mensagem paga a partida do CLI (≈ 1–3 s) a cada pergunta; meta medida (contrato §8) e, se não
  atingida, evolução para processo persistente (alternativa B) sem mudar a API.
- (−) Histórico só na máquina da cópia principal (não versionado, não compartilhado); perder `.squad/` perde as conversas.
- (−) O Orquestrador do chat não tem a memória de trabalho do plantão: responde pelo estado registrado (log, gates,
  alertas, arquivos). A UI diz isso.
- (−) Custo de tokens por pergunta (contexto injetado a cada turno, limitado a 24 KB).

## Alternativas
| Alternativa | Por que não |
|---|---|
| A. Mensagem via plantão (evento no log, resposta no próximo ciclo) | contraria "na hora" e "não pelo plantão" (resposta 1) e poluiria o log |
| B. Processo persistente (`claude -p --input-format stream-json` aberto) | menor latência, mas só Claude tem o modo; morre com o servidor e exige supervisão; fica como evolução se a meta de latência falhar |
| C. `run_agent.py --read-only` | grava `.squad/runs` e `progress` no log: a conversa apareceria como trabalho da squad (contraria resposta 4) |
| D. API do fornecedor direto (HTTP) | exige chave no servidor e quebra a independência de runner; o CLI já está autenticado |
| E. Polling incremental em vez de SSE | mais simples, porém 300–1500 ms a mais por trecho; mantido só como recuperação após recarregar |
| F. Modelo grava o destravar (ferramenta `Bash log.py`) | efeito colateral decidido pelo modelo; viola a resposta 2 e abre injeção de prompt vinda do log |
| G. Conversas em `docs/squad/conversas/` (git) | repositório público e histórico permanente de texto livre; exigiria máscara e confirmação a cada mensagem |
| H. Conversa única contínua | contexto cresce sem limite e encarece cada turno; várias conversas com a última aberta por padrão atendem igual |
| I. Destravar também B4, B5, A2 e A3 | B4 exige respostas do humano à triagem; B5 exige ação técnica; A2 não tem evento humano existente; A3 é merge no GitHub (ADR-011) |
