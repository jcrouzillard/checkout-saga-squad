# Contrato — Executor e modelo por agente (D26, `50366913d891`, tipo operação)

> Decisão: [ADR-027](../adr/027-executor-e-modelo-por-agente.md). Não toca contratos do checkout (eventos, API dos
> serviços). Implementar **depois do merge da D24** (ADR-025), que também altera `server.py`, `log.py` e `index.html`.
> Termos: **executor** = CLI que roda o agente (`claude` = Claude Code, `codex` = Codex CLI); **modelo** = ID ou alias
> pedido ao executor; **papel** ∈ `orquestrador, arquiteto, backend, devops, observabilidade, frontend, qa, auditor`.

## 1. Donos por arquivo
| Dono | Arquivos | O quê |
|---|---|---|
| **Orquestrador** | `tools/squad/executores.py` (novo) | resolvedor, CLI, checagem, gancho `guard-agent` (§4, §5, §6, §8.6) |
| **Orquestrador** | `tools/squad/gate.py` (novo) | `record`: grava `docs/squad/gates/<G>-<n>.json` e o evento `gate` a partir do bloco `parecer` (§7.3) |
| **Orquestrador** | `tools/squad/run_agent.py`, `triage.py`, `conversa.py`, `plantao.sh`, `alerts.py`, `log.py`, `server.py`, `product.py` | uso do resolvedor, perfis de permissão, eventos, API, alerta `executor-divergente` |
| **Orquestrador** | `docs/squad/prompts/plantao.md`, `docs/squad/orquestrador.md`, `docs/squad/gates.md` | despacho por `via`; parecer do Auditor gravado pelo chamador |
| **Orquestrador** | `.claude/settings.json` (novo), `.claude/agents/auditor.md`, `AGENTS.md` | gancho `PreToolUse`; Auditor somente leitura; `.claude/**` na tabela de donos (Orquestrador) |
| **Orquestrador** | `docs/squad/products/checkout-saga/product.toml` | tabela `[executors]` (§3.1) |
| **Frontend** | `squad-control/index.html` | tela Executores (§10.1) e bloco da demanda (§10.2) |
| **QA** | `tests/squad/test_executores_d26.py` (novo), `tests/squad/fixtures/d26/**` (atalhos falsos de `claude`/`codex`), `tests/ui/**` | §12 |
| **Arquiteto** | ADR-027 e este contrato | — |

## 2. Estado atual (resumo; detalhes no ADR-027 §1)
`SQUAD_RUNNER`/`SQUAD_MODEL` globais; `SQUAD_CHAT_RUNNER`/`SQUAD_CHAT_MODEL` na conversa; subagentes nativos sempre
Claude; `run_agent` aninhado herda `SQUAD_MODEL` do pai; Auditor via `run_agent` com perfil de escrita.

## 3. Configuração
### 3.1 Cadastro — `product.toml` (revisado por PR; a tela não edita)
```toml
[executors]
allowed = ["claude", "codex"]          # guarda: executores aceitos neste produto (ordem irrelevante)
seed = { runner = "claude" }           # semente do padrão da squad quando o runtime ainda não existe nesta máquina
```
Ausente = `allowed = ["claude","codex"]`, `seed = {runner="claude"}`. O parser da F2a já aceita e ignora a tabela;
`product.py` passa a expor `Product.executors` e `Product.runtime_dir` (hoje `data_root/.squad`; F3:
`$SQUAD_HOME/products/<id>/runtime`). Executor fora de `allowed` → recusado na tela, no CLI e no resolvedor.

### 3.2 Runtime — `<runtime_dir>/executores.json` (por máquina e por produto; gravado só por `executores.py`/servidor)
```json
{
  "schema": 1, "version": 7, "updatedAt": "2026-09-25T20:00:00Z",
  "squad":  { "runner": "claude", "model": null },
  "agents": {
    "orquestrador": { "runner": "claude", "model": "claude-opus-5-5" },
    "arquiteto":    { "runner": "codex",  "model": "gpt-5.6-sol" },
    "backend": null, "devops": null, "observabilidade": null, "frontend": null, "qa": null, "auditor": null
  },
  "policy": { "onUnavailable": "padrao" },
  "codexAck": null
}
```
- `agents.<papel> = null` = **usar o padrão** (herda executor **e** modelo do `squad`).
- `model = null` = **padrão do executor**: no `claude`, o alias `model:` do frontmatter do papel (`opus`/`sonnet`; o
  Orquestrador não tem frontmatter → sem `--model`); no `codex`, sem `-m` (vale o `~/.codex/config.toml`).
