# ADR-026: Revisão do ADR-024: o produto sai do repositório, a memória vai para o Postgres (Neon) com cache local e a entrega do desafio usa uma exportação congelada

**Status**: Proposto (2026-09-25, Arquiteto, D25 `233278d0cfa9`). A decisão final dos três pontos é do humano (§8).
**Substitui**: ADR-024 §4.1 (repositório e distribuição), §4.3 (onde fica a memória), §4.4.2 (extração da memória com
`git filter-repo`), §4.12 (links, na parte que depende da Q4), §4.13 (na parte da F3) e as linhas F3/F4 do §6.
Também retira "banco de dados para a memória" do §8 do ADR-024. O resto do ADR-024 continua valendo, junto com a
errata do §11 que a D23 aplicou: cadastro TOML (§4.2), histórico legado inteiro (§4.4, Q3), camadas de regras (§4.5),
ambientes (§4.7), painel (§4.8), isolamento (§4.9), transição sem parar (§4.10) e demandas em voo (§4.11).
**Ajuste pós-G1** (G1-D25, ciclo 1, APPROVE com ressalvas): §9 fixa as restrições obrigatórias para os contratos
F3a–F3c; números corrigidos no §1, §3.1 e §5.2; legado = log inteiro na migração (§4.2.8, S9, §5.1).
**Anexo**: mapa [`docs/contracts/plataforma-multiproduto-mapa.md`](../contracts/plataforma-multiproduto-mapa.md), seção H.
**Relaciona-se com**: ADR-017 (300 ms e 64 KB no `/api/live`), ADR-018 (produtivo inquebrável), ADR-019 (evidências
mascaradas), ADR-020 e ADR-023 (conversas e anexos fora do git), ADR-021 (versão e ambiente), ADR-025 (publicador da
porta 7070) e o contrato F2a (`f2a-resolvedor-de-produto.md`, `codes.json`).

**Por que um ADR novo e não outra revisão do ADR-024.** (1) O ADR-024 recebe a errata do §11 na branch da D23, que
ainda está aberta. Reescrever os mesmos parágrafos aqui geraria conflito de merge entre as duas branches. (2) O
G1-D22 aprovou o texto do ADR-024 como está. Um ADR que substitui seções nomeadas preserva essa trilha de auditoria.
(3) As três mudanças formam uma decisão só: memória em banco + produto fora do repositório + entrega por exportação.
No ADR-024 só entram um aviso de substituição no cabeçalho e nas seções substituídas.

## 1. Contexto

Pedido do humano na D25: revisar três pontos antes da F3, sem implementar nada.

