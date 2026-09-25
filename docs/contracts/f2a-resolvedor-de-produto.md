# Contrato — F2a: resolvedor de produto e códigos de demanda congelados (D23, `6450aecde7f9`, tipo operação)

> Decisão: [ADR-024](../adr/024-plataforma-multiproduto.md) §4.2, §4.4.1, §4.10, §6 (linha F2a), com a errata do §11
> do ADR. Mapa: [`plataforma-multiproduto-mapa.md`](plataforma-multiproduto-mapa.md), pontos **A1, B1, B13, B14**.
> Respostas do humano (cartão da D23): **Q2** — numeração `D` global (D23, D24…) até a F5; a partir da F5 o produto
> `squad-platform` usa `P` (P1…); o checkout continua em `D`; **D1–D23 congeladas como aparecem hoje no painel**.
> **Q3** — D1–D21 inteiras na memória do checkout, sem dividir, visíveis como somente leitura na plataforma (F5).
> **Branch em voo (§4.11)**: a **D24** (`cf7a120591b0`, `feature/D24-publicar-squad-control`, worktree `plankton-d24`)
> está em andamento e mexe em `server.py`/`index.html`. Decisão do Orquestrador (log `31400c3b82d1`): quem for
> integrada por último traz a `develop` e resolve os conflitos (como D18/D19/D20); o humano pode escolher outra ordem no PR.
>
> **Congelamento (ressalva do G1)**: a D24 já existe no log, portanto a tabela congela **D1–D24**; a primeira demanda
> nova depois da F2a é a **D25**.
>
> **Regra de ouro da fase**: quem não informa produto (`--product`/`SQUAD_PRODUCT`) vê **exatamente** o comportamento de
> hoje — mesmos caminhos, mesmos códigos, mesma saída. Nada é movido. Contratos de domínio (`events.md`, `api.md`) não mudam.

## 1. Donos por arquivo

| Dono | Arquivos | O quê |
|---|---|---|
| **Orquestrador** | `tools/squad/product.py` (novo) | resolvedor (§2), códigos (§4), transcrições (§6), CLI `freeze-codes`/`codes` (§4.5) |
| **Orquestrador** | `docs/squad/products/checkout-saga/product.toml` (novo) | cadastro mínimo (§3) |
| **Orquestrador** | `docs/squad/products/checkout-saga/codes.json` (novo) | tabela congelada D1–D24 + apelidos (§4.3) |
| **Orquestrador** | `tools/squad/{gitflow,github_sync,triage}.py` | caminhos pelo resolvedor (§5); `gitflow` usa o código congelado e valida `feature-start` (§5.1) |
| **Orquestrador** | `tools/squad/{alerts,testenv,pending,conversa}.py` | cálculo de código substituído por `product.demand_codes` (§4.4); assinaturas públicas mantidas |
| **Orquestrador** | `tools/squad/server.py`, `tools/squad/log.py` | gravação de `code` no `task` (§4.2); `codes` no `/api/state`; transcrições (§6) |
| **Orquestrador** | `tools/squad/run_agent.py` | runs em `runs_dir` resolvido e caminho exato da transcrição no metadado (§6) |
| **Frontend** | `squad-control/index.html` (só `demandCode`, `findDemand` e `demandInfo`) | usar o código do servidor (§4.6); nenhuma mudança visual |
| **QA** | `tests/squad/test_produto_f2a.py` (novo), `tests/squad/fixtures/f2a/**` | critérios do §8 |
| **Arquiteto** | este contrato, errata do ADR-024 §11 | — |

`products/**` na raiz **não** é criado nesta fase: o cadastro fica em `docs/squad/products/` (Orquestrador, `docs/squad/**`)
até a F4, quando vai para `plat:products/<id>/` com o mesmo conteúdo.

## 2. Resolvedor — `tools/squad/product.py`

Módulo só-stdlib (`tomllib`, `json`, `pathlib`, `fcntl`, `subprocess`). Nenhum efeito colateral na importação.

