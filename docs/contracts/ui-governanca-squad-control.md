# Contrato — Governança ao vivo, bloqueios/avisos e tema do Squad Control (D14, `1e3d3c894630`, tipo operação)

> Decisão: [ADR-017](../adr/017-alertas-e-estado-dos-agentes-no-servidor.md).
> Implementação: **Orquestrador** (`tools/squad/server.py`, `tools/squad/log.py`) e **Frontend** (`squad-control/index.html`).
> Parte de: D13 ([ADR-016](../adr/016-navegacao-unica-por-tarefa.md), rotas e menu mantidos) e D11
> ([ADR-014](../adr/014-consumo-da-ia-por-fonte-real.md), faixa `#ai-usage` mantida).
> Respostas do humano (`docs/squad/inbox/done/1e3d3c894630.json`):
> 1. Critérios: **C1** impedimentos, bloqueios e avisos visíveis na primeira tela, sem clicar; **C2** estado de cada
>    agente e de cada demanda atualiza sozinho em **até 3 s**; **C3** heurísticas de usabilidade (Nielsen) conferidas tela a tela.
> 2. **Bloqueio** = gate REJECT (RETURN), intervenção humana obrigatória, 3º ciclo de autocorreção, triagem com perguntas
>    em aberto. **Aviso** = gate com confiança < 70%, agente sem progresso há X minutos, PR aguardando merge.
> 3. Escopo: usabilidade **e** tema visual juntos; pode haver eventos/dados novos em `tools/squad/**`.
> 4. Inaceitável: falta de visibilidade em tempo real e detalhamento raso de cada integrante. Ao olhar um integrante:
>    **o que realmente está fazendo** e **se há espera de ação** (dele, de subagentes ou do humano); o que o humano tem de
>    fazer fica **explícito**.
>
> Restrições mantidas: HTML estático sem build e sem dependências além de fontes; `decisions.jsonl` só ganha campos
> opcionais; `log.py`/`gitflow.py` sem quebra; ações humanas atuais, rotas/menu da D13 e `#ai-usage` preservados;
> tema **próprio e sóbrio**, sem identidade visual do Itaú (sem logo, sem laranja/azul institucionais, sem nome da marca).

## 1. Inventário (medido em 2026-09-24 sobre a develop com D11 + D13)

| Tema | O que existe | O que falta para D14 |
|---|---|---|
| Atualização | `setInterval(refresh, 3000)` (`index.html` l.1547) baixa `/api/state` inteiro: **1,28 MB**, montagem **0,3–0,75 s** (66 runs) | pior caso atual ≈ 3 s + 0,75 s + render > 3 s (C2 falha); sem indicador "atualizado há"; `#srv-down` só aparece após erro |
| Agentes | `runs[]` por transcrição: `status` (trabalhando/coordenando/concluído/parado/interrompido), `current` (ferramenta pendente), `files`, `activity` (80), `model`, `demand`, `toolCount` | nada consolidado **por agente**; sem passo; sem comandos recentes separados; Orquestrador lido com `delegations_only` (só chamadas `Agent`); sem "espera de" |
| Espera de ação | `nextAction()`/`needsYou()` no cliente (l.543–565) para gates e triagem | espera de **subagente** (Agent pendente), de **Auditor** (handoff sem gate), de **pergunta ao humano** no chat (AskUserQuestion pendente) não aparecem |
| Bloqueios/avisos | `gateNeedsHuman` (l.451): `human_required`, confiança < 70% ou risco alto; `classify` (l.1262) com **outra** regra (RETURN = "ação") | sem **3º ciclo** (o texto cita, o código não calcula — `cycle` só existe nos arquivos `docs/squad/gates/*.json`); sem **agente sem progresso**; PR aguardando está em "Precisa de você" mas não é aviso; sem histórico para auditoria |
| Tempo de ferramenta | — | medido nas 1.607 execuções de ferramenta das transcrições: p50 2 s, p95 16 s, **p99 180 s, p99,9 501 s**, máx. 862 s (build) |
| Tema | só claro; tokens parciais (`--dim #7A7B80` = **4,22:1** em branco, 3,9:1 em `--panel2`, abaixo de AA para 11–12 px); todos os agentes com a mesma cor; estado do agente = ponto de 7 px **só por cor**, piscando sem `prefers-reduced-motion` | modo escuro, tokens completos, estados com ícone + texto |

## 2. Problemas atuais por heurística (Nielsen) — evidência no código atual

| H | Heurística | Problema (onde) | Correção neste contrato |
|---|---|---|---|
| H1 | Visibilidade do status | Nenhum "ao vivo / atualizado há N s"; atraso só vira erro. Estado do agente é um ponto de 7 px (l.108). Agente parado há 14 min continua "trabalhando" (`parse_run`: "parado" só após 900 s). Orquestrador mostra só delegações. 3º ciclo não é calculado. | §5 regras, §6 barra global e indicador, §7 painel do integrante, §8 ≤ 3 s |
| H2 | Linguagem do usuário | Rótulos técnicos crus: "coordenando", "ocioso", `handoff`, "Bash · …", "Pensando / escrevendo a próxima ação"; "Novidade/Ação necessária" não correspondem a "bloqueio/aviso" do humano. | vocabulário único (§4) e rótulos de ferramenta traduzidos (§7.4) |
| H3 | Controle e liberdade | Toasts de ação não expiram e o 4º remove o mais antigo sem aviso (l.1281); não há como marcar aviso como visto. | §6.4 "Visto" por aviso (local), toasts só para bloqueio novo |
| H4 | Consistência | Duas regras para "precisa de humano" (`gateNeedsHuman` × `classify`); "concluído" usa a cor de link; `.pill`, `.tag`, `.s`, `.dot` são quatro linguagens de estado. | uma regra no servidor (§5), um componente de estado (§10.5) |
| H5 | Prevenção de erros | Botões de decisão de gate funcionam com dados defasados sem aviso; "Seguir mesmo assim" com estilo inline. | decisão desabilitada com dado > 15 s (§8.3); variante `danger-outline` (§10.5) |
| H6 | Reconhecer em vez de lembrar | Faixa de agentes mostra só `lastAction` (sem demanda, passo, idade); para saber por que um agente parou é preciso ler o feed. | cartão com tarefa/demanda/passo/idade/espera (§7.1) |
| H7 | Flexibilidade e eficiência | Squad = 8 cartões de 560 px com rolagem aninhada; sem filtro "só comigo". | grade compacta + gaveta; filtro `?alerta=` (§6.3) |
| H8 | Estética minimalista | Feed com até 80 itens de 600 caracteres; tudo com o mesmo peso (borda preta de 1 px); tira de autoria ocupa uma linha inteira. | hierarquia §6; autoria vai para o rodapé do menu lateral |
| H9 | Diagnóstico e recuperação | Erro de ferramenta = "· erro" vermelho; execução interrompida sem orientação. | §7.3 estado "interrompido" com próxima ação; erro com comando e saída resumida |
| H10 | Ajuda | Sem legenda de estados/severidades; nenhuma explicação de **por que** algo é bloqueio. | cada item traz `rule` + "Por quê?" (§5.3); legenda em `#/auditoria/politicas` |
| A11y | WCAG 2.2 AA | `--dim` < 4,5:1; estado só por cor (1.4.1); animação sem redução (2.3.3); sem tema escuro. | tokens §10 com contrastes medidos |

