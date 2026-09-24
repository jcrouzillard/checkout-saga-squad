# Contrato — Navegação do Squad Control (D13, `efe387a35d71`, tipo operação)

> Decisão: [ADR-016](../adr/016-navegacao-unica-por-tarefa.md). Implementação: **Frontend** (`squad-control/index.html`).
> Servidor: **nenhuma mudança necessária** (rotas por hash são só do cliente; todas as APIs atuais são mantidas).
> Respostas do humano: (1) só o **Squad Control**; (2) aplicar boas práticas reconhecidas e citá-las; (3) funcionalidades
> **inteligíveis e agrupadas**, navegação **fluida**, "**uma coisa leva a outra**"; (4) pode reagrupar, renomear e
> remover telas/itens **sem perder funcionalidade**.
> Escopo: navegação, arquitetura de informação, links contextuais e indicação de local. Não muda regras de negócio,
> estados de demanda (`demandInfo`), validação (ADR-008), backlog (ADR-009), entrega por PR (ADR-011), modelo (ADR-012),
> nem a faixa de consumo (ADR-014).

## 1. Práticas de usabilidade adotadas

| # | Prática | Fonte | Onde se aplica aqui |
|---|---|---|---|
| P1 | Visibilidade do estado do sistema | Nielsen #1 | faixa de etapas (stepper) da demanda; contador "Precisa de você"; item de menu ativo |
| P2 | Correspondência com o mundo real (vocabulário do usuário) | Nielsen #2 | nomes por tarefa ("Precisa de você", "Revisar PR"), não por artefato interno ("decisions.jsonl") |
| P3 | Controle e liberdade (voltar, desfazer, sair) | Nielsen #3 | rota na URL → Voltar/Avançar do navegador, F5 e link compartilhável funcionam |
| P4 | Consistência e padrões | Nielsen #4; WCAG 3.2.3 *Consistent Navigation* | **um** menu primário, sempre no mesmo lugar, mesmos nomes em menu, título e breadcrumb |
| P5 | Reconhecer em vez de lembrar | Nielsen #6 | a próxima ação aparece onde o item está; notificação leva ao item, não a uma lista |
| P6 | Flexibilidade e eficiência | Nielsen #7 | deep links, filtros na URL, atalho "Nova demanda" global |
| P7 | Design minimalista | Nielsen #8 | progressive disclosure: lista compacta → detalhe; históricos em seções recolhíveis |
| P8 | Arquitetura de informação por tarefa / por objeto (OOUX) | Rosenfeld & Morville; Sophia Prater (OOUX) | a **Demanda** é o objeto central: página única que agrega validação, execução, gates, PR e registro |
| P9 | Navegação primária única e rasa, poucas opções | NN/g *menu design*; Lei de Hick | 5 itens de primeiro nível (hoje 7 no menu + 3 abas duplicadas) |
| P10 | Breadcrumbs e indicação de local | NN/g *Breadcrumbs*; WCAG 2.4.8 *Location*, 2.4.2 *Page Titled* | trilha "Demandas › D13 › Gates"; `document.title` por tela |
| P11 | Progressive disclosure | NN/g | detalhe da demanda mostra primeiro a "Próxima ação"; histórico e registro abaixo/recolhidos |
| P12 | *Next best action* / fila de atenção (padrão de consoles de operação e *inbox*) | NN/g *dashboards*; padrões de console de incidentes | tela inicial "Painel" com a lista do que depende do humano, ordenada por urgência |
| P13 | Faro de informação (*information scent*) | Pirolli & Card | rótulos de link dizem o destino ("Decidir G2 na D13", "Revisar PR #12 ↗") |
| P14 | Múltiplos caminhos e bloco pulável | WCAG 2.4.5 *Multiple Ways*, 2.4.1 *Bypass Blocks* | menu + breadcrumb + links contextuais + notificações; link "Pular para o conteúdo" |
| P15 | Mensagens de status sem roubar foco | WCAG 4.1.3; 2.4.3 *Focus Order* | polling não move foco; troca de rota move o foco para o `h1` e anuncia no `#sr-live` |

## 2. Inventário (estado atual → novo lugar)

Linhas de referência: `squad-control/index.html` do commit base desta branch. "Cliques" = a partir do **Painel** (tela inicial).