- `model` aceito: alias do Claude (`opus|sonnet|haiku|fable|default`) só com `runner=claude`; ID exato com
  `provider_of(ID)` (ADR-012 §3) compatível com o executor (`claude`→Anthropic, `codex`→OpenAI); fornecedor
  desconhecido é aceito com aviso `modelo_fornecedor_desconhecido`; fornecedor incompatível → `modelo_incompativel`.
  Máx. 100 caracteres, `^[A-Za-z0-9._:/\[\]-]+$`.
- `policy.onUnavailable ∈ {"padrao","parar"}`, padrão `"padrao"` (§6.3).
- `codexAck`: `{"by","at","products":[…]}` — exigido (ADR-024 §4.9) só com **2+ produtos cadastrados** para salvar
  qualquer papel em `codex`. Com 1 produto (hoje) é `null` e não é exigido.
- Arquivo **ausente** → criado na primeira leitura a partir da semente e das variáveis antigas (§3.3), com evento
  `executor-config` `via:"migracao"`. Arquivo ilegível/esquema inválido → o resolvedor **falha** (código 4) e nenhum
  agente é acionado; o painel mostra bloqueio "configuração de executores ilegível" (nunca cai num padrão silencioso).
- Gravação: trava `locks_dir/executores.lock` (flock, 5 s), `baseVersion` (≠ `version` → 409 `versao_desatualizada`),
  escrita atômica (tmp + `os.replace`), `version += 1`.
- **Localização única**: `executores.py` resolve o arquivo na **cópia principal** (`testenv.find_main_root`) ou em
  `$SQUAD_ROOT_DATA`; um `run_agent.py` chamado de um worktree usa o mesmo arquivo (nunca um `.squad/` do worktree).

### 3.3 Migração das variáveis
Só na criação do arquivo: `squad = {runner: SQUAD_RUNNER, model: SQUAD_MODEL}`; se `SQUAD_CHAT_RUNNER`/`SQUAD_CHAT_MODEL`
existirem e diferirem, viram `agents.orquestrador`. Depois disso as quatro variáveis são **ignoradas** como
configuração: se definidas com valor diferente do resolvido, `run_agent`/`conversa`/`plantao.sh` escrevem aviso em
stderr e a tela Executores mostra "variável X ignorada". `SQUAD_MODEL` continua existindo **só** como herança
filho→`log.py` do modelo efetivo (ADR-012); `run_agent.py` deixa de lê-la como `--model`.

## 4. Precedência e resolução
```
resolve(papel, demanda?, contexto) =
  1. demanda informada e contexto ∉ {plantao, conversa, triagem}:
       a) último executor-config{scope:"demand", demand, role:papel} com valor ≠ null   → origem "demanda"
       b) executor-snapshot da demanda (cria se não existir, §4.1)                      → origem da foto
  2. agents[papel] ≠ null                                                               → origem "agente"
  3. squad                                                                              → origem "squad"
  (o arquivo sempre existe após a migração; embutido/semente só alimentam a criação)
  depois: checagem (§6) → efetivo = configurado | padrão da squad (fallback) | parar
```
- Contextos que usam a configuração **atual** (sem foto): o ciclo do plantão (papel `orquestrador`), a conversa
  (papel `orquestrador`) e a triagem (papel `arquiteto`, antes da fila). Delegação (D19), gates e todos os passos da
  demanda usam a foto.
- **Troca de executor numa conversa aberta**: vale a partir do próximo turno; com executor diferente do da sessão, o
  turno abre sessão nova no novo executor (o histórico e o contexto injetado continuam; `conversa` grava
  `runner` do turno). Troca só de modelo no mesmo executor: `--resume` com o novo `--model`/`-m`.

### 4.1 Foto da demanda (`executor-snapshot`)
Gravada por `executores.py snapshot --demand <id>` no passo C.2 do plantão (após `feature-start`) ou, se faltar, pelo
primeiro `resolve --demand <id>` fora dos contextos da §4. Conteúdo: os 8 papéis resolvidos (`runner`, `model`,
`source`), `squad`, `policy`, `configVersion`. Uma por demanda (a segunda chamada devolve a existente). Mudar a
configuração geral **não** altera demandas com foto; para isso existe a troca por demanda (§9, §10.2).