## 3. Princípios adotados
Visibilidade do status (H1) como requisito de primeira classe; **gestão por exceção** (o que foge do normal sobe, o
normal fica quieto — padrão de centros de operação/NOC); **uma regra, um lugar** (servidor calcula, a UI exibe —
auditável e igual para todo consumidor); severidade nunca só por cor (WCAG 1.4.1: ícone + palavra + cor); "quem age
agora" sempre explícito (RACI mínimo: `owner`); rastreabilidade: todo item cita a regra e o evento de origem.

## 4. Vocabulário (usado igual na UI, na API e na auditoria)

| Termo | Significado | Ícone (forma) | Cor (token) |
|---|---|---|---|
| **Bloqueio** | a demanda **não anda** sem uma ação (de alguém nomeado) | octógono ⬣ com "×" | `--danger` |
| **Aviso** | anda, mas há risco ou atraso que merece atenção | triângulo ▲ com "!" | `--warn` |
| **Sua ação** | item cujo `owner` é `humano` (bloqueio ou aviso) + ações não-alerta atuais (Iniciar, validação atrasada) | etiqueta "Você" | `--accent` |
| **Espera de ação** | um integrante não prossegue até outro agir (`waiting.on`) | relógio ◷ | `--warn` se > limite, senão `--muted` |

## 5. Bloqueios e avisos — regras exatas (calculadas no servidor)

### 5.1 Definições auxiliares
- `code(demand)`: `D{n}` pela ordem dos eventos `task` com `agent == "humano"` (mesma regra de `demandCode` do cliente).
- Demanda **encerrada**: tem `control/cancel`, `delivered`, ou gate G3 APPROVE sem PR (regra `is_done`). Itens de
  demanda encerrada **fecham** (vão para o histórico). **Exceção (errata G2-D14)**: se a demanda está encerrada só por
  G3 APPROVE sem PR e esse G3 tem `needsHuman(g)` (confiança < 70%, risco alto ou `human_required`) sem `decided(g)`,
  o B2 desse G3 **continua aberto** (AGENTS.md: intervenção humana obrigatória). `control/cancel` e `delivered` fecham tudo.
- Gates de uma chave `k = (demand|null, gate)`: eventos `type == "gate"` do log em ordem de `ts`, complementados pelo
  arquivo `docs/squad/gates/<gate>-<Dn>.json` (campos `cycle`, `human_required`) quando o arquivo é o mais recente (mesma
  heurística de `latestGateFor`, ±5 s).
- `cycle(g)` = posição (1-based) de `g` entre os gates da chave; se o arquivo trouxer `cycle`, vale o maior dos dois.
- `returns(k)` = número de gates RETURN da chave **após** a última decisão humana `human` da mesma chave (ou desde o início).
- `needsHuman(g)` = `human_required` **ou** `confidence < 0.70` **ou** `risk == "alto"` **ou** `returns(k) >= 3`
  (AGENTS.md, Limites de autonomia; `docs/squad/orquestrador.md` §Autocorreção: máx. 2 ciclos de autocorreção; o 3º RETURN escala).
- `decided(g)` = existe evento `human` com mesmo `gate`/`demand` e `ts > g.ts`.
- Última atividade de uma run = `max(ts)` de `activity[]` (inclui `progress` do log e o mtime da saída/transcrição).

### 5.2 Regras

| Id | Severidade | Tipo (`kind`) | Abre quando | Fecha quando | `owner` (quem age) | Ação (rótulo → destino) |
|---|---|---|---|---|---|---|
| **B1** | bloqueio | `gate-return` | último gate da chave é `RETURN` | novo gate na chave; `human/OVERRIDE` posterior; demanda encerrada | agente de origem do trabalho devolvido (`gate.to`, senão `from` do arquivo, senão o autor do último `handoff` para o Auditor); vira `humano` se B2/B3 também valem | "Ver parecer de Gx" → `#/demandas/Dn/gates` |
| **B2** | bloqueio | `human-required` | último gate da chave com `needsHuman(g)` (exceto `returns>=3`, que é B3) e **não** `decided(g)` | `decided(g)`; novo gate; demanda encerrada (exceto G3 APPROVE que encerrou a demanda — ver §5.1) | `humano` | "Decidir Gx" → `#/demandas/Dn/gates` (squad base: `#/painel/squad-base`) |
| **B3** | bloqueio | `cycle-limit` | `returns(k) >= 3` e não `decided` | decisão humana na chave; demanda encerrada | `humano` | "Decidir Gx — 3º ciclo" → `#/demandas/Dn/gates` |
| **B4** | bloqueio | `triage-open` | último `validation` da demanda com `status == "perguntas"` sem `clarification` cujo `validation` = seu id | `clarification`; `start` com `override`; `control/cancel` | `humano` | "Responder n perguntas" → `#/demandas/Dn/validacao` |
| **A1** | aviso | `low-confidence` | gate com `confidence < 0.70` **já decidido** pelo humano (APPROVE/OVERRIDE) — risco aceito | novo gate da chave com `confidence >= 0.70`; demanda encerrada | `squad` (informativo) | "Ver parecer" → `#/demandas/Dn/gates` |
| **A2** | aviso | `agent-stalled` | run **não encerrada** (turno aberto ou ferramenta pendente, ou run externa `trabalhando`) com `600 s <= now − última atividade < STALLED_MAX_S` (3600 s; acima disso a run é considerada abandonada/sessão morta e **não** gera A2); **ou** run externa `interrompido` (pid morto sem "Finalizado") da última hora | nova atividade; run encerrada | `humano` (verificar terminal/permissão) se a run é do Claude Code interativo; `orquestrador` (retomar) se é `run_agent.py` | "Ver integrante" → `?agente=<papel>` |
| **A3** | aviso | `pr-waiting` | evento `review` sem `delivered`/`review-rejected` posterior do mesmo `pr` | `delivered` ou `review-rejected` | `humano` | "Revisar PR #n" → `url` (externo) + "Ver Dn" |