| # | Funcionalidade | Onde está hoje | Onde fica | Cliques |
|---|---|---|---|---|
| I1 | Abas do topo "Execução / Política / Demandas" (l. 243) | cabeçalho | **removidas** (duplicavam o menu lateral) | — |
| I2 | Menu lateral OPERAÇÃO/GOVERNANÇA/PRODUTO (l. 249-261) | lateral | **menu único** de 5 itens (§4) | — |
| I3 | Linha do tempo da demanda ativa + "Agora:" (`renderExecucoes`, `demandSteps`) | Execuções | Demanda › seção **Execução**; resumo "Agora" no Painel (Em andamento) | 1 |
| I4 | Pipeline base F1→G3 (sem demanda ativa, `pipelineStatus`) | Execuções | Painel › bloco **Squad base (ADR-000)**, só quando não há demanda ativa | 0 |
| I5 | Faixa de agentes (`renderSquadStrip`) + gaveta do agente (`renderDrawer`) | Execuções; gaveta global | Painel e Squad; gaveta abre de qualquer tela (`?agente=`) | 1 |
| I6 | Recomendação do Auditor (último gate, confiança, risco) | Execuções | Demanda › **Próxima ação** (se exige humano) e seção **Gates**; Painel se sem demanda | 1-2 |
| I7 | Evidências do gate + Intervenção humana (nota, Enviar/Devolver/Aceitar devolução/Seguir mesmo assim; `/api/human`) | Execuções | Demanda › **Próxima ação** / **Gates** (gate da própria demanda); Painel › Squad base para gate sem demanda | 2 |
| I8 | Pausar / Retomar / Prioridade / Cancelar (em andamento; `controlsHtml`, `/api/demand/control`) | Execuções e card em Demandas | Demanda › cabeçalho (ações da demanda) | 2 |
| I9 | Selo de modelos por demanda (`demandModelsHtml`) e por evento/execução (`modelChip`) | Execuções, Demandas, Decisões, gaveta | Demanda › cabeçalho; Auditoria › Eventos; gaveta | 1 |
| I10 | Bloco de revisão/entrega (PR, commit, devolvida pelo revisor; `reviewHtml`) | Execuções e card | Demanda › **Próxima ação** ("Revisar PR #n ↗") e cabeçalho (link do PR); Painel se aguardando revisão | 1 |
| I11 | Formulário Nova demanda (título, descrição, tipo, quando, prioridade; `/api/demand`) | Demandas (coluna esquerda) | **Nova demanda** `#/demandas/nova` — botão no menu, no Painel e em Demandas | 1 |
| I12 | Fila do Orquestrador (posição, prioridade) | Demandas | Demandas › filtro **Na fila** (com posição) e cabeçalho da demanda ("3º na fila") | 2 |
| I13 | Backlog: listar, editar inline, prioridade/rota/agente, Mover para a fila, cancelar (`backlogItemHtml`, `/api/demand/edit`, `/api/demand/start`) | Demandas | Demandas › filtro **Backlog** (lista) → Demanda › Próxima ação ("Mover para a fila") e **Editar** | 2-3 |
| I14 | Perguntas da validação + Enviar respostas (`questionsHtml`, `/api/demand/clarify`) | card em Demandas | Demanda › **Próxima ação**; item no Painel "Responder N perguntas" | 1 |
| I15 | Iniciar (prioridade/rota/agente) + override com nota (`preStartHtml`) | card em Demandas | Demanda › **Próxima ação** | 1-2 |
| I16 | Cancelar antes do início (confirmação com motivo; `preCancelHtml`) | card em Demandas | Demanda › ações da demanda | 2-3 |
| I17 | Lista "Demandas registradas" (status, tags tipo/issue/prioridade/rota/gates, último passo) | Demandas | Demandas › lista compacta com filtros; detalhe na Demanda | 1 |
| I18 | Link da issue no GitHub | card | lista e cabeçalho da Demanda ("issue #n ↗") | 1 |
| I19 | Decisões: log completo (`renderDecisoes`) | menu Decisões | **Auditoria › Eventos** (+ filtros demanda/agente/tipo); Demanda › **Registro** (filtrado) | 1 |
| I20 | Evidências: pareceres dos gates (`renderEvidencias`) | menu Evidências | **Auditoria › Gates**; Demanda › **Gates** (gates da demanda, pelo log) | 1 |
| I21 | Handoffs (briefs) | menu Evidências | **Auditoria › Handoffs** | 2 |
| I22 | Políticas: gates.md + constituição (`/api/policy`) | aba Política e menu Políticas | **Auditoria › Políticas** | 2 |
| I23 | Agentes: feed ao vivo de cada agente (`renderAgentes`) | menu Agentes | **Squad** | 1 |
| I24 | Observabilidade: seletor de produto, Grafana/Jaeger em iframe, abrir em nova aba | menu Observabilidade | **Produto** (`#/produto/grafana`, `#/produto/jaeger`) | 1-2 |
| I25 | Links do produto (Console de Checkout, API de pedidos; `project.json`) | lateral, sem indicação de externo | **Produto** e rodapé do menu, com "↗" e "(abre em nova aba)" | 1 |
| I26 | Sino: painel de notificações, não lidas, badge vermelho se ação | cabeçalho | mantido; cada item leva ao **item** (§6.2) | 1 |
| I27 | Toasts + notificação do SO | canto inferior | mantidos; "Ver" leva ao item (§6.2) | 1 |
| I28 | Contadores do menu (log, agentes trabalhando, demandas) | lateral | Painel = nº "Precisa de você"; Squad = agentes trabalhando; Auditoria › Eventos mostra o total do log | 0 |
| I29 | Faixa `#ai-usage` (D11) | topo de `<main>`, exceto Observabilidade | igual: todas as telas exceto **Produto** | 0 |
| I30 | Anúncios `aria-live` de mudança de estado das demandas | global | mantido | — |
| I31 | Tira "Desafio Técnico … / autor" e nome do produto no cabeçalho | cabeçalho | mantidos | — |

