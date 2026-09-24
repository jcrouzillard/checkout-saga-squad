# ADR-014: Consumo da IA lido somente da fonte real do provedor

**Status**: Aceito (2026-09-23, Arquiteto — D11 `642a73cb38e5`)

## Contexto
A D11 pede, fixo no topo das telas de Operação e Governança do Squad Control, o consumo das IAs da squad
(janela de 5 h e semanal, % usado e quanto falta). O humano decidiu: (1) Claude Code e Codex **separados**, sem somar;
(2) **somente a fonte real do provedor** — proibida estimativa por tokens; (3) atualizar a cada polling do painel e,
se indisponível, mostrar o **último valor** com alerta e hora da coleta.

Investigação nesta máquina (2026-09-23, somente leitura):
- **Codex** (CLI plano *plus*): `~/.codex/sessions/AAAA/MM/DD/rollout-*.jsonl` traz eventos
  `{"type":"event_msg","payload":{"type":"token_count","rate_limits":{...}}}` com `limit_id:"codex"`,
  `primary {used_percent, window_minutes:300, resets_at:<epoch s>}` (5 h) e
  `secondary {used_percent, window_minutes:10080, resets_at}` (7 dias). São os valores que o servidor da OpenAI
  devolve ao CLI. Não há subcomando não interativo de status (`codex --help`); `codex exec` gastaria cota.
- **Claude Code** (2.1.x): não há `rate_limits` nas transcrições `~/.claude/projects/**` nem cache local de
  cabeçalhos `anthropic-ratelimit-unified-*`; não há comando não interativo de uso. A **única** fonte real local é o
  JSON que o Claude Code entrega ao comando de **statusline** a cada atualização:
  `rate_limits.five_hour.{used_percentage, resets_at}` e `rate_limits.seven_day.{used_percentage, resets_at}`
  (`resets_at` em epoch s). O usuário já tem `statusLine` próprio em `~/.claude/settings.json` que lê esses campos.

## Decisão
1. **Codex**: o servidor do painel (`tools/squad/server.py`) lê o último evento `token_count` com `rate_limits`
   não nulo no(s) rollout(s) mais recente(s) de `$CODEX_HOME/sessions` (padrão `~/.codex/sessions`).
2. **Claude Code**: um *tee* de statusline (`tools/squad/statusline_usage.py`) recebe o JSON do Claude Code, grava
   um snapshot mínimo (só números e horários, nunca credenciais) em `<DATA_ROOT>/.squad/usage/claude.json` e
   **encadeia** a statusline já configurada pelo usuário, repassando o mesmo stdin e devolvendo a saída dela
   inalterada. Nada substitui a statusline do usuário.
3. Sem fonte → o provedor aparece como **indisponível**; nenhum número é inventado ou estimado.
4. O dado é exposto no campo `usage` de `GET /api/state` (já consultado a cada 3 s) e em `GET /api/usage`.

## Consequências
- (+) Números iguais aos que cada CLI mostra; nenhuma chamada extra (paga) a modelo; nada de segredo sai do disco.
- (−) Os valores só se renovam quando a ferramenta está em uso: Codex quando uma sessão emite `token_count`;
  Claude Code quando uma sessão **interativa** redesenha a statusline (execuções `claude -p` não acionam
  statusline). Por isso o contrato mostra a hora da coleta e o alerta de desatualizado/indisponível.
- (−) Formatos são internos aos CLIs e podem mudar; a leitura é tolerante (campo ausente → indisponível).

## Alternativas
- Estimar pelo total de tokens das transcrições — **vetada** pelo humano (resposta 2).
- Chamar a API do provedor para ler cabeçalhos de rate limit — gasta cota/credencial e exige token no servidor.
- Substituir a statusline do usuário — quebraria a preferência dele; o encadeamento preserva.