## 5. CLI `tools/squad/executores.py`
| Comando | Efeito | Saída / código |
|---|---|---|
| `show [--json]` | configuração, resolvido por papel, estado dos executores | 0 |
| `resolve <papel> [--demand <id>] [--context plantao\|conversa\|triagem\|passo] [--no-snapshot] --json` | `{"role","runner","model","modelArg","source","via","profile","configured":{…},"fallback":null\|{…},"warnings":[]}` | 0 ok · 3 parar (política) · 4 configuração ilegível · 5 executor fora de `allowed` |
| `check [--runner claude\|codex] [--fresh]` | checagem §6.1 | 0 todos ok · 6 algum indisponível |
| `set --scope squad\|agent\|demand\|policy [--role] [--demand] --runner --model --by humano [--ack]` | grava e registra `executor-config` | 0 · 2 validação · 7 recusado (dentro de agente) |
| `apply-all --runner --model --by humano [--ack]` | §9 `aplicar-a-todos` | idem |
| `snapshot --demand <id>` | §4.1 | 0 |
| `guard-agent` | gancho `PreToolUse` (§8.6); lê o JSON do stdin | 0 permite · 2 nega (motivo em stderr) |
| `check-session orquestrador --runner claude` | usado pelo plantão em sessão (§8.5) | 0 · 3 suspenso |
`via = "nativo"` somente se `runner == "claude"` e `model ∈ {null, opus, sonnet, haiku, fable}`; senão `"run_agent"`.
`set`/`apply-all` recusam (código 7) quando `SQUAD_RUN` ou `CLAUDECODE` estão no ambiente ou stdin não é TTY: agente não
muda a própria configuração (proteção contra erro, não contra adversário — ADR-024 §4.9). O caminho do humano é o painel.

## 6. Checagem do executor e política
### 6.1 Checagem
| Executor | Instalado | Login | Versão |
|---|---|---|---|
| `claude` | `shutil.which("claude")` | `claude auth status --json` (código 0 e `loggedIn: true`; `ANTHROPIC_API_KEY` no ambiente também conta) | `claude --version` |
| `codex` | `shutil.which("codex")` | `codex login status` (código 0) | `codex --version` |
- Timeout 5 s por comando; ambiente do filho pela lista de permissão da conversa (`child_env`), mantendo
  `CODEX_HOME` e `CLAUDE_CONFIG_DIR` (é assim que o teste simula "sem login", §12). A saída **nunca** é gravada nem
  exibida (pode conter e-mail/conta): só `{installed, loggedIn, version, checkedAt, detail∈{ok,nao-instalado,sem-login,
  desconhecido,timeout}}`.
- Cache em `<runtime_dir>/executores-status.json`, validade 5 min; `--fresh`/`POST …/checar`/salvar ignoram o cache.
- `desconhecido` (comando de status inexistente ou saída não reconhecida) **não** bloqueia: aviso amarelo.

### 6.2 Na hora de salvar (tela e CLI)
Executor escolhido `nao-instalado`/`sem-login` → a primeira tentativa devolve 409 `executor_indisponivel` com
`warnings[]`; a tela mostra o aviso na linha do papel e o botão "Salvar mesmo assim" reenvia com `acknowledge: true`.
O evento `executor-config` registra `warnings` e `acknowledged: true`.

### 6.3 Na execução (plantão, delegação, gates, triagem, conversa)
Antes de iniciar, `resolve` checa o executor configurado:
- disponível → roda;
- indisponível e `policy = "padrao"` e o padrão da squad disponível → evento `executor-fallback` (`action:"padrao"`),
  roda no padrão; alerta `executor-fallback` (aviso) no painel e na demanda;
- indisponível e (`policy = "parar"` ou padrão também indisponível ou o papel já é o padrão) → `executor-fallback`
  (`action:"parou"`), código 3, **não inicia**; alerta de bloqueio `executor-indisponivel` (regra B8; B8/B9 são os
  próximos livres em `alerts.py` hoje — se a D24 ocupar, usar os seguintes) com ações
  "tentar de novo" e "usar o padrão nesta demanda" (grava `executor-config{scope:"demand"}` com o padrão). A demanda
  não é cancelada nem falha: o plantão retoma no próximo ciclo após a correção.
- **Falha de autenticação na saída** (código ≠ 0 e a saída casa `not logged in|please run /login|401|unauthorized|
  codex login` nas primeiras 50 linhas, **sem** nenhum `progress` do agente depois do "Iniciado") → classificada
  `sem-login`, cache invalidado e aplica a mesma política **uma vez** (nova run com `--fallback-of <run>`).
- Conversa: com `parar`, o envio devolve 503 `executor_indisponivel` (hoje: `runner ausente`); com `padrao`, o turno
  roda no padrão e a resposta traz `fallback`.

## 7. Permissões por papel × executor
Regra: nenhum executor recebe **mais** permissão do que o papel tem no outro; sem equivalente exato, usa-se o mais
próximo que não amplia, e a diferença fica na §7.2.