## 3. Problemas encontrados

| # | Problema (evidência) | Heurística violada |
|---|---|---|
| X1 | **Dois menus sobrepostos**: abas do topo (Execução, Política, Demandas) repetem 3 dos 7 itens do menu lateral, com nomes diferentes (singular × plural). | Nielsen #4, #8; WCAG 3.2.3 |
| X2 | **Local falso**: a aba "Execução" fica marcada em Decisões, Evidências e Agentes (l. 987); ao abrir por notificação/toast (`data-goto`, l. 980-981) as abas não são atualizadas → duas indicações de local contraditórias. | Nielsen #1, #4; WCAG 2.4.8 |
| X3 | **Estado fora da URL**: F5 volta sempre para Execuções; Voltar do navegador sai do painel; não há link para uma demanda/gate. | Nielsen #3, #7 |
| X4 | **Execuções mostra só uma demanda** (`activeDemand()` = a última ativa); demandas paralelas ou já entregues não têm tela de execução, e o card não linka para ela. | Nielsen #6; OOUX |
| X5 | **Ciclo da demanda espalhado**: validar/iniciar/backlog em Demandas; execução/gate/intervenção em Execuções; pareceres em Evidências; eventos em Decisões — sem links entre eles. | P8; Nielsen #6 |
| X6 | **Notificações levam a telas, não a itens** (`view: "demandas"`/`"execucoes"`): o humano precisa procurar o card/gate. | Nielsen #6; P13 |
| X7 | **Não existe "o que depende de mim"**: perguntas, gates obrigatórios e PRs a revisar estão em telas diferentes; só o sino (lista cronológica) os mistura com novidades. | P12; Nielsen #1 |
| X8 | **Demandas sobrecarregada**: formulário + fila + backlog + todos os cards + parágrafo explicativo de 5 linhas numa só tela, crescendo sem filtro. | Nielsen #8; P11 |
| X9 | **Rótulos pelo artefato, não pela tarefa**: "Decisões" é o log de eventos inteiro; "Evidências" mistura pareceres e handoffs; contador de Decisões (tamanho do log) é ruído. | Nielsen #2, #8 |
| X10 | **Links externos misturados ao menu** (Console, API) sem indicação de que abrem outra aplicação. | Nielsen #4; P13 |
| X11 | **Intervenção humana pode ir para o gate errado**: a tela mostra o gate da demanda ativa, mas o POST usa `latestGate()` global (l. 1096-1098). | Nielsen #5 (prevenção de erro) — defeito |
| X12 | **Abaixo de 900 px os dois menus empilham** (abas no cabeçalho + lateral virando bloco de links que quebra), empurrando o conteúdo para baixo. | Nielsen #8; WCAG 2.4.1 |

## 4. Nova arquitetura de informação

### 4.1 Menu primário único (5 itens, nesta ordem)

| Item | Rota | Pergunta que responde | Conteúdo |
|---|---|---|---|
| **Painel** (inicial) | `#/painel` | "O que depende de mim e o que está andando?" | **Precisa de você** (fila de próximas ações), **Em andamento** (todas as demandas ativas com "Agora: …" e etapa), **Entregues recentemente** (3 últimas com PR), faixa de agentes; **Squad base (ADR-000)** só sem demanda ativa |
| **Demandas** | `#/demandas` | "Quais são as demandas e em que pé estão?" | lista compacta com filtros; botão **Nova demanda**; cada linha leva à página da demanda |
| **Squad** | `#/squad` | "O que cada agente está fazendo?" | cards dos agentes (feed ao vivo; atual Agentes); a gaveta continua disponível de qualquer tela |
| **Auditoria** | `#/auditoria/eventos` | "O que aconteceu, quem decidiu e com base em quê?" | abas locais: **Eventos** (ex-Decisões) · **Gates** (ex-Evidências/pareceres) · **Handoffs** · **Políticas** |
| **Produto** | `#/produto/grafana` | "Como o checkout está se comportando?" | seletor de produto, Grafana/Jaeger, abrir em nova aba, links externos do produto |

