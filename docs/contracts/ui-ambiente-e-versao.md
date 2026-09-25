# Contrato — Ambiente e versão do Squad Control (D18, `b72a6bd8caf3`, tipo operação)

> Decisão: [ADR-021](../adr/021-ambiente-e-versao-do-squad-control.md). Aditivo a ADR-016 (menu único), ADR-017
> (tema Grafite, `/api/live`) e ADR-018 (teste do checkout — **não** é o assunto aqui).
> Implementação por dono: **Orquestrador** (`tools/squad/**`: `server.py` e, se preciso, um módulo novo
> `tools/squad/instance.py`), **Frontend** (`squad-control/**`), **DevOps** (`Makefile`, só se criar alvo de teste),
> **QA** (`tests/**`).
> Respostas do humano (`e7df6310d4b6`): (1) só o ambiente do **próprio Squad Control**, que tem teste apartado;
> (2) versão = combinação de **tag de release + versão do pom + commit**; (3) **sempre visível**, de preferência no
> rodapé do menu à esquerda.

## 1. Ambiente (regra determinística)
Avaliada **uma vez na subida** do servidor, na ordem; a primeira que decide vence.

| # | Condição | `name` | `source` |
|---|---|---|---|
| 1 | `SQUAD_ENV` ∈ {`produtivo`, `teste`} (minúsculas, sem espaços nas pontas) | valor dado | `SQUAD_ENV` |
| 2 | `SQUAD_ENV` definida com outro valor | `desconhecido` | `SQUAD_ENV` (reason: `valor inválido: <v>`) |
| 3 | git indisponível ou `ROOT` fora de repositório | `desconhecido` | `indeterminado` |
| 4 | `ROOT` == cópia principal **e** porta == 7070 **e** `DATA_ROOT` == `ROOT` | `produtivo` | `inferido` |
| 5 | qualquer outro caso | `teste` | `inferido` |

- `ROOT` = raiz do código em execução (`server.py`); `DATA_ROOT` = `SQUAD_ROOT_DATA` resolvido (padrão `ROOT`).
- **Cópia principal** = o worktree cujo branch é `develop`, resolvido **pela mesma função** de
  `testenv.main_root()` (reuso, não cópia). Comparação por caminho resolvido (`Path.resolve()`).
- `reason` (texto curto, pt-BR) explica a decisão, ex.: `worktree plankton-d16, porta 7170`.
- **Dados compartilhados**: `dataIsMain = (DATA_ROOT == cópia principal) ou (SQUAD_LOG resolvido está dentro da cópia
  principal)` — o log efetivamente usado pela instância (`environment.log`, §4) também conta. Em `teste` com `dataIsMain=true` o selo
  diz "dados do produtivo" (a instância grava no log real).
- Rótulos: `produtivo` → "Produtivo"; `teste` → "Teste"; `desconhecido` → "Ambiente desconhecido".

## 2. Versão
Calculada **uma vez na subida** (`startedAt`), timeout de 2 s por comando, falha → `null` (nunca derruba o servidor).

| Campo | Fonte | Exemplo | Ausente |
|---|---|---|---|
| `release` | `git tag --list 'v[0-9]*' --sort=-v:refname` → 1ª linha (maior versão do repositório, **não** `git describe`) | `v1.0.0` | `null` → "sem tag" |
| `pom` | `<project><version>` de `ROOT/pom.xml` (filho direto de `<project>`, **não** o do `<parent>`) | `1.1.0-SNAPSHOT` | `null` → "pom ?" |
| `commit` / `commitFull` | `git rev-parse --short=7 HEAD` / `git rev-parse HEAD` | `91e3a64` | `null` → "commit ?" |
| `branch` | `git rev-parse --abbrev-ref HEAD`; `HEAD` → `null` (destacado) | `develop` | `null` → "destacado" |
| `dirty` | `git status --porcelain --untracked-files=no -- tools/squad squad-control` não vazio | `false` | `null` |
| `display` | `"<release> · <pom> · <commit>"` com os textos de ausente; se `dirty`, sufixo `" +alterações"` | `v1.0.0 · 1.1.0-SNAPSHOT · 91e3a64` | — |

- `dirty` olha **só o código que o servidor executa/serve**; `docs/squad/memory/**` e demais pastas não contam.

## 3. Atualidade ("desatualizado — reinicie")
- `headNow` = `git rev-parse HEAD`, com **cache de 30 s**, calculado **somente** ao responder `/api/state` ou
  `/api/instance` (nunca em `/api/live`).
- **Custo por janela de 30 s**: `git rev-parse HEAD` + `git status --porcelain` (recalcula `dirty` e `display`, que
  acompanham o disco). `git diff --name-only <commitFull> <headNow> -- tools/squad squad-control` roda **só quando o
  HEAD muda** (resultado memorizado por `headNow`); HEAD igual a `commitFull` → 0 arquivos, sem diff.
