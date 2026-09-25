# Checklist — D20 (41bdb8b49835): visual da conversa v2 — validação do QA (G3)

Contrato: `docs/contracts/ui-conversa-visual-v2.md` §4 · Parecer anterior: `docs/squad/gates/G2-D20.json`.
Branch `feature/D20-visual-do-chat` (HEAD `6c3a906` + mudanças do QA só em `tests/**`), 25/09/2026.

**Ambiente:** servidores do worktree em portas livres (7471–7474) com dados temporários no scratchpad (nunca o :7070 nem
o log real); navegador descartável `zenika/alpine-chrome:with-puppeteer` (Chromium 124, `TZ=America/Sao_Paulo`,
axe-core wcag2aa); `SQUAD_CHAT_RUNNER=fake` em tudo, exceto **1** pergunta ao `claude` real (CA-V5).

## Resultado por critério

| CA | Resultado | Evidência |
|---|---|---|
| CA-V1 cabeçalho acima, mesmo lado | PASS | `d20-conversa-visual-result.json` CA-V1: `li` coluna, `meta.bottom ≤ body.top`, desvio lateral ≤ 1 px durante e após; 0 elementos `.live` em `#chat` |
| CA-V2 formatação ao vivo = final | PASS | cor do `p` ao vivo = concluída = `--text`, peso 400; `strong` só "08:47"; `ul` disc; cursor dentro do último `li`; `innerHTML` ao vivo == final |
| CA-V3 um único indicador | PASS | 1 fase visível, dentro de `li.c-msg--streaming`; barra oculta; "total … s" 1 vez; erro 1 vez no rodapé, barra oculta |
| CA-V4 horário local (UI) | PASS | 08:47 (São Paulo), 20:47 (Tóquio), `ontem 08:47`, title `dd/mm/aaaa 08:47:59`, nenhum horário com segundos; POST envia `tz` |
| CA-V5 servidor/prompt | PASS | unitário `test_conversa_tz_d20` 7/7; **runner real** (1 pergunta): "a que horas registrei as respostas da D19?" → "hoje às **08:47**" (evento `11:47:11+00:00` = 08:47 BRT, mesmo formato do painel), sem 11:47; registros seguem em `Z` — `d20-ca-v5-real.json` |
| CA-V6 Markdown completo e seguro | PASS | 390 escuro: p, `ol` decimal, lista aninhada, código, `pre` 120 col. com rolagem própria, citação, tabela 4×3 em contêiner `overflow-x:auto`, link interno `#/painel…`, externo `noopener noreferrer`, `**negrito` literal, `<img onerror>` literal (0 `img`), sem rolagem horizontal — `d20-390-escuro-markdown.png` |
| CA-V7 rolagem | PASS | histórico de 30 mensagens + resposta LONGO (~10 s): ao enviar vai ao fim; no fim acompanha (8 amostras ≤ 80 px); rolado 400 px para cima, `scrollTop` fixo por 3 s com texto crescendo e botão "Nova resposta" (`aria-controls=chat-msgs`); clicar → fim, botão some, foco no campo; rolar manualmente ao fim também o esconde — `d20-1440-claro-rolagem.png` |
| CA-V8 composição | PASS | 1 linha ≥ 44 px; 12 linhas cresce; 60 linhas = 40 vh com rolagem interna; volta a 1 linha após enviar; contador oculto com 100, visível com 7 000, `over` com 8 001; durante o turno Enter não envia, rascunho mantido, "Parar" na posição de "Enviar" (± 2 px); dica visível em 1440 e só em `aria-describedby` em 390 |
| CA-V9 largura e espaçamento | PASS | 1440: corpo ≤ 68ch, balão humano ≤ 85 %; 390: sem rolagem horizontal, balão ≤ 88 %, "Ir para o fim"/Enviar/Parar/"Tentar de novo" ≥ 44 px; separador de dia presente |
| CA-V10 tema Grafite | PASS | axe wcag2aa sem violações em `#chat` durante e após o streaming nos 4 casos; nenhum texto de mensagem com a cor `--ok`. Capturas: `d20-{1440,390}-{claro,escuro}-{streaming,final}.png` (8) |
| CA-V11 acessibilidade | PASS | `aria-live` só "Resposta do Orquestrador recebida" (nenhum trecho); teclado: Shift+Tab do campo chega em "Ir para o fim" (contorno de foco 2 px), Enter rola e devolve o foco ao campo; Tab até "Parar" + Enter cancela (d17); Esc fecha e o foco volta a `#chat-btn`; `prefers-reduced-motion: reduce` → cursor e ícone de fase com `animation: none` |
| CA-V12 sem regressão | PASS com ressalva | `d17-conversa.js` 20/20 (CA-1, 2, 3, 21, 23, reconexão, estados, destravar, axe, 390); `tests/squad/*` todas verdes uma a uma; indicador `.live` do cabeçalho intacto (flex, cor de estado). **Ressalva:** a reverificação "após o rebase sobre a D18 (PR #171)" não é possível ainda — a D18 não está na `develop` nem nesta branch |

## Suítes de `tests/squad/` (uma a uma, `SQUAD_CHAT_RUNNER=fake`)
test_conversa_tz_d20 7 OK · test_conversa_d17 44 OK · test_alertas_d14 20 OK · test_ambiente_teste_d15 41 OK ·
test_bugs_d16 38 OK · test_bugs_d16_qa 18 OK · test_governanca_d14_qa 19 OK · test_e2e_compose_seguro_d15 11 OK ·
test_entrega_por_pr.py "Todas as verificações passaram".

## O que o QA mudou (só `tests/**`)
- `tests/ui/d17-conversa.js`: `estado-erro` segue o contrato v2 §3.5 (flag "Erro" + "Tentar de novo" no rodapé da
  mensagem, texto do erro 1 vez, barra oculta); `tentar-de-novo` agora tem critério (novo turno com a mesma pergunta,
  erro só no rodapé da nova mensagem, foco no campo); CA23 espera o anúncio (o `announce()` escreve 50 ms depois —
  a leitura imediata era corrida do roteiro, não defeito); `executablePath` do ambiente.
- `tests/ui/d20-conversa-visual.js`: CA-V6, V7, V8, V9, V10 (8 capturas + axe) e V11 completos.
- `tests/squad/conversa_fake_runner.py`: palavras-chave `MDV6` (Markdown do CA-V6) e `LONGO` (~10 s, CA-V7).
- Resultados: `d17-conversa-result.json`, `d20-conversa-visual-result.json`, `d20-ca-v5-real.json`.

## Defeitos
Nenhum defeito de produção encontrado. Observação (não bloqueia): link interno do Markdown ganha `?conversa=<id>`
para manter o painel aberto — compatível com "internos `#/…`" do contrato.