Abaixo dos itens, separado: botão **+ Nova demanda** (ação global) e, em grupo "Links do produto", os links externos com "↗".
Abas locais (Auditoria, Produto, filtros de Demandas) são navegação **secundária** dentro da página, com estilo diferente
do menu (segmentos), nunca repetindo itens do menu primário.

Removidos (funcionalidade preservada no novo lugar, §2): abas do topo; itens Execuções, Decisões, Evidências, Políticas,
Agentes e Observabilidade como itens de primeiro nível.

### 4.2 Página da demanda (hub) — `#/demandas/<Dn>`
Ordem vertical (progressive disclosure):
1. **Breadcrumb** "Demandas › Dn · <título>" e sobretítulo `Dn · STATUS` (texto do `demandInfo().status`).
2. **Cabeçalho**: título, tags (tipo, prioridade, rota, "nº na fila", veio do backlog, override), `issue #n ↗`, `PR #n ↗`
   quando houver, selo de modelos; **ações da demanda** conforme estado (Pausar/Retomar, Prioridade, Cancelar; Editar e
   Cancelar no backlog/pré-início — mesmas regras de hoje).
3. **Etapas** (stepper, P1): Registrada → Validação → Na fila → Execução → Gates → Revisão (PR) → Entregue.
   Variante backlog: Backlog → Na fila → …; Cancelada/Pausada/Devolvida marcam a etapa em que pararam. Derivado só de
   `demandInfo()` — nenhum estado novo.
4. **Próxima ação** (caixa destacada, uma só): a primeira que se aplicar, na ordem da §4.3. Sem ação humana pendente:
   texto "Nada depende de você agora — <quem está trabalhando>" com link para a execução.
5. Seções com âncora (índice local clicável, fica visível no topo da página em ≥ 900 px):
   **Execução** (linha do tempo `demandSteps`, agentes envolvidos → gaveta) · **Gates** (cada gate da demanda com
   recomendação, confiança, risco, evidências, decisão humana registrada) · **Validação** (perguntas e respostas) ·
   **Registro** (eventos do log com `demand = id`, recolhível, link "ver na Auditoria").

### 4.3 "Precisa de você" (Painel) e "Próxima ação" (Demanda) — mesma regra
Derivada do estado atual (`/api/state`), sem campo novo. Ordem de urgência:

| Ordem | Condição (já calculável hoje) | Rótulo | Destino |
|---|---|---|---|
| 1 | último gate da demanda com `RETURN`, confiança < 70% ou risco alto, sem evento `human` posterior | "Decidir G<n> — intervenção obrigatória/recomendada" | `#/demandas/Dn/gates` (foco no campo de nota) |
| 2 | `vinfo.st === "perguntas"` | "Responder N pergunta(s) do Arquiteto" | `#/demandas/Dn/validacao` (foco na 1ª resposta) |
| 3 | `inReview` (e `review` de release sem `delivered` posterior) | "Revisar PR #n ↗" + "ver demanda" | link do PR (nova aba) e `#/demandas/Dn` |
| 4 | `preStart` e validação pronta (ou sem `kind`) | "Iniciar" | `#/demandas/Dn` (Próxima ação com prioridade/rota/agente) |
| 5 | `vinfo.st === "atrasada"` | "Validação atrasada — aguardar ou iniciar com override" | `#/demandas/Dn` |
| 6 | gate sem demanda (pipeline base) que exige humano | "Decidir G<n> da squad base" | `#/painel#squad-base` |

O contador do item **Painel** no menu = nº de linhas desta lista (badge vermelho se houver ordem 1 ou 2). Backlog e
"Devolvida pelo revisor" não entram (o próximo passo é da squad ou opcional); aparecem em Em andamento/Demandas.

### 4.4 Demandas (lista)
- Filtros (segmentos, com contagem, na URL `?f=`): **Ativas** (padrão: tudo que não é Entregue/Concluída/Cancelada nem
  Backlog) · **Precisa de você** · **Na fila** (ordenada pela posição) · **Backlog** (ordem do ADR-009) · **Entregues** ·
  **Canceladas** · **Todas**.
- Linha: `Dn`, título, status, tags curtas (tipo, prioridade, issue ↗, PR ↗), e **um** botão com a próxima ação (§4.3)
  quando houver. Clique na linha (link `<a href>`) abre a demanda. A descrição longa e o texto explicativo do ciclo
  saem da lista (ciclo vira o stepper; texto de ajuda fica recolhido em "Como funciona o ciclo da demanda").
- **Nova demanda** (`#/demandas/nova`): o formulário atual inteiro, sem alteração de campos/validações. Ao registrar
  com sucesso, navega para `#/demandas/<Dn nova>` (resposta 201 do `/api/demand` traz o `id`), onde a validação aparece.

