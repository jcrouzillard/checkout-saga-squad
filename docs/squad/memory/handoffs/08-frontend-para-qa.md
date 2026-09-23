# Handoff 08 — Frontend → QA (D2 `48b6ace91207`, gate G2)

## O que mudou
`checkout-console/index.html` reescrito conforme `docs/contracts/ui-checkout-console.md` (ADR-007). `nginx.conf` intacto.
Nenhuma chamada nova: `POST /orders`, `GET /orders/{id}`, `GET /orders?customerId=`, `GET /inventory/stock/{sku}`, link `GET /sagas/{id}`.
Ressalvas do G1 tratadas: (1) "Pedido criado" lê só `ORDER/CREATED` e "Desfecho" só `ORDER/CONFIRMED|CANCELED` (`recordsFor`);
(2) total vem de `totalAmount` (antes do 1º GET mostra "aguardando o serviço"); (3) `try/finally` reabilita o botão em qualquer
erro, `api()` nunca lança; (4) `aria-live="polite"` em `#track` (resumo + linha do tempo; ticker/tabela/curl com `aria-live="off"`);
(5) frase "O que vai acontecer" (`#fault-explain`) para cada valor de `simulate` e para "nenhum".

## Mapa CA → onde na tela
| CA | Onde / como |
|----|-------------|
| CA1 | `nav#steps`: 1 Montar (edição) → 2 Enviar (POST em voo) → 3 Acompanhar; `aria-current="step"` |
| CA2 | `ol#timeline` (5 etapas, ícone + texto, "tentativa N", "compensando", nota com `detail`); `details#det-hist` com `history[]` |
| CA3 | `section#summary` (sticky ≥ 901 px): ID 8 chars + "Copiar ID completo", status + motivo, itens SKU × qtd, total, entrega, rastreio |
| CA4 | `#fault-explain`, atualiza no `change` do cenário (tabela `EXPLAIN`) |
| CA5 | 202 → `#form-msg` "Pedido aceito — Saga iniciada · <id>" e resumo aberto sem esperar poll; botão "Enviando…" desabilitado |
| CA6 | 400/409: `detail` + `errors[]` junto do campo (`#<campo>-err`, `aria-describedby`, `aria-invalid`, foco); rede/502-504: "Serviço de pedidos indisponível — tente novamente"; mesma chave reaproveitada se o corpo for igual (`lastFailed`) |
| CA7 | `setTimeout` 1 s, para em terminal; `#ticker` "atualizado há N s"; `#slow` após 120 s com link de diagnóstico |
| CA8 | `ul#recent` com botões (Enter/Espaço), status texto+cor, R$, entrega, data/hora, motivo; vazio → "Este cliente ainda não tem pedidos."; atualiza ao fim de cada saga |
| CA9 | `<label for>` em todos os campos; `:focus-visible` 2px `#1F3A5F`; `--dim` escurecido p/ #626368 (≥ 4.5:1); `lang="pt-BR"` |
| CA10 | ≤ 900 px: coluna única na ordem passos → form → resumo → timeline → pedidos; controles `min-height: 44px` |
| CA11 | Só Google Fonts; sem `<script src>`; fallback de fontes do sistema |
| CA12 | `buildBody()` com as mesmas linhas da versão anterior (md5 idêntico vs `HEAD`); `<form novalidate>` para o 400 vir da API |

## Validação feita
- `curl localhost:8090/` = 200 após `docker compose restart checkout-console`.
- Pelo proxy: feliz DIGITAL → CONFIRMED; `payment=DECLINE` → CANCELED/PAYMENT_DECLINED; `shipping=FAIL` e `TIMEOUT_ONCE` também;
  `GET /orders?customerId=c-demo` e `GET /inventory/stock/{sku}` OK; `quantity=0` → 400 com `errors[items[0].quantity]`.
- Sintaxe do JS verificada com JavaScriptCore (`osascript -l JavaScript`, `new Function`); `stepState` testado com os
  `history[]` reais de DECLINE, FAIL e TIMEOUT_ONCE (resultado igual à tabela §2).

## Limitações / para o QA verificar
- Sem teste em navegador real feito por mim (CA3 sticky, CA9 teclado/contraste, CA10 390 px são manuais).
- Pedido aberto pela lista não tem bloco curl (o corpo original não é exposto pela API) e não mostra o cenário.
- `REASONS` traduz motivos conhecidos; os desconhecidos aparecem como vieram da API.
