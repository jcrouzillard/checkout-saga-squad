# Checklist QA — D13 Navegação do Squad Control (`efe387a35d71`)

Contrato: `docs/contracts/ui-navegacao-squad-control.md` (CA-1..CA-16, PA-1..PA-23, T1..T10). Base: `8f18e8b` (G2 aprovado).
Script: `tests/ui/d13-navegacao.js` (Puppeteer em Docker). Servidores do worktree:
- **7112**: dados reais, **somente leitura**. O script aborta todo POST (0 POSTs enviados). `SQUAD_TRANSCRIPTS`/`CODEX_HOME` vazios.
- **7113**: `SQUAD_ROOT_DATA` = cópia temporária no scratchpad (memory, gates, inbox, project.json da cópia principal).
  Fixtures entram **só** no log temporário: D14/D15/D16 ativas (Backend na D14 via `.squad/runs` com pid vivo), D17 backlog,
  D20 validação atrasada, D21 devolvida pelo revisor, D22 backlog. As decisões humanas foram conferidas nesse log.
Contagem de cliques: sempre a partir do Painel. Abrir sino ou toast conta 1. Digitar não conta.

## Tarefas (§9.3)
| # | Resultado | Caminho, cliques e evidência |
|---|---|---|
| **T2** toast, 1440 | **PASSA** | D14 G2 RETURN 62% `human_required`; D16 (a última ativa) recebeu G1 depois. Toast "D14 · Auditor devolveu G2" → **Abrir D14** (1) → `#/demandas/D14/gates`, foco em `note-fx14aaaaaaaa-G2`, menu Demandas → nota → **Aceitar devolução** (2). POST `{"action":"APPROVE","gate":"G2","demand":"fx14aaaaaaaa"}`. No log: `human` com `gate=G2` e `demand=fx14aaaaaaaa`. **2 cliques (limite 3).** |
| **T2** sino, 390 | **PASSA** | D15 G2 RETURN 58% (conf. < 70%); D16 recebeu G2 APPROVE depois. Sino (1) → item "D15 · Auditor devolveu G2" (2) → `#/demandas/D15/gates`, foco na nota → **Seguir mesmo assim** (3). No log: `human` G2 / `fx15bbbbbbbb` / OVERRIDE. **3 cliques.** Sem rolagem horizontal (`d13-t2-decisao-390.png`). |
| **T2** página + **T10** teclado | **PASSA** | Novo ciclo G2 da D14 com D16 G3 depois. Sem mouse: Shift+Tab ×10 do `h1` até "Pular para o conteúdo" (visível no foco) → Enter → foco no `h1` "Painel" → Tab ×3 → "Decidir G2" (Precisa de você) → Enter → foco na nota da D14 → Tab → "Aceitar devolução" (`G2`, `fx14aaaaaaaa`) → Enter. No log: `human` G2 / D14. `#sr-live`: "D14 aberta", depois "Decisão sobre G2 da D14 enviada ao Orquestrador." Menu por teclado (Demandas, Squad, Auditoria, Painel): foco no `h1` e anúncio "<Tela> aberta" em todas. Esc fecha a gaveta (tira `?agente=`) e o sino (foco volta ao sino). |
| **T9** 1440 e 390 | **PASSA** | Em `#/demandas/nova`: título, tipo Operação e descrição preenchidos pela metade, foco na descrição. Evento novo no log, 10,5 s (6 polls): valores, radio, foco (`dem-detail`) e cursor (39 → 45 depois de continuar digitando) preservados; a rota não mudou. CA-11: `details` do Registro aberto e rolagem (600 px) mantidos por 7 s na D14. |
| **T5** 1440 | **PASSA com ressalva** | `#/demandas/D14/gates`: a mesma tela e o mesmo alvo depois de F5 e em outra aba (a D14 tinha decisão pendente, então a página rola até a Próxima ação com foco na nota, como previsto). D16 sem pendência: a seção Gates fica no topo. F5 também preserva `?agente=backend` (gaveta aberta), `?f=backlog` e `?demanda=D14&tipo=gate` na Auditoria. Ressalva DEF-2: o índice local não marca a seção ativa. |
| **T7** 1440 e 390 | **PASSA** | Produto (1) → Jaeger (2) → iframe `:16686`. "Abrir Jaeger em nova aba ↗" (3) abre outra aba e a original fica em `#/produto/jaeger`. Voltar → `#/produto/grafana` (foco no `h1`) → Voltar → `#/painel`. |
| **T1** 1440 e 390 | **PASSA** | Painel "+ Nova demanda" (1). Validações do formulário conferidas: sem título e sem tipo mostram mensagem. Registrar leva a `#/demandas/D18` (D19 a 390). Validação com 2 perguntas injetada no log temporário: Próxima ação "Responder 2 perguntas do Arquiteto" → link Validação (1, foco na 1ª resposta) → 2ª resposta (2) → Enviar (3). O evento `clarification` tem 2 respostas e a Próxima ação passa a "Iniciar". **3 cliques depois de registrar, sem usar o menu.** |
| **T3** 1440 e 390 (reais) | **PASSA** | Painel › Entregues recentemente › D11 (**1**): "Entregue · PR #106 · commit 73c6a4e"; seção Gates com G1 85%, G2 90% e G3 88%, todos APPROVE; etapa "Entregue (7 de 7)". |
| **T4** 1440 e 390 | **PASSA** | Faixa de agentes › Backend (1): gaveta aberta com foco em Fechar e "Executando agora" na sessão da D14 → "Abrir D14 ›" (2) → `#/demandas/D14` com a gaveta fechada e o menu em Demandas. |
| **T6** 1440 | **PASSA** | Demandas (1) → Backlog (2) → Mover para a fila (3), com a mensagem "movida do backlog para a fila" → Na fila (4): "D17 … 1º na fila". O evento `start` tem `fromBacklog`. **4 cliques (limite 4).** Captura: `d13-fila-1440.png`. |
| **T8** 1440 e 390 | **PASSA** | Auditoria (1) → Políticas (2): gates.md e CLAUDE.md. |