## 5. Rotas (hash) e estado na URL

| Rota | Tela | Observações |
|---|---|---|
| `#/painel` (e hash vazio) | Painel | inicial |
| `#/demandas[?f=ativas\|acao\|fila\|backlog\|entregues\|canceladas\|todas]` | Demandas | filtro padrão `ativas` |
| `#/demandas/nova` | Nova demanda | |
| `#/demandas/<ref>[/execucao\|/gates\|/validacao\|/registro]` | Demanda (rolada até a seção) | `<ref>` = código `D13` (canônico) **ou** id do log (`efe387a35d71`); inexistente → mensagem "Demanda não encontrada" + link para Demandas |
| `#/squad` | Squad | |
| `#/auditoria/eventos[?demanda=Dn&agente=<papel>&tipo=<type>]` | Auditoria › Eventos | filtros combináveis; cada linha com demanda tem link para ela |
| `#/auditoria/gates[?demanda=Dn]` · `#/auditoria/handoffs` · `#/auditoria/politicas` | Auditoria | |
| `#/produto/grafana\|jaeger[?produto=<id>]` | Produto | |
| qualquer rota + `?agente=<papel>` | abre a gaveta do agente por cima | fechar remove o parâmetro |

Regras: navegação por `<a href="#/…">` (abre em nova aba com Ctrl/Cmd+clique); `hashchange` redesenha; Voltar/Avançar
funcionam; F5 preserva tela, item, seção, filtros e gaveta. Aliases das telas antigas (redirecionam com `replaceState`):
`#execucoes`/`#/execucoes` → última demanda ativa ou Painel; `#/decisoes` → `#/auditoria/eventos`; `#/evidencias` →
`#/auditoria/gates`; `#/politicas` → `#/auditoria/politicas`; `#/agentes` → `#/squad`; `#/observabilidade` → `#/produto/grafana`.
Rota desconhecida → Painel com aviso discreto "Página não encontrada".

## 6. Fluxos "uma coisa leva a outra"

### 6.1 Links contextuais obrigatórios
| De | Para |
|---|---|
| item de "Precisa de você" / "Em andamento" (Painel) | a demanda, na seção da ação |
| linha da lista de Demandas | a demanda |
| demanda › Execução › agente | gaveta do agente (`?agente=`) |
| gaveta › sessão (`run.demand`) | a demanda daquela sessão ("D13 ›") |
| demanda › Gates › gate | Auditoria › Gates filtrado pela demanda; evidências do gate em linha |
| demanda › cabeçalho | issue ↗, PR ↗, commit (texto) |
| demanda › Registro | Auditoria › Eventos `?demanda=Dn` |
| Auditoria › Eventos/Gates › código da demanda | a demanda |
| Painel › faixa de agentes | gaveta do agente |
| após registrar demanda | a demanda nova |
| após Iniciar / Mover para a fila / Enviar respostas / decidir gate | permanece na demanda; Próxima ação e stepper se atualizam; mensagem no `#sr-live` |

### 6.2 Notificações e toasts → item (substitui `view` de `classify`)
| Evento | Destino |
|---|---|
| `gate` | `#/demandas/Dn/gates` (sem demanda: `#/painel#squad-base`) |
| `handoff` | `#/demandas/Dn/execucao` (sem demanda: `#/painel`) |
| `defect` | `#/auditoria/eventos?demanda=Dn&tipo=defect` (sem demanda: `?tipo=defect`) |
| `start`, `control` | `#/demandas/Dn` |
| `validation` | `#/demandas/Dn/validacao` |
| `review` / `delivered` / `review-rejected` | `#/demandas/Dn` (release sem demanda: `#/auditoria/eventos?tipo=review`) |
O texto do botão do toast passa de "Ver" para "Abrir Dn" (ou "Abrir" sem demanda). Clicar marca como lido (regra atual).

### 6.3 Jornada típica (verificada nas tarefas T1-T6 da §9.3)
Nova demanda → (registrou) página da demanda, etapa Validação → (perguntas) Próxima ação "Responder" → Enviar →
Próxima ação "Iniciar" → Iniciar → etapa Na fila/Execução, linha do tempo ao vivo → (gate devolvido: toast "Abrir D13")
→ seção Gates, decidir → … → Próxima ação "Revisar PR #n ↗" → (merge) etapa Entregue com PR e commit.

## 7. Indicação de local
- Item do menu ativo: fundo branco + barra 3 px `#1F3A5F` + peso 600 (estilo atual) **e** `aria-current="page"`; a
  página da demanda, Nova demanda e filtros marcam **Demandas**; as abas de Auditoria/Produto marcam o item pai.
