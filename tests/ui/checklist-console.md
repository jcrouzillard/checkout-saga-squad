# Checklist manual — Console de Checkout (D2 `48b6ace91207`, gate G2 → G3)

> Verificação do QA sobre `checkout-console/index.html` (contrato `docs/contracts/ui-checkout-console.md`,
> handoff `docs/squad/memory/handoffs/08-frontend-para-qa.md`, gate `docs/squad/gates/G2-D2.json`, 88%).
> Ambiente: `docker compose` já em execução, console em `http://localhost:8090/`. Evidências abaixo são
> automatizadas (curl/grep) sempre que possível, mais 2 capturas reais com Chrome headless
> (`zenika/alpine-chrome`, `--network host`, sem necessidade de `host.docker.internal` — a máquina
> alcançou `localhost:8090` diretamente). Legenda: ✅ passou · ⚠️ parcial/validar · ❌ falhou.

| CA | Resultado | Evidência |
|----|-----------|-----------|
| CA1 — Fluxo em 3 passos, passo atual destacado | ✅ | `grep -n aria-current` → `nav#steps` com `<li data-step="1" aria-current="step">` inicial (linha 132) e `setPhase()` movendo o atributo (linha 290); `tests/ui/console-1440.png` mostra o passo "1 Montar pedido" destacado. |
| CA2 — Linha do tempo com texto+ícone, tentativas e compensações; tabela `history[]` recolhível | ✅ | `stepState()` (index.html, função completa) implementa exatamente a tabela §2 do contrato (casos `SUCCEEDED/CREATED/CONFIRMED`→done, `FAILED/CANCELED`→fail, `COMPENSATED`→comp, `TIMED_OUT`+`tentativa N`, `COMPENSATING`→"compensando"). Validado contra `history[]` real de um `payment=DECLINE` pelo proxy: `ORDER/CREATED → INVENTORY/STARTED → INVENTORY/SUCCEEDED → PAYMENT/STARTED → PAYMENT/FAILED(DECLINED) → INVENTORY/COMPENSATING → INVENTORY/COMPENSATED → ORDER/CANCELED(PAYMENT_DECLINED)` (orderId `674b4f97…`) — mapeia para Estoque "Compensada", Pagamento "Falhou", Desfecho cancelado com motivo, conforme esperado. `<details id="det-hist">` recolhível presente. |
| CA3 — Resumo sempre visível, sticky em desktop, campos do contrato | ✅ | `#summary` com ID 8 chars (`slice(0,8)`, linha 485) + botão "Copiar ID completo" (linha 189); CSS `@media (min-width: 901px) { .summary { position: sticky; top: 0 } }` (linha 113). `console-1440.png`: coluna direita "Resumo do pedido" ao lado do formulário. Comportamento de rolagem em si não testado (headless não rola a página) — sticky confirmado só por CSS. |
| CA4 — "O que vai acontecer" por cenário | ✅ | `const EXPLAIN = {...}` cobre `""` (nenhum/feliz), `DECLINE`, `shipping FAIL`, `payment TIMEOUT`, `TIMEOUT_ONCE`, `inventory OUT_OF_STOCK`, `payment SLOW` — uma frase por valor de `simulate` existente + "nenhum", exatamente como exige o CA4. `console-1440.png` mostra a frase do cenário "Nenhum · caminho feliz". |
| CA5 — Feedback < 1s, botão "Enviando…" desabilitado | ✅ | Código: `sending=true; $("#send").disabled=true; $("#send").textContent="Enviando…"` antes do `await api(...)` (linhas 369-370); no `202` mostra `"Pedido aceito — Saga iniciada · <id>"` (linha 391) antes de iniciar o polling. Tempo real < 1s não cronometrado em DevTools (fora do escopo desta rodada), mas a ordem das operações no código garante o requisito. |
| CA6 — Erros claros (400/409, rede/5xx), reaproveita Idempotency-Key | ✅ | Testado ao vivo pelo proxy: `quantity=0` → `400` problem+json com `errors:[{"field":"items[0].quantity","message":"must be greater than or equal to 1"}]`; `GET /orders` sem `customerId` → `400` com `detail` e `errors[{"field":"customerId",...}]`. Código trata `409` (mesma chave/corpo diferente) e rede/`502-504` → "Serviço de pedidos indisponível — tente novamente" com reabilitação do botão (`try/finally`) e reaproveita `lastFailed.key` (linha 367). **Não testado ao vivo**: parar `order-service` de fato (evitado para não afetar a avaliação paralela do Jev) — código revisado, comportamento ⚠️ não observado na tela. |
| CA7 — Polling 1s, para em terminal, aviso após 120s | ⚠️ | Código: `setTimeout` de polling que para em `CONFIRMED`/`CANCELED` (`TERMINAL`) e `#slow` exibido só após 120000ms (linha 534) com link de diagnóstico. Duração real do cenário `TIMEOUT` (~20s) confirmada pela suíte e2e (`timeout_step`, `tests/e2e/last-report.json`, 20s), mas não observada ao vivo no navegador nesta rodada (orçamento de tempo). |
| CA8 — Pedidos do cliente via `GET /orders?customerId=` | ✅ | `curl http://localhost:8090/api/order/orders?customerId=<id>&limit=20` pelo proxy devolve o mesmo array/ordem de `GET /orders?customerId=` direto (`createdAt desc`); `console-1440.png` mostra a lista "Pedidos do cliente c-demo" com status colorido (CANCELADO/CONFIRMADO), R$, tipo de entrega, data/hora e motivo (`pagamento recusado (PAYMENT_DECLINED)`), e nota "Fonte: GET /orders?customerId= (mais recentes primeiro)". |
| CA9 — Acessibilidade (label, foco, teclado, contraste, aria-live, lang) | ⚠️ | `grep`: `<label for="customer/sku/qty/delivery/fault">` (5/5); `:focus-visible{outline:2px solid var(--accent)}`; `lang="pt-BR"`; `aria-live="polite"` em `#form-msg`/`#track`, `aria-live="off"` nas subregiões (ticker/tabela/curl); contraste `--dim #626368` = 5.99:1 e 5.54:1 (≥4.5:1, calculado pelo Frontend no G2, não recalculado aqui). **Navegação só-teclado não testada interativamente** (headless não simula Tab/Enter) — item permanece ⚠️ "não verificado interativamente", só por inspeção de código. |
| CA10 — Responsivo a 390px, coluna única, ordem correta, alvos ≥44px | ✅ | Chrome headless real, `--window-size=390,844` → `tests/ui/console-390.png`: coluna única, sem indício de rolagem horizontal, ordem visível = passos (empilhados 1/2/3) → formulário "Novo pedido"; `min-height: 44px` em inputs/selects/botões/itens de lista (`grep -n "min-height: *44px"`, 7 ocorrências) e `@media (max-width: 900px)` reorganiza o layout em coluna. Resumo/timeline/pedidos ficam abaixo da dobra (não capturados na screenshot de viewport, mas a ordem de DOM A→B→C→D→E é a mesma do desktop). |
| CA11 — Sem libs externas além de Google Fonts | ✅ | `grep -n "<script src"` → vazio; únicos hosts externos: `fonts.googleapis.com`, `fonts.gstatic.com` (`grep -noE 'https?://...'`); HTML/CSS/JS num único `index.html` (620 linhas), sem build. |
| CA12 — Corpo do `POST /orders` idêntico (regras preservadas) | ✅ | `buildBody()` monta `{customerId, deliveryType, items:[{sku,quantity,unitPrice}], shippingAddress, simulate}` — mesmos campos usados nos `curl` de `tests/e2e/scenarios.md`; testado ao vivo pelo proxy com pedido `PHYSICAL` feliz e `payment=DECLINE`: `GET /orders/{id}` pelo proxy bateu com `GET /orders/{id}` direto no `order-service` (mesmo `status`); nenhuma chamada fora de `api.md` (`grep` em `api()`: só `order/orders`, `order/orders/{id}`, `order/orders?customerId=&limit=`, `inventory/inventory/stock/{sku}`, `saga/sagas` para diagnóstico). Equivalência byte-a-byte com a versão anterior aceita por evidência do Frontend/G2 (diff vazio vs `HEAD~1`), não recomputada aqui. |