## Critérios de aceite
| CA | Status | Evidência |
|---|---|---|
| CA-1 | PASSA | Um único `nav[aria-label=Principal]` com 5 itens na ordem Painel, Demandas, Squad, Auditoria e Produto. Nenhum `.tabs`. |
| CA-2 | PASSA | Hash vazio abre o Painel com "Precisa de você". |
| CA-3 | PASSA com ressalva | 28 rotas testadas a 1440 e a 390, inclusive `D13` e o id do log, `D999` ("Demanda não encontrada"), filtros e gaveta. Os aliases `#execucoes`, `#/decisoes`, `#/evidencias`, `#/politicas`, `#/agentes` e `#/observabilidade` redirecionam. `#/xyz` vai ao Painel com aviso. Voltar funciona: D13 → Demandas → Painel. F5 preserva a rota (T5). Ressalva DEF-4: aviso antigo persistente. |
| CA-4 | PASSA | Exatamente um `aria-current=page` em todas as rotas, e ele corresponde à tela, também ao chegar por toast, sino, alias, gaveta e Voltar. |
| CA-5 | PASSA | Breadcrumb com link em todas as páginas de 2º nível. `document.title` = `(não lidas) <Tela ou Dn> · Squad Control · Checkout Saga`. A troca de rota leva o foco ao `h1` e anuncia em `#sr-live` (T10). |
| CA-6 | PASSA com ressalva | Páginas conferidas: ativa (D13, D14), na fila (D17, D18), backlog (D22), entregue (D11), cancelada (D15, D19), devolvida pelo revisor (D21) e aprovada abrindo PR (D16). Ressalvas: DEF-2 e DEF-5. |
| CA-7 | **FALHA parcial** | A ordem 1 aparece (badge vermelho, "Decidir G2") e some depois da decisão. A ordem 3 (PR #104 da D12) e a ordem 4 (Iniciar) funcionam. **DEF-1**: a ordem 5 (validação atrasada) continua listando demandas **já iniciadas** (D17 vinda do backlog e D20 iniciada com override) e infla o badge. |
| CA-8 | PASSA | No sino e no toast, gate vai para `/Dn/gates`, `control`/`start` para `/Dn`, `review-rejected` para `/Dn`. O botão do toast diz "Abrir Dn". |
| CA-9 | PASSA | Três decisões em demandas que **não** eram a última ativa. Os eventos `human` do log temporário têm o gate e a demanda exibidos, e o gate da D16 (a mais recente) não foi afetado. |
| CA-10 | PASSA | Registrar leva à demanda nova. Enviar respostas, Iniciar (PA-3), controles e decisão de gate mantêm o usuário na demanda, com mensagem e anúncio. |
| CA-11 | PASSA | T9 e a D14 com `details` e rolagem. A faixa `#ai-usage` aparece em todas as rotas exceto `#/produto/*`. |
| CA-12 | PASSA | Requisições da UI: só `GET /api/state|project|policy` e, na cópia temporária, POST em `/api/demand`, `/api/demand/{clarify,start,edit,control}` e `/api/human`, com os corpos atuais. |
| CA-13 | PASSA | Nenhum `<script src>`. Só o link de fontes que já existia (IBM Plex). |
| CA-14 | PASSA | A 390 px, `scrollWidth` = 390 nas 28 rotas, o menu fica numa barra única com itens de 44 px e as tarefas foram executadas nessa largura. A 1440 px, lateral de 208 px. |
| CA-15 | **FALHA parcial** | **DEF-3**: os links de PR de `reviewHtml` (Entregues recentemente PR #106/#95/#90; cabeçalho de entregue ou devolvida) não têm "↗" nem "(abre em nova aba)". O mesmo ocorre na issue do item de backlog (l. 892, visto no código). Os demais externos estão conformes, e os internos usam `#/…`. |
| CA-16 | PASSA | "Pular para o conteúdo" é o 1º focável e, quando ativado, leva ao `h1`. Navegação completa por teclado; Esc fecha a gaveta e o sino. Nota: na carga o foco já vai para o `h1`, então o 1º Tab entra no conteúdo; o skip é alcançado com Shift+Tab. |

## Paridade (máx. de cliques a partir do Painel)
| PA | Status | Caminho (cliques) |
|---|---|---|
| PA-1 | PASSA | "+ Nova demanda" (1) → Registrar (2). Mensagens de título e tipo obrigatórios verificadas (T1). |
| PA-2 | PASSA | Precisa de você › Responder (1) → Enviar (2) (T1). |
| PA-3 | PASSA | "Iniciar na D18" (1) → prioridade alta, rota direta, agente frontend → Iniciar (2): `start` com esses valores e "1º na fila". Override: "Ver validação" (1) → marcar override (2) → Iniciar sem nota mostra erro → nota → Iniciar (3): `start.override=true` com a nota. |
| PA-4 | PASSA | Demandas (1) → Backlog (2) → Editar (3) → Salvar: `edit.changes.title`. Salvar é o clique de ação, como no PA-7. |
| PA-5 | PASSA | Precisa de você › D19 (1) → Cancelar demanda (2) → motivo → Confirmar (3): `control cancel` com o motivo e status CANCELADA. |
| PA-6 | PASSA | Demandas (1) → Na fila (2), com a posição. |
| PA-7 | PASSA | Em andamento › D16 (1) → Pausar/Retomar (2), Prioridade (select) e Cancelar + Confirmar (D15: `cancel`). Obs.: na D16 com G3 aprovado o servidor recusa o cancelamento (409, regra anterior). |
| PA-8 | PASSA | "Agora" no Painel (0); Ver execução (1). |
| PA-9 | PASSA | T2 (2–3). |
| PA-10 | PASSA | D14 (1) → Evidências (2), com o parecer completo quando existe arquivo. |
| PA-11 | PASSA | `#/painel/squad-base`: linha do tempo com 6 passos e botões `G1` sem demanda (0–1 quando não há demanda ativa). |
| PA-12 | PASSA | PR em revisão (D12) no Painel, link externo (1). Entregue com commit (T3, 1). Devolvida pelo revisor (D21, 1–2). |
| PA-13 | PASSA | D11 (1) → issue #96 ↗ (2). |
| PA-14 | PASSA | "Modelos:" no cabeçalho da demanda; selos nos eventos (Auditoria, 338) e na gaveta (gpt-5-codex · OpenAI). |
| PA-15 | PASSA | Auditoria (1): 405 de 405 eventos, com selos. |
| PA-16 | PASSA | Auditoria (1) → Handoffs (2). |
| PA-17 | PASSA | T8 (2). |
| PA-18 | PASSA | Squad (1): 8 cards. Gaveta (1) fecha com Esc. |
| PA-19 | PASSA | Produto (1) → Jaeger (2) → nova aba ↗. Seletor de produto presente (só 1 produto no project.json). |
| PA-20 | PASSA | 1440: lateral "Links do produto" ↗ (1). 390: Produto (1) → link (2). |
| PA-21 | PASSA | Sino com não lidas e badge de ação; toasts "Abrir Dn". Notificação do SO não testável em headless (código mantido). |
| PA-22 | PASSA | Faixa de consumo em todas as rotas exceto Produto (0). |
| PA-23 | PASSA | Contador do Squad = agentes trabalhando (0); total do log na aba Eventos (1). |

## Contador no título da aba (item 6 do G2)
`document.title` = "(30) …" = **notificações não lidas do sino** (`renderBell`, limitadas às últimas 30). O badge do Painel
mostra à parte o nº de "Precisa de você" (6 na fixture; 2 com o D14 pendente, e vermelho). Isso segue o contrato §7
(`[(<não lidas>) ]`), portanto **conforme**. As duas contagens são independentes, e o título não reflete "Precisa de você".

## Migração dos scripts antigos
- `tests/ui/d9-screenshots.js`: sem `.tabs` e sem `data-view`. Usa `#execucoes`, `#/demandas?f=todas`, `#/demandas/D10` e
  `#/auditoria/eventos`, com gaveta via `?agente=auditor`. POST abortado. **Rodou com sucesso** a 1440 e 390: selos presentes,
  `scrollWidth` = viewport, sem `undefined`/`NaN`. Os únicos erros são 404 de favicon, que já existiam.
- `tests/ui/d11-screenshots.js`: telas pelos aliases (`ROUTE`), formulário em `#/demandas/nova`, cabeçalho a 390 conferido
  pelos itens do `#menu` e sem `.tabs`. **Rodou com sucesso** contra 7112/7113. A faixa fica visível e presa ao topo depois da
  rolagem e oculta em Produto. Estados do Claude (fresh 42,5%, atenção 85%, crítico 97%, stale, none, corrompido) lidos da
  fixture. A altura fica entre 68 e 69 px (≤ 72) de 600 a 1440 px. Foco e texto foram mantidos por mais de 2 ciclos enquanto
  a faixa se atualizava (30 → 88 → 96%). Sem erros além do favicon. As montagens estão no cabeçalho do script.

## Defeitos (dono: Frontend, `squad-control/index.html`)
- **DEF-1 (médio, CA-7)**: `nextAction` ordem 5 (`vinfo.st === "atrasada"`) não exige `preStart`. Demandas já iniciadas sem
  validação (vindas do backlog, ou com override) aparecem em "Precisa de você" como "Validação atrasada" até a execução
  começar, o que infla o badge. Reprodução: fixture D17 (Mover para a fila) e D20 (override) com mais de 3 min.
- **DEF-2 (baixo, §7/CA-6)**: `renderDemanda` lê a seção em `route.parts[2]` (l. 685), mas a rota `#/demandas/Dn/<secao>` a
  guarda em `parts[1]`. Por isso o índice local nunca marca `aria-current="location"` e `#/demandas/Dn/registro` não abre o
  Registro. Verificado em execucao, gates, validacao e registro: `toc=null`, `regOpen=false`.
- **DEF-3 (baixo, CA-15)**: os links de PR em `reviewHtml` (l. 826/828) e a issue do item de backlog (l. 892) não usam
  `extLink`, então ficam sem "↗" e sem "(abre em nova aba)".
- **DEF-4 (baixo, CA-3)**: depois de `#/xyz`, ir para `#/painel#squad-base` mantém o aviso "Página não encontrada" (l. 1154:
  o aviso só é limpo quando a rota já é canônica).
- **DEF-5 (baixo, CA-6)**: na seção Gates, cada ciclo de um mesmo gate mostra a **última** decisão humana (`humanFor` sem
  limite superior). O 1º G2 da D14, decidido às 12:33:25 (T2), aparece com a decisão das 12:39:34 (`d13-demanda-gates-1440.png`).
- Observação que já existia desde o D7, não é regressão do D13: "Cancelar demanda" (em andamento) guarda a confirmação no nó
  do DOM, e o polling de 3 s a desfaz se o humano demorar para confirmar.

## Capturas (`tests/ui/`)
Com dados reais: `d13-painel`, `d13-demandas`, `d13-demanda-ativa` (D13), `d13-demanda-entregue` (D11), `d13-auditoria` e
`d13-produto`, cada uma a 1440 e 390. Com fixture: `d13-painel-fixture`, `d13-demanda-gate` e `d13-demanda-backlog` (1440 e 390),
`d13-demanda-gates-1440`, `d13-fila-1440`, `d13-gaveta-1440`, `d13-t1-validacao-390` e `d13-t2-decisao-390`.