**Conciliação B2 × A1** (o humano pôs "confiança < 70%" em aviso; AGENTS.md torna a intervenção **obrigatória** nesse
caso — hierarquia de verdade nº 2 prevalece): enquanto não houver decisão humana, o gate é **bloqueio B2**; depois da
decisão, vira **aviso A1** até um gate da mesma chave com ≥ 70% ou o encerramento. A categoria do humano é preservada
como trilha de risco aceito.

**Deduplicação**: um item por evento de origem; se várias regras valem para o mesmo gate, `kinds[]` lista todas,
`severity` = a mais alta, `owner` = `humano` se alguma regra diz `humano`. `id` estável = `<kind principal>:<id do evento
de origem>` (A2: `agent-stalled:<runId>`).

**Ordenação**: bloqueios antes de avisos; dentro de cada grupo, `owner == humano` primeiro, depois `openedAt` mais antigo.

### 5.3 Por que X = 10 min (A2)
Medição nas 1.607 execuções de ferramenta registradas nas transcrições desta squad: p99 = 180 s, p99,9 = 501 s, máximo
= 862 s (um build). Um agente com turno aberto e **nenhuma** atividade por 600 s está além do p99,9 da duração normal de
uma ferramenta (≈ 1 falso positivo a cada 1.600 ferramentas) e ainda bem antes do limite antigo de "parado" (900 s).
Abaixo de 5 min (usado pelo `pending.py` para "Arquiteto ocupado") os builds do Maven/Docker gerariam avisos falsos com
frequência (p99 = 3 min). Ferramenta pendente ≥ 180 s (p99) não é aviso: aparece no cartão como "comando longo".
O limite fica em `thresholds.stalledSeconds` na API (ajustável por `SQUAD_STALLED_S`), exibido na legenda.
Teto (errata G2-D14): `STALLED_MAX_S = 3600` s. Run aberta sem atividade há mais de 1 h é tratada como sessão morta:
sai do A2 e não conta como `trabalhando`/`sem-progresso`. O valor deve constar em `thresholds.stalledMaxSeconds` do
`/api/live` e do `/api/state` (§9.1).

### 5.4 Histórico (auditoria)
Para B1–B4, A1 e A3 o servidor também devolve os itens **fechados** (reconstruídos do log: `openedAt`, `closedAt`,
`closedBy` = agente/humano do evento que fechou, `closedByEvent`). A2 é só ao vivo (depende de mtime). Nada é gravado
no log: tudo é derivável e reprodutível a partir de `decisions.jsonl` + `docs/squad/gates/`.

## 6. Hierarquia visual e primeira tela

### 6.1 Barra global (todas as telas, dentro do `<header>`, sticky)
Ordem: marca · **indicador ao vivo** · **contadores** · tema · sino.
- Indicador ao vivo: "● Ao vivo · atualizado há 1 s" (≤ 5 s) · "▲ Atrasado · há 9 s" (> 5 s, `--warn`) ·
  "✕ Sem conexão desde 14:02:10" (> 15 s ou erro, `--danger`, com o texto atual de `#srv-down`). `role="status"`;
  o texto "há N s" **não** é anunciado a cada segundo (só a mudança de faixa).
- Contadores: `⬣ 2 bloqueios` · `▲ 3 avisos` · `Você: 3` — cada um é link para `#/painel/alertas` (com
  `?alerta=bloqueio|aviso|voce`). Zero é mostrado em `--muted` ("0 bloqueios"), nunca escondido (constância de posição).
  Em 390 px viram `⬣2 ▲3 Você 3` com `aria-label` completo.
- Tema: botão "Tema: Sistema" (cicla Sistema → Claro → Escuro), `aria-label` com o estado.
- A tira "Desafio Técnico… · Julien…" sai do topo e vai para o rodapé do menu lateral (em < 900 px, para o fim da página).
- `#ai-usage` (D11) continua sticky no topo de `<main>`, logo abaixo do cabeçalho, inalterada.

### 6.2 Painel (`#/painel`) — ordem, de cima para baixo
1. **Sua próxima ação** (caixa de destaque, só se houver `owner == humano`): o 1º item "Você" pela ordem §5.2, com
   título, demanda, "há N min", a regra em uma linha e o botão primário. Nenhuma outra caixa usa esse estilo.
2. **Central de bloqueios e avisos** (`id="alertas"`, h2 "Bloqueios e avisos"): duas listas, **Bloqueios** e **Avisos**,
   até 5 itens cada + "Ver todos (n)". Linha do item: ícone+palavra de severidade · `Dn` + título da demanda (ou
   "Squad base"/"Release") · tipo em linguagem natural ("Auditor devolveu G2 · 62%") · **Quem age**: "Você" | papel ·
   **Desde**: "há 12 min" (+ hora no `title`) · botão da ação · "Por quê?" (`<details>` com `rule` e link do evento na
   Auditoria). Vazia: "✓ Nenhum bloqueio" / "✓ Nenhum aviso" em `--ok`.
   Abaixo, "Outras ações suas" (não-alerta: Iniciar, validação atrasada) com a regra de `nextAction()` atual (D13 §4.3).
   **Esta seção substitui "Precisa de você"**; o contador `#c-painel` do menu passa a ser `summary.voce`.
3. **Squad ao vivo**: grade de 8 cartões do integrante (§7.1), 4 × 2 em 1440, 1 coluna em 390.
4. **Em andamento** (D13), cada linha com estágio, "Agora: …" e os chips de bloqueio/aviso da demanda.
5. **Entregues recentemente** e **Squad base** (D13, inalterados).

### 6.3 Outras telas
- `#/painel/alertas[?alerta=bloqueio|aviso|voce]`: rola até a central e aplica o filtro (nova sub-rota, compatível D13).
- **Demanda** (`#/demandas/Dn`): abaixo do stepper, faixa com os bloqueios/avisos **daquela** demanda (mesmo componente);
  "Próxima ação" continua (D13) e, se houver bloqueio com `owner` ≠ humano, diz "Aguardando <papel>: <ação> · há N min".
  Seção Execução ganha, para cada integrante ativo na demanda, o cartão compacto (§7.1).
- **Demandas** (lista): coluna/chip de severidade por demanda; filtro `?f=acao` passa a usar `owner == humano`.
- **Squad** (`#/squad`): grade de cartões (§7.1) + tabela "Esperas" (quem espera quem, desde quando). A gaveta
  (`?agente=`) é o **painel do integrante** (§7.2). Some a rolagem aninhada de 560 px.