- Breadcrumb acima do `h1` em páginas de 2º nível ou mais: "Demandas › D13 · Título", "Auditoria › Gates",
  "Produto › Jaeger". Cada nível anterior é link. `nav aria-label="Trilha"`.
- `h1` único por tela; `document.title` = `[(<não lidas>) ]<Tela ou Dn> · Squad Control · <produto>`.
- Seção ativa da demanda destacada no índice local; aba local ativa com `aria-selected`/`aria-current`.
- Ao trocar de rota: rola ao topo (ou à seção), foco no `h1` (`tabindex="-1"`), anúncio "<Tela> aberta" no `#sr-live`.

## 8. Layout

### 8.1 1440 px
```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ [SC] Squad Control │ Checkout Saga · Orquestrador + Auditor                    🔔 3      │ 56
│ Desafio Técnico | Checkout Saga com Squad Agêntica        Julien Crouzillard · Software… │ tira
├────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ Painel       2 │ ┌ #ai-usage (sticky) ─ Claude Code 5 h ▬▬ 41% · Semana … │ Codex … ┐  │
│ Demandas       │ Demandas › D13 · Navegação do Squad Control                             │
│ Squad        1 │ D13 · EM ANDAMENTO                                                      │
│ Auditoria      │ Navegação do Squad Control                [Pausar] Prioridade[normal▾]  │
│ Produto        │ operação · normal · rota padrão · issue #41 ↗      [Cancelar demanda]   │
│                │ Modelos: Arquiteto: claude-opus-… · Anthropic                           │
│ [+ Nova demanda]│ ●Registrada─●Validação─●Na fila─◉Execução─○Gates─○Revisão─○Entregue    │
│                │ ┌ PRÓXIMA AÇÃO ──────────────────────────────────────────────────────┐ │
│ LINKS DO PRODUTO│ │ Auditor devolveu G2 · 62% · risco médio — intervenção obrigatória  │ │
│ Console ↗      │ │ [observação………………]  [Aceitar devolução] [Seguir mesmo assim]       │ │
│ API pedidos ↗  │ └────────────────────────────────────────────────────────────────────┘ │
│                │ Execução · Gates · Validação · Registro          (índice local)        │
│                │ ┌ Execução (linha do tempo) ───────────┐ ┌ Gates ──────────────────┐   │
│                │ │ A  Arquiteto: contrato …   14:02     │ │ G1 APPROVE 86% · …      │   │
│                │ │ G1 Auditor avaliou …       14:10     │ │ G2 RETURN 62% · evid. … │   │
│                │ │ F  Frontend: …             agora     │ └─────────────────────────┘   │
│                │ └──────────────────────────────────────┘                                │
│                │ ▸ Registro (23 eventos) · ver na Auditoria                              │
└────────────────┴─────────────────────────────────────────────────────────────────────────┘
Painel (#/painel): h1 "Painel" · PRECISA DE VOCÊ (lista de ações com botão) · EM ANDAMENTO (Dn, título, etapa, Agora: …)
· faixa de agentes · ENTREGUES RECENTEMENTE · [Squad base (ADR-000) só sem demanda ativa].
```

### 8.2 390 px
```
┌──────────────────────────────────┐
│ [SC] Squad Control        🔔 3   │ 48
│ Painel² Demandas Squad Auditori›│ 44 — menu em uma linha, rolagem horizontal própria
├──────────────────────────────────┤
│ #ai-usage empilhada (Claude/Codex)│
│ Demandas › D13                   │
│ D13 · EM ANDAMENTO               │
│ Navegação do Squad Control       │
│ ●●●◉○○○  Execução (4 de 7)       │
│ ┌ PRÓXIMA AÇÃO ────────────────┐ │
│ │ Decidir G2 — obrigatória     │ │
│ │ [observação]                 │ │
│ │ [Aceitar devolução        ]  │ │
│ │ [Seguir mesmo assim       ]  │ │
│ └──────────────────────────────┘ │
│ [Pausar] [Prioridade ▾]          │
│ [Cancelar demanda]               │
│ ▸ Execução  ▸ Gates  ▸ Registro  │
│ (tira de autoria abaixo do menu, │
│  pode quebrar em 2 linhas)       │
└──────────────────────────────────┘
```
Abaixo de 900 px: o menu lateral vira **uma** barra horizontal logo abaixo do cabeçalho (sem as abas antigas);
se não couber, rola dentro do próprio container (`overflow-x:auto`) com o item ativo trazido à vista; o corpo da página
nunca rola na horizontal. "+ Nova demanda" aparece no topo de Painel e Demandas; os links externos ficam em Produto.
Stepper abaixo de 600 px vira pontos + legenda "Etapa (n de 7)". Alvos de toque ≥ 44 px no menu.

## 9. Critérios de aceite