### 7.1 Matriz
| Papel / contexto | Perfil | Claude Code | Codex CLI |
|---|---|---|---|
| Conversa (Orquestrador) | `leitura` | `--tools Read Glob Grep` · `--disallowedTools Bash Write Edit NotebookEdit WebFetch WebSearch Task Agent` + `claude_deny_paths` · `--strict-mcp-config` sem servidores · `--permission-mode dontAsk` | `exec -s read-only --skip-git-repo-check -c approval_policy="never" -c mcp_servers={}`; resume: `-c sandbox_mode="read-only"` |
| Triagem (Arquiteto) | `leitura` | igual à conversa (troca o atual `--allowedTools`, que só pré-aprova) | igual à conversa |
| Auditor (gates) | `auditoria` | `--tools Read Glob Grep Bash` · `--allowedTools Read Glob Grep "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git status:*)" "Bash(ls:*)"` · `--disallowedTools Write Edit NotebookEdit WebFetch WebSearch Task Agent` + `claude_deny_paths` · `--permission-mode dontAsk` | `exec -s read-only --skip-git-repo-check -c approval_policy="never"` |
| Arquiteto, Backend, DevOps, Observabilidade, Frontend, QA | `escrita` | `--permission-mode acceptEdits --allowedTools Bash Read Write Edit Glob Grep` (como hoje) | `exec -s workspace-write -C <cwd> --add-dir <dir do log> --add-dir <runs_dir> -c sandbox_workspace_write.network_access=true -c approval_policy="never" --skip-git-repo-check` |
| Orquestrador (plantão) | `orquestracao` | igual a `escrita` | `exec -s danger-full-access -c approval_policy="never" --skip-git-repo-check` — **depende do aceite do humano** (Q2); sem aceite, `escrita` + `--add-dir` da cópia principal, do pai dos worktrees, `~/.claude` e `~/.codex`, com o risco da §13 |
| Subagente nativo (sessão Claude Code) | do papel | frontmatter `tools:`; Auditor passa a `tools: Read, Glob, Grep` (+ `Bash(git …:*)` se a versão aceitar padrão no frontmatter; senão o diff vai no prompt) | — (Codex não tem subagentes; papel em `codex` sempre `via=run_agent`) |
`<dir do log>` = pasta de `product.log` (cópia principal). Delegação (D19): perfil do papel com `cwd = worktree`.

### 7.2 Sem equivalente exato
| Claude Code | Codex | Tratamento |
|---|---|---|
| Permissão por ferramenta (`--tools`, `--disallowedTools`) | só sandbox de arquivos/rede | `leitura`/`auditoria` do Codex = `read-only` (nenhuma escrita), o que cobre Write/Edit/Bash de escrita |
| Negação de leitura por caminho (`Read(//…)`) | inexistente: `read-only` lê a máquina toda | **limitação declarada** (ADR-024 §4.9): saída mascarada (`conversa.mask`) antes de gravar/exibir; aviso na tela ao escolher `codex` |
| Lista de comandos `Bash(prefixo:*)` no Auditor | `read-only` permite qualquer comando que não grave | Auditor no Codex pode **ler** mais (ex.: `docker ps`), nunca gravar; declarado |
| `acceptEdits` + Bash = sem sandbox de escrita | `workspace-write` restringe a cwd + `--add-dir` | Codex fica mais restrito (permitido pela regra); gravação fora do cwd falha e aparece na run |
| Rede sempre disponível (Bash) | rede desligada por padrão no `workspace-write` | ligada no perfil `escrita` (`network_access=true`, confirmar no CA-11) |
| `--add-dir` = diretório extra acessível | `--add-dir` = diretório extra **gravável** | cada perfil lista os seus explicitamente |
| `--session-id <uuid>` antes de rodar | id da thread só na saída; `exec resume` não aceita `-s`/`-C` | como na conversa D17/D21 (`-c sandbox_mode=…`, `--skip-git-repo-check`) |