- **Auditoria**: nova aba **Alertas** (`#/auditoria/alertas[?demanda=Dn&tipo=<kind>&estado=aberto|fechado]`) com o
  histórico §5.4 (aberto em, fechado em, por quem, regra, evento de origem). Aba Políticas ganha a legenda de
  severidades, estados e limites (`thresholds`).

### 6.4 Notificações
- Toast **só** para bloqueio novo (id que não estava na resposta anterior) e para aviso novo com `owner == humano`;
  demais novidades só no sino. Toast de bloqueio fica até ser fechado; máximo 3, o excedente vira "+n no sino".
- `aria-live="assertive"` só para bloqueio novo com `owner == humano`; o resto `polite`.
- Sino: níveis `bloqueio | aviso | novidade` (substituem "Ação necessária | Novidade"), vindos de `alerts[]`.
- "Visto" em aviso: guarda o id em `localStorage` (`sc-seen-alerts`) e esmaece o item; bloqueio não pode ser dispensado.

## 7. O integrante da squad

### 7.1 Cartão compacto (Painel, Squad, Execução da demanda) — altura fixa, 5 linhas
```
┌──────────────────────────────────────────┐
│ 🧩 Backend         ● TRABALHANDO  há 4 s │  nome · estado (ícone+texto) · idade da última atividade
│ D14 · F2 implementação                   │  demanda + passo  (ou "Sem tarefa")
│ ▶ Executando testes (Bash) · 1 min 12 s  │  ferramenta atual em linguagem natural + duração
│ ◷ Aguarda: Você — decidir G2 · há 12 min │  espera (só se houver; cor por limite)
│ claude-opus-5-5 · Anthropic · 38 ações   │  modelo (D9) · contagem
└──────────────────────────────────────────┘
```
Clique/Enter abre `?agente=<papel>`. Cartão com bloqueio `owner == humano` ligado a ele ganha borda esquerda `--danger`.

### 7.2 Painel do integrante (gaveta `?agente=`, 640 px; tela cheia < 600 px)
Seções, nesta ordem (todas ao vivo, sem perder rolagem nem `details` abertos no polling):
1. **Cabeçalho**: emoji, nome, papel, estado, modelo + fornecedor + runner, "sessão iniciada 13:58 · 38 ações".
2. **Agora**: tarefa (`description` da run), demanda (`Dn` + título, link), **passo** (§9.4), ferramenta atual com rótulo
   natural, alvo (arquivo/comando resumido) e duração; se nada pendente: "Última atividade há 40 s: <resumo>".
3. **Espera de ação** (caixa destacada quando há): "Aguarda **<quem>**: <o quê> · desde 14:10 (há 12 min)" + botão da
   ação quando `on == humano` (mesmo destino da central). Para o Orquestrador, lista **cada** subagente em espera
   ("Aguardando Backend — 'Implementar D14' · há 4 min" → link para o cartão do Backend).
4. **O que o humano precisa fazer** (sempre presente): "Nada agora" ou a lista de itens `owner == humano` ligados a este
   integrante (mesma demanda ou origem), com botão.
5. **Arquivos recentes** (até 10, escritos/editados; link "ver no registro") e **Comandos recentes** (até 5: descrição
   + comando truncado em 200 caracteres, mascarado §9.5, resultado ok/erro).
6. **Linha do tempo** da run atual (padrão: só ferramentas e `progress`; alternância "Mostrar mensagens do agente").
   Erros com o comando e as 3 primeiras linhas do erro.
7. **Execuções anteriores** (colapsadas: descrição, demanda, início/fim, resultado, modelo).

### 7.3 Estados do integrante (`agents[].state`) — um só por vez, precedência de cima para baixo

| Estado | Rótulo na UI | Regra | Ícone | Cor |
|---|---|---|---|---|
| `interrompido` | Interrompido | run externa com pid morto sem "Finalizado" (última hora) — também abre A2 | ■ | `--danger` |
| `sem-progresso` | Sem progresso | A2 aberto para a run atual (não interrompida) | ▲ | `--warn` |
| `trabalhando` | Trabalhando | run não encerrada com atividade < 600 s | ● (pulso; sem animação com `prefers-reduced-motion`) | `--ok` |
| `aguardando` | Aguardando | run encerrada/sem run e `waiting` presente | ◷ | `--warn` |
| `concluido` | Concluiu | última run encerrada há < 15 min, sem `waiting` | ✓ | `--accent` |
| `ocioso` | Livre | nenhuma run ou última encerrada há ≥ 15 min | ○ | `--muted` |

O Orquestrador com `Agent` pendente fica `trabalhando` (coordenando) **e** com `waiting.on` = subagentes.

### 7.4 Espera de ação (`agents[].waiting`) — regras

| Integrante | Condição | `waiting.on` | Texto |
|---|---|---|---|
| Orquestrador | `tool_use` `Agent` sem `tool_result` na sessão principal | papéis dos subagentes (`resolve_agent` da descrição) | "Aguardando <papel>: <descrição>" |
| Orquestrador | `AskUserQuestion` ou `ExitPlanMode` pendente | `humano` | "Pergunta aberta para você no terminal" |
| Orquestrador | há item `owner == humano` aberto | `humano` | o rótulo do item mais urgente |
| Qualquer agente X | último `handoff` de X na demanda com `to == auditor` (ou `to` ausente e gate esperado) sem gate posterior | `auditor` | "Aguardando parecer do Auditor (Gx)" |
| Qualquer agente X | X é `owner` de B1 e não tem run ativa | `orquestrador` | "Aguardando reenvio da correção de Gx" |
| Auditor | há `handoff` para ele sem gate e ele não tem run ativa | `orquestrador` | "Aguardando delegação da avaliação de Gx" |
| Qualquer agente X | há B2/B3/B4 aberto na demanda da run de X | `humano` | rótulo do bloqueio |

`waiting.since` = `ts` do evento/ferramenta que abriu a espera. Espera > `thresholds.waitWarnSeconds` (600 s) fica em `--warn`.
Rótulos naturais de ferramenta: Bash → "Executando: <description>"; Read → "Lendo <arquivo>"; Edit/Write → "Editando
<arquivo>"; Grep/Glob → "Procurando <padrão>"; Agent → "Delegando a <papel>"; progress → "Marco: <título>".

## 8. Tempo real ≤ 3 s (C2)

### 8.1 Orçamento (do fato no disco até a tela)
`poll 1,5 s` + `/api/live` ≤ 300 ms (p95) + render ≤ 200 ms ⇒ pior caso ≈ **2,0 s** (margem de 1 s para C2).

### 8.2 Mecânica
- Cliente consulta **`GET /api/live`** a cada **1,5 s** (leve, §9.1). `GET /api/state` (pesado) só quando
  `live.version` muda ou a cada 15 s, e sempre ao abrir uma página de demanda/auditoria.
