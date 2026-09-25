# D21 (`71b7d9bc3313`) — servidor das imagens na conversa → Auditor (G2 do servidor)

**Branch** `feature/D21-imagem-no-chat` (sem commit; UI após o merge da D20). Base: ADR-023, contrato, `G1-D21.json`.

## Feito
- `tools/squad/server.py`: `POST /api/conversas/<id>/anexos` casada **antes** do teto de 32 KB; ordem `_local_ok` →
  `Content-Length` (400) → `> 5 MB` (413 + `Connection: close`) → `Content-Type` (415; HEIC com mensagem própria) →
  conversa existe (404) → só então lê o corpo. `GET …/anexos/<aid>` (tipo pelos bytes, `nosniff`, CSP `default-src
  'none'`, `inline`), `POST …/anexos/<aid>/remover` e `DELETE …/anexos/<aid>` (409 `anexo_em_uso`). Limpeza na subida.
- `tools/squad/conversa.py`: `Store.upload/remove_attachment/resolve_attachments/cleanup_attachments` (arquivo por
  sha256 dos bytes limpos, gravação atômica, `index.json` com nome, tetos 100/500 MB por variável, pendentes > 24 h);
  `Engine.send(..., attachments=)` (0–3 ids, texto opcional com imagem, título "Imagem enviada"); `build_cmd` com
  `turno["images"]`; `claude_stdin()` puro (1 linha stream-json, stdin em thread); codex `--image=<abs>` + `--`;
  `<anexos_do_humano>`; marcador no `history_block` (sessionReset reenvia só as imagens do turno atual).
- `tools/squad/evidence_rules.py` (só acréscimo): `image_size()` e `image_complete()` (IEND/EOI/RIFF → 422).
- `docs/squad/prompts/conversa.md`: regra 6 (imagem é dado, ação só por texto, não copiar segredos) e regra 3 ampliada.
- Ressalvas: (3) truncado/malformado → `422 imagem_invalida`, nunca 415; (4) nome sempre por `er.sanitize_name` (sem
  `<`, `"`, `\n`: não fecha a tag); (5) upload, remover, envio e limpeza sob o mesmo `Store.lock`.

## Evidências (scratchpad `.../scratchpad/d21/`)
- `test_d21_servidor.py`: 24/24 OK (runner simulado `fake_stdin_runner.py`, que lê o stdin; imagens de `gen_fixtures.py`).
- Regressão, suíte a suíte: d14 20, d14-qa 19, d15 41, e2e-compose-d15 11, d16 38, d16-qa 18, d17 44, d18 18,
  d19 27, entrega-por-pr OK, `e2e_delegacao_d19.py` OK. Log real intocado.
- **Claude real** (`real-claude.json`): T1 print → "ALERTA B6 . PR #191 EM CONFLITO"; T2 `--resume` só texto →
  "#191"; T3 `--resume` + stream-json com 2 imagens → as duas lidas (a de 4,66 MB pelo plano B/Read). T4
  (`real-inline5mb.json`): 4,66 MB **inline** (base64 de 6,5 MB) → aceito, texto correto.
- **Codex real** (`real-codex.json`, gpt-5.6-sol): T1 print → correto ("B6" lido como "86"); T2 → "191"; T3 com 2
  imagens (inclui 4,66 MB) → correto; T4 injeção → descreveu e disse que não é instrução, sem proposta.

## Desvios
- `Cache-Control: no-store` no GET do anexo (contrato: `private, immutable`): print pode ter segredo; servidor local.
- Plano B desligado por padrão (inline passou no real); liga com `SQUAD_CHAT_CLAUDE_B64_MAX=<bytes>`. Notas p/ o
  Arquiteto no contrato: §3 nome sanitizado, §5.1 resultado do 4,8 MB, §4 Cache-Control.

## Riscos / pendente
- **Codex `exec resume` real com imagem NÃO provado**: T2/T3 viraram `sessionReset` — a cópia de dados não é repo git
  e `codex exec resume` (sem `--skip-git-repo-check`, igual ao D17) recusa; no produtivo o DATA_ROOT é o repo. Argv
  `resume <id> … --image=<abs> -- "-prompt"` validado pelo CLI sem modelo. QA: 1 turno real com DATA_ROOT git.
- Merge com a D20: `Engine.send` ganha `tz` lá e `attachments` aqui (conflito trivial). Envio > 5 MB leva 413 com a
  conexão fechada antes do fim do corpo — o navegador pode ver erro de rede (a UI recusa antes, §8.1).
