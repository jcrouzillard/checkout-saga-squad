# Contrato — Visual da conversa com o Orquestrador, v2 (D20)

- Demanda: **D20** (`41bdb8b49835`, bug de operação, severidade média) — "Melhorar e corrigir o visual do chat".
- Evidência: `docs/squad/operacao/bugs/41bdb8b49835/evidencias/01-colado-2026-09-25-a-s-8.48.17.png`.
- Base: `docs/contracts/conversa-com-o-orquestrador.md` (D17, ADR-020) §9. Este documento **substitui** os itens
  *Mensagens*, *Composição* e *Estados* do §9 naquilo em que divergem; o resto do contrato D17 (rotas, SSE, registro,
  segurança, propostas) continua valendo.
- Donos da implementação: **Frontend** (`squad-control/index.html`, bloco D17 `chat`/`c-*`); **Orquestrador**
  (`tools/squad/conversa.py`, `tools/squad/server.py`, `docs/squad/prompts/conversa.md`) só para o §3.4 (defeito d);
  **QA** (`tests/**`) para o roteiro de navegador do §8.

## 1. Diagnóstico (causa de cada defeito)

| # | Defeito relatado | Causa encontrada | Onde |
|---|---|---|---|
| a | Nome, runner e "Respondendo…" do Orquestrador numa **coluna à esquerda** da bolha; "Você" e horário **acima** da bolha à direita | **Colisão de nome de classe.** O balão ao vivo é `<li class="c-msg orquestrador live">`. A regra global `.live { display:inline-flex; align-items:center; white-space:nowrap; color:var(--ok); font-weight:500 }` (indicador "ao vivo" do cabeçalho, linha ~344) também casa com ele: o `li` vira flex em **linha**, então `.who` e `.bub` ficam lado a lado e o cabeçalho é centralizado na vertical. Mensagens concluídas não têm `.live` e ficam certas — por isso o defeito só aparece durante o streaming. | `squad-control/index.html`: CSS `.live` (l. 344) × `chatLiveEl()` (`mk("li","c-msg orquestrador live")`) |
| b | Resposta em andamento inteira em **verde e negrito**, diferente da formatação final | Mesma colisão: `.live` aplica `color: var(--ok)` (verde) e `font-weight: 500` a todo o conteúdo herdado; ao chegar `fim`, o `li` é recriado sem `.live` e o texto volta ao normal. Agravantes: o cursor `.c-caret` é anexado ao `bub` quando o último bloco é lista, criando uma linha vazia com um bloco verde; e as listas saem com marcador **○** porque o `<ul>` do Markdown fica dentro do `<ol class="c-msgs">` e o navegador aplica o estilo de lista aninhada (`circle`). | `.live` (l. 344); `chatRenderLive()` (anexo do caret); `.c-msg .bub ul` sem `list-style-type` |
| c | "Respondendo…" **repetido** no cabeçalho da mensagem e na barra acima do campo | Dois desenhos da mesma fase: `chatRenderLive()` escreve `· ${phaseText(a)}` no `.ph` do cabeçalho **e** `chatRenderStatus()` escreve `phaseText(a)` + segundos na barra `#chat-status`. Com a resposta concluída, também há duplicação: a barra diz "Resposta concluída em X s" e o rodapé da mensagem diz "total X s"; em erro, a barra e a *flag* da mensagem dizem o mesmo. | `chatRenderLive()`, `chatRenderStatus()`, `chatTurnEnded()` |
| d | Horários em **fusos diferentes** (08:47:59 no cabeçalho × 11:47:11 no texto) | A UI está certa: `hhmm()` usa `toLocaleTimeString` → fuso do navegador (BRT, UTC−3 → 08:47:59). O **11:47:11 é texto do modelo**: o contexto `<dados_da_squad>` montado por `context_block()` repassa `eventosRecentes[].ts` crus do `decisions.jsonl`, que estão em **UTC** (`2026-09-25T11:47:11+00:00`, gerado por `log.py` com `timezone.utc`), sem dizer o fuso do humano; o prompt `docs/squad/prompts/conversa.md` não tem regra de horário; e o modelo também lê o `decisions.jsonl` direto (ferramenta Read), igualmente em UTC. **A causa é do servidor/prompt**, não da UI (correção exata no §3.4). Agravante de UI: horário com segundos em fonte mono, sem data, dificulta comparar. | `tools/squad/conversa.py` `context_block()` (l. ~248–257); `docs/squad/prompts/conversa.md` |