- Sem requisições sobrepostas (a próxima só após a anterior terminar); em aba oculta (`document.hidden`) o intervalo
  vai a 10 s e volta a 1,5 s com refresh imediato ao voltar.
- Render incremental: só redesenha regiões cujo hash de dados mudou (barra global, central, cartões, gaveta); foco,
  rolagem, `details` abertos e campos `data-keep` preservados (regra D13).
- Idades ("há N s") recalculadas localmente a cada 1 s a partir de `now` do servidor + deslocamento do relógio.

### 8.3 Dados defasados
Indicador §6.1. Com a última resposta boa > 15 s: botões de decisão de gate, responder, iniciar e cancelar ficam
`disabled` com o motivo "Sem dados atuais — reconectando" (H5). Ao reconectar, reabilitam sem recarregar a página.

## 9. Mudanças de API e servidor (dono: Orquestrador) — só acréscimos

### 9.1 Novo `GET /api/live` (≤ 64 KB, `Cache-Control: no-store`)
```json
{
  "now": "2026-09-24T14:30:02+00:00",
  "version": "b3f1…",                         // hash de (tamanho+mtime do log, mtimes de docs/squad/gates, handoffs, inbox, .squad/runs/*.json)
  "serverMs": 41,
  "thresholds": { "stalledSeconds": 600, "stalledMaxSeconds": 3600, "longToolSeconds": 180, "waitWarnSeconds": 600, "lowConfidence": 0.7, "maxAutoCycles": 2 },
  "summary": { "bloqueios": 2, "avisos": 3, "voce": 3, "trabalhando": 2, "aguardando": 1, "semProgresso": 0 },
  "alerts": [ Alert ],                         // só abertos, já ordenados (§5.2)
  "agents": [ Agent ]                          // sempre os 8 papéis, na ordem de AGENTS do cliente
}
```
`Alert`:
```json
{ "id": "human-required:1c948fb92532", "severity": "bloqueio", "kind": "human-required", "kinds": ["gate-return","human-required"],
  "rule": "B2 — confiança 62% < 70% sem decisão humana (AGENTS.md, Limites de autonomia)",
  "demand": "1e3d3c894630", "code": "D14", "gate": "G2", "cycle": 2, "returns": 1, "confidence": 0.62, "risk": "moderado",
  "title": "Auditor devolveu G2 · 62%", "detail": "…",
  "owner": "humano", "agent": "frontend",
  "openedAt": "2026-09-24T14:10:00+00:00", "ageSeconds": 720,
  "action": { "label": "Decidir G2", "href": "#/demandas/D14/gates", "external": null },
  "source": { "event": "1c948fb92532", "file": "docs/squad/gates/G2-D14.json" } }
```
`Agent`:
```json
{ "agent": "backend", "state": "trabalhando", "runId": "a1b2…", "runner": "claude",
  "model": "claude-opus-5-5", "modelProvider": "Anthropic",
  "task": { "description": "Backend: D14 …", "demand": "1e3d…", "code": "D14", "step": "F2 · implementação", "startedAt": "…" },
  "current": { "tool": "Bash", "label": "Executando: testes do serviço", "target": "mvn -q test …", "since": "…", "long": false },
  "lastActivityAt": "…", "lastActivity": "Editando services/…/Foo.java",
  "lastProgress": { "ts": "…", "title": "…" },
  "recentFiles": ["…"], "recentCommands": [ { "ts": "…", "label": "…", "command": "…", "error": false } ],
  "recent": [ Activity ],                      // últimos 20 itens da run atual (formato de runs[].activity)
  "waiting": { "on": ["humano"], "reason": "Decidir G2", "since": "…", "alert": "human-required:1c94…", "action": { "label": "Decidir G2", "href": "#/demandas/D14/gates" } },
  "subagents": [ { "agent": "backend", "description": "…", "since": "…", "runId": "…" } ],   // só Orquestrador
  "toolCount": 38, "alerts": ["agent-stalled:…"] }
```

### 9.2 `GET /api/state` — campos novos (os atuais ficam iguais)
`version`, `thresholds`, `summary`, `alerts` (abertos), `alertsHistory` (fechados, §5.4), `agents` (como em `/api/live`).
`log[]` de eventos `gate` ganha (só na resposta) `cycle` e `returns`. `runs[]` ganha `lastActivityAt`, `stalled`
(bool) e `waitingOn` (lista). Consumidores atuais (painel D13, `github_sync.py`, testes) não são afetados.

### 9.3 Orquestrador lido por inteiro
`collect_runs` passa a ler a sessão principal com **todas** as ferramentas (não só `Agent`), sem as mensagens de texto
(conversa com o humano) — `activity` com `kind: "tool"` apenas; `status` "coordenando" vira `trabalhando` + `subagents`.
Pendências `Agent`/`AskUserQuestion`/`ExitPlanMode` alimentam §7.4.

### 9.4 Passo (`task.step`)
Prioridade: (1) campo `step` do último `progress`/`handoff` do agente na demanda (novo, opcional); (2) derivado do papel:
Arquiteto → "Triagem" (se validação aberta) ou "F1 · contrato"; Backend/DevOps/Observabilidade/Frontend → "F2 ·
implementação"; QA → "F3 · validação"; Auditor → "G<n> · parecer" (n = 1 + gates APPROVE da demanda; rota direta
começa em G2); Orquestrador → etapa da demanda (Registrada/Validação/Na fila/Execução/Gates/Revisão).
`log.py` ganha `--step <texto curto>` (opcional, ≤ 40 caracteres) — acréscimo; nenhum comando atual muda.
`docs/squad/orquestrador.md`/`AGENTS.md` (dono Orquestrador) passam a recomendar `--type progress --step` a cada marco.

### 9.5 Desempenho e segurança
- Cache de `parse_run` por `(caminho, mtime, tamanho)` e do log por `(mtime, tamanho)`; `/api/live` não chama
  `enrich_log` nem lê handoffs. Meta: `/api/live` p95 ≤ 300 ms com 66+ runs; registrar `serverMs`.
- Comandos exibidos: truncados em 200 caracteres e mascarados (`(?i)(token|secret|password|passwd|api[_-]?key)=\S+`,
  `gh[pousr]_[A-Za-z0-9]{20,}`, `sk-[A-Za-z0-9-]{20,}`, `Bearer \S+` → `***`). Servidor segue em `127.0.0.1`.
- Limites e regras em constantes nomeadas no topo de `server.py` (`STALLED_S`, `LONG_TOOL_S`, `WAIT_WARN_S`,
  `LOW_CONFIDENCE`, `MAX_AUTO_CYCLES`), com teste unitário por regra B1–B4/A1–A3 (log sintético via `SQUAD_LOG`).

