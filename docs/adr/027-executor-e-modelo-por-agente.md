# ADR-027: Executor de IA (Claude Code ou Codex) e modelo escolhidos por agente, com padrão da squad e troca por demanda

**Status**: Proposto (2026-09-25, Arquiteto, D26 `50366913d891`, tipo operação).
**Contrato**: [`docs/contracts/executor-e-modelo-por-agente.md`](../contracts/executor-e-modelo-por-agente.md).
**Relaciona-se com**: ADR-012 (modelo no log: esta decisão acrescenta o *configurado* ao *efetivo*), ADR-008 (triagem),
ADR-020 (conversa somente leitura), ADR-022 (delegação `run_agent --delegation`), ADR-024 §4.2/§4.5/§4.9 (cadastro,
papéis, isolamento), ADR-026 §4 (memória sincronizada; o runtime fica na máquina), ADR-025 (publicador, D24 em voo).

## 1. Contexto (verificado no código em 2026-09-25, `develop` 1ba49fa)
- O executor vem de variáveis de ambiente globais: `SQUAD_RUNNER` e `SQUAD_MODEL` (`run_agent.py`, `triage.py`,
  `plantao.sh`), e `SQUAD_CHAT_RUNNER`/`SQUAD_CHAT_MODEL` só para a conversa (`conversa.py:187-193`). Não há escolha
  por agente nem por demanda, nem registro de quem mudou.
- **Caminho que ignora o executor**: o plantão numa sessão do Claude Code (`/loop`) delega pela ferramenta Agent
  (subagentes de `.claude/agents/*.md`, `model:` do frontmatter). Esse caminho **sempre** usa Claude, qualquer que seja
  `SQUAD_RUNNER`; `plantao.md` §C.5 diz "use a ferramenta nativa, se existir; senão `run_agent.py`".
- **Herança indevida**: `run_agent.py` lê `SQUAD_MODEL` como `--model` padrão e exporta `SQUAD_MODEL` ao filho (ADR-012).
  Um `run_agent` aninhado (Orquestrador → Arquiteto) herda o modelo **do Orquestrador**, inclusive de outro fornecedor.
- **Permissões desiguais hoje**: o Auditor nativo tem `tools: Read, Glob, Grep, Bash`, mas via `run_agent.py` recebe o
  perfil de escrita (`acceptEdits` + `Write`/`Edit`) no Claude e `workspace-write` no Codex. A triagem usa
  `--allowedTools Read Glob Grep` (pré-aprova, não restringe) e a conversa usa `--tools` + `--disallowedTools` (restringe).
- CLIs instalados nesta máquina: `codex-cli 0.156.1` (`codex login status`, `exec --add-dir`, `-s read-only|workspace-write|
  danger-full-access`, `--skip-git-repo-check`, `-o`) e `Claude Code 2.1.280` (`claude auth status --json`,
  `--permission-mode … dontAsk`, `--tools`, `--disallowedTools`).
- Limites do Codex já declarados: leitura não isolada no `read-only` (ADR-024 §4.9, `CODEX_WARNING`); `codex exec
  resume` fora de repositório git reiniciava a sessão sem aviso (defeito `c1b28e123d53`, corrigido na D21 com
  `--skip-git-repo-check`).

## 2. Decisão
1. **Um resolvedor único** (`tools/squad/executores.py`, Orquestrador) responde, para cada acionamento, `(executor,
   modelo, origem, via)`. Todo caminho que aciona um agente chama o resolvedor: `run_agent.py` (plantão, delegação,
   gates, qualquer papel), `triage.py`, `conversa.py`, `plantao.sh` e o gancho da ferramenta Agent (item 5). As
   variáveis `SQUAD_RUNNER`, `SQUAD_MODEL` (como entrada), `SQUAD_CHAT_RUNNER` e `SQUAD_CHAT_MODEL` deixam de
   configurar: só semeiam o arquivo na primeira carga (migração) e, depois, são ignoradas com aviso.
   `--runner`/`--model` de `run_agent.py` só valem com `--dry-run`.