```python
DEFAULT_PRODUCT = "checkout-saga"

class ProductError(Exception): ...          # cadastro ausente/inválido, id desconhecido; CLIs saem com código 2

@dataclass(frozen=True)
class Product:
    id: str; name: str; code_prefix: str   # do cadastro
    platform_root: Path   # raiz de onde a squad roda = Path(product.py).parents[2] (o ROOT de hoje)
    repo_root: Path       # árvore do produto nesta execução; na F2a = platform_root (mesma árvore, como hoje)
    data_root: Path       # $SQUAD_ROOT_DATA ou repo_root (resolvido)
    log: Path             # $SQUAD_LOG ou data_root/docs/squad/memory/decisions.jsonl
    memory_dir: Path      # log.parent — arquivos "companheiros" do log: github-sync.json
    gates_dir: Path       # data_root/docs/squad/gates
    handoffs_dir: Path    # data_root/docs/squad/memory/handoffs
    inbox_dir: Path       # data_root/docs/squad/inbox
    runs_dir: Path        # data_root/.squad/runs
    locks_dir: Path       # data_root/.squad/locks   (criado sob demanda; .squad/ já está no .gitignore)
    config_dir: Path      # platform_root/docs/squad/products/<id>   (product.toml, codes.json)
    explicit: bool        # True se o produto veio de argumento ou SQUAD_PRODUCT

def resolve(product: str | None = None) -> Product
def demand_codes(rows: list[dict], p: Product | None = None) -> dict[str, str]       # §4.4
def resolve_code(ref: str, rows, p=None, source: str | None = None) -> str | None     # §4.3 (código/apelido → id)
def append_task(entry: dict, p: Product | None = None) -> dict                        # §4.2 (única gravação de `task` do humano)
def transcript_dir_for(path: Path) -> Path                                             # §6
def transcript_dirs(p: Product | None = None) -> list[Path]                            # §6
```

**Precedência do produto**: argumento `product` (CLIs: `--product <id>`) > `SQUAD_PRODUCT` > `DEFAULT_PRODUCT`.
`id` deve casar `^[a-z][a-z0-9-]{1,40}$`; id desconhecido (sem `config_dir/product.toml`) → `ProductError`.
**Produto implícito sem arquivo**: se nada foi informado e `product.toml` do `checkout-saga` não existe, o resolvedor usa
os valores embutidos (`name="Checkout Saga"`, `code_prefix="D"`) — o comportamento de hoje não depende do arquivo.
Com produto **explícito**, o arquivo é obrigatório.

**Precedência dos caminhos** (todas já existem hoje e continuam valendo **sem** exigir `SQUAD_PRODUCT` nesta fase; a
restrição "só com produto explícito" do mapa F4 é da F2b): `SQUAD_LOG` > `SQUAD_ROOT_DATA` > `repo_root`;
`SQUAD_TRANSCRIPTS` > slug (§6). Com nenhuma variável definida, cada caminho é **byte a byte** o de hoje (CA-1).

Os módulos deixam de calcular `ROOT/LOG/DATA_ROOT` por conta própria para os caminhos da memória; os nomes de módulo
(`server.LOG`, `server.DATA_ROOT`, `gitflow.LOG`, `alerts.demand_codes`, `testenv.demand_codes`…) continuam existindo
como apelidos do resolvido, para não quebrar `tests/squad` nem quem importa.

## 3. Cadastro mínimo — `docs/squad/products/checkout-saga/product.toml`

Lido com `tomllib` (somente leitura; nenhuma ferramenta o reescreve; mudança = PR revisado pelo humano).

```toml
schema = 1

[product]
id = "checkout-saga"          # obrigatório; igual ao nome da pasta
name = "Checkout Saga"        # obrigatório
code_prefix = "D"             # obrigatório; ^[A-Z]$ (Q2: checkout = D; squad-platform = P a partir da F5)
```