### 7.3 Parecer do Auditor gravado pelo chamador
O Auditor termina com um bloco ` ```parecer ` contendo o JSON de `docs/squad/gates.md` (gate, from, to,
recommendation, confidence, risk, evidências, observações). `tools/squad/gate.py record --demand <id> --from-output
<arquivo> [--run <id>]` valida o esquema, mascara o texto (`evidence_rules`), grava `docs/squad/gates/<G>-<n>.json` e o
evento `gate` (`--agent auditor`, `--run`, `--model` efetivo). `run_agent.py auditor` chama `gate.py` ao terminar; no
caminho nativo, o Orquestrador salva a resposta do subagente e chama `gate.py`. Bloco ausente/ inválido → `gate`
não é gravado e `progress` "parecer inválido" (conta como ciclo de autocorreção). O Auditor deixa de rodar
build/testes: exige a evidência do QA (RETURN se faltar).

## 8. Como cada acionamento usa a escolha
1. **`run_agent.py <papel>`**: chama `resolve` (contexto `passo`, ou `plantao` quando `papel = orquestrador` sem
   `--demand`); monta o comando pelo **perfil** do papel (§7) e executor efetivo; `--runner/--model` só com
   `--dry-run` (senão sai 2 com "use o painel ou `executores.py`"); código 3 do `resolve` → sai 3 sem rodar. Grava os
   campos do §9.2. Exporta ao filho `SQUAD_RUN` e `SQUAD_MODEL` **só** com o efetivo (nunca o do pai).
2. **`triage.py`**: sem `--runner`; `run_agent.py arquiteto … --context triagem --no-snapshot`.
3. **`conversa.py`**: `default_runner()`/`requested_model()` passam a vir de `resolve orquestrador --context conversa`;
   o `fake` segue aceito só com `SQUAD_CHAT_FAKE` (testes).
4. **`plantao.sh`**: sem `SQUAD_RUNNER`; imprime o executor resolvido do Orquestrador a cada ciclo e chama
   `run_agent.py orquestrador @docs/squad/prompts/plantao.md` (resolve internamente). Código 3 → registra e espera o
   próximo ciclo.
5. **Plantão numa sessão do Claude Code (`/loop`)**: o prompt começa por `executores.py check-session orquestrador
   --runner claude`; código 3 → responde só "plantão desta sessão suspenso: Orquestrador configurado para <x>; use
   tools/squad/plantao.sh" e não trata a fila. Cada despacho de papel: `executores.py resolve <papel> --demand <id>
   --json` → `via=nativo` usa a ferramenta Agent com `model` = alias resolvido (ou omitido); `via=run_agent` usa
   `python3 "$MAIN/tools/squad/run_agent.py" <papel> …`. O modelo da própria sessão é o do humano (`/model`): se diferir
   do configurado, a diferença aparece na tela (não é bloqueada; para forçar, use `plantao.sh`).
6. **Gancho `guard-agent`** (`.claude/settings.json`: `hooks.PreToolUse[{matcher:"Agent|Task", hooks:[{type:"command",
   command:"python3 \"$CLAUDE_PROJECT_DIR/tools/squad/executores.py\" guard-agent"}]}]`): papel = `tool_input.subagent_type`
   se for um dos 8; senão, 1º casamento no `prompt` de `agente \*\*(Papel)\*\*` ou `--agent <papel>`; sem papel →
   permite. Demanda = 1º `--demand <12 hex>` do prompt. Nega (código 2) se `resolve` der `via=run_agent`, se
   `tool_input.model` diferir do alias resolvido, ou se a configuração estiver ilegível; a mensagem diz o comando
   `run_agent.py` a usar. Ao permitir, grava `executor-dispatch` (`via:"nativo"`). Vale em qualquer sessão deste
   repositório e dos worktrees (o `.claude/settings.json` vai junto).
7. **Delegação (D19)** e **gates**: via `run_agent.py` (item 1) ou nativo conforme `via` (item 5); gates com o perfil
   `auditoria` e `gate.py record`.
8. **Detecção (servidor)**: para cada run com `agent` e `demand` (nativa ou `run_agent`), se o executor efetivo ≠ o
   configurado da foto/troca por demanda e não há `executor-fallback` para aquela run → alerta `executor-divergente`
   (regra B9, aviso) com run, papel, configurado e efetivo. É assim que um desvio de qualquer caminho fica visível
   mesmo com o gancho desligado.

## 9. Eventos e campos (aditivos; gravados por `executores.py`/servidor com `product.append`, fora do `TYPES` do `log.py`, como `delegation`)
### 9.1 Eventos novos
| `type` | Quem grava | Campos além de `id, ts, agent, title` |
|---|---|---|
| `executor-config` | servidor (`via:"painel"`), CLI (`via:"cli"`), migração | `scope` (`squad\|agent\|demand\|policy\|apply-all`), `role?`, `demand?`, `before`, `after` (`{runner,model}` ou `{onUnavailable}`), `by:"humano"`, `user` (usuário do SO do servidor), `machine` (id de `sync/machine.json` do ADR-026 ou `hostname`), `configVersion`, `warnings[]`, `acknowledged` |
| `executor-snapshot` | `executores.py` | `demand`, `executors{papel:{runner,model,source}}`, `squad`, `policy`, `configVersion` |
| `executor-fallback` | `executores.py`/`run_agent` | `demand?`, `role`, `run?`, `configured{runner,model}`, `reason` (`nao-instalado\|sem-login\|desconhecido\|timeout`), `action` (`padrao\|parou`), `effective{runner,model}?` |
| `executor-dispatch` | gancho `guard-agent` | `demand?`, `role`, `via:"nativo"`, `configured{runner,model}`, `source` |
`agent` = `humano` em `executor-config`; `orquestrador` nos demais. `title` legível ("Arquiteto: claude → codex").

### 9.2 Campos novos em runs e `progress`
`.squad/runs/<id>.json` e os `progress` "Iniciado/Finalizado via …": `runnerConfigured`, `modelConfigured` (alias,
ID ou `null`), `configSource` (`demanda|agente|squad`), `profile`, `fallback` (`null` ou `{reason, from}`) — além de
`runner`, `model`, `modelRequested`, `modelProvider` (ADR-012). `log.py` ganha `--runner-configured`,
`--model-configured`, `--config-source` (opcionais).

### 9.3 Diferença configurado × efetivo (regra única, servidor)
Há diferença quando: executor ≠; ou `modelConfigured` é ID exato e ≠ `model`; ou é alias e o `model` não contém o
alias (ex.: `opus` × `claude-sonnet-5`); ou `fallback ≠ null`. `modelConfigured = null` nunca gera diferença de
modelo. Motivo exibido: `fallback:<reason>`, `sessao` (modelo da sessão interativa), `executor`, `modelo`.

## 10. API (dono: Orquestrador; rotas atuais = apelido do produto padrão, ADR-024 §4.8)
| Rota | Corpo | Resposta |
|---|---|---|
| `GET /api/executores` | — | `{config, version, resolved:[{role,runner,model,source,via,profile}], status:{claude:{…},codex:{…}}, allowed, policy, ignoredEnv:[…], lastEffective:{papel:{runner,model,modelProvider,run,at}}, history:[últimos 20 executor-config], plantao:{runner,via:"sessao"\|"plantao.sh",at}}` |
| `POST /api/executores` | `{baseVersion, squad, agents, policy, acknowledge?}` | 200 `{version, warnings}` · 400 `executor_nao_permitido\|modelo_incompativel\|formato_invalido` · 409 `versao_desatualizada\|executor_indisponivel` |
| `POST /api/executores/aplicar-a-todos` | `{baseVersion, runner, model, acknowledge?}` | idem; efeito: `squad = {runner, model}` e **todos** os `agents = null` (inclusive Orquestrador e Auditor); um `executor-config{scope:"apply-all"}` com o antes completo |
| `POST /api/executores/checar` | — | `status` recalculado |
| `POST /api/demand/executores` | `{demand, role, runner\|null, model?, acknowledge?}` | 200 · 404 demanda · 409 `demanda_encerrada` (entregue/cancelada) |
`/api/state` acrescenta, por demanda, `executors: [{role, configured{runner,model,source}, effective:[{runner,model,
modelProvider,run,at}], diff, reason}]` (só no `/api/state`; o `/api/live` e o orçamento do ADR-017 não mudam, exceto os
alertas B8/B9 que já passam pelo cálculo de alertas). Recusas no formato `{"error","code"}`.

## 11. Interface (Frontend, `squad-control/index.html`, sem biblioteca nova, tema Grafite)
### 11.1 Tela Executores (`#/squad/executores`, link na tela da squad)
- Linha **Padrão da squad** + uma linha por papel (8). Colunas: Agente · Executor (`Usar o padrão` · `Claude Code` ·
  `Codex`) · Modelo (campo livre com sugestões: aliases do Claude e IDs já vistos em runs deste produto; vazio =
  "padrão do executor") · Efetivo recente (chip ADR-012 `<ID> · <Fornecedor>` e "há X min") · Estado (Instalado ·
  Login · versão; "sem login" em aviso).