2. **Camadas, da mais geral para a mais específica** (a mais específica vence):
   embutido (`claude`, modelo do frontmatter) → **cadastro do produto** (`[executors]` do `product.toml`: executores
   permitidos e semente) → **padrão da squad** → **por agente** (ou "usar o padrão") → **por demanda** (opcional).
   Executor e modelo andam juntos: "usar o padrão" herda os dois; modelo vazio = "padrão do executor" (alias do
   frontmatter no Claude; padrão do `~/.codex/config.toml` no Codex, sem `-m`).
3. **Onde mora** (alinhado ao ADR-024 §4.2 e ADR-026 §4):
   - **Cadastro (`product.toml`, revisado por PR)**: só a guarda `executors.allowed` e a semente. A tela não o edita.
   - **Padrão da squad + por agente + política**: arquivo de **runtime do produto nesta máquina** —
     hoje `<cópia principal>/.squad/executores.json` (`.squad/` já está no `.gitignore`); após a F3,
     `$SQUAD_HOME/products/<id>/runtime/executores.json`. Por máquina porque instalação e login são por máquina e
     a memória sincronizada (ADR-026) seria aplicada em máquinas sem o executor.
   - **Por demanda**: no **log** (eventos `executor-snapshot` e `executor-config` com `scope: "demand"`), porque é
     estado da demanda e viaja com ela.
   - **Auditoria de mudanças**: todo `executor-config` vai para o log (quem, o quê, antes/depois, quando, máquina).
4. **Foto na entrada da demanda**: no primeiro despacho após a demanda entrar na fila, o resolvedor grava
   `executor-snapshot` com a tabela resolvida dos 8 papéis. Os passos da demanda usam a foto (mais a troca por
   demanda, se houver). Assim "Aplicar a todos: Codex" vale **por inteiro para a próxima demanda** e não troca de
   fornecedor no meio de uma demanda em andamento. Exceções que usam a configuração **atual**: o próprio ciclo do
   plantão (Orquestrador), a conversa e a triagem (antes da fila).
5. **Subagentes nativos do Claude Code não furam a escolha**: o resolvedor devolve `via = "nativo"` só quando o
   executor do papel é `claude` **e** o modelo é "padrão" ou um alias aceito pela ferramenta Agent (`opus`, `sonnet`,
   `haiku`, `fable`). Em qualquer outro caso, `via = "run_agent"`. Isso é garantido em três níveis:
   (a) **prompt**: `plantao.md` passa a exigir `executores.py resolve` antes de cada despacho e seguir `via`;
   (b) **bloqueio**: gancho `PreToolUse` do Claude Code (`.claude/settings.json`, matcher `Agent|Task`) roda
   `executores.py guard-agent` e **nega** o subagente cujo papel resolve para outro executor ou modelo;
   (c) **detecção**: o servidor compara cada run (nativa ou não) com a foto da demanda e abre alerta
   `executor-divergente` se um papel rodou num executor diferente do configurado sem `executor-fallback` que explique.
   O plantão numa sessão do Claude Code só roda se o Orquestrador estiver em `claude`; senão o ciclo responde
   "plantão desta sessão suspenso" e o plantão passa a ser o `tools/squad/plantao.sh`.