- Obrigatórios: `schema` (= 1), `product.id`, `product.name`, `product.code_prefix`. Falta, tipo errado, `id` diferente
  da pasta ou prefixo inválido → `ProductError` com o campo e o arquivo na mensagem.
- Tabelas/campos desconhecidos (as do esboço do ADR-024 §3: `[repo]`, `[git]`, `[github]`, `[env.*]`…) são **aceitos e
  ignorados** nesta fase — a F2b os passa a ler sem mudar o formato.
- `docs/squad/project.json` continua como está (C10 é da F2b).

## 4. Códigos de demanda congelados

### 4.1 Formato
- `code` = `code_prefix` + número decimal sem zero à esquerda: `^[A-Z][1-9][0-9]*$` (ex.: `D25`).
- O **id** do `task` continua sendo a chave canônica; o código é rótulo estável. Um código nunca é reutilizado
  (demanda cancelada mantém o seu).
- Numeração por prefixo: `D` conta só códigos `D`. O `P` (F5) começa em `P1` e não interfere na sequência `D`.

### 4.2 Gravação em demandas novas (quem grava e como evitar corrida)
- Todo `task` com `agent = "humano"` passa a sair com dois campos a mais: `"code": "D25", "code_prefix": "D"`.
- **Únicos gravadores**: `server.py` (`POST /api/demand`, os dois caminhos — demanda comum e bug, `server.py:1535` e
  `:1882`) e `log.py --agent humano --type task`. Os dois chamam `product.append_task(entry)`; nenhum outro código
  grava `task` do humano. `task` de outros agentes (hoje 66 do orquestrador) não recebe código.
- `append_task`, **sob trava exclusiva entre processos** `fcntl.flock(locks_dir/"codes.lock", LOCK_EX)` (a
  `LOG_WRITE_LOCK` do servidor é só entre threads e não cobre `log.py` nem um segundo servidor sobre o mesmo log):
  1. relê o log inteiro (hoje ~650 linhas; custo desprezível);
  2. calcula `demand_codes(rows)` (§4.4) e `next = prefix + (maior número com esse prefixo + 1)`;
  3. grava a linha (`O_APPEND`, uma linha, `flush`+`fsync`) com `code`/`code_prefix` e solta a trava.
  Tempo máximo esperando a trava: 5 s → erro 503 no servidor / código 1 no `log.py` (nada gravado).
- Se `entry` já traz `code` (ex.: reimportação), `append_task` **recusa** (`ProductError`): código só nasce aqui.

### 4.3 Tabela congelada — `docs/squad/products/checkout-saga/codes.json`
Fica **fora** de `docs/squad/memory/` de propósito: lá é memória viva (`STATE` do `gitflow.py`), descartada do worktree
e proibida no PR pelo critério G3 "memória fora do PR"; a tabela é **configuração imutável revisada no PR** (errata
ADR-024 §11, E2). Na F3 ela vai para `mem:codes.json` sem mudar de formato.

```json
{
  "schema": 1,
  "product": "checkout-saga",
  "prefix": "D",
  "generatedAt": "2026-09-25T…+00:00",
  "rule": "posicional do painel em 2026-09-25: n-ésimo task com agent=humano no log",
  "source": {"log": "docs/squad/memory/decisions.jsonl", "lines": 652, "sha256": "…", "lastTaskId": "cf7a120591b0"},
  "codes": {"13e55010e3f5": "D1", "…": "…", "6450aecde7f9": "D23", "cf7a120591b0": "D24"},
  "aliases": [
    {"alias": "D7",  "id": "e31bdfb73679", "code": "D8",  "sources": ["…"]},
    {"alias": "D8",  "id": "349e5b1bf818", "code": "D7",  "sources": ["…"]},
    {"alias": "D9",  "id": "174084ec85d0", "code": "D10", "sources": ["…"]},
    {"alias": "D10", "id": "f2324e0f25de", "code": "D9",  "sources": ["…"]}
  ]
}
```