Regra que evita a recorrência de (a)/(b): **toda classe do chat é prefixada `c-`** (o estado ao vivo passa a ser
`c-msg--streaming`); nenhum seletor global genérico (`.live`, `.muted`, `.partial`…) pode ser o único responsável por
layout dentro de `#chat`.

## 2. Referências de usabilidade adotadas
Padrões consolidados de ChatGPT / Claude.ai (resposta do assistente como texto de leitura, sem balão; pergunta do
humano em balão à direita; parar no lugar de enviar; botão "ir para o fim"), Slack/Intercom (cabeçalho
autor · horário sempre na mesma posição; separador de dia; horário curto com data completa no *tooltip*), WCAG 2.2 AA
(1.4.3 contraste, 1.4.10 reflow sem rolagem horizontal em 320–390 px, 2.2.2 animação pausável/`prefers-reduced-motion`,
2.5.8 alvos, 4.1.3 mensagens de status sem roubar foco).

## 3. Especificação visual

### 3.1 Estrutura de cada mensagem (igual durante e após o streaming)
```
<li class="c-msg c-msg--orq [c-msg--streaming]">      <li class="c-msg c-msg--hum">
  <div class="c-meta">  ◆ Orquestrador · claude-… · 08:47   </div>     <div class="c-meta"> Você · 08:47 </div>
  <div class="c-body">  …Markdown…                         </div>     <div class="c-body c-bubble"> texto </div>
  [<div class="c-foot"> 1º trecho 1,8 s · total 23,3 s </div>]
  [cartão de proposta]
```
- `li` é **bloco** (`display:flex; flex-direction:column`), nunca linha. O cabeçalho `.c-meta` fica **sempre acima**
  do conteúdo, alinhado ao mesmo lado do conteúdo: Orquestrador à esquerda (borda esquerda do meta = borda esquerda do
  corpo), humano à direita (borda direita do meta = borda direita do balão).
- `.c-meta` (uma linha, quebra se faltar espaço): marcador visual do autor (Orquestrador: quadrado 16 px `--accent`
  com "O" `--on-accent`; humano: sem marcador) · **nome** (600, `--text`) · *chip* do modelo (Orquestrador; o runner
  vai no `title` do chip, não como texto solto) · horário (§3.5). Nada de estado da fase no cabeçalho.
- **Orquestrador**: sem balão preenchido; conteúdo como texto de leitura em `--text`, peso 400, largura total da
  coluna. **Humano**: balão `--accent-soft`, borda `--line`, raio 12 px (canto inferior direito 4 px), padding 10×14,
  `max-width: 85%` da coluna, `white-space: pre-wrap`, texto literal (sem Markdown).
- Estado final diferente de `ok` (erro, cancelada, tempo esgotado, interrompida): *flag* com ícone + texto no
  **rodapé** da mensagem (não no cabeçalho), junto de "Tentar de novo" quando couber.

### 3.2 Coluna de leitura, espaçamento e tipografia
- Painel mantém `min(640px,100%)` (D17 §9). Coluna de mensagens: `max-width: 68ch` centralizada, padding lateral
  20 px (≥ 901 px) / 12 px (≤ 900 px).
- Espaço entre mensagens de autores diferentes 20 px; entre meta e corpo 4 px; entre corpo e rodapé 6 px.
- Corpo: 14 px / 1.6, IBM Plex Sans. Meta e rodapé: 12 px, `--muted`/`--dim`. Horários com
  `font-variant-numeric: tabular-nums` na fonte do texto (não mono).
- **Separador de dia** entre mensagens de datas locais diferentes: linha `--line` com rótulo central "Hoje", "Ontem"
  ou "24 de setembro" (`role="separator"`, texto também lido por leitor de tela).

### 3.3 Markdown (mesmo renderizador e mesmo CSS durante e após o streaming)
- Um único `mdRender()` produz o DOM nas duas fases; a fase ao vivo só acrescenta o cursor. Dado o mesmo texto, o
  DOM ao vivo (sem o cursor) é **idêntico** ao final.
- Suportado: parágrafo; `**negrito**` (600) e `*itálico*`; títulos `#…` → 15 px 600; listas `-`/`*`/`1.` com
  **`list-style-type` explícito** (`disc` / `decimal`; `circle` só em lista aninhada real, indentação ≥ 2 espaços);
  `código` inline (mono 12.5 px, fundo `--raised`, raio 3 px); bloco ```` ``` ```` (mono 12.5 px, fundo `--raised`,
  borda `--line`, `overflow-x:auto`, `white-space:pre`, altura máx. 320 px); citação `>` (borda esquerda 3 px
  `--line-strong`, `--muted`); tabela com pipes `| a | b |` em contêiner `overflow-x:auto`; links conforme D17 §9
  (internos `#/…`, `http(s)` com `rel="noopener noreferrer"` e aviso "abre em nova aba"; `Dn` vira link da demanda).
  Links sublinhados, cor `--accent`.
