# D21 — Imagens na conversa: resultado do QA por CA e roteiro do aceite humano

Demanda `71b7d9bc3313` · contrato `docs/contracts/imagens-na-conversa.md` (§10) · gate `docs/squad/gates/G2-D21.json`
(ressalvas para o QA 1–6). Rodada do QA em 25/09/2026, worktree `feature/D21-imagem-no-chat` (commit f58d10e + testes).

## 1. Como reproduzir

| O quê | Comando / arquivo |
|---|---|
| Servidor, runner simulado (CA-I8…I13, I17…I20, I22) | `python3 tests/squad/test_conversa_anexos_d21.py` (27 testes; fixtures em `tests/squad/fixtures/d21/`, as duas pesadas geradas por `gen_fixtures.gerar_pesadas`) |
| Runner simulado que lê o stdin stream-json | `tests/squad/conversa_fake_runner.py` (grava `.sessao/fake_last_stdin.json`; palavra `IMGECO`) |
| Navegador (CA-I1…I8, I12, I21) | `tests/ui/d21-imagens.js` (instruções no cabeçalho) → `tests/ui/d21-imagens-result.json` + `tests/ui/d21-*.png` |
| Turnos REAIS (CA-I14/I15, custo) | `python3 tests/squad/real_conversa_anexos_d21.py codex\|claude --dir <scratch>` (cópia de dados vira repositório git próprio; calço no PATH grava o argv) |
| Regressão D20 com relógio fixo | `tests/ui/d20-conversa-visual.js` (defeito `af1bc2450bca` corrigido: `clock` fixo em 2026-09-24 12:00Z no CA-V4) |

## 2. Resultado por CA

| CA | Resultado | Evidência |
|---|---|---|
| CA-I1 colar | PASS | d21-imagens: colar com foco no campo e na lista → 1 cartão, 1 upload, campo inalterado |
| CA-I2 colar texto | PASS | só texto e texto+imagem → nenhum upload, `defaultPrevented` falso |
| CA-I3 arrastar | PASS | sobreposição com o texto exato; arrastar texto sem sobreposição; drop fora do painel não navega |
| CA-I4 botão | PASS | `aria-label`, `title`, `accept` exatos, 44×44 |
| CA-I5 animação | PASS | anel ≥ 400 ms (411 ms); com upload lento `aria-valuenow` 0…99 (99 valores) e "Processando" depois; reduced-motion sem animação, texto "Enviando 0%"/"Processando…" |
| CA-I6 remover | PASS | cartão sai, `POST …/remover` 1×, "Imagem removida" no aria-live; servidor: arquivo apagado, 409 em uso |
| CA-I7 até 3 imagens | PASS | 4 coladas → 3 + aviso exato; envio com 3 na ordem; só imagem → `text:""`; servidor 413 `anexos_demais` |
| CA-I8 validação | PASS | navegador (sem requisição) e servidor: pdf/gif/falso/HEIC 415, truncado 422, gigante 422, JPEG com `image/png` aceito como JPEG |
| CA-I9 > 5 MB antes de ler | PASS | `test_ca_i9_corpo_que_nunca_termina`: CL 5242881 e corpo que nunca chega → 413 em < 1 s, `Connection: close`, servidor fecha; PDF 415 sem ler; navegador recusa `grande.png` (6,3 MB) sem requisição |
| CA-I10 metadados | PASS | reprocessar o gravado remove 0; sem `GPS`/`Exif`/`<x:xmpmeta`/`tEXt`; nome = sha256; mesmo arquivo 2× → 200 |
| CA-I11 servir com segurança | PASS | tipo real, `nosniff`, CSP; `../x`, `..%2Fx`, 63 hex, maiúsculas, `<aid>.png`, outra conversa → 404; Origin estranha → 403 sem ler |
| CA-I12 histórico | PASS | F5 → miniaturas na ordem com `alt` exato; visualizador (Enter abre, foco no Fechar, ←/→, Esc fecha e devolve o foco); arquivo sumido → "Imagem indisponível" sem erro de página |
| CA-I13 build_cmd | PASS | unitários `T01Comando` (claude mesmas flags + stream-json; codex `--image=<abs>` e `--`; sem imagem = D17) |
| CA-I14 claude real | PASS | T1 print → "ALERTA B6 . PR #191 EM CONFLITO"; T2 `--resume` + stream-json com segundo.png + quase5mb.png (4,7 MB) inline → texto das duas, `tools: []`, mesmo sessionId, sem `SQUAD_CHAT_CLAUDE_B64_MAX` (2 turnos: o turno retomado com imagem foi o 2º, não o 3º, pelo limite de 2 turnos) |
| CA-I15 codex real | PASS | cópia de dados como repositório git: T1 print (lê "ALERTA 86 · PR #191", o "B" da fonte 5×7 vira "8"), T2 "191" com `sessionReset: false`, T3 com segundo.png e pergunta "-leia…" → "CODIGO VERDE 4271 / FILA KAFKA PARADA", `sessionReset: false`, mesmo threadId nos 3, argv de T3 = `exec resume <th> --json -c sandbox_mode="read-only" --image=<abs> -- <prompt>` |
| CA-I16 injeção | PASS (codex) · claude real não repetido | codex real: descreve o texto como dado, sem proposta, `tools: []`, `x.txt` inexistente, `decisions.jsonl` (cópia e worktree) igual; `git status` da cópia igual (o do worktree mudou só pelas capturas das suítes de UI rodando em paralelo). Claude: barreira por argv (Read/Glob/Grep) no fake; turno real fora do orçamento |
| CA-I17 somente leitura | PASS (fake) | `--disallowedTools`, `--strict-mcp-config`, tools Read/Glob/Grep com imagem; log intacto |
| CA-I18 sessão perdida | PASS | marcador `[imagem anexada: "print.png" 1440×900]`, 0 blocos image no turno sem imagem; só a imagem do turno atual quando há |
| CA-I19 limites | PASS | tetos por variável → 413 com os dois códigos; pendente 25 h apagado na subida e no upload; referenciado fica |
| CA-I20 registro e git | PASS | linha com 3 imagens < 2 KB, sem base64; `git check-ignore` dos anexos; sem `.squad/runs` |
| CA-I21 teclado e larguras | PASS | ordem observada: Tab `#chat-text → #chat-attach (clipe) → #chat-send → fim da página`; Shift+Tab `#chat-send → #chat-attach → #chat-text → "Remover imagem 1: tecl.png" → link → miniatura`. Enter no clipe abre o seletor (1 anúncio "Imagem anexada"), Enter no × remove, Enter no campo envia com imagem. 390 px sem rolagem horizontal, × e clipe ≥ 44 px (1440: × 32 px visuais); capturas `d21-{1440,390}-{claro,escuro}-{bandeja,enviando,historico,erro}.png` |
| CA-I22 sem regressão | PASS | `tests/squad/` uma a uma: d14 20, d15 41, d16-qa 18, d16 38, d21 27, d17 44 (ver nota), d20-tz 7, d19 27, e2e-compose-d15 11, entrega-por-pr ok, d14-qa 19, d18 18, e2e_delegacao_d19 ok; UI: d17 20/20, d19 39/39, d20 CA-V1…V12 17/17 (CA-V4 com relógio fixo); mensagens > 32 KB → 413 |
| CA-I23 aceite humano | PENDENTE (humano) | roteiro na §3 |