**`codes` esperado** (cálculo atual do painel sobre o log real, conferido em 2026-09-25 com 652 linhas; o gerador
refaz e o teste compara — CA-3):

| Código | id | Código | id | Código | id |
|---|---|---|---|---|---|
| D1 | `13e55010e3f5` | D9 | `f2324e0f25de` | D17 | `e1d6eae16073` |
| D2 | `48b6ace91207` | D10 | `174084ec85d0` | D18 | `b72a6bd8caf3` |
| D3 | `62f458c8038b` | D11 | `642a73cb38e5` | D19 | `402e76f187f9` |
| D4 | `1cc732c62a2d` | D12 | `1ac2708028fd` | D20 | `41bdb8b49835` |
| D5 | `d91b7a8b31d9` | D13 | `efe387a35d71` | D21 | `71b7d9bc3313` |
| D6 | `c6f83b5bb5c7` | D14 | `1e3d3c894630` | D22 | `b26da7851764` |
| D7 | `349e5b1bf818` | D15 | `518f89f27ae8` | D23 | `6450aecde7f9` |
| D8 | `e31bdfb73679` | D16 | `841f9a27e64a` | D24 | `cf7a120591b0` |

**Divergências (lista exata → `aliases`)**. Só estes 4 ids têm código citado diferente do painel; o levantamento varreu
`docs/adr`, `docs/contracts`, `docs/architecture`, `docs/squad/**/*.md`, `tests/**/*.md`, nomes de branch e de parecer:

| id | Painel (congelado) | Citado como | Onde (`sources`) |
|---|---|---|---|
| `e31bdfb73679` (cancelar demanda na validação) | **D8** | D7 | `docs/contracts/ui-cancelar-demanda.md`; `tests/ui/checklist-cancelar-d7.md`; branch `feature/D7-cancelar-demanda-na-validacao`; `docs/squad/gates/G1-D7.json`, `G2-D7.json`, `G2-D7-2.json`, `G3-D7.json`; ADR-024 §1 e mapa B14 (como exemplo) |
| `349e5b1bf818` (entrega por PR) | **D7** | D8 | `docs/adr/011-merge-com-revisao-humana.md`; `docs/contracts/entrega-por-pr.md`; `tests/ui/checklist-entrega-por-pr-d8.md`; branch `feature/D8-entrega-por-pr-com-revisao-humana`; `G1-D8.json`, `G2-D8.json`, `G2-D8-2.json`, `G3-D8.json`; ADR-024 §1, mapa B14 |
| `174084ec85d0` (modelo usado na demanda) | **D10** | D9 | `docs/adr/012-modelo-no-log-da-squad.md`; `docs/contracts/ui-modelo-por-agente.md`; branch `feature/D9-modelo-usado-na-demanda`; `G1-D9.json`, `G2-D9.json`, `G3-D9.json`; ADR-024 §1, mapa B14 |
| `f2324e0f25de` (alinhar documentação/código/infra) | **D9** | D10 | `docs/contracts/d10-alinhamento.md`; branch `feature/D10-alinhar-documentacao-codigo-infra`; `G1-D10.json`, `G2-D10.json`, `G3-D10.json`; ADR-024 §1, mapa B14 |

Causa provável: a ordem do log mudou depois que as branches foram nomeadas (importação de memória entre branches) — é
exatamente o que o `code` gravado no evento elimina daqui para frente.

**Semântica dos apelidos (sem ambiguidade)**: o apelido `D7` colide com o código congelado `D7`. Por isso:
- `resolve_code("D7", rows)` (sem `source`) → **sempre** o código congelado (`349e5b1bf818`). Vale para o painel
  (`#/demandas/D7`), a conversa (`_resolve_demand`), `gitflow` e o sino.
- `resolve_code("D7", rows, source="docs/contracts/ui-cancelar-demanda.md")` → `e31bdfb73679`: o apelido só vale no
  contexto de uma das `sources` dele (caminho relativo, nome de branch ou nome de arquivo de parecer).