- Marcação incompleta durante o streaming (`**abc` sem fechamento) aparece como texto literal até fechar; não pode
  "vazar" estilo para o resto da mensagem.
- Cursor ao vivo: anexado ao **último nó de texto mais profundo** (último `li`, `p`, célula ou `pre`), nunca como
  linha própria; 2 px × 1em `--accent`; pisca só sem `prefers-reduced-motion: reduce`.

### 3.4 Horários (corrige d)
**UI (Frontend):** todo horário exibido vem de `ts` (UTC no registro) convertido pelo `Intl.DateTimeFormat` **sem**
`timeZone` (fuso do navegador). Formato único, absoluto:
- mesmo dia local → `08:47`; dia anterior → `ontem 08:47`; outro dia → `24/09 08:47`; outro ano → `24/09/2025 08:47`.
- `<time datetime="<ISO UTC>" title="25/09/2026 08:47:59 (America/Sao_Paulo)">`. Sem segundos na tela.
- A lista "Conversas" e o subtítulo "desde …" usam a mesma função.

**Servidor e prompt (Orquestrador — mudança exata, sem nova rota):**
1. `POST /api/conversas/<id>/mensagens` aceita campo **opcional** `"tz"`: nome IANA (`^[A-Za-z]+(?:/[A-Za-z0-9_+\-]+){0,2}$`,
   ≤ 64 caracteres, validado por `zoneinfo.ZoneInfo`). Inválido ou ausente → fuso local do servidor. Não gera erro
   novo; demais campos e respostas iguais. A UI envia `Intl.DateTimeFormat().resolvedOptions().timeZone`.
2. `context_block()` recebe o fuso e: (i) converte `eventosRecentes[].ts` para ISO **com o deslocamento local**
   (`2026-09-25T08:47:11-03:00`); (ii) acrescenta ao cabeçalho `fuso="America/Sao_Paulo" utc="-03:00"` e `gerado=` no
   mesmo fuso. O registro em `.squad/conversas/*.jsonl` e o `decisions.jsonl` **continuam em UTC** (não mudar `now_iso()`
   nem `log.py`).
3. `docs/squad/prompts/conversa.md` ganha a regra: "Horários: cite sempre no fuso indicado em `<dados_da_squad fuso>`,
   como `HH:MM` (com `dd/mm` quando não for hoje). Valores `ts` lidos de arquivos (`…Z` ou `+00:00`) estão em UTC:
   converta antes de citar. Nunca escreva um horário UTC sem conversão."

### 3.5 Um único indicador de estado (corrige c)
- **Durante o turno**, a fase aparece **uma vez**, dentro da mensagem ao vivo, como última linha do corpo:
  ícone + texto + segundos (`◌ Pensando… 3 s`, `⌕ Lendo docs/adr/020… 5 s`, `✎ Respondendo… 9 s`,
  `■ Parando…`), `--muted`, 12.5 px. Antes do primeiro trecho essa linha é todo o corpo; depois, fica abaixo do texto.
- A barra `#chat-status` **não mostra fase nem "concluída"**. Ela fica só para estados da conversa sem mensagem
  própria: *indisponível*, *ocupado* (com link), falha ao enviar/rede. Resultado de turno (erro, cancelada, tempo
  esgotado) aparece só no rodapé da mensagem (§3.1). Tempo total aparece só no rodapé ("total 23,3 s").
- `aria-live` (D17 §9) inalterado: anuncia apenas "Resposta do Orquestrador recebida" e erros.

### 3.6 Rolagem
- Acompanha o fim **somente** se o usuário estava a ≤ 80 px do fim antes do novo conteúdo; ao enviar uma pergunta,
  sempre vai ao fim.
- Se o usuário rolou para cima e chega conteúdo novo, a posição **não muda** e aparece o botão flutuante
  **"Ir para o fim"** (↓ + texto; "Nova resposta ↓" se chegou texto novo), canto inferior direito da lista, 16 px
  acima do compositor, ≥ 44×44 px em 390 px, `aria-controls="chat-msgs"`. Clicar rola ao fim (suave, instantâneo com
  `prefers-reduced-motion`) e o botão some; também some ao rolar manualmente até o fim.