6. **Checagem antes de usar**: `claude auth status --json` / `codex login status` (+ `which`, `--version`), com
   cache de 5 min. Ao salvar na tela: aviso e confirmação explícita. Na execução: executor indisponível → evento
   `executor-fallback` e a **política** decide: `padrao` (usa o padrão da squad; **padrão recomendado**, porque o
   aceite exige "aviso e não quebra") ou `parar` (não inicia o passo, abre alerta de bloqueio com ações "tentar de
   novo" e "usar o padrão nesta demanda"). Se o próprio padrão estiver indisponível, para sempre. Falha de
   autenticação detectada **na saída** da execução (antes de qualquer escrita) segue a mesma política, uma vez.
7. **Registro por execução**: `.squad/runs/<id>.json` e os `progress` de início/fim passam a ter `runnerConfigured`,
   `modelConfigured`, `configSource` e `fallback`, ao lado do `runner`/`model` efetivos (ADR-012). A tela da demanda
   (D10) mostra, por papel, configurado → efetivo e marca "diferente" com o motivo.
8. **Permissões por papel, iguais em qualquer executor**: três perfis (`leitura`, `auditoria`, `escrita`) mais o
   caso do Orquestrador, com mapeamento fixo no contrato §7. Regra: nenhum executor recebe **mais** permissão do que o
   papel tem no outro; onde o Codex não tem equivalente exato, usa-se a opção mais próxima que **não** amplia,
   e a diferença fica declarada. Consequência nova: **o Auditor passa a ser somente leitura nos dois executores**
   (sem Write/Edit e sem shell de escrita); o parecer sai como bloco JSON e quem grava `docs/squad/gates/*.json` e o
   evento `gate` é o chamador (`tools/squad/gate.py record`), como a triagem já faz com `validation`.

## 3. Consequências
- (+) Nenhum acionamento escolhe executor por conta própria; a escolha é auditável (configurado × efetivo × mudança).
- (+) Corrige a herança indevida de `SQUAD_MODEL` e a permissão de escrita do Auditor via `run_agent`.
- (+) Fica claro que plantão com Orquestrador no Codex = `plantao.sh`, não `/loop`.
- (−) Um passo a mais em cada despacho (resolver) e um gancho no Claude Code (`.claude/settings.json`, novo arquivo).
- (−) O Auditor deixa de rodar build/testes: passa a exigir a evidência do QA (a devolver com RETURN se faltar).
- (−) Orquestrador no Codex precisa de `danger-full-access` (§7 do contrato): no Claude ele já tem Bash sem sandbox,
  e `workspace-write` quebraria `gh`, `git push` e o lançamento de outros executores. Pede aceite do humano.
- (−) Codex continua com leitura não isolada (ADR-024 §4.9); com 2+ produtos exige o reconhecimento por produto.
- (−) Toca `server.py`, `log.py` e `index.html`, que a D24 também altera: implementar **depois** do merge da D24.

## 4. Alternativas rejeitadas
| Alternativa | Por que não |
|---|---|
| Configuração só no `product.toml` | o cadastro só muda por PR (ADR-024 §4.2); a tela precisa salvar na hora |
| Configuração só no log (compartilhada entre máquinas via Neon) | aplicaria a escolha numa máquina sem o executor ou sem login; o log fica como trilha, não como fonte |
| Manter as variáveis de ambiente como sobreposição | é exatamente o "caminho que ignora a escolha" que a demanda proíbe |
| Resolver a cada passo, sem foto por demanda | troca de fornecedor no meio da demanda; "a próxima demanda roda inteira no Codex" deixaria de ser verificável |
| Proibir subagentes nativos | perde a integração com o Claude Code sem ganho quando o papel já é `claude` |
| Confiar só no prompt do plantão | não é verificável; por isso o gancho (bloqueio) e o alerta (detecção) |
| Auditor com `workspace-write` no Codex para gravar o parecer | o cwd fica gravável; deixaria de ser somente leitura |

## 5. Perguntas ao humano (nenhuma bloqueia o G1; Q2 bloqueia só o Orquestrador no Codex)
1. **Q1** Política quando o executor não está disponível: padrão proposto `padrao` (usa o padrão da squad e avisa).
   Prefere `parar`?
2. **Q2** Aceita o Orquestrador no Codex com `danger-full-access` (equivale ao Bash sem sandbox que ele já tem no
   Claude)? Sem aceite, fica em `workspace-write` ampliado, com risco de falhar em `gh`/`git push`/lançar o Claude.
3. **Q3** Aceita que o Auditor deixe de rodar build/testes e passe a exigir a evidência do QA (necessário para ser
   somente leitura também no Codex)?
4. **Q4** Configuração por máquina (não sincronizada pelo Neon do ADR-026) está bem, com a trilha de mudanças no log?
5. **Q5** Foto por demanda: uma mudança geral não afeta demandas já iniciadas (use "Trocar só nesta demanda"). Ok?