- **Aplicar a todos**: executor + modelo, confirmação **na própria tela** (sem `confirm()`), texto "O padrão da squad
  passa a ser X e os 8 agentes voltam a usar o padrão. Demandas já iniciadas mantêm a configuração delas."
- **Se o executor escolhido não estiver disponível**: `Usar o padrão da squad (recomendado)` · `Parar e me avisar`.
- Aviso fixo ao escolher Codex: texto do `CODEX_WARNING` (leitura não isolada). Com Orquestrador em `codex` e plantão
  em sessão: "O plantão desta sessão do Claude Code será suspenso; rode tools/squad/plantao.sh".
- Salvar → avisos por linha (409) e "Salvar mesmo assim". Histórico: últimas 20 mudanças (quem, quando, antes → depois).
### 11.2 Tela da demanda (D10, ADR-015/016)
Bloco **Executores desta demanda**: papel · configurado (`executor · modelo`, origem) · efetivo (chips das runs) ·
marca **Diferente** (cor de aviso) com o motivo da §9.3. Botão "Trocar só nesta demanda" (papel, executor, modelo) →
`POST /api/demand/executores`. Alertas B8/B9 da demanda aparecem no topo como os demais.

## 12. Critérios de aceite (verificáveis)
Testes automáticos em `tests/squad/test_executores_d26.py` com `SQUAD_ROOT_DATA`/`SQUAD_LOG` temporários e **atalhos
falsos** de `claude`/`codex` no `PATH` (`tests/squad/fixtures/d26/bin/`): imprimem o cabeçalho do Codex
(`model: gpt-5.6-sol`/`provider: openai`) ou gravam uma transcrição com `message.model` e respondem ao
`auth status`/`login status` conforme variável do teste. **Custo zero de tokens.**
| # | Critério | Verificação |
|---|---|---|
| CA-1 | Precedência: demanda > foto > agente > squad; `null` herda executor e modelo | tabela de casos em `resolve --json` |
| CA-2 | Arquivo ausente é criado da semente e de `SQUAD_RUNNER`/`SQUAD_CHAT_*`, com `executor-config via:"migracao"`; depois as variáveis são ignoradas com aviso | 2 execuções com ambientes diferentes |
| CA-3 | Arquivo ilegível → `resolve` sai 4 e `run_agent` não inicia nenhum processo | arquivo corrompido + atalho falso que registra chamada |
| CA-4 | `run_agent.py --runner codex` sem `--dry-run` sai 2; com `--dry-run` mostra o comando | chamada direta |
| CA-5 | `run_agent` aninhado não herda o modelo do pai (`SQUAD_MODEL=gpt-x` no ambiente, papel em `claude` → `--model` do papel) | `--dry-run` |
| CA-6 | Comando por perfil × executor = §7.1 exatamente (8 papéis + conversa + triagem, 2 executores) | `--dry-run` e `conversa.build_cmd` |
| CA-7 | Foto: `snapshot` grava 1 evento; mudar a configuração depois não muda `resolve --demand` da demanda; demanda nova usa a nova | log temporário |
| CA-8 | `guard-agent`: papel em `codex` → código 2 com o comando `run_agent`; papel em `claude`/`opus` → 0 e `executor-dispatch`; `tool_input.model` divergente → 2; `general-purpose` com "agente **Arquiteto**" no prompt é tratado como Arquiteto; sem papel → 0 | JSON no stdin |
| CA-9 | Sem login (`CODEX_HOME=<vazio>`), `policy=padrao` → `executor-fallback{action:"padrao"}`, run no padrão, alerta aviso; `policy=parar` → código 3, nenhum processo, alerta B8 | atalhos falsos + log |
| CA-10 | Falha de autenticação na saída → 1 nova run no padrão (`--fallback-of`), nunca 2 | atalho falso que sai 1 com "Not logged in" |
| CA-11 | Codex `escrita` grava no worktree e no log da cópia principal; rede ligada; Auditor no Codex não consegue gravar (tentativa de escrita falha) | **run real curta** (1 prompt de 1 linha, menor modelo disponível) |
| CA-12 | Auditor: `gate.py record` grava gate e evento a partir do bloco `parecer`; bloco inválido não grava | fixture de saída |
| CA-13 | `POST /api/executores`: 409 `executor_indisponivel` sem `acknowledge`; 200 com; `executor-config` com `before/after/by/user/machine/when`; 409 `versao_desatualizada` | servidor em porta livre |
| CA-14 | `aplicar-a-todos` → `squad` = escolhido e 8 `agents = null`; um evento `apply-all` | idem |
| CA-15 | Run grava `runnerConfigured/modelConfigured/configSource/fallback` + efetivo; `/api/state.demands[].executors[].diff` segue a §9.3 | runs falsas |
| CA-16 | Alerta `executor-divergente` para run nativa de papel configurado em `codex` sem fallback | transcrição falsa de subagente |
| CA-17 | Conversa usa o executor do Orquestrador; troca de executor abre sessão nova no próximo turno | `SQUAD_CHAT_RUNNER=fake` só para o atalho |
| CA-18 | Tela: tabela, "Aplicar a todos", política, avisos por linha, histórico; bloco da demanda com "Diferente" | `tests/ui` + inspeção |
| **CA-H1** (humano) | Orquestrador em `claude` (modelo Anthropic) e Arquiteto em `codex`; inicio uma demanda; o painel mostra o Arquiteto com modelo **OpenAI** e o Orquestrador com modelo **Anthropic**, sem "Diferente" | demanda de prova (abaixo) |
| **CA-H2** (humano) | "Aplicar a todos: Codex"; a próxima demanda roda **inteira** no Codex (todas as runs `codex`, incluindo Orquestrador via `plantao.sh` e Auditor), e a demanda anterior mantém a foto | idem |
| **CA-H3** (humano) | Com o Codex sem login (`CODEX_HOME` vazio no processo do plantão, sem mexer no login real), a demanda recebe aviso e **não quebra**: roda no padrão (`padrao`) ou fica parada com alerta B8 e retoma após "usar o padrão nesta demanda" (`parar`) | idem |
**Prova de baixo custo para os CA-H**: uma demanda de operação "Prova D26: responder OK" sem mudança de arquivo; o
humano a cancela depois do G1 (custo ≈ triagem + 1 ciclo do Orquestrador + 1 passo do Arquiteto + 1 do Auditor), com
os menores modelos de cada fornecedor (`haiku` no Claude; o menor modelo do Codex disponível na conta).