- Pareceres continuam ligados à demanda pelo campo `demand` (id) dentro do JSON, não pelo nome do arquivo; nenhum
  arquivo de parecer, branch ou documento antigo é renomeado.

### 4.4 Cálculo único — `product.demand_codes(rows, p)`
Substitui os 7 cálculos posicionais (`alerts.py:93`, `gitflow.py:415`, `pending.py:33`, `testenv.py:385`,
`conversa.py` via `rules.codes`, `index.html:2790` `demandCode`, `index.html:1919` `demandInfo` — `D${index + 1}`,
que alimenta `info.code`: lista, rotas `#/demandas/<código>`, alertas e `teFor`). Determinístico, só leitura:

```
frozen = codes.json["codes"] (se o arquivo existe e prefix == p.code_prefix), senão {}
tasks  = eventos com type == "task" e agent == "humano" e id, na ordem do log
taken  = { frozen[t.id] para t em tasks se t.id em frozen } ∪ { t.code para t em tasks se t.code válido e com o prefixo }
last = 0
para t em tasks:
    se t.id em frozen:           c = frozen[t.id]
    senão se t.code válido:      c = t.code
    senão:                       n = last + 1; enquanto prefixo+n ∈ taken: n += 1; c = prefixo+n; taken += {c}
    out[t.id] = c; last = max(last, número(c))
```
- Consequência 1 (paridade): no log real de hoje, todo `task` do humano está em `frozen` → códigos idênticos ao painel.
- Consequência 2 (logs sintéticos de `tests/squad`): nenhum id do congelado aparece → o laço dá D1, D2… exatamente
  como hoje (a tabela só vale para ids presentes; nada "começa em D25" num log de teste).
- Consequência 3 (lacuna): `task` gravado entre a geração da tabela e o deploy do novo servidor, sem `code`, recebe o
  próximo posicional — o mesmo número que o painel de hoje mostraria.
- Conflito (dois ids com o mesmo `code` gravado — só por edição manual): o primeiro no log fica; `product.py codes
  --check` sai 1 e lista. O servidor não cai.

### 4.5 Geração e verificação (CLI)
- `python3 tools/squad/product.py freeze-codes --until cf7a120591b0 [--log <arq>] --out <arq>`: aplica a regra
  posicional atual (idêntica a `alerts.demand_codes` de `develop`) aos `task` até o id dado, inclusive; preenche
  `source` (linhas, sha256) e os `aliases` da tabela acima. **Só lê o log**; escreve apenas `--out`.
- `python3 tools/squad/product.py codes [--check] [--json]`: imprime id → código resolvido e apelidos; `--check` falha
  em conflito, em id do congelado ausente do log e em divergência com a regra posicional para ids do congelado.
- **Momento da geração** (resposta-padrão do Auditor, G1): no worktree da D23, sobre uma **cópia** do log da cópia
  principal (`freeze-codes` só lê o log); **regenerada pelo Orquestrador imediatamente antes do `feature-finish`** com
  `--until` no último `task` do humano existente nesse momento. Hoje é `cf7a120591b0` (D24); se entrar D25+ na janela,
  a tabela vai até ele. O PR informa o `lastTaskId` usado.

### 4.6 Painel (Frontend) e API
- `GET /api/state` ganha `codes: {id: código}` (todas as demandas) e cada `task` do humano em `log` sai com `code`
  resolvido (acréscimo na resposta, como o `enrich_log`; o log em disco não muda). `GET /api/live` **não muda** de
  chaves (test_alertas_d14).
- `index.html`: `demandCode(id)` = `state.codes?.[id]` → `task.code` → posicional (só com servidor antigo);
  `findDemand(code)` e `demandInfo` (`info.code`, hoje `D${index + 1}`) usam o mesmo mapa. Nenhuma mudança visual.