Nota CA-I22: `test_conversa_d17` falhou 1× (CA-18, `pgrep -f conversa_fake_runner.py` achou um runner simulado de
OUTRO servidor, o das suítes de UI rodando ao mesmo tempo) e passou 44/44 sozinho — defeito do teste registrado para o QA.

## 3. Roteiro do aceite humano (CA-I23, item 3 do G2) — preparar, não executar pelo QA

Onde: Squad Control real **depois do merge** (produtivo) ou no ambiente de teste pedido pelo humano
(`test-env-request`). Runner padrão da máquina.

1. Cmd+Ctrl+Shift+4 e selecione uma área com texto legível (vai para a área de transferência).
2. Abra o painel do chat, clique no campo e pressione Cmd+V → miniatura com anel de progresso e ✓.
   Repita com o foco na **lista** de mensagens (clique numa mensagem) → também anexa.
3. Escreva "o que tem nesse print?" e envie → a resposta descreve corretamente o print.
4. F5 → a imagem continua no balão; clique nela → visualizador; Esc fecha.
5. Copie células do Excel/Numbers e Cmd+V no campo → só o texto entra, nenhuma miniatura.
6. Arraste um `.pdf` → "<nome>: formato não aceito. Envie PNG, JPEG ou WEBP."; arraste um PNG > 5 MB →
   "<nome>: imagem acima de 5 MB (x,y MB)."
7. Reinicie o servidor com `SQUAD_CHAT_RUNNER=codex` (só no ambiente de teste) e repita os passos 2–3 uma vez.
8. Evidência: capturas `tests/ui/d21-aceite-*.png` e registro
   `python3 tools/squad/log.py --agent humano --type human --title "D21: aceite do Cmd+V" --demand 71b7d9bc3313 ...`.

## 4. Observações para o G3
- Desvios aceitos no G2 continuam: Enviar habilitado com campo vazio (mostra "mensagem vazia"); clipe depois do
  campo no DOM (Tab vai campo → clipe; Shift+Tab alcança o clipe e o remover); duplicata sai da bandeja com aviso.
- Contrato ainda sem as notas do G1/G2 (change-request do Arquiteto, item 7 do G2).
- `codex exec resume` depende de o cwd estar num repositório git (sem `--skip-git-repo-check`); no produtivo está.