- `state`:
  - `atual` — `headNow == commitFull`, ou o diff acima lista 0 arquivos (commits só de memória/docs **não**
    desatualizam);
  - `desatualizado` — o diff lista ≥ 1 arquivo (`changedPaths` = nº de arquivos listados);
  - `indeterminado` — git falhou/timeout ou `commitFull` nulo.
- Texto: "Desatualizado: o código mudou desde a subida. Reinicie (`make squad`)."

## 4. API (só acréscimo)
`GET /api/instance` → 200 `application/json`, `Cache-Control: no-store`; e o mesmo objeto em `GET /api/state` como
chave nova `instance`. **`version` existente não muda** (é a versão dos dados, ADR-017). `/api/live` não muda.

```json
{
  "environment": { "name": "teste", "label": "Teste", "source": "inferido",
                   "reason": "worktree plankton-d16, porta 7170",
                   "port": 7170, "worktree": "plankton-d16", "root": "/…/plankton-d16",
                   "dataRoot": "/…/plankton", "log": "/…/plankton/docs/squad/memory/decisions.jsonl",
                   "dataIsMain": true },
  "build": { "release": "v1.0.0", "pom": "1.1.0-SNAPSHOT", "commit": "91e3a64",
             "commitFull": "91e3a64ed9d19d34380effac73d9b771e356e85f", "branch": "develop",
             "dirty": false, "startedAt": "2026-09-24T20:09:34Z",
             "display": "v1.0.0 · 1.1.0-SNAPSHOT · 91e3a64" },
  "freshness": { "state": "atual", "headNow": "91e3a64", "changedPaths": 0, "checkedAt": "2026-09-24T21:00:00Z" }
}
```
- `environment.log` (acréscimo alinhado ao G3): caminho resolvido do log que a instância usa (`SQUAD_LOG`, padrão
  `DATA_ROOT/docs/squad/memory/decisions.jsonl`); é base do aviso "dados do produtivo" (§1).
- Caminhos absolutos aparecem **só** no detalhe (instância local, 127.0.0.1); nada de segredo ou variável além das listadas.
- Servidor antigo (sem a rota) responde 404 → a UI mostra o selo em `desconhecido` com "servidor sem suporte à versão
  — reinicie" (é exatamente o caso "desatualizado").

## 5. UI (`squad-control/index.html`)
- **≥ 900 px**: bloco `.instance` no **fim da coluna do menu**, acima da autoria, com `position: sticky; bottom: 0`
  dentro de `.side` (sempre visível sem rolar, a 1440 × 900 e a 1280 × 720). Conteúdo, em linhas:
  1. rótulo do ambiente em caixa alta (**texto**) + marcador; `teste` usa o par `--warn/--warn-soft`, `produtivo`
     `--ok/--ok-soft`, `desconhecido` `--muted/--raised`; 
  2. `display` em `IBM Plex Mono` 12 px (quebra permitida em `·`);
  3. se `dataIsMain` em teste: "dados do produtivo"; se `dirty`: "alterações locais não commitadas";
  4. se `desatualizado`/`indeterminado` (⚠ nos dois): linha em `--danger` com o texto da §3 (ou "Não foi possível verificar a versão").
- **< 900 px** (menu vira barra horizontal): selo **compacto** no cabeçalho, ao lado de "Squad Control": rótulo do
  ambiente + `commit` (ex.: `TESTE · 91e3a64`), com "⚠" textual quando desatualizado **ou indeterminado**
  (QA-D18-1). Mesmo detalhe ao tocar. A 390 px não pode gerar rolagem horizontal do corpo nem empurrar o sino para
  fora da tela.
- **Desvios de layout aceitos no G2** (prevalecem sobre o item acima):
  - 600–900 px: o cabeçalho omite o nome do produto e usa rótulos curtos para caber o selo;
  - 600–780 px: o selo compacto oculta o `commit` (só rótulo + ⚠); o commit segue no detalhe e no `aria-label`;
  - < 600 px: o selo compacto fica **fixo no canto inferior esquerdo** (não no cabeçalho), e os toasts sobem 64 px
    para não o cobrir.
- **Detalhe**: o selo é um `<button aria-expanded>` que abre painel com todos os campos da §4 (tag, pom, commit
  completo, branch, worktree, porta, origem dos dados, subiu em, HEAD atual, motivo do ambiente) e botão "Copiar".
  Também `title` com `display`. Fecha com Esc e clique fora.
- **Acessibilidade**: `aria-label` = "Ambiente: <label>. Versão <display>[. Desatualizado, reinicie | . Não foi possível verificar a
  versão]" (o segundo sufixo em `indeterminado`/ausente, QA-D18-1); contraste AA
  nos dois temas; estado nunca só por cor.