## 10. Tema "Grafite" (próprio, sóbrio; claro e escuro)

### 10.1 Cores — tokens (contraste medido contra `--surface`, WCAG 2.x)

| Token | Claro | Contraste | Escuro | Contraste | Uso |
|---|---|---|---|---|---|
| `--bg` | `#F7F7F5` | — | `#111316` | — | fundo da página |
| `--surface` | `#FFFFFF` | — | `#1A1D21` | — | cartões, cabeçalho, gaveta |
| `--raised` | `#F0F1F2` | — | `#22262B` | — | menu lateral, hover, código |
| `--text` | `#1B1D21` | 16,9:1 | `#E8EAED` | 14,0:1 | texto |
| `--muted` | `#4B5058` | 8,1:1 | `#B4BAC2` | 8,7:1 | texto secundário |
| `--dim` | `#646A73` | 5,5:1 | `#969DA6` | 6,2:1 | metadados, hora (substitui `#7A7B80`) |
| `--line` | `#E3E4E6` | decorativa | `#2C3036` | decorativa | divisórias |
| `--line-strong` | `#858B94` | 3,4:1 | `#737A84` | 3,9:1 | borda de controle/foco de campo (≥ 3:1) |
| `--accent` | `#0B5F6A` (petróleo) | 7,3:1 | `#5CC3CF` | 8,2:1 | links, primário, "Você", concluído |
| `--accent-soft` | `#E6F1F2` | 6,4:1 | `#12343A` | 6,4:1 | fundo de destaque |
| `--danger` | `#A4262C` | 7,3:1 | `#FF8A85` | 7,4:1 | bloqueio, erro |
| `--danger-soft` | `#FBEDED` | 6,4:1 | `#3A1D1E` | 6,7:1 | fundo de bloqueio |
| `--warn` | `#8A5300` | 6,3:1 | `#F2B24C` | 9,1:1 | aviso, espera longa |
| `--warn-soft` | `#FDF3E3` | 5,8:1 | `#3A2C14` | 7,3:1 | fundo de aviso |
| `--ok` | `#2E6B3F` | 6,4:1 | `#6FCF8E` | 8,9:1 | trabalhando, passou |
| `--ok-soft` | `#EAF3EC` | 5,6:1 | `#1B3223` | 7,2:1 | fundo positivo |
| `--on-accent` | `#FFFFFF` (7,3:1) | | `#111316` (9,0:1) | | texto sobre `--accent`/`--danger` |

Colunas "soft" = contraste do texto da mesma família sobre o fundo suave. Nada de laranja saturado nem azul
institucional; `--warn` é âmbar escuro/ocre. Avatares: fundo `--raised`, emoji D3 mantido; o nome sempre em texto.

### 10.2 Modo
`<html data-theme="light|dark">`; padrão = `prefers-color-scheme`; escolha do usuário em `localStorage["sc-theme"]`
(`system|light|dark`) aplicada por script inline **no `<head>`** (sem flash). `color-scheme` acompanha (barras de rolagem
e controles nativos). O iframe de Produto (Grafana/Jaeger) não é tematizado.

### 10.3 Tipografia (IBM Plex Sans/Mono, já em uso — única dependência externa)
Escala: 12 (metadados, mín.) · 13 (tabela, cartão) · 14 (corpo) · 16 (h3) · 20 (h2) · 26 (h1). Pesos 400/500/600.
Números e horas em Plex Mono com `font-variant-numeric: tabular-nums` (idades não "pulam"). Rótulos de estado em
maiúsculas 11,5 px/600 com `letter-spacing: .04em` só dentro de badges. Linha 1,5 (corpo), 1,3 (títulos).

### 10.4 Espaçamento, forma e profundidade
Base 4 px: 4 · 8 · 12 · 16 · 24 · 32 · 48. Raio 4 px (controles e cartões), 999 px só em badges. Sem sombras, exceto
gaveta/painel de notificações (`0 8px 24px rgb(0 0 0 / .12)`; escuro `.4`). Alvos de toque ≥ 44 × 44 px em < 900 px;
≥ 32 px de altura no desktop. Foco: `outline 2px solid var(--accent)`, `offset 2px`, sempre visível.

### 10.5 Componentes de estado (um só vocabulário)
- `.sev` (severidade): ícone SVG inline (octógono/triângulo/círculo-i) + palavra + cor; fundo `*-soft`, borda esquerda 3 px.
- `.state` (estado do agente): ícone de §7.3 + rótulo; substitui `.dot`, `.pill`, `.tag` de status.
- Botões: `primary` (fundo `--accent`), `secondary` (borda `--line-strong`), `danger-outline` (Seguir mesmo assim,
  Cancelar demanda). `disabled` com motivo em `title` **e** texto adjacente.
- Movimento: pulso de "trabalhando" 1,6 s; com `prefers-reduced-motion: reduce` sem animação alguma.

## 11. Layout