- Recarregar a lista (polling, `chatRender`) preserva a posição e o foco.

### 3.7 Composição
- `textarea` com rótulo visível ("Sua pergunta ao Orquestrador"), **altura automática**: 1 linha (mín. 44 px) até
  40 vh, depois rolagem interna; volta a 1 linha após enviar.
- Contador `n/8000` visível a partir de 7 000 caracteres (sempre em `aria-describedby` quando visível); > 8 000 em
  `--danger` e envio bloqueado com mensagem.
- Atalhos visíveis abaixo do campo em > 480 px: "Enter envia · Shift+Enter nova linha · Esc fecha"
  (`<kbd>`). Em ≤ 480 px a dica fica só em `aria-describedby`.
- Durante o turno, o campo **continua editável** (rascunho da próxima pergunta), Enter não envia (dica muda para
  "Aguarde a resposta ou pare"), e o botão **Enviar vira "Parar"** no mesmo lugar (mesmo tamanho, estilo perigo
  contornado). Isso altera o D17 §9 ("desabilitada durante o turno").

### 3.8 Tema Grafite (ADR-017) e larguras
- Só tokens existentes (`--text`, `--muted`, `--dim`, `--surface`, `--raised`, `--line`, `--line-strong`,
  `--accent`, `--accent-soft`, `--on-accent`, `--danger`, `--warn`, `--ok`); **nenhuma** cor verde/`--ok` em texto
  de mensagem. Claro e escuro verificados.
- 1440 px: painel à direita, 640 px. 390 px: painel em tela cheia, coluna com padding 12 px, balão humano
  `max-width: 88%`, sem rolagem horizontal do corpo (tabelas e código rolam no próprio contêiner).

### 3.9 Acessibilidade
- Ordem do DOM = ordem de leitura: autor → horário → conteúdo → rodapé. Cada `li` tem `aria-labelledby` no meta.
- Contraste AA (≥ 4.5:1 texto, ≥ 3:1 ícones/bordas de foco) nos dois temas; foco visível em links, botões e
  "Ir para o fim".
- Estado nunca só por cor (ícone + texto). Alvos ≥ 44 px em 390 px. Foco permanece no campo durante o streaming.

## 4. Critérios de aceite (roteiro de navegador)
Preparação comum: servidor local com `SQUAD_CHAT_RUNNER=fake` emitindo em trechos (≥ 400 ms entre trechos) o texto
`FX` abaixo; navegador (Playwright) com `timezoneId: "America/Sao_Paulo"`, larguras 1440 e 390, temas claro e escuro.
`FX` = `"Recebido. O registro confirma:\n\n- **08:47** – suas respostas à triagem da D19 foram registradas.\n- 08:47 – você iniciou a D19.\n\nUse `pending` e veja [o painel](#/painel)."`
Capturas em `tests/ui/d20-*.png`.