### 9.1 Estrutura e comportamento
- **CA-1** Existe **um único** menu primário (`nav[aria-label="Principal"]`) com exatamente 5 itens: Painel, Demandas,
  Squad, Auditoria, Produto. Não existe `.tabs` no cabeçalho nem qualquer outro conjunto que repita esses itens.
- **CA-2** Abrir `/` (hash vazio) mostra o Painel com a seção "Precisa de você" (ou o estado vazio "Nada depende de você
  agora" + botão Nova demanda).
- **CA-3** Toda rota da §5 abre a tela/item/seção correspondente; F5 preserva a tela, a demanda, a seção, os filtros e a
  gaveta; Voltar retorna à tela anterior; os aliases antigos redirecionam; rota inexistente → Painel com aviso.
- **CA-4** Em toda tela exatamente um item do menu tem `aria-current="page"` e o estilo ativo, e ele corresponde à tela
  (inclusive ao chegar por notificação, toast, breadcrumb, link contextual ou alias). Não há nenhuma outra indicação de
  local contraditória.
- **CA-5** Páginas de 2º nível têm breadcrumb com links; `document.title` segue a §7; ao trocar de rota o foco vai ao
  `h1` e há anúncio no `#sr-live`.
- **CA-6** A página de **qualquer** demanda (ativa, na fila, backlog, entregue, cancelada), não só a última ativa,
  mostra stepper, Próxima ação, Execução, Gates, Validação e Registro coerentes com `demandInfo()`.
- **CA-7** "Precisa de você" e "Próxima ação" seguem a §4.3 (ordem e condições); o badge do item Painel é igual ao
  número de linhas e fica vermelho com ordem 1 ou 2.
- **CA-8** Cada evento notificável leva ao destino da §6.2 (sino e toast), com o botão "Abrir Dn".
- **CA-9** A decisão humana num gate envia a `/api/human` o **gate e a demanda exibidos** (corrige X11); gate de outra
  demanda nunca é afetado.
- **CA-10** Registrar demanda leva à página da nova demanda; Iniciar, Mover para a fila, Enviar respostas, controles e
  decisão de gate mantêm o usuário na demanda com mensagem de resultado e foco no próximo controle lógico.
- **CA-11** Polling (3 s) não troca de rota, não rola a página, não fecha `details`/gaveta abertos, não perde valores
  `data-keep` nem o foco (regras atuais de `render()`/`editing()` mantidas); a faixa `#ai-usage` continua atualizando
  mesmo com formulário em edição e aparece em todas as rotas exceto `#/produto/*`.
- **CA-12** Nenhuma API muda: o painel usa só `GET /api/state|/api/project|/api/policy` e `POST /api/demand`,
  `/api/demand/start|clarify|control|edit`, `/api/human`, com os mesmos corpos de hoje.
- **CA-13** Sem dependência nova (sem framework, sem biblioteca de rotas; JS puro com `hashchange`); IBM Plex Sans/Mono,
  paleta atual (`--accent #1F3A5F` etc.), avatares/emoji D3 e selos D9 preservados.
- **CA-14** Em 390 px: sem rolagem horizontal do corpo; menu em uma barra única; todas as tarefas da §9.3 executáveis.
  Em 1440 px: menu lateral de 208 px; conteúdo até 1440 px.
- **CA-15** Links externos (issue, PR, Console, API, Grafana/Jaeger em nova aba) têm "↗" visível e "(abre em nova aba)"
  para leitor de tela; links internos são `<a href="#/…">` (funcionam com Ctrl/Cmd+clique).
- **CA-16** Existe "Pular para o conteúdo" como primeiro elemento focável; navegação completa por teclado (Tab/Enter,
  Esc fecha gaveta e sino).

### 9.2 Checklist de paridade (nenhuma funcionalidade perdida) — máx. **3 cliques** a partir do Painel
O QA marca cada linha com o caminho usado e o nº de cliques (abrir sino/toast conta 1). Itens com ação pendente devem
ser alcançáveis em **≤ 2** cliques a partir do Painel (1 para chegar ao item + 1 para agir).

| # | Funcionalidade (inventário §2) | Máx. cliques |
|---|---|---|
| PA-1 | Registrar demanda (todos os campos, validações e mensagens) — I11 | 2 |
| PA-2 | Responder perguntas da validação — I14 | 2 |
| PA-3 | Iniciar com prioridade/rota/agente; iniciar com override + nota obrigatória — I15 | 2 / 3 |
| PA-4 | Backlog: ver ordenado, editar (título, descrição, tipo, prioridade), Mover para a fila — I13 | 3 |
| PA-5 | Cancelar antes do início com motivo e confirmação — I16 | 3 |
| PA-6 | Ver a fila com posição — I12 | 2 |
| PA-7 | Pausar, Retomar, Repriorizar, Cancelar em andamento (confirmação) — I8 | 2 |
| PA-8 | Ver linha do tempo e "Agora" de uma demanda ativa — I3 | 1 |
| PA-9 | Decidir gate (Enviar/Devolver; Aceitar devolução/Seguir mesmo assim; nota) — I6, I7 | 2 |
| PA-10 | Ver evidências de um gate e o parecer completo — I7, I20 | 2 |
| PA-11 | Pipeline base F1→G3 e sua intervenção (sem demanda ativa) — I4 | 0-1 |
| PA-12 | Ver PR aguardando revisão e abrir no GitHub; ver entregue com commit; ver devolvida pelo revisor — I10 | 2 |
| PA-13 | Abrir issue da demanda — I18 | 2 |
| PA-14 | Ver selos de modelo (demanda, evento, execução) — I9 | 2 |
| PA-15 | Log completo com modelo por evento (ex-Decisões) — I19 | 1 |
| PA-16 | Handoffs — I21 | 2 |
| PA-17 | Políticas (gates.md, constituição) — I22 | 2 |
| PA-18 | Feed ao vivo de todos os agentes; gaveta de um agente (Esc fecha) — I5, I23 | 1 |
| PA-19 | Observabilidade: trocar produto, Grafana/Jaeger, abrir em nova aba — I24 | 2 |
| PA-20 | Console de Checkout e API de pedidos — I25 | 1-2 |
| PA-21 | Sino (não lidas, badge de ação), toasts, notificação do SO — I26, I27 | 1 |
| PA-22 | Faixa de consumo da IA — I29 | 0 |
| PA-23 | Contagem de agentes trabalhando e total de eventos do log — I28 | 0 / 1 |

### 9.3 Tarefas de usabilidade (QA executa em 1440 e 390 px; registra cliques, caminho e desvios)
Critério de sucesso por tarefa: concluída sem voltar a uma tela errada (nenhum "desvio"), dentro do limite de cliques.

| # | Tarefa | Limite |
|---|---|---|
| T1 | Registrar uma demanda "operação" e, sem usar o menu, chegar às perguntas do Arquiteto e respondê-las. | 3 após registrar |
| T2 | Com um toast/sino "Auditor devolveu G2" de uma demanda que **não** é a última ativa, abrir e decidir o gate certo (verificar no log que `gate` e `demand` do evento `human` batem). | 3 |
| T3 | Partindo do Painel, descobrir qual PR entregou uma demanda já entregue e quais gates a aprovaram. | 3 |
| T4 | Ver o que o Backend está fazendo na demanda ativa, depois abrir a demanda da sessão dele pela gaveta. | 3 |
| T5 | Copiar a URL da seção Gates de uma demanda, abrir em outra aba e recarregar: mesma tela, mesma seção. | 0 (colar URL) |
| T6 | Mover um item do backlog para a fila e confirmar sua posição na fila. | 4 |
| T7 | Abrir os traces do produto no Jaeger e voltar com o botão Voltar do navegador para a tela anterior. | 3 |
| T8 | Encontrar a regra dos gates (Políticas). | 2 |
| T9 | Com o formulário Nova demanda preenchido pela metade, esperar 3 ciclos de polling: nada se perde e o foco permanece. | — |
| T10 | Navegar T2 somente por teclado; confirmar foco no `h1` após cada troca de rota e anúncio no leitor de tela. | — |

Evidências esperadas do QA: `tests/ui/checklist-navegacao-d13.md` (paridade + tarefas) e screenshots em 1440/390 do
Painel, Demandas, página da demanda (ativa, backlog, entregue), Auditoria e Produto. Scripts antigos que clicam em
`nav a[data-view=…]`/`.tabs` precisam ser atualizados (dono: QA); os aliases de hash da §5 facilitam a migração.

## 10. Restrições
- Somente `squad-control/index.html` (dono Frontend). Sem dependências novas; sem build; sem CDN nova.
- Visual corporativo atual: IBM Plex Sans/Mono, `#1F3A5F`, bordas 1 px, raio 2 px, sem sombras novas além das existentes.
- Não alterar APIs, formato do log, regras de estado (`demandInfo`, `validationInfo`, `effectiveDemand`) nem a faixa
  `#ai-usage` (markup, container queries, `renderUsage` fora do caminho de `editing()`).
- Não perder foco/valores durante o polling (mecanismo `data-keep`/`focusKey` preservado e estendido às novas telas).
- Notificações continuam com `localStorage` (`sc.notif.*`); rota não é gravada em `localStorage` (a URL é a fonte).
- Fora de escopo: Console de Checkout; qualquer mudança em `tools/squad/**` (se o Frontend precisar de dado novo, abre
  solicitação ao **Orquestrador**; este contrato não exige nenhuma).