## Fluxo funcional pelo proxy (item 2 da tarefa)

- `POST http://localhost:8090/api/order/orders` (PHYSICAL, feliz) → `202`; `GET http://localhost:8090/api/order/orders/{id}` → `CONFIRMED`, igual ao `GET http://localhost:8081/orders/{id}` direto.
- `POST .../orders` com `simulate={"payment":"DECLINE"}` → `202`; `GET .../orders/{id}` → `CANCELED`/`PAYMENT_DECLINED`, `history[]` com a cadeia de compensação completa (ver CA2 acima).
- `GET http://localhost:8090/api/order/orders?customerId=<id>&limit=20` → array `200`, mesmo formato do D1.
- Confirmado via `grep -n "api("` que a tela só chama `GET order/orders/{id}` e `GET order/orders?customerId=` (além de `POST order/orders` e `GET inventory/inventory/stock/{sku}`) — nenhum endpoint fora de `api.md`.

## Defeitos encontrados

Nenhum defeito real encontrado nesta rodada. Os dois pontos abertos no `G2-D2.json` (`limit=20` fixo na
lista do cliente — dentro do range 1–200 do contrato — e ausência do bloco curl/cenário em pedido aberto
pela lista) são limitações aceitas, não bloqueantes, já registradas pelo Frontend/Auditor.

## Itens não verificados nesta rodada (para o Auditor decidir se bloqueiam o G3)

- CA6: mensagem de indisponibilidade com `order-service` realmente parado (só revisão de código).
- CA7: comportamento visual do "A Saga está demorando" após 120s (lógica revisada, não observada).
- CA9: navegação só-teclado (Tab/Enter/Espaço) de ponta a ponta.