| # | Critério | Como verificar |
|---|---|---|
| CA-V1 (a) | Cabeçalho acima do conteúdo, mesmo lado, durante e após o streaming | Reproduzir a evidência: conversa com uma resposta concluída + pergunta "Mandei la" + resposta ao vivo. Durante o streaming e após `fim`, para cada `li.c-msg`: `getComputedStyle(li).flexDirection === "column"` (ou `display:block`); `meta.bottom ≤ body.top`; Orquestrador: `|meta.left − body.left| ≤ 1`; humano: `|meta.right − body.right| ≤ 1`. Nenhum elemento de `#chat` com classe `live`. |
| CA-V2 (b) | Formatação ao vivo = formatação final | No meio do streaming: `color` do `p` do corpo == `color` de um `p` de mensagem concluída (== `--text`), `font-weight` 400; `strong` só em "08:47" do primeiro item. Após `fim`, `body.innerHTML` final == `body.innerHTML` ao vivo capturado com o texto completo antes do `fim`, removidos o cursor e a linha de fase. `ul` com `list-style-type: disc`. Cursor é filho do último `li` (não do corpo). |
| CA-V3 (c) | Um único indicador de fase | Durante o turno: exatamente **1** elemento visível em `#chat` cujo texto casa `/Pensando|Lendo|Procurando|Consultando|Respondendo|Parando/`, dentro de `li.c-msg--streaming`; `#chat-status` oculto. Após `fim` ok: nenhum texto "concluída" em `#chat-status`; "total … s" aparece 1 vez (rodapé). Em erro simulado: texto do erro aparece 1 vez (rodapé), barra oculta. |
| CA-V4 (d) — UI | Horário no fuso do navegador, formato consistente | Mensagem com `ts` `2026-09-25T11:47:59Z` e data do navegador 25/09/2026: meta mostra `08:47` e `title` contém `25/09/2026 08:47:59`; com `timezoneId: "Asia/Tokyo"` mostra `20:47`; mensagem de 24/09 mostra `ontem HH:MM`; nenhum horário do chat com segundos; lista "Conversas" usa o mesmo formato. |
| CA-V5 (d) — servidor | Contexto e prompt no fuso do humano | Teste unitário: `context_block(..., tz="America/Sao_Paulo")` com evento `ts` `2026-09-25T11:47:11+00:00` → `eventosRecentes[0].ts == "2026-09-25T08:47:11-03:00"` e cabeçalho com `fuso="America/Sao_Paulo" utc="-03:00"`; `tz` inválido (`"../x"`, 65 chars) → fuso do servidor, resposta `202` inalterada. `conversa.md` contém a regra do §3.4.3. Registros `.jsonl` e `decisions.jsonl` continuam com `Z`/`+00:00`. Com runner real: pergunta "a que horas registrei as respostas da D19?" → horário citado igual ao exibido no painel de demandas (fuso local). |
| CA-V6 | Markdown completo e seguro | Resposta simulada com parágrafo, lista numerada, lista aninhada, `código`, bloco ```` ``` ```` de 120 colunas, citação, tabela 4×3, link interno, link externo, `**negrito` sem fechar: todos com a tag esperada; `pre` e tabela rolam no próprio contêiner; `document.body.scrollWidth ≤ innerWidth` em 390; link externo com `rel="noopener noreferrer"`; nenhum HTML do texto interpretado (`<img onerror>` aparece literal). |
| CA-V7 | Rolagem respeita o usuário | Com histórico longo: rolar 400 px para cima durante o streaming → `scrollTop` não muda por 3 s de trechos e aparece "Ir para o fim"/"Nova resposta"; clicar → fim, botão some, foco segue no campo. Parado no fim → acompanha cada trecho (distância ao fim ≤ 80 px). Enviar pergunta → vai ao fim. |
| CA-V8 | Composição | Colar 12 linhas → altura cresce; 60 linhas → altura = 40 vh e rola internamente; após enviar volta a 1 linha. Contador oculto com 100 caracteres, visível com 7 000. Durante o turno o campo aceita digitação, Enter não envia, o botão no lugar de "Enviar" é "Parar" (mesmo `getBoundingClientRect` ± 2 px de posição). Dica de atalhos visível em 1440, oculta em 390. |
| CA-V9 | Largura de leitura e espaçamento | Em 1440: largura do corpo do Orquestrador ≤ 68ch; balão humano ≤ 85% da coluna. Em 390: sem rolagem horizontal do corpo, balão ≤ 88%, alvos (links de rodapé, "Ir para o fim", Enviar/Parar) ≥ 44 px. Separador de dia aparece entre mensagens de 24/09 e 25/09. |
| CA-V10 | Tema Grafite | Claro e escuro: contraste ≥ 4.5:1 (axe/cálculo) para corpo, meta, rodapé, linha de fase e links; nenhum texto de mensagem com a cor de `--ok`. Capturas `d20-{1440,390}-{claro,escuro}-{streaming,final}.png`. |
| CA-V11 | Acessibilidade | Só teclado: abrir, digitar, enviar, parar, "Ir para o fim", fechar com Esc (foco volta ao botão). `aria-live` anuncia só conclusão/erro (nenhum anúncio por trecho). Com `prefers-reduced-motion: reduce` o cursor e o ícone não animam. |
| CA-V12 | Sem regressão | CA-1…CA-23 do contrato D17 que tocam a UI (CA-1, 2, 3, 10, 18, 19, 21, 23) continuam passando; `tests/squad/*.py` passam; o indicador `.live` do cabeçalho do Squad Control mantém a aparência de antes. |

## 5. Fora do escopo
- Rotas, SSE, formato dos registros, fluxo de propostas e segurança do D17 — exceto o campo opcional `tz` e o
  contexto/prompt do §3.4 (causa de d).
- Largura do painel (continua `min(640px,100%)`), redimensionamento, painel destacável, avatares com imagem.
- Edição/regeneração de mensagem, reações, copiar mensagem, busca, exportar, anexos, voz.
- Horário relativo que se atualiza sozinho ("há 2 min") — preterido para evitar redesenho periódico; formato absoluto
  com dia (§3.4).
- Mudar `log.py`/`decisions.jsonl` para horário local (continuam em UTC).