### 11.1 1440 × 900 (Painel) — central e squad acima da dobra
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ [SC] Squad Control · Checkout Saga   ● Ao vivo · há 1 s   ⬣ 2 bloqueios  ▲ 3 avisos  Você 3   ◐ 🔔│ 56
├───────────────┬──────────────────────────────────────────────────────────────────────────────────┤
│ Painel      3 │ #ai-usage (D11, sticky) Claude Code 5 h ▬▬ 41% · semana …  │ Codex …           │ ≤72
│ Demandas      │ Painel                                              [+ Nova demanda]           │
│ Squad       2 │ ┌ SUA PRÓXIMA AÇÃO ─────────────────────────────────────────────────────────────┐│
│ Auditoria     │ │ ⬣ D14 · Decidir G2 — confiança 62% < 70%, sem decisão humana · há 12 min       ││
│ Produto       │ │ Auditor devolveu a implementação do Frontend (ciclo 2 de 2)      [Decidir G2]  ││
│               │ └───────────────────────────────────────────────────────────────────────────────┘│
│[+ Nova demanda│ BLOQUEIOS (2)                                  AVISOS (3)                          │
│               │ ⬣ D14 Auditor devolveu G2·62% Você 12min [Decidir]│▲ D12 PR #104 aguardando Você 2h [Revisar]│
│ LINKS DO PROD.│ ⬣ D15 3 perguntas da triagem  Você  5min [Responder]│▲ Backend sem progresso há 11 min [Ver]│
│ Console ↗     │                              Outras ações suas: D16 Iniciar │▲ D11 seguiu com 64%  [Ver] │
│ ───────────── │ SQUAD AO VIVO                                          2 trabalhando · 1 aguardando │
│ Desafio Técn… │ ┌Orquestrador──────┐┌Arquiteto────────┐┌Backend──────────┐┌Frontend─────────┐     │
│ Julien C. …   │ │● TRABALHANDO 2 s ││○ LIVRE          ││▲ SEM PROGRESSO  ││● TRABALHANDO 1 s│     │
│               │ │D14 · Gates       ││Sem tarefa       ││D14·F2 11 min    ││D14·F2 implement.│     │
│               │ │◷ Aguarda Frontend││                 ││▶ docker compose…││▶ Editando index…│     │
│               │ │  · há 4 min      ││                 ││◷ verificar term.││                 │     │
│               │ └──────────────────┘└─────────────────┘└─────────────────┘└─────────────────┘     │
│               │ ┌DevOps┐ ┌Observabilidade┐ ┌QA┐ ┌Auditor ◷ Aguarda Orquestrador: delegar G3┐     │
│               │ EM ANDAMENTO … · ENTREGUES RECENTEMENTE … · (Squad base)                          │
└───────────────┴──────────────────────────────────────────────────────────────────────────────────┘
```
Central em 2 colunas (Bloqueios | Avisos) a partir de 1100 px; abaixo, empilhadas (Bloqueios primeiro).

### 11.2 390 × 844
```
┌────────────────────────────────────┐
│ [SC] Squad Control        ◐  🔔 3  │ 48
│ ● Ao vivo 1 s   ⬣2  ▲3  Você 3     │ 32  (linha própria; contadores são links)
│ Painel³ Demandas Squad² Auditoria ›│ 44  menu D13 com rolagem própria
├────────────────────────────────────┤
│ #ai-usage empilhada (D11)          │
│ ┌ SUA PRÓXIMA AÇÃO ──────────────┐ │
│ │ ⬣ D14 · Decidir G2 · há 12 min │ │
│ │ confiança 62% < 70%            │ │
│ │ [        Decidir G2          ] │ │
│ └────────────────────────────────┘ │
│ BLOQUEIOS (2)                      │
│ ⬣ D14 Auditor devolveu G2 · 62%    │
│   Você · há 12 min     [Decidir]   │
│ ⬣ D15 3 perguntas · Você [Responder]│
│ AVISOS (3)                         │
│ ▲ D12 PR #104 · Você · 2 h [Revisar]│
│ ▲ Backend sem progresso · 11 min   │
│ SQUAD AO VIVO (lista, 1 coluna)    │
│ ● Orquestrador · D14 · há 2 s      │
│   ◷ Aguarda Frontend · 4 min     › │
│ ▲ Backend · sem progresso 11 min › │
│ …                                  │
└────────────────────────────────────┘
```
Em 390 px o cartão do integrante vira linha de 2–3 linhas (nome+estado+idade; demanda·passo; espera). Gaveta ocupa a
tela inteira com "Fechar" fixo no topo. Corpo sem rolagem horizontal (regra D13).

## 12. Preservado (paridade)
Rotas, aliases, menu de 5 itens, trilha, página da demanda, `?agente=` (D13/ADR-016); faixa `#ai-usage` com seu
comportamento e `--usage-h` (D11/ADR-014); selos de modelo (D9/ADR-012); todas as ações humanas (nova demanda,
backlog/editar, iniciar/override, responder triagem, pausar/retomar/repriorizar/cancelar, decidir gate
APPROVE/RETURN/OVERRIDE, revisar PR); sino, toasts e notificação do navegador; `/api/*` atuais inalterados.

## 13. Critérios de aceite (verificáveis)

### 13.1 Regras e servidor (QA com log sintético via `SQUAD_LOG`/`SQUAD_ROOT_DATA`)
- **CA-S1** Para cada regra B1–B4, A1–A3 existe um cenário que abre e um que fecha o item; `/api/live.alerts` confere
  `severity`, `kind(s)`, `owner`, `action.href`, `openedAt`, `source.event`.
- **CA-S2** 3 RETURN seguidos do mesmo `(demand, gate)` sem decisão humana ⇒ B3 com `owner: humano`; após `human` na
  chave, `returns` volta a 0.
- **CA-S3** Gate com 62% sem decisão ⇒ B2 (não A1); após `human/APPROVE` ⇒ A1; novo gate da chave com 80% ⇒ A1 fecha.
- **CA-S4** Run com turno aberto e última atividade há 601 s ⇒ A2 e `state: sem-progresso`; 599 s ⇒ nada.
  Ferramenta pendente há 200 s ⇒ `current.long: true`, sem A2.
- **CA-S5** Orquestrador com `Agent` pendente ⇒ `waiting.on` contém o papel do subagente e `subagents[]` lista-o;
  `AskUserQuestion` pendente ⇒ `waiting.on: ["humano"]`.
- **CA-S6** `/api/live` ≤ 64 KB e p95 ≤ 300 ms (20 medições, dados reais da cópia principal); `/api/state` mantém
  todas as chaves anteriores (diff de chaves) e `log.py` sem `--step` grava exatamente o mesmo formato de hoje.
- **CA-S7** Comando com `ghp_…`, `sk-…`, `password=…` aparece mascarado em `recentCommands`.
- **CA-S8** `alertsHistory` reconstrói, para a D13 real, os gates e a revisão de PR com `openedAt`/`closedAt`/`closedBy`.

### 13.2 Primeira tela e tempo real (C1, C2)
- **CA-U1 (C1)** Em 1440 × 900 e 390 × 844, sem rolar nem clicar, a partir de **qualquer** rota: contadores de bloqueios,
  avisos e "Você" visíveis no cabeçalho; no Painel, "Sua próxima ação" e ao menos os 2 primeiros bloqueios e 2 primeiros
  avisos visíveis acima da dobra (1440) / a caixa de próxima ação e o 1º bloqueio (390).
- **CA-U2 (C2)** Anexar um evento `gate` RETURN ao log, iniciar/terminar uma ferramenta numa transcrição e anexar
  `progress`: o bloqueio, o estado do cartão e a etapa da demanda mudam na tela em **≤ 3 s** (10 repetições, máx. ≤ 3 s,
  medido por Playwright do `write` até o seletor).
- **CA-U3** Indicador: parar o servidor ⇒ "Atrasado" entre 5 e 6,5 s e "Sem conexão" até 16,5 s; decisões desabilitadas
  com o motivo; religar ⇒ volta a "Ao vivo" em ≤ 3 s sem recarregar.
- **CA-U4** O polling não perde foco, rolagem, `details` abertos, texto digitado nem a gaveta aberta (repetir por 30 s).

### 13.3 Integrante (resposta 4)
- **CA-I1** Cartão de cada um dos 8 papéis mostra: estado (ícone + texto), idade da última atividade, demanda + passo,
  ferramenta atual em linguagem natural (quando houver), espera (quando houver), modelo.
- **CA-I2** Gaveta mostra as 7 seções de §7.2; "O que o humano precisa fazer" sempre presente; botão leva ao destino certo.
- **CA-I3** Com um bloqueio `owner: humano` na D14, o cartão do Orquestrador e o do agente de origem mostram
  "Aguarda: Você — <ação>" e a borda `--danger`.

### 13.4 Tema e acessibilidade
- **CA-T1** Todos os pares texto/fundo dos tokens ≥ 4,5:1 (texto) e ≥ 3:1 (bordas de controle, ícones de estado), nos
  dois modos — verificado por script sobre os valores de `:root` e `[data-theme=dark]`; axe-core sem violação de contraste.
- **CA-T2** Alternância Sistema/Claro/Escuro persiste após F5, sem flash do tema errado; `prefers-color-scheme` respeitado.
- **CA-T3** Nenhum estado ou severidade depende só de cor (inspeção com filtro de escala de cinza: todos distinguíveis
  por ícone/palavra); `prefers-reduced-motion` desliga o pulso.
- **CA-T4** Nenhum logo, nome ou cor institucional do Itaú (sem `#EC7000`/laranjas saturados, sem azul institucional).
- **CA-T5** Paridade §12: checklist da D13 §9.2 (máx. 3 cliques) repassado sem regressão; 17 rotas × 1440/390 sem
  erro de console nem rolagem horizontal.

### 13.5 Heurísticas tela a tela (C3) — o QA marca ✓/✗ com captura em 1440 e 390

| Tela | H1 | H2 | H3 | H4 | H5 | H6 | H7 | H8 | H9 | H10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Barra global | ao vivo + contadores | "bloqueio/aviso/Você" | links p/ filtro | mesmos ícones em toda tela | — | contadores sempre no mesmo lugar | atalho p/ central | 1 linha | "Sem conexão" diz o que fazer | legenda na Política |
| Painel | próxima ação + central + squad ao vivo | tipos em frase natural | "Visto" em aviso | `.sev`/`.state` únicos | decisão bloqueada c/ dado velho | quem age + desde no item | filtro `?alerta=` | 1 destaque só | "Por quê?" em cada item | "Por quê?" cita a regra |
| Demanda | faixa de alertas da demanda | etapas em português | voltar/trilha (D13) | mesma próxima ação | confirmação/override com nota | cartões dos integrantes ativos | seções âncora | seções recolhíveis | parecer + evidências | link p/ regra |
| Squad + gaveta | estado, agora, espera | rótulos naturais de ferramenta | fechar/Esc devolve foco | mesmo cartão do Painel | — | tarefa+passo sem abrir feed | tabela de esperas | feed só ferramentas por padrão | erro com comando e saída | legenda de estados |
| Demandas (lista) | chip de severidade | filtros em português | filtros na URL | — | — | código Dn + título | `?f=acao` | — | vazio explica | — |
| Auditoria (+Alertas) | histórico aberto/fechado | regra por extenso | filtros na URL | — | — | fechado por quem | filtros combináveis | tabela paginada | evento de origem | Política com limites |
| Nova demanda | validação ao vivo | tipos explicados | cancelar | — | campos obrigatórios | — | — | — | mensagens de erro por campo | ajuda por tipo |

### 13.6 Tarefas de usabilidade (QA, 1440 e 390; registrar cliques e tempo)
T1 "Há algo bloqueado? Quem precisa agir?" — responder em ≤ 5 s, 0 cliques. T2 "O que o Backend está fazendo agora e
desde quando?" — ≤ 1 clique. T3 "O Orquestrador está esperando alguém?" — ≤ 1 clique. T4 "Decida o gate pendente" —
≤ 2 cliques a partir de qualquer tela. T5 "Qual agente está sem progresso e o que devo verificar?" — ≤ 1 clique.
T6 "Quem fechou o bloqueio de G2 da D13 e quando?" — ≤ 3 cliques (Auditoria › Alertas).

## 14. Entrega e donos
1. **Orquestrador** (`tools/squad/server.py`, `log.py`, testes em `tools/squad/test_*.py` se existirem, senão QA em
   `tests/squad/`): §9 inteiro; constantes §9.5; recomendação de `--step` em `AGENTS.md`/`docs/squad/**`.
2. **Frontend** (`squad-control/index.html`): §6, §7, §8, §10, §11 consumindo `/api/live`; remove `gateNeedsHuman` e a
   regra de `classify` para gates (passa a usar `alerts[]`), mantendo `nextAction()` só para as ações não-alerta.
3. **QA**: §13 (scripts Playwright de C2 e contraste; checklist de heurísticas com capturas `tests/ui/d14-*`).
4. **Auditor**: G1 deste contrato; G2/G3 pelos CAs acima.

## 15. Riscos
- Heurística de "espera" por transcrição (Claude Code) não enxerga prompts de permissão; mitigado por A2 com texto
  "verificar o terminal". Codex/`run_agent.py` só expõem saída e `progress` (sem ferramenta atual detalhada).
- Poll de 1,5 s aumenta a carga local; mitigado por `/api/live` leve, caches por mtime e 10 s em aba oculta.
- O `code` Dn calculado no servidor precisa ser idêntico ao do cliente (mesma regra; CA-S1 confere).

## 16. Histórico
- 2026-09-24 — v1 (Arquiteto, D14 `1e3d3c894630`).
- 2026-09-24 — errata pós-G2 (Arquiteto, D14 `1e3d3c894630`; `docs/squad/gates/G2-D14.json`), alinhando o contrato a
  `tools/squad/alerts.py`, sem mudar regra de negócio:
  1. §5.2/§5.3: teto `STALLED_MAX_S = 3600` s no A2; `thresholds.stalledMaxSeconds` acrescentado em §9.1.
  2. §7.3: `interrompido` passa a ter precedência sobre `sem-progresso` (a run interrompida também abre A2).
  3. §5.1/§5.2: G3 APPROVE com `needsHuman` sem decisão mantém B2 aberto mesmo com a demanda encerrada por `is_done`.
  4. Registro de divergência: a regra "confiança < 70% é **bloqueio** (B2) até a decisão humana e **aviso** (A1)
     depois" diverge da primeira resposta do humano na triagem, que a classificou só como aviso. Prevalece pela
     hierarquia de verdade (AGENTS.md: ADRs/regras da constituição acima de preferências de UI; "Limites de autonomia"
     torna a intervenção obrigatória). Mudá-la exige **novo ADR**.