## 13. Limitações do Codex (declaradas)
1. **Leitura não isolada** no `read-only` (ADR-024 §4.9): conversa, triagem e Auditor no Codex podem ler qualquer
   arquivo da máquina; saída mascarada; com 2+ produtos exige `codexAck` por produto.
2. **`exec resume` fora de repositório git** reiniciava a sessão (defeito `c1b28e123d53`): todo comando Codex leva
   `--skip-git-repo-check`; `resume` não aceita `-s`/`-C` (usar `-c sandbox_mode=…`).
3. **Sem subagentes nativos**: com o Orquestrador no Codex, toda delegação é `run_agent.py` (processos aninhados).
4. **Processos aninhados herdam o sandbox**: um Orquestrador Codex em `workspace-write` não consegue lançar `claude`
   (grava em `~/.claude`) nem usar `gh`/`git push` → por isso o perfil `orquestracao` (Q2).
5. **`.git` pode ser protegido** no `workspace-write` (conforme versão): papéis `escrita` não commitam (regra atual);
   o Orquestrador commita — coberto pelo perfil `orquestracao`; verificado no CA-11/CA-H2.
6. **Modelo efetivo** só pelo cabeçalho da saída (ADR-012); `-m` inexistente na conta falha na saída (vira falha
   comum, não fallback).
