# D17 · servidor da conversa com o Orquestrador → Auditor (G2) · `e1d6eae16073`

**Feito** (ADR-020, contrato `docs/contracts/conversa-com-o-orquestrador.md`, G1-D17 com ressalvas aplicadas):
- `tools/squad/conversa.py`: `build_cmd` (Claude `--tools Read Glob Grep` + `--disallowedTools` de escrita/shell/web/
  subagente + `--strict-mcp-config`; Codex `-s read-only` / `exec resume -c sandbox_mode="read-only"`), `Store`
  (`.squad/conversas/<id>.jsonl`, fsync, 2 000 msgs/4 MB, `recover()` → `interrompida`), `Engine` (1 turno no servidor,
  timeout `SQUAD_CHAT_TIMEOUT_S`, cancelar mata o grupo, `sessionReset` com as 20 últimas mensagens), contexto
  `<dados_da_squad>` ≤ 24 KB mascarado, `validate_proposal` (lista fechada §6.1) e `confirm`/`discard`.
- `tools/squad/server.py`: rotas `/api/conversas*` (§7, SSE §7.1 + `?after=`), `_local_ok` e 32 KB pelo
  `Content-Length` **antes** de ler o corpo; `/api/human` e `/api/demand/control` refatoradas em
  `record_human_decision`/`record_control` sob `LOG_WRITE_LOCK` comum (`append_log`), sem mudar resposta nem evento.
- `docs/squad/prompts/conversa.md`: somente leitura, dados ≠ instrução, formato ```destravar.

**Ressalvas G1**: (1) sem `Read(~/**)`: negações pontuais `~/.ssh`, `~/.aws`, `~/.config`, `~/.claude`, `~/.codex`,
`~/.gnupg`, `~/.docker`, `~/.kube`, `~/.netrc`, `~/.gitconfig`…; (2) `Read(//<DATA_ROOT>/.env)`, `.env.*`, `.git/**`;
(3) resposta do codex passa por `transcripts.mask` + `evidence_rules.mask_text` antes de exibir/gravar e as rotas
devolvem `readIsolation: "reduzida"` + `isolationWarning` (claude: `"restrita"`, `null`). Recomendadas: APPROVE só com
B2/B3 (B1 puro → só OVERRIDE); cwd `.squad/conversas/.sessao/` absoluto; `tools` gravado por resposta separa latência
com/sem leitura.

**Evidências** (scripts em scratchpad, servidor próprio na 7271–7274, dados copiados; nada no log/servidor reais):
- runner simulado: 56/56 (CA-2,3,4,6,8,9,10,11,12,13,14,15,16,17,18,20); CA-22 igualdade byte a byte com o
  `server.py` do HEAD (9 chamadas, status/campos/ordem/valores) + reinício → `interrompida`: 4/4; unitários 12/12
  (codex, env, máscara, CA-19 503 preservando a mensagem, contexto real 9,7 KB).
- runner real `claude` (2 chamadas, `claude-opus-5-5`): `firstTextMs` 2 585 ms / 2 060 ms, `totalMs` 7,5 s / 3,7 s
  (ambas sem ferramenta); 2º turno retomou a sessão e lembrou a 1ª pergunta; pedido de criar `x.txt`, rodar `log.py`,
  commit e ler `.env` recusado: `x.txt` ausente, `decisions.jsonl` e `git status` iguais, canário do `.env` ausente,
  transcrição em `~/.claude/projects/<…--squad-conversas--sessao>` (fora de `transcripts_root()`).
- suítes `tests/squad/` uma a uma: d14 20, d14-qa 19, entrega-por-pr OK, d15 41, d16 38, d16-qa 18, e2e-d15 11 — todas OK.

**Desvios aditivos** (decisão registrada): `readIsolation`/`isolationWarning`/`title` nas respostas; `texto` com
`replace: true` ao (re)conectar; status `erro` sai como `event: erro` com `message`; 409 `turno_em_andamento` traz
`conversa`/`turn`; 503 do envio traz `message`; `404 proposta_nao_encontrada`; `meta-update` `threadStarted` (codex).

**Falta / riscos**: QA — CA-5 (10 perguntas, p50/p95 com e sem ferramenta), CA-7 com leitura real de arquivo não
carregado como instrução (o AGENTS.md entrou como instrução do diretório pai, sem `Read`) e CA-1/23 da UI. O
`CLAUDE.md`/`AGENTS.md` da raiz entram como instruções na sessão do chat (custo de tokens; o prompt da conversa
prevalece). Se o servidor morrer com turno aberto, o processo do runner não é morto (termina sozinho; o turno vira
`interrompida`). `/api/human` e `/api/demand/control` seguem sem `_local_ok` (fora do escopo, §13).