- **Carga**: lê `instance` do `/api/state` já buscado; atualiza por `GET /api/instance` a cada 60 s e ao voltar o
  foco à aba. Sem novas chamadas no ciclo de 1,5 s.
- **Título da aba**: em `teste`/`desconhecido`, prefixo `[TESTE] ` / `[?] ` no `document.title` (produtivo sem prefixo).

## 6. Critérios de aceite
| # | Critério | Como verificar |
|---|---|---|
| CA1 | Cópia principal, porta 7070, sem `SQUAD_ROOT_DATA` → `environment.name=produtivo`, `source=inferido` | teste unitário com `ROOT`/porta/`DATA_ROOT` simulados + `curl :7070/api/instance` |
| CA2 | Worktree de feature (qualquer porta) → `teste`; `reason` cita worktree e porta | unitário; instância em `plankton-d18` porta ≠ 7070 |
| CA3 | Cópia principal em porta ≠ 7070, ou com `SQUAD_ROOT_DATA` de outra pasta → `teste` | unitário |
| CA4 | `SQUAD_ENV=produtivo` num worktree → `produtivo`, `source=SQUAD_ENV`; `SQUAD_ENV=xyz` → `desconhecido` com motivo | unitário |
| CA5 | Sem git (PATH sem git ou `ROOT` fora de repo) e sem `SQUAD_ENV` → `desconhecido`; servidor sobe e responde | unitário |
| CA6 | Teste com `SQUAD_ROOT_DATA` = cópia principal → `dataIsMain=true` e a UI mostra "dados do produtivo" | unitário + tela |
| CA7 | `release` = maior tag `v*` mesmo quando não é ancestral do HEAD (hoje `v1.0.0` em `develop`); sem tags → `null` e "sem tag" | repo temporário com tag fora da história |
| CA8 | `pom` lê a versão do projeto, não a do `<parent>` (hoje `1.1.0-SNAPSHOT`, não `3.4.5`) | unitário |
| CA9 | `display` exato `v1.0.0 · 1.1.0-SNAPSHOT · <sha7>` (separador ` · `, U+00B7) | unitário |
| CA10 | Commit novo que só altera `docs/squad/memory/**` → `freshness.state=atual` | repo temporário |
| CA11 | Commit novo que altera `tools/squad/**` ou `squad-control/**` após a subida → `desatualizado`, `changedPaths ≥ 1`, e a UI mostra o texto de reinício | repo temporário + tela |
| CA12 | Arquivo modificado não commitado em `squad-control/` → `dirty=true` e "+alterações"; modificado só em `docs/squad/memory/` → `dirty=false` | repo temporário |
| CA13 | `/api/live` não executa git (0 subprocessos) e seu payload/headers não mudam; `/api/instance` roda no máximo `rev-parse` + `status` por janela de 30 s, e `diff --name-only` só quando o HEAD muda | teste com contador de `subprocess` |
| CA14 | `/api/state` mantém todas as chaves anteriores (incl. `version`) e acrescenta `instance` | teste de contrato |
| CA15 | 1440 px: selo visível no rodapé do menu sem rolar, em página longa rolada até o fim | Playwright (`tests/ui`) |
| CA16 | 390 px: selo compacto fixo no canto inferior esquerdo (desvio G2), toasts 64 px acima; sem rolagem horizontal do corpo; sino visível | Playwright |
| CA17 | Selo abre/fecha por teclado (Enter/Esc) e o detalhe lista os campos da §4; `aria-label` conforme §5 | Playwright + axe sem violações novas |
| CA18 | Tema claro e escuro: estado legível por texto; contraste AA | axe / inspeção |
| CA19 | Servidor antigo (sem `/api/instance` → 404) com UI nova: selo "desconhecido" com texto de reinício, sem erro no console | Playwright com rota interceptada |
| CA20 | Nenhuma falha de git derruba `/api/state` (timeout 2 s por comando) | unitário com git que dorme |

## 7. Riscos
- **Instância de teste gravando no log real** (`dataIsMain`): o selo só **avisa**; bloquear escrita fica fora (ver §8).
- **Worktree não-`develop` na cópia principal** (alguém faz checkout de outra branch em `plankton/`): vira `teste`
  pela regra — correto, mas pode surpreender; o `reason` explica.
- **Tag só em `main`**: a "última release" pode não estar no código em execução; o detalhe mostra `branch` e commit.
- **Custo do git em repositório grande**: mitigado por cálculo na subida + cache de 30 s + timeout.

## 8. Fora de escopo
- Ambiente/versão do checkout (`checkout-saga`/`checkout-teste`) — já no cartão "Ambientes" (D15).
- Reiniciar o servidor pela tela; recarregar código a quente.
- Bloquear escrita de uma instância de teste nos dados do produtivo.
- Convenção de porta ou alvo `make` para subir o Squad Control de teste (pode virar demanda própria).
- Mudar `version` de `/api/state`/`/api/live` ou o formato do `/api/live`.