7. **Ganchos do Claude Code não se aplicam ao Codex**; não há o que guardar (sem subagentes), a garantia é o resolvedor.

## 14. Riscos
| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Conflito com a D24 em `server.py`/`log.py`/`index.html` | alta | médio | implementar após o merge da D24; lógica nova isolada em `executores.py` |
| Gancho desligado/ignorado (ex.: `--dangerously-skip-permissions`, outra versão) | média | médio | detecção B9 no servidor independe do gancho (§8.8) |
| Papel não detectado em subagente genérico | média | baixo | heurística declarada + B9 |
| `claude auth status`/`codex login status` mudarem de formato | média | baixo | `desconhecido` não bloqueia; falha real na saída cai na §6.3 |
| Orquestrador Codex com `danger-full-access` | — | alto | aceite explícito do humano (Q2); alternativa `escrita` declarada |
| Auditor sem build/testes perde verificação | baixa | médio | G2/G3 exigem evidência do QA; RETURN se faltar |
| Troca por demanda abusada para contornar a política | baixa | baixo | toda troca vira `executor-config` e aparece na demanda |

## 15. Fora do escopo
Outros executores (Copilot, Devin), escolha de parâmetros além do modelo (esforço, temperatura), limites de custo por
executor (D11 continua medindo), autenticação/multiusuário no painel (ADR-024 §8), isolamento contra agente malicioso,
mover o arquivo para `$SQUAD_HOME` (F3), rotas `/api/p/<id>/executores` (F5).

## 16. Rollback
Reverter o PR: os eventos novos ficam no log e são ignorados pelo código antigo; `executores.json` fica em `.squad/`
sem efeito; as variáveis `SQUAD_RUNNER`/`SQUAD_CHAT_*` voltam a valer. `.claude/settings.json` sai junto (sem gancho).