Fatos verificados em 2026-09-25 (cópia principal em `develop`, `eef4dd9`):
- **O que está vivo é a plataforma.** Das 22 demandas do legado, 18 mudaram a fábrica (ADR-024 §1). Dos PRs
  integrados na `develop`, só o #85 (D6) é do produto e o #95 (D10) é misto. Os outros (#30, #32, #41, #42, #48,
  #56, #67, #74, #84, #90, #104, #106, #118, #136, #143, #161, #171, #179, #189, #191, #197, #203) mudaram
  `tools/squad`, `squad-control`, `docs/squad` ou o protocolo. As branches em voo (D23, D24, D25) também são da
  plataforma.
  **Correção de número**: o pedido do humano falava em "14 PRs"; o `gh` (só leitura, 2026-09-25) mostra **24 PRs
  integrados** na `develop`, que são exatamente os listados acima (#85 e #95 incluídos). Este ADR usa 24.
- **Issues**: 189 no repositório (`gh issue list --state all`) e 189 itens no Project nº 1 em 2026-09-25 (a primeira
  versão deste ADR dizia 173).
- **O Project nº 1 é do usuário, não do repositório.** `github_sync.py` usa `gh project … --owner` e não amarra o
  Project a um repositório. Ele pode ter itens de mais de um repositório.
- **O publicador (ADR-025, D24) está preso à cópia principal deste repositório**: `plankton/` em `develop`, com
  `git ls-remote origin`, worktree `plankton-squad-prev` e porta 7070. Os worktrees `plankton-dNN`, o plantão e o
  `plankton-teste` também partem daqui.
- **O produto está estável**: os serviços, a infra e o `checkout-console` quase não mudam desde a D10.
- A F2a (D23) já fixa `code` no evento `task` e `docs/squad/products/checkout-saga/codes.json`, com D1–D24
  congeladas. Com isso a ordem física do log deixa de mudar os códigos, e é isso que permite sincronizar sem ordem
  total entre máquinas (§4.2.6).
- IDs de evento: `uuid4().hex[:12]` (`log.py:116`), ou seja 48 bits aleatórios. Colisão é improvável mas possível. A
  sincronização detecta colisão e nunca sobrescreve (§4.2.5).
- `docs/desafio.md` §14 pede, no material entregue: código, infraestrutura, arquitetura (incluindo a da squad), os
  agentes (prompt, objetivo, responsabilidades, ferramentas, entradas e saídas, regras e interação), **evidências**
  (histórico ou registros de execução, decisões e resultados por agente) e o README. O §15 valoriza "Memory Layer" e
  o §16 valoriza "rastreabilidade" e "auditável".

## 2. Decisões (resumo)

1. **Sentido da separação: o produto sai.** O checkout é extraído para um repositório novo (`jcrouzillard/checkout-saga`).
   O repositório atual vira a plataforma e é renomeado para `jcrouzillard/squad-platform`, **sem nunca reutilizar** o
   nome antigo. Ele fica com todo o histórico, os PRs, as issues, as branches em voo e o publicador. Troca o ADR-024 §4.1.
2. **Memória: Postgres no Neon atrás da `MemoryStore`, com cache local.** Todas as leituras vêm do cache local. As
   gravações passam por uma fila de pendentes. A sincronização roda nos dois sentidos, é idempotente pelo id e grava
   o log no Neon só por inclusão, com hash encadeado por máquina. Conflitos de sentido viram alerta para o humano. A
   conexão usa `psycopg` 3 como exceção declarada e isolada à regra de stdlib. Os modos `git` (o §4.3 antigo) e
   `local` continuam como alternativas. Troca o ADR-024 §4.3.
3. **Evidências do desafio: exportação congelada e verificável** no repositório entregue (`docs/evidencias/squad/`),
   gerada a cada release e com um verificador stdlib próprio. Antes da F4, uma tag `entrega-desafio-<data>` congela o
   repositório atual inteiro. Dar acesso aos dois repositórios é complemento, nunca requisito.

## 3. Ponto 1: sentido da separação

### 3.1 Comparação

| Critério | A — extrair a plataforma (ADR-024 §4.1) | **B — extrair o produto (recomendado)** |
|---|---|---|
| Histórico git | a plataforma nasce de `filter-repo` com SHAs novos (tabela `MIGRATION-SHAS.md`). Ela é o lado com mais commits e é o que continua mudando | a plataforma **mantém os SHAs**. O produto, pequeno e estável, nasce de `filter-repo` com a tabela de SHAs |
| PRs (#30…#203) | 22 dos 24 PRs integrados ficam no repositório do produto, longe do código que mudaram | os PRs ficam junto do código que mudaram. Os do produto (#85, #95) continuam válidos no repositório antigo |
| Issues (189) | espelham sobretudo demandas da fábrica e ficam no repositório do produto. As `operacao` novas vão para outro repositório | continuam no repositório da plataforma, que é onde está a maioria. A partir da F4 as issues do checkout vão para `checkout-saga` |
| Project nº 1 | é do usuário, então nada muda | é do usuário, então nada muda. Recebe itens dos dois repositórios, filtráveis pelo campo "Repositório" |
| Nome | `checkout-saga-squad` continua nomeando o produto; nada a renomear | renomear para `squad-platform`. O GitHub redireciona web, API e `git` do nome antigo **enquanto ninguém criar outro repositório com esse nome** (a confirmar na doc de renomeação do GitHub; a regra de nunca reutilizar o nome vai para o cadastro e para o `squad doctor`) |
| Links existentes (`blob/develop/docs/squad/…` nas issues, handoffs e ADRs da fábrica) | continuam válidos só enquanto o produto mantiver os arquivos (Q7) | continuam válidos pelo redirecionamento. Os arquivos da memória legada ficam congelados neste repositório (§4.2.8) e o ADR-024 §4.12 fica mais simples |
| Branches em voo | as da plataforma precisam ser reaplicadas no repositório novo (SHAs diferentes, sem merge entre repositórios) | continuam onde estão. Só as branches do produto seriam reaplicadas, e hoje não há nenhuma |
| Publicador (ADR-025), 7070, plantão, `plankton-dNN` | mudam para `$SQUAD_PLATFORM`, e o publicador troca de remoto e de worktree de rollback | ficam onde estão, sem mudança |
| Produtivo do checkout (Compose, ADR-018) | fica onde está | muda de diretório: um `up` controlado do projeto `checkout-saga` a partir do clone novo, **com o mesmo nome de projeto**, preservando volumes (sem `down`, sem `-v`). Os serviços com bind mount são recriados. O `plankton-teste` é recriado a partir do clone novo |
| Calços `tools/squad/*.py` | necessários por um release no produto | **dispensados**: os caminhos `tools/squad/…` continuam existindo na plataforma. O produto só perde o que é dele |
| ADRs e contratos | os da fábrica (008, 009, 011, 012, 014–026) mudam de repositório | os da fábrica ficam onde estão. Os do produto (001–007, 010, 013 e os contratos `api`, `events`, `ui-checkout-console`, `d10-alinhamento`) vão para o produto com os mesmos números |
| Esforço F3 | igual nos dois sentidos (a memória sai do git) | igual |
| Esforço F4 | alto: extração grande, CI nova, calços, mudança da 7070 e do publicador, branches em voo | médio: extração pequena, mudança do Compose com janela, `AGENTS.md` dividido |
| Esforço F5 | igual | igual. O `squad-platform` já é o repositório atual, então cadastrá-lo como produto é só configuração |
| Entrega do desafio (§5) | o repositório entregue continua sendo `checkout-saga-squad` e precisa de exportação | o repositório entregue é `checkout-saga` e precisa de exportação. O mesmo mecanismo serve aos dois sentidos |

### 3.2 Decisão e justificativa
**B.** Quem muda de lugar deve ser a parte menor e estável, que aqui é o produto. A parte que concentra histórico, PRs,
issues, branches em voo, o publicador e o hábito dos agentes (a plataforma) fica parada. B elimina os calços e a mudança
da 7070, preserva os SHAs que os eventos do log citam (`commit`, `sha`) e mantém válidos quase todos os links sem
reescrever nada. O único custo que A não tem é mudar o produtivo do checkout de diretório, e isso é uma operação
conhecida do ADR-018 com janela escolhida pelo humano.
Resultado nos dois sentidos: a plataforma administra produtos cadastrados e não tem nenhum produto embutido. Em B isso
se verifica com o critério F4 (a) do §6: `grep` sem `services/`, `pom.xml`, `checkout-console/` nem `docker-compose.yml`
de produto na plataforma.

### 3.3 Alternativas rejeitadas
- **A (ADR-024 §4.1)**: tecnicamente correta, mas move a parte viva e obriga os calços e a mudança do publicador
  recém-decidido (ADR-025).
- **B sem renomear** (plataforma continua `checkout-saga-squad`): zero risco de link, mas o nome passa a mentir sobre o
  conteúdo. Fica como alternativa se o humano preferir (Q-A2).
- **B com o produto novo reutilizando o nome `checkout-saga-squad`**: quebra o redirecionamento de todos os links
  antigos. **Proibido.**
- **Monorepo, submódulo, pacote**: rejeitados pelo ADR-024 §4.1, pelos mesmos motivos.

## 4. Ponto 2: memória no Neon, com cache local

### 4.1 Arquitetura

```
 agentes (Bash) ──log.py──►  CACHE LOCAL  ◄──leitura── server.py (/api/live ≤ 300 ms), plantão, alertas, gitflow
                             $SQUAD_HOME/products/<id>/memory/   (formato de hoje: decisions.jsonl, gates/, handoffs/,
                             inbox/, bugs/, codes.json, github-sync.json)
                             $SQUAD_HOME/products/<id>/sync/     (machine.json, acked.json, cursor.json, conflicts.jsonl,
                                                                  status.json, sync.log)
                                     ▲  │ fila = eventos desta máquina com mseq > acked
                   recebe (pull) ────┘  ▼ envia (push)
                     SINCRONIZADOR (thread do server.py, única dona do segredo) ──psycopg──► Neon (Postgres)
                                                                                 esquema squad_<id>, papel squad_writer_<id>
```

- **`MemoryStore`** é uma interface com os métodos `append_event`, `put_doc`, `read_*`, `pending`, `sync`, `verify` e
  `bootstrap`. Os backends são `neon`, `git` e `local`. No cadastro fica `[memory] backend = "neon" | "git" | "local"`
  e `url_env = "SQUAD_MEMORY_URL_CHECKOUT_SAGA"`: **o nome** da variável, nunca o valor. O cache local existe **nos
  três backends**, e os leitores de hoje continuam lendo arquivos. Por isso a F3 não precisa reescrever o painel.
- **Quem grava.** O `log.py` e os demais gravadores, chamados pelos agentes, **só gravam no cache local** com trava
  (`flock`). Eles não fazem rede e não conhecem o segredo. Só o sincronizador, dentro do `server.py`, fala com o Neon.
  Isso atende ao pedido de que "só o servidor e o gravador do log" recebam o segredo: o gravador que fala com o Neon é
  o sincronizador. O mesmo desenho garante funcionar sem rede.
- **Sem servidor no ar**, os pendentes esperam. `squad memory sync` (CLI, só para o humano, lê o `.env`) é o caminho
  manual.

### 4.2 Regras de sincronização
1. **Identidade da máquina**: `sync/machine.json` guarda `{machine: <uuid4>, label}` e é criado na primeira execução. O
   rótulo aparece no painel, e o uuid nunca muda.
2. **Campos novos por evento** (só acréscimo, e leitores antigos ignoram): `machine`, `mseq` (1, 2, … por máquina e
   produto), `prev` (hash do evento anterior da mesma máquina) e `hash = sha256(JSON canônico do evento sem hash)`.
   JSON canônico = chaves ordenadas, `separators=(",", ":")`, UTF-8 e `ensure_ascii=False`.
3. **Fila**: os pendentes são os eventos desta máquina com `mseq > acked.json[machine]`. Não existe arquivo de fila
   separado que possa divergir do log.
4. **Push**: em lotes de até 500, numa transação, `INSERT … ON CONFLICT (id) DO NOTHING RETURNING arrival_seq`. Para
   cada id que não voltou, o sincronizador lê o `hash` no Neon: hash igual significa que já estava lá (confirmado);
   hash diferente é uma **colisão de id**, e aí gera um alerta de integridade, **nunca sobrescreve** e **para o envio**
   dessa máquina até o humano decidir. Só depois do `COMMIT` o sincronizador avança `acked.json`. Se o processo morrer
   entre o commit e o `acked`, a próxima rodada reenvia e o `ON CONFLICT` absorve o reenvio.
5. **Pull**: `SELECT … WHERE arrival_seq > cursor ORDER BY arrival_seq LIMIT 1000`. Id que já existe no cache com o
   mesmo hash é ignorado. Id que existe com hash diferente vira alerta de integridade. Id novo é anexado ao cache (com
   trava), e então o cursor avança. A quebra do encadeamento de outra máquina (um `prev` que não bate) vira alerta.
   Uma lacuna de `mseq` (eventos que ainda estão para chegar) não é erro: a sincronização fica pendente e o painel
   mostra quantos eventos faltam.
6. **Ordem**: a ordem canônica é a de chegada no Neon (`arrival_seq`). No cache local, os eventos que ainda não
   subiram vêm depois dos sincronizados. Para isso o cache guarda o `arrival_seq` **de cada id** (`arrival.json` ou
   coluna no índice local), inclusive dos próprios eventos, que voltam com o número no `RETURNING` do push ou no pull;
   o resumo global da exportação (§5.1) é calculado nessa ordem. Nada no painel depende da posição física da linha: os códigos saem de
   `code`/`codes.json` (F2a).
7. **Documentos** (gates, handoffs, inbox, bugs, `github-sync.json`, `codes.json`): cada gravação vira uma **versão
   nova** com `(path, version_id, parent_version_id, sha256, machine)` e só por inclusão. A versão mais recente de um
   caminho é a folha única da árvore. Duas folhas para o mesmo caminho formam uma divergência: se o caminho estiver na
   tabela de sentido (§4.3), o caso vira conflito de sentido; senão vale a regra por tipo (§4.3). O parecer do Auditor
   já é imutável por ciclo (`G2-D30.json`, ciclo n), e a regra só formaliza isso.
8. **Legado (o log inteiro na hora da migração)**: na carga da F3a (`squad memory migrate`), o `decisions.jsonl` atual
   é importado **inteiro** (D1–D24 congeladas no `codes.json` e também tudo o que vier depois, D25 em diante, até o
   momento da migração), na ordem do arquivo como máquina `legado`. O encadeamento é calculado na importação, e um evento `migration` guarda contagem,
   sha256 do arquivo e o SHA git de origem. Os arquivos continuam **congelados no histórico git** deste repositório. É
   isso que dispensa o `git filter-repo` da F3 (ADR-024 §4.4.2 e §4.13 deixam de valer para a memória).
9. **Códigos de demanda com várias máquinas**: (detalhado e corrigido no §9.2: reserva só pelo sincronizador, fora da trava, confirmada pelo evento `code-confirmed`) com a máquina online, o código novo é reservado no Neon (tabela
   `codes`, com `UNIQUE (code)`). Se a reserva falhar, a máquina tenta o seguinte. Offline, a demanda nasce com
   **código provisório** (`D?`), que aparece no painel como "provisório". O `feature-start` exige código confirmado,
   porque o nome da branch não pode mudar depois. Uma demanda criada offline pode ser triada e discutida, mas só abre
   branch depois de sincronizar.
10. **Frequência**: push quando há pendentes (espera de 5 s a partir da última gravação, lotes a cada 60 s no máximo);
    pull a cada 30 min (`SQUAD_SYNC_PULL_S`); botão **Sincronizar agora** a qualquer momento. A conexão é aberta e
    fechada a cada rodada, **nunca fica aberta**, para o Neon poder hibernar e não gastar horas de computação (§4.8).

### 4.3 Conflitos: a sincronização nunca escolhe
Tabela de sentido (fixa na plataforma e ampliada por ADR). Cada linha define a chave de "uma só decisão esperada":

| Tipo | Chave | Conflito quando |
|---|---|---|
| parecer do Auditor (`gate`, `gates/G*-*.json`) | demanda + gate + ciclo | recomendações diferentes (APPROVE × RETURN) ou duas folhas do mesmo arquivo |
| estado da demanda (`task-canceled`, `delivered`, `pr-opened`, `human-intervention` com decisão) | demanda | transições incompatíveis (cancelada numa máquina e com PR aberto ou entregue na outra) |
| handoff | demanda + passo | dois handoffs do mesmo passo para agentes diferentes |
| pedido de ambiente de teste, atualização do produtivo | produto | dois pedidos ativos ao mesmo tempo vindos de máquinas diferentes |
| código de demanda | código | colisão de código apesar da reserva (Neon indisponível durante uma janela) |

Efeito: **os dois eventos são guardados**. É gravado um alerta `sync-conflict` (tipo de alerta do ADR-017, com a
etiqueta das duas máquinas). A demanda fica **bloqueada** no `gitflow` (sem `feature-finish` nem `review-sync`) e no
plantão até o humano gravar `conflict-resolved` com a escolha, que é um evento novo, também só por inclusão.
Divergências **sem sentido de negócio** têm regra mecânica, declarada e testada: `github-sync.json` é estado derivado e
é recalculado pelo espelho a partir do GitHub (só a máquina marcada `mirror = true` no runtime espelha); em
`inbox/*.json` vale a união dos campos, e campo com valor diferente vira conflito de sentido.

### 4.4 Integridade e auditoria
- **Só por inclusão no Neon**: o papel `squad_writer_<id>` recebe `USAGE` no esquema, `SELECT, INSERT` nas tabelas e
  `USAGE` nas sequências. `UPDATE`, `DELETE` e `TRUNCATE` são revogados, e o papel **não é dono** de nada. Como segunda
  barreira, um gatilho `BEFORE UPDATE OR DELETE … RAISE EXCEPTION` protege contra o próprio dono por engano. O cursor
  e o `acked` ficam **no local**, então o gravador nunca precisa de `UPDATE`. No Neon, as rodadas vão para `sync_runs`,
  também só por inclusão.
- A criação do esquema e dos papéis é feita **uma vez**, pelo humano, com `squad memory setup`. O comando pede a
  conexão do dono por `getpass`, não a grava em lugar nenhum e cria o papel de gravação. **Só a conexão do papel de
  gravação vai para o `.env`.** Se ela vazar, quem a tiver consegue incluir e ler, mas não consegue apagar nem alterar
  o histórico.
- **Verificação** (`squad memory verify`, que também roda em cada pull e a cada 24 h): (a) contagem total e por
  máquina; (b) hash da cabeça de cada máquina e continuidade do encadeamento; (c) resumo global = `sha256` da
  concatenação dos `hash` em ordem de chegada, calculado dos dois lados; (d) conjunto de ids (contagem + `sha256` da
  lista ordenada); (e) documentos: `sha256` de cada folha. Divergência vira alerta com a lista de ids e caminhos.
- A verificação do legado recalcula o sha256 do arquivo congelado no git e compara com o evento `migration`.

### 4.5 Máquina nova
`squad memory init --product <id>` baixa tudo do Neon (eventos, documentos, `codes`), monta o cache, roda o `verify` e
só então libera o painel: até lá, o status fica "Carregando memória" e o painel é somente leitura. Se o Neon estiver
incompleto (por exemplo, porque outra máquina nunca sincronizou ou porque o Neon foi recriado), `squad memory push --all`
reenvia tudo do cache de uma máquina que tem os dados. É idempotente pelo id e aceita o encadeamento dela.

### 4.6 Segredo
- A variável `SQUAD_MEMORY_URL_<ID>` fica no `.env` da **cópia principal da plataforma** (fora do git, como hoje). O
  humano a coloca lá; nenhum agente escreve, lê ou cita esse arquivo.
- O `server.py` lê o `.env` com um leitor próprio que **não** exporta a variável para `os.environ`. O ambiente dos
  filhos (runners, `run_agent`, conversa, `testenv`, publicador) é montado por uma lista de permissão que remove
  `SQUAD_MEMORY_URL*`, `DATABASE_URL`, `PG*` e `NEON_*`.
- As mensagens de erro do driver passam por um filtro que troca host, usuário, banco e qualquer `postgres(ql)://…` por
  `<memória>` antes de ir para `sync.log`, `status.json`, `/api/*`, o log ou alertas.
- Limite declarado, na linha do ADR-024 §4.9 (a proteção é contra erro, não contra adversário): um runner com Bash
  roda com o mesmo usuário do sistema e **consegue** ler um arquivo que esse usuário lê. A negação `Read(.env)` do
  runner claude reduz o risco mas não o elimina. Mitigações: papel sem `UPDATE`/`DELETE`, variável fora do ambiente
  dos runners, e o prompt da constituição proíbe ler o `.env`. Isolamento forte exigiria um usuário do sistema próprio
  para o servidor (fora do escopo, Q-B4).

### 4.7 Driver: `psycopg` 3, exceção declarada à regra de stdlib
| Opção | Decisão |
|---|---|
| **`psycopg[binary]` 3.x, versão fixa** | **escolhida**. Postgres padrão (sem prender ao Neon), TLS, parâmetros, transações e `COPY` para a carga. Instalada num `venv` da plataforma (`$SQUAD_HOME/venv`, `squad doctor` verifica). Só o módulo `memory_neon.py` importa, e só quando o backend é `neon`. Sem o driver, o backend fica indisponível: status "Erro de sincronização · driver ausente", e o cache local segue normalmente |
| API HTTP do Neon (endpoint SQL-over-HTTP do driver serverless) | rejeitada: é o protocolo do driver JS deles, sem contrato público estável para outros clientes (a confirmar na documentação do Neon), e prende a memória ao Neon |
| Neon Data API (REST) | rejeitada: autenticação por JWT e mais uma camada de permissões. A confirmar se saiu do beta |
| Protocolo Postgres escrito em stdlib (SCRAM + TLS com `ssl`) | rejeitada: centenas de linhas críticas de segurança mantidas por nós |

A exceção vale **só** para `memory_neon.py`. O resto da plataforma continua só stdlib, e `tests/squad` roda sem o
driver usando um backend falso com a mesma semântica. O teste de integração usa um Postgres descartável em container
(`docker compose -p squad-memtest`, ADR-018), nunca o Neon real.

### 4.8 Plano gratuito do Neon (números **a confirmar**; não houve acesso à web nesta revisão)
| Limite (lembrança de 2025) | Efeito para nós | Como confirmar |
|---|---|---|
| armazenamento ~0,5 GB por projeto | estimativa: ~300 eventos/dia × ~1 KB mais as versões de documentos, **na ordem de 0,2 a 0,4 GB/ano** (a medir) | console do Neon → Usage; `SELECT pg_database_size(current_database())`, que o `verify` passa a registrar em `sync_runs` |
| computação limitada em horas-CU por mês; mínimo 0,25 CU | com a conexão só aberta nas rodadas, o Neon fica acordado quando a squad trabalha (algo como 10 h/dia × 0,25 CU ≈ 75 CU-h/mês) | console → Billing/Usage; página de preços do Neon |
| hibernação após ~5 min sem uso (não desligável no gratuito) | primeira consulta com partida a frio de ~0,5 a alguns segundos: o sincronizador usa `connect_timeout = 10 s` e tentativas com espera crescente. As leituras não são afetadas (vêm do cache) | medir a latência da primeira consulta no `sync.log` |
| janela de restauração curta (horas) | não serve como backup; o backup real é o cache local de cada máquina + `push --all` | configurações do projeto → History retention |

**Ao atingir um limite**: 70% e 90% do armazenamento geram alerta. No limite, as inclusões falham, o status vira
"Erro de sincronização · limite do Neon" e **nada se perde** (a fila cresce localmente). O humano escolhe entre subir
de plano ou abrir uma **época nova**: o dono cria um esquema ou projeto novo, a época antiga recebe um evento `epoch-sealed`
com contagem e hash e fica só para leitura ou é exportada (§5), e a nova começa referenciando o selo. Apagar para
liberar espaço **não** é opção, porque o log é só por inclusão.

### 4.9 O que não vai para o Neon
Nada disso vai para o Neon: conversas, anexos e imagens (ADR-020 e ADR-023), `runs/`, transcrições, travas, sessões,
rascunhos de bug, `bug-pseudonym.key` e `usage/` (tudo em `run:`, como no ADR-024 §4.3). As **evidências de bug** vão
para o Neon: o sincronizador reaplica a máscara do ADR-019 antes do envio e **recusa** (e gera alerta) qualquer arquivo
que a máscara altere, porque isso indicaria conteúdo sem máscara. Evidências acima de 1 MB ficam no local, e o Neon
guarda só o sha256 e a máquina ("evidência só na máquina X").

### 4.10 Status no painel
`/api/live` ganha `memory: {state, pending, conflicts, lastOkAt, machine}`, com no máximo 200 bytes, lido de
`sync/status.json` **sem rede** (ADR-017). Estados:
- **Sincronizado**: sem pendentes, último pull com sucesso há menos de 2× o intervalo e o último `verify` passou.
- **Offline · N pendentes**: a última tentativa falhou por rede ou tempo esgotado.
- **Erro de sincronização**: falha de autenticação, permissão, driver, integridade, limite ou conflito. Gera alerta.

O botão **Sincronizar agora** chama `POST /api/memory/sync`, que só o humano usa (os agentes não chamam essa rota,
como no ADR-025). O modo `local` mostra "Só local", e o modo `git` mostra o estado do push.

### 4.11 Alternativas (backend principal)
| Alternativa | Situação |
|---|---|
| Git local por produto com remoto privado (ADR-024 §4.3) | continua como backend `git`, para quem não tem conta. É mais fraco em várias máquinas (conflito de arquivo, `push --force` reescreve o histórico) |
| Só local (`local`) | backend `local`: uma máquina só, sem nenhuma dependência |
| SQLite local como cache | rejeitado agora: os leitores de hoje leem arquivos, e trocar o formato do cache aumentaria a F3. Fica para evolução atrás da `MemoryStore` |
| Neon como fonte de leitura | rejeitado: fere os 300 ms do ADR-017 e o funcionamento offline |

### 4.12 Critérios verificáveis da sincronização (entram no aceite da F3b)
| # | Critério | Como verificar |
|---|---|---|
| S1 offline | sem rede (URL apontando para um host inalcançável), um ciclo de demanda com 50 eventos, gate e handoff funciona; `/api/live` com p95 ≤ 300 ms; status "Offline · 50 pendentes"; nenhum evento perdido | teste com backend real e destino em buraco negro; contagem local = 50 novos |
| S2 sem duplicar | depois de reconectar, o push roda 3 vezes; a contagem no Neon é igual à local e os ids são únicos. Com `SIGKILL` entre o `COMMIT` e o `acked`, a nova rodada não duplica nada | Postgres descartável; `SELECT count(*), count(DISTINCT id)` |
| S3 duas máquinas | dois `SQUAD_HOME` (máquinas A e B) gravam 100 eventos cada offline e depois sincronizam; os dois caches ficam com os mesmos 200 ids, os encadeamentos válidos e o mesmo resumo global | `squad memory verify` nos dois |
| S4 conflito | A aprova o G2-D30 ciclo 1 e B devolve o mesmo gate; depois da sincronização aparece o alerta `sync-conflict` nas duas, os dois eventos ficam guardados, `feature-finish` recusa, e **não existe** nenhum evento de resolução automática. Depois do `conflict-resolved` do humano, o fluxo segue | teste de ponta a ponta com as duas máquinas |
| S5 integridade | `UPDATE`, `DELETE` e `TRUNCATE` com o papel de gravação dão erro de permissão; alterar uma linha do cache faz o `verify` falhar apontando o id; a colisão de id com hash diferente é recusada com alerta | Postgres descartável com os mesmos `GRANT`s do `setup` |
| S6 máquina nova | um `SQUAD_HOME` vazio + `init` produz um cache com resumo global igual ao de A e um `/api/state` normalizado igual. Neon recriado vazio + `push --all` de A dá `verify` verde | teste + cópia normalizada |
| S7 segredo | a URL, o host e a senha de teste não aparecem em log, runs, transcrições, `sync.log`, `server.log`, respostas `/api/*` nem no ambiente de um runner falso que imprime o próprio ambiente | `grep` com o valor sentinela |
| S8 máscara | evidência com dados pessoais sem máscara é recusada no envio, com alerta | teste com o corpus da D16 |
| S9 legado | `migrate` importa o log inteiro existente na hora (D1–D24 e os posteriores) com contagem e sha256 iguais aos do arquivo congelado; o `migration` fica gravado no Neon e no git | `migrate --verify` |

## 5. Ponto 3: evidências do desafio (§14)

### 5.1 Decisão
**Exportação congelada e verificável** no repositório entregue (em B, `checkout-saga`), em
`docs/evidencias/squad/<versão>/`, gerada por `squad memory export --product checkout-saga` no `release-start` e revisada
no PR de release (é o único momento em que memória entra num repositório de produto: um retrato fixo, não um estado
vivo). Conteúdo:
- `log.jsonl`: todos os eventos do produto (legado importado na migração + os posteriores) em ordem de chegada, com `hash`/`prev`;
- `gates/`, `handoffs/`, `inbox/` (demandas encerradas) e `bugs/` (já mascarados, ADR-019);
- `prompts/`: o prompt **composto** de cada papel (base da plataforma + especialização do produto), a constituição,
  os gates-base, os prompts de plantão, delegação, conversa e triagem, e o README "como a squad opera", tudo na versão
  da plataforma em uso;
- `decisoes/`: cópia dos ADRs e contratos da fábrica que o produto usou;
- `arquitetura/`: o diagrama e a visão da squad agêntica (§14 pede "diagramas da squad" no material entregue; o
  `docs/architecture` do produto não basta apontar para a plataforma);
- `MANIFEST.json`: versão e SHA da plataforma e do produto, contagens, sha256 de cada arquivo, cabeças do encadeamento
  por máquina, resumo global e o `arrival_seq` máximo no Neon na hora da exportação;
- `verificar.py`, só stdlib, que recalcula hashes, encadeamento e resumo **sem rede** e sem o Neon.

Conversas e anexos não entram (ADR-020); o que foi decidido nelas já está no log. Antes da F4, a tag
`entrega-desafio-<data>` no repositório atual congela tudo como está hoje (código, squad e memória no git). É a evidência
mais simples possível e não depende de nada que esta revisão muda.

### 5.2 Onde cada item do §14 fica depois da separação (sentido B)
| Item do §14 | `checkout-saga` (entregue) | `squad-platform` | Neon / local |
|---|---|---|---|
| Código-fonte (serviços, APIs, testes) | `services/**`, `checkout-console/**`, `tests/e2e`, `pom.xml` | código da squad e `tests/squad` (complemento) | — |
| Infraestrutura (Dockerfile, compose, provisionamento, observabilidade) | `Dockerfile`, `docker-compose.yml`, `infra/**`, `Makefile` | — | — |
| Arquitetura (solução, Saga, **squad**) | `docs/architecture/**` (a visão agêntica fica aqui e aponta para a plataforma) | `docs/architecture` da fábrica, ADRs 008… | — |
| Agentes (prompt, objetivo, papéis, ferramentas, E/S, regras, interação) | `AGENTS.md` (bloco da constituição gerado), `squad/roles/**`, `.claude/agents/*.md` gerados, `evidencias/squad/<v>/prompts/` | `roles/`, `prompts/`, `policies/` (fonte) | — |
| Evidências: histórico e registros de execução | `evidencias/squad/<v>/log.jsonl` + `MANIFEST.json` | — | fonte viva: log no Neon e cache local; `runs/` e transcrições só local |
| Evidências: decisões arquiteturais | `docs/adr/` do produto + `evidencias/squad/<v>/decisoes/` | ADRs da fábrica (fonte) | eventos `decision` |
| Evidências: resultados por agente | `evidencias/squad/<v>/{gates,handoffs}/` | — | fonte viva |
| Documento técnico (README, execução, testes, falhas, **como a squad opera**) | `README.md` + `evidencias/squad/<v>/prompts/README-squad.md` | `README.md` da plataforma (fonte) | — |
| Histórico git, PRs, issues e Project | tag `entrega-desafio-<data>` (antes da F4) + PRs do produto | PRs #30…#203, 189 issues (via redirecionamento) | Project nº 1 (do usuário) |

### 5.3 Alternativas
| Alternativa | Situação |
|---|---|
| Só dar acesso aos dois repositórios | rejeitada como forma principal: o Neon não é acessível ao avaliador, a memória viva muda depois da entrega e não há retrato verificável. Serve como **complemento**: os links vão no README |
| Só a tag antes da F4 | necessária, mas não cobre o trabalho feito depois da separação |
| Exportação no repositório da plataforma | rejeitada: o §14 pede o material junto da solução entregue |
| Exportação contínua (a cada evento) | rejeitada: volta a sujar o produto (o problema original da D22) |

## 6. Plano de fases (substitui as linhas F3 e F4 do ADR-024 §6; F1, F2a, F2b, F5 e F6 continuam valendo)

| Fase | Entrega | Critério de aceite (verificável) | Rollback |
|---|---|---|---|
| **F3a — memória fora do repositório (backend `local`)** | `MemoryStore` + cache em `$SQUAD_HOME/products/<id>/memory` + `run:`; `migrate` com máquina `legado`, encadeamento e evento `migration`; `gitflow` sem `STATE` no modo externo; campos `machine/mseq/prev/hash` no `log.py`; `README` "movido para" em `docs/squad/memory` | ADR-024 F3 (a), (c), (d), (e) + S9; **sem** `git filter-repo` | `SQUAD_MEMORY_MODE=repo` + reimportação por id (ADR-024 §4.10) |
| **F3b — backend Neon e sincronização** | `memory_neon.py` (psycopg), `setup`/`init`/`sync`/`verify`/`push --all`, sincronizador no `server.py`, tabela de sentido, alertas `sync-conflict`/integridade, `memory` no `/api/live`, botão, reserva de código, filtro de segredo, lista de permissão do ambiente | S1–S8; `tests/squad` verde **sem** driver instalado | `backend = "local"` no cadastro: o cache continua íntegro e o Neon só deixa de receber |
| **F3c — exportação de evidências** | `squad memory export` + `verificar.py` + integração no `release-start` (só depois da F4, §9.3); tag `entrega-desafio-<data>` | a exportação de um release verifica offline; mudar 1 byte faz o `verificar.py` falhar; os itens do §5.2 presentes, com o diagrama da squad | apagar a pasta da exportação no PR |
| **F4 — extração do produto (sentido B)** | `checkout-saga` extraído com `filter-repo` (serviços, infra, console, `docs/architecture`, ADRs/contratos do produto, `tests/e2e`, CI Maven) + `MIGRATION-SHAS.md`; produto removido da plataforma; `AGENTS.md` dividido (constituição na plataforma, bloco gerado no produto); cadastro `checkout-saga` apontando para o clone novo; mudança do Compose `checkout-saga` com janela; `plankton-teste` recriado; renomeação para `squad-platform` | (a) nenhum arquivo de produto na plataforma (`grep`/lista); (b) `git log --follow` do `server.py` inalterado (mesmos SHAs); (c) produtivo do checkout com volumes preservados (`prod-fingerprint` de dados antes/depois igual) e smoke verde; (d) CI verde nos dois repositórios; (e) um link antigo `blob/develop/docs/squad/…` de issue abre pelo redirecionamento; (f) uma demanda `produto` e uma `operacao` entregues depois do corte; (g) primeiro release do `checkout-saga` com a exportação commitada e verificada offline (§9.3) | o produto continua no histórico da plataforma: reverter o PR de remoção e voltar o Compose ao diretório antigo (mesmo projeto, mesmos volumes) |

Dependências novas: a F3a exige a F2a. A F3b exige a F3a, a conta Neon com `setup` feito pelo humano (Q-B1) e a URL no
`.env`. A F3c exige a F3a (pode vir antes da F3b; nesse caso exporta do cache; onde a exportação fica antes da F4: §9.3). A F4 exige F2b + F3a + F3c. A F4 não
depende da F3b: o backend pode continuar `local` durante a extração. A Q4 do ADR-024 deixa de bloquear a F3: com o
Neon, os links de parecer em PRs e issues passam a citar o id do evento e trazem o resumo no corpo (ADR-024 §4.12, caso
"só local"), e os links antigos continuam válidos pelo §3.

## 7. Riscos novos (entram no ADR-024 §7)

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Neon inalcançável (rede, hibernação, incidente) | alta (ocasional) | baixo | leitura sempre local; fila; espera crescente; status "Offline" |
| Limite do plano gratuito atingido (armazenamento ou computação) | média em 1 ano | médio | alerta a 70% e 90%; conexão curta; época nova ou plano pago; nada se perde localmente |
| Vazamento da string de conexão (log, chat, ambiente de runner, `.env` lido por Bash) | média | alto | papel só de inclusão; variável fora do ambiente dos filhos; filtro de mensagens; S7; limite declarado (§4.6) |
| Sincronização duplicar ou perder eventos (queda no meio do lote) | média | alto | `ON CONFLICT` por id, `acked` só depois do `COMMIT`, `verify` por contagem e hash (S2) |
| Conflito de sentido não detectado (tipo novo fora da tabela) | média | alto | tabela ampliada por ADR; regra de documento com duas folhas vale para qualquer caminho |
| Colisão de id de 48 bits entre máquinas | muito baixa | médio | detectada pelo hash e nunca sobrescrita; ids novos podem crescer para 16 hex por ADR |
| Código de demanda duplicado offline | média com 2+ máquinas | médio | reserva no Neon; código provisório; `feature-start` exige código confirmado |
| Dependência `psycopg` quebrar (versão, wheel ausente para o Python do host) | baixa | médio | versão fixa em `venv`; `doctor`; backend cai para "driver ausente" sem afetar o cache |
| Mudança do produtivo do checkout de diretório (F4, sentido B) recriar serviços ou perder dados | média | alto | mesmo nome de projeto (volumes preservados); sem `down`/`-v`; janela escolhida pelo humano; `prod-fingerprint` antes/depois |
| Alguém criar um repositório com o nome antigo e quebrar os redirecionamentos | baixa | alto | regra no cadastro e no `squad doctor`; reescrita dos links para SHA fixo como plano B (ADR-024 §4.12) |
| Exportação de evidências divergir da memória viva | média | médio | exportação por release com `MANIFEST` que referencia o `arrival_seq`; `verificar.py` |
| Leitura do Neon por outro produto | baixa | médio | um esquema e um papel por produto; variável por produto; negação por produto no runner claude (ADR-024 §4.9) |

## 8. Perguntas ao humano
- **Q-A1** (troca a Q1 do ADR-024): aceita o **sentido B** (o produto sai para `jcrouzillard/checkout-saga`; o repositório
  atual vira a plataforma)? Público ou privado?
- **Q-A2**: renomear o repositório atual para `squad-platform` (recomendado) ou manter `checkout-saga-squad`?
- **Q-A3**: o endereço `checkout-saga-squad` já foi entregue ao avaliador? Se sim, o README da plataforma ganha no topo
  um aviso apontando para o produto e para a tag `entrega-desafio-<data>`.
- **Q-B1**: um projeto Neon com **um esquema por produto** (recomendado no gratuito) ou um banco por produto? Quem roda
  o `squad memory setup` (só o humano, com a conexão do dono digitada na hora)?
- **Q-B2** (troca a Q4 do ADR-024): o backend `git` precisa ser implementado já na F3 ou só `local` + `neon`, com o `git`
  sob demanda? Recomendado: sob demanda.
- **Q-B3**: mais de uma máquina está prevista a curto prazo? Se não, a reserva de código e o S3/S4 continuam sendo
  implementados (são baratos), mas a prova com duas máquinas usa dois `SQUAD_HOME` no mesmo host.
- **Q-B4**: aceita o limite declarado do segredo (um runner com Bash consegue ler o `.env`) ou quer um usuário do
  sistema separado para o servidor?
- **Q-C1**: a entrega é o repositório `checkout-saga` com a exportação (recomendado), ou prefere entregar os dois
  repositórios com a exportação num deles?
- **Q-C2**: autoriza criar agora a tag `entrega-desafio-<data>` no estado atual (antes da F3)?

## 9. Restrições obrigatórias para os contratos da F3a–F3c (ressalvas do G1-D25)

O G1-D25 aprovou este ADR com ressalvas. Cada item abaixo é **obrigatório** no contrato da fase indicada e vira
critério do G1 dessa fase: o contrato que não o cobrir volta ao Arquiteto.

### 9.1 Segredo (`SQUAD_MEMORY_URL_*`): caminhos que já existem no código (contrato F3b; S7 ampliado)
| # | Caminho de vazamento | Restrição |
|---|---|---|
| R1 | `/api/project` (`server.py:1660-1670`) lê o `.env` da raiz e substitui **qualquer** `{{VAR}}` de `project.json` (arquivo editável por agentes) na resposta | a substituição passa a ser por **lista de permissão** de nomes (`GRAFANA_PORT`, `CONSOLE_PORT`, … declarados no contrato); nome fora da lista vira texto vazio e gera alerta; `SQUAD_MEMORY_URL_*` (e qualquer nome com `URL`, `TOKEN`, `KEY`, `SECRET`, `PASSWORD`) é recusado mesmo se alguém o incluir na lista. O mesmo vale para o cadastro TOML (F2a) e qualquer outro ponto que interpole `{{VAR}}` |
| R2 | `run_agent.py:150` e `:227` repassam o `os.environ` inteiro aos filhos | lista de permissão igual à de `conversa.py` (`ENV_ALLOW`/`ENV_PREFIX`, `conversa.py:96-97` e `child_env`, `:222-225`, que já não repassa `SQUAD_*`); a regra cobre também `testenv.py`, o publicador (ADR-025), o plantão e o `github_sync`. Além disso o servidor lê o `.env` num dicionário próprio e **nunca** grava a URL em `os.environ`, para que nenhum filho do servidor a herde |
| R3 | um agente com Bash pode rodar `squad memory sync` | o CLI **não** lê a URL: `sync`, `verify`, `push --all` e `init` pedem ao servidor (`POST /api/memory/sync`, só do humano, ADR-017) e não abrem conexão. Só `setup` fala com o Neon a partir do CLI, com a conexão do dono digitada via `getpass` em tty (sem tty, recusa). O que resta (um agente com Bash lendo o arquivo do segredo) é o limite declarado da Q-B4 |
| R4 | até a F4 o `.env` da cópia principal é o mesmo que o Compose do produtivo interpola | a URL fica num **arquivo separado**, `$SQUAD_HOME/secrets/memory.env` (modo 600, fora de qualquer worktree e fora do alcance do `docker compose`), nunca no `.env` do repositório. O cadastro guarda só o nome da variável (`cad:memory.url_env`). Se o humano preferir o `.env` (pedido original), isso entra como aceitação explícita na Q-B4 |

S7 passa a testar, além do runner falso: `{{SQUAD_MEMORY_URL_X}}` em `project.json` e no cadastro (resposta sem o
valor), ambiente do filho de `run_agent.py`/`testenv.py`/publicador sem `SQUAD_MEMORY_*`, CLI sem tty recusando
`setup`, e `sync` pelo CLI sem servidor falhando sem abrir conexão.

### 9.2 Reserva de código no Neon × `product.append_task` da D23 (contratos F3a e F3b)
A D23 grava `code = max+1` dentro do próprio evento `task`, sob `fcntl.flock(codes.lock)` com `LOCK_TIMEOUT_S = 5 s`
(`product.py:320-345`), chamado por `server.py:1071` e por `log.py:168`. Regras:
1. **Reserva fora da trava.** Rede nunca acontece com `codes.lock` segura (o `connect_timeout` de 10 s estouraria a
   trava de 5 s e travaria os outros gravadores). O `task` é gravado sob a trava como hoje, com `code` **provisório**
   (`D?<id>`) sempre que o backend for `neon`; o `max+1` local só vale no backend `local`/`git` (F3a sem mudança de
   comportamento).
2. **Quem reserva é só o sincronizador** (thread do servidor, §4.1), na rodada de push: `INSERT INTO codes … ON
   CONFLICT DO NOTHING`, tentando o seguinte em caso de colisão. A requisição HTTP que cria a demanda não fala com o
   Neon (corrige o §4.2.9, que dava a entender reserva na requisição).
3. **Registro do código confirmado**: o `task` é imutável; a confirmação é um **evento novo `code-confirmed`**
   `{task: <id do task>, code: "D31", reserved_at, machine}`, gravado no cache sob a trava e sincronizado como qualquer
   evento. O leitor resolve o código da demanda como: `code-confirmed` mais recente para o id, senão o `code` do `task`.
   `codes.json` passa a ser derivado desses eventos (é documento, §4.2.7). Dois `code-confirmed` com códigos diferentes
   para o mesmo `task` é conflito de sentido (entra na tabela do §4.3).
4. **`log.py` é offline** (caminho dos agentes, §4.1): sempre grava provisório no backend `neon`; o painel mostra
   "provisório" até o `code-confirmed`, e o `feature-start` continua exigindo confirmado.
5. Critério no G1 da F3b: duas máquinas (dois `SQUAD_HOME`) criam demanda offline, sincronizam e recebem códigos
   distintos; `strace`/log do teste mostra zero conexões com `codes.lock` segura.

### 9.3 F3c antes da F4: onde fica a exportação (contrato F3c)
Enquanto `checkout-saga` não existe, o único repositório é o atual (a futura plataforma), e o §5.3 rejeita exportar
para o repositório da plataforma. Portanto:
- a F3c entrega **o mecanismo** (`squad memory export`, `verificar.py`, testes) e gera exportações só em diretório de
  trabalho (`$SQUAD_HOME/products/checkout-saga/exports/<versão>/`), **sem commit**;
- a integração no `release-start` fica **desligada** até a F4 (`export.enabled = false` no cadastro);
- a evidência versionada antes da F4 é só a tag `entrega-desafio-<data>` (Q-C2);
- a primeira exportação commitada em `docs/evidencias/squad/<versão>/` acontece no primeiro release de `checkout-saga`
  depois da F4 (critério (g) da F4: esse release existe e o `verificar.py` passa offline).
- Se a Q-C1 escolher "entregar os dois repositórios com a exportação num deles", este item é revisto por ADR.

### 9.4 Correções de detalhe (contratos F3a/F3b)
- `arrival_seq` por id no cache (§4.2.6); o contrato F3b define o arquivo e o critério (resumo global igual em duas
  máquinas depois do pull).
- Legado = o log inteiro na hora da migração (§4.2.8, S9), não "D1–D24".
- Mapa H0: B16 (anexos) sai da linha do cache e fica só em `run:` (corrigido no anexo).
- A exportação leva o diagrama da squad (§5.1 `arquitetura/`; mapa H9).

### 9.5 Impacto em F5 dos pontos 2 e 3
- **Ponto 2 (memória)**: cada produto novo da F5 ganha esquema `squad_<id>`, papel `squad_writer_<id>`, variável
  `SQUAD_MEMORY_URL_<ID>` no arquivo de segredo (R4) e nome na lista de recusa do R1; a lista de permissão do R2 não muda
  (é por prefixo recusado, não por produto). A reserva de código (§9.2) é por produto (tabela `codes` no esquema do
  produto), então códigos `D…` repetem entre produtos e toda referência passa a ser `<produto>/<código>`; o evento
  `code-confirmed` e a tabela de sentido valem sem mudança. A negação de leitura cruzada (ADR-024 §4.9) passa a cobrir
  também o arquivo de segredo.
- **Ponto 3 (evidências)**: `squad memory export --product <id>` já é por produto; cada produto da F5 liga
  `export.enabled` só quando tiver repositório próprio (mesma regra do §9.3). O `MANIFEST.json` referencia o esquema do
  produto e o `verificar.py` não muda. Produto sem entrega externa pode deixar a exportação desligada.