- **Apelidos no painel** (resposta-padrão do Auditor, G1): **não** nesta fase (§7). A UI mostra só o código congelado;
  `resolve_code` com `source` vale para conversa/`gitflow`/sino quando houver contexto; exibir apelidos fica para a F5.

## 5. Scripts que passam a respeitar o log configurado

### 5.1 `gitflow.py`
- `LOG`, `events()` e `demand_code()` pelo resolvedor; `demand_code(id)` = `product.demand_codes(events())[id]`.
- `log()` e demais chamadas a `log.py` passam `SQUAD_LOG=<log resolvido>` no ambiente do filho explicitamente.
- `feature-start <código> <slug> --demand <id>`: se o código não for o resolvido para o id → sai 2 ("código X ≠ Y da
  demanda"); sem `--demand`, comportamento de hoje.
- `default_worktree` usa o código congelado (`plankton-d23`); nomes de branch/worktree existentes não mudam.
- **Operações de memória no git** (`snapshot_state`, `import_memory`, `align_memory`, `discard_state`, `STATE` em
  `feature_sync`/`review_update`): só agem quando `log == repo_root/docs/squad/memory/decisions.jsonl` (memória no repo,
  o caso de hoje). Com `SQUAD_LOG` fora do repositório → são puladas com a linha `memória fora do repositório
  (SQUAD_LOG=<caminho>): <etapa> ignorada` e **nunca** tocam o log do repositório.
- Links para GitHub continuam usando o caminho canônico relativo (`docs/squad/memory/…`), como hoje (F3 muda).

### 5.2 `github_sync.py`
- `LOG = p.log`, `STATE = p.memory_dir/"github-sync.json"`, `HANDOFFS = p.handoffs_dir`. Sem variáveis, iguais aos de
  hoje; com `SQUAD_LOG` temporário, o estado do espelho fica ao lado do log temporário (nunca grava o `github-sync.json`
  real). `server.github_issues()` lê o mesmo `p.memory_dir/"github-sync.json"`.
- `link()` inalterado nesta fase (§5.1, último item).

### 5.3 `triage.py`
- `LOG = p.log`; `log.py` e `run_agent.py` filhos recebem `SQUAD_LOG` explícito. Prompt de triagem continua lido de
  `platform_root/docs/squad/prompts/triagem.md`.

## 6. Pasta de transcrições unificada (`server.py` e `run_agent.py`)

Regra do Claude Code (conferida em `~/.claude/projects`): pasta = `~/.claude/projects/` + caminho absoluto do **cwd da
sessão** com todo caractere fora de `[A-Za-z0-9]` trocado por `-` (ex.: `…/Desafio Itau/plankton-d23` →
`-Users-…-Desafio-Itau-plankton-d23`). Hoje `run_agent` usa o slug do `ROOT` (errado quando `--worktree` muda o cwd) e o
servidor o do `DATA_ROOT` (errado quando os dados vêm de outra cópia).

- `transcript_dir_for(path)` = `$SQUAD_TRANSCRIPTS` se definido; senão `~/.claude/projects/<slug(path.resolve())>`.
  Uma única implementação, usada pelos dois.
- `run_agent.py`: o metadado vai para `p.runs_dir` (hoje `ROOT/.squad/runs`; iguais sem `SQUAD_ROOT_DATA`) e ganha
  `"transcript": "<caminho absoluto>"` = `transcript_dir_for(cwd efetivo do filho) / f"{sessionId}.jsonl"` (runner
  claude). `effective_model` lê desse caminho.
- `server.py`: para runs com `transcript`, usa-o; com só `sessionId` (runs antigas), procura `<sessionId>.jsonl` em
  `transcript_dirs()`. `collect_runs` e `enrich_log` varrem `transcript_dirs()`.
- `transcript_dirs(p)` = `[$SQUAD_TRANSCRIPTS]` se definido (exclusivo, como hoje); senão, sem repetição e só as que
  existem (resposta-padrão do Auditor, G1: varrer todos os worktrees): slug de `data_root`, de `repo_root`, da cópia principal (`testenv.find_main_root`) e de cada worktree de
  `git -C <cópia principal> worktree list --porcelain`. A lista é guardada em cache por 30 s (orçamento do `/api/live`,
  ADR-017). Worktrees removidos saem da varredura; suas runs continuam achadas pelo `transcript` gravado.

## 7. Fora do escopo (F2b em diante)
Ler do cadastro qualquer valor além de `id/name/code_prefix` (repo GitHub, branches, owners, portas, Compose, PII…);
`project.json`; placeholders nos prompts; `--product` em todos os comandos; `SQUAD_HOME`; mover memória, conversas,
runs ou arquivos (F3/F4); `log.py` recusar log de outro produto (B15, F3); rotas `/api/p/<id>` e seletor (F5); mostrar
apelidos na UI; renomear branches, pareceres ou documentos antigos; prefixo `P` (F5).

## 8. Critérios de aceite (verificáveis; teste em `tests/squad/test_produto_f2a.py`, sem tocar o log real)

Mapa com o ADR-024 §6: (a) = CA-3…CA-6; (b) = CA-7…CA-9; (c) = CA-10…CA-12; (d) = CA-14.

- **CA-1 Equivalência sem produto**: sem `SQUAD_PRODUCT/SQUAD_LOG/SQUAD_ROOT_DATA/SQUAD_TRANSCRIPTS`, `resolve()` devolve
  `id="checkout-saga"`, `code_prefix="D"` e `log/gates_dir/handoffs_dir/inbox_dir/runs_dir` iguais às constantes de
  hoje de `server.py`, `gitflow.py`, `github_sync.py`, `triage.py`, `run_agent.py` (comparação de `Path`).
- **CA-2 Precedência e cadastro**: argumento > `SQUAD_PRODUCT` > padrão; id inexistente → `ProductError`; `product.toml`
  sem `code_prefix`, com `id` ≠ pasta ou prefixo `"DD"` → `ProductError` citando o campo; tabela desconhecida
  (`[env.prod]`) é aceita; produto implícito com o arquivo ausente (cadastro de teste via diretório temporário) → valores
  embutidos.
- **CA-3 Paridade com o painel de hoje** (critério do humano): o teste copia `docs/squad/memory/decisions.jsonl` da cópia
  principal para um diretório temporário (só leitura na origem; sha256 da origem igual antes/depois) e compara
  `alerts.demand_codes` **da `develop`** (`git show origin/develop:tools/squad/alerts.py`, importado de arquivo
  temporário) com `product.demand_codes` novo: mapas **idênticos** para todos os `task` do humano; em particular
  D1–D24 = tabela do §4.3.
- **CA-4 Imunidade à reordenação**: na cópia temporária, trocar de posição as linhas dos `task` D7 e D8 → o cálculo
  antigo troca os códigos, o novo não (congelado).
- **CA-5 Apelidos**: para cada linha da tabela de divergências e cada `source`, `resolve_code(alias, rows, source=…)`
  = id da linha; `resolve_code(alias, rows)` sem `source` = id do código congelado; `product.py codes --check` sai 0
  sobre a cópia do log real.
- **CA-6 Demandas novas**: em log temporário com a tabela real, `POST /api/demand` (servidor em porta livre com
  `SQUAD_ROOT_DATA`/`SQUAD_LOG` temporários) grava `code="D25"`, `code_prefix="D"`; um segundo grava `D26`;
  `log.py --agent humano --type task` grava o seguinte. **Corrida**: 20 gravações concorrentes (10 processos `log.py` +
  10 `POST`) produzem 20 códigos distintos e consecutivos; `append_task` com `code` já preenchido é recusado.
  Log sintético sem ids congelados: primeiro `task` = `D1`.
- **CA-7 `gitflow.py` honra o log**: com `SQUAD_LOG` = log temporário contendo um `task` sintético (id só nele):
  `gitflow.LOG` é o temporário, `demand_code(id)` resolve, `log()` grava no temporário, `feature-start D99 x --demand
  <id>` com código errado sai 2 sem criar branch; `import_memory`/`snapshot_state` imprimem "ignorada".
- **CA-8 `github_sync.py` e `triage.py` honram o log**: com `SQUAD_LOG` temporário e `gh` falso no `PATH`, uma passada
  do espelho lê só o temporário e grava `github-sync.json` ao lado dele; `triage.py <id sintético>` com runner falso
  grava o `validation` no temporário.
- **CA-9 Nada no real** (vale para CA-6…CA-8): sha256, tamanho e mtime de `docs/squad/memory/decisions.jsonl` e de
  `github-sync.json` do repositório iguais antes/depois; nenhum id sintético aparece neles.
- **CA-10 Transcrição a partir de worktree**: `run_agent.py … --worktree <dir temp>` com runner claude falso que grava a
  transcrição em `transcript_dir_for(<dir temp>)` (`HOME` temporário) → o metadado tem `transcript` com esse caminho e
  `/api/state` mostra o modelo da run (`modelSource` ≠ `none`).
- **CA-11 Transcrição com dados em outro lugar**: servidor com `SQUAD_ROOT_DATA` ≠ raiz do código e `HOME` temporário →
  runs gravadas por `run_agent` aparecem (runs em `data_root/.squad/runs`) e as transcrições da cópia principal e de um
  worktree registrado são varridas por `collect_runs`/`enrich_log`.
- **CA-12 `SQUAD_TRANSCRIPTS`** continua exclusivo: definido, só essa pasta é lida (testes existentes intactos).
- **CA-13 Painel**: `/api/state.codes` presente e igual a `product.demand_codes`; `/api/live` com o mesmo conjunto de
  chaves de hoje; `index.html` mostra D1–D24 iguais aos de hoje (lista, rota `#/demandas/<código>` e alertas, via `demandInfo`) (verificação visual em 1440 no painel com o log real
  copiado) e usa `state.codes`.
- **CA-14 `tests/squad` verde**: todos os arquivos `tests/squad/test_*.py` passam, inclusive os que usam logs sintéticos
  com códigos posicionais (D14, D15, D19).

## 9. Riscos

| Risco | Mitigação |
|---|---|
| `task` gravado entre a geração da tabela e o deploy fica sem `code` e pode mudar de número se o log for reordenado | regra de lacuna = posicional (igual ao painel); tabela regenerada antes do `feature-finish` (§4.5) |
| Colisão do apelido com o código congelado (`D7`) confundir humano/conversa | código sem contexto = sempre o congelado; apelido só com `source` (§4.3) |
| Varredura de várias pastas de transcrição estourar os 300 ms do `/api/live` | cache de 30 s da lista; só pastas existentes; runs novas com caminho exato (§6) |
| `flock` indisponível (FS de rede) | host é macOS/Linux local; falha da trava = erro explícito, nada gravado |
| Conflito com a D24 em voo (`server.py`/`index.html`) | quem integrar por último traz a `develop` e resolve (decisão `31400c3b82d1`) |
| Worktrees em voo rodando ferramentas antigas gravam `task` sem `code` | cálculo de lacuna cobre; só a cópia principal grava `task` (servidor 7070) |
| Branch histórica `feature/P1-portabilidade-entre-fornecedores` (PR #32) usa `P1` | não afeta a F2a (não é demanda do log). **Restrição da F5** (resposta-padrão do Auditor, G1): a sequência `P` pula códigos que já são nome de branch (começa em `P2` ou reserva `P1` na tabela do `squad-platform`); o `gitflow` já recusa branch existente |

## 10. Rollback
Reverter o PR: `code`/`code_prefix` gravados nesse meio-tempo são campos a mais, ignorados pelo código antigo; os
números coincidem com o posicional salvo reordenação do log (sem efeito em dados). Nada foi movido.
