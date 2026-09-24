# Checklist D15 — Ambiente de teste compartilhado (518f89f27ae8)

Contrato: `docs/contracts/ambiente-de-teste.md` §9. Branch `feature/D15-ambiente-de-teste`.
Nada foi subido, parado, recriado, construído ou apagado pelo QA: todo o Docker é **falso** nos testes, e as provas
reais são só leitura (`docker ps`, `docker compose -p checkout-saga config --hash`, `testenv.py prod-fingerprint`).

Legenda: **OK** = verificado com teste automatizado/leitura real · **A VALIDAR (humano)** = exige subir o
`checkout-teste` de verdade, só com autorização humana explícita, sempre entre dois
`bash tests/squad/prova_produtivo_intacto.sh` (antes / `--compare` depois).

| CA | Critério | Situação | Evidência |
|----|----------|----------|-----------|
| CA1 | compose parametrizado não muda o produtivo | OK | `tests/squad/prova_produtivo_intacto.sh`: `config --hash '*'` da branch (com `.env` da cópia principal) == da cópia principal, 11 serviços, e == `com.docker.compose.config-hash` dos 11 containers em execução |
| CA2 | regra forte de portas | OK | `TestGuard.test_config_real_do_teste_passa`, `test_portas_adulteradas_recusadas_sem_up`, `test_portas_ocupadas_no_host_e_por_outro_projeto_R8`; `testenv.py check-ports` real (G2) |
| CA3 | isolamento total (rede, volume, imagens, dados, traces) | parcial: OK no config / A VALIDAR (humano) no ar | `test_imagens_so_das_5_de_aplicacao_R1`, `test_down_sem_v_e_comandos_sempre_com_projeto_de_teste`; pedido/trace cruzado exige o teste no ar |
| CA4 | produtivo intocado por todo o ciclo | OK nesta rodada / A VALIDAR (humano) no ciclo real | `prova_produtivo_intacto.sh` antes e depois das 5 suítes: digest `b80841ef7cc18130` idêntico, `identical: true`, `diff: []` |
| CA5 | publicar só por pedido do humano | OK | `test_publish_sem_pedido_do_humano_CA5`, `test_409_sem_pr_aberto`, `test_formato_api_e_http` (409) |
| CA6 | pronto para testar (saúde real 18080-18084/18090, página) | A VALIDAR (humano) | lógica coberta por `test_publicar_fila_liberar_e_proximo` (docker falso) |
| CA7 | fila sem recriar containers | A VALIDAR (humano) | lógica: `test_publicar_fila_liberar_e_proximo` (nenhum `docker compose` para o 2º pedido) |
| CA8 | pedido obsoleto sai da fila | A VALIDAR (humano) | lógica: `test_pedido_obsoleto_sai_da_fila_CA8` |
| CA9 | dados persistem após republicação | A VALIDAR (humano) | lógica: republicação usa `up`, nunca `down -v` (`test_zz`/CA16 e `test_down_sem_v...`) |
| CA10 | apagar dados só com APAGAR | A VALIDAR (humano) no volume real | `test_reset_so_com_APAGAR`, `TestQaLock.test_reset_data_com_lock_tomado`, API 400 sem/errado `confirm` |
| CA11 | desatualizado e republicar sem fila | OK | `test_republicar_desatualizado_nao_passa_pela_fila_CA11` |
| CA12 | entregue libera o teste | OK | `test_publicar_fila_liberar_e_proximo` (`released reason=delivered`) |
| CA13 | produtivo atualizado só no alterado | OK (simulado) / A VALIDAR (humano) real | `TestProd.test_so_o_servico_alterado_CA13` |
| CA14 | merge sem código não reinicia nada | OK | `TestProd.test_so_docs_nada_CA14` |
| CA15 | rollback | OK (simulado) / A VALIDAR (humano) real | `test_rollback_CA15`, `test_migracao_sem_rollback_B5_R4` |
| CA16 | nada destrutivo no produtivo | OK | `test_zz_CA16_nenhum_comando_destrutivo`; e2e: `test_e2e_compose_seguro_d15.py` (todo compose com `-p`, `kill`+`start`, sem `up/down/rm`) |
| CA17 | e2e no teste não toca o produtivo | OK (docker falso) / A VALIDAR (humano) `make e2e-teste` real | `test_e2e_compose_seguro_d15.py`: `run.sh` real com `E2E_COMPOSE_PROJECT=checkout-teste` gera só `compose -p checkout-teste --env-file infra/teste/teste.env kill|start saga-orchestrator` e nunca `checkout-saga`; local sem `E2E_ALLOW_PROD` → SKIP sem docker nem POST |
| CA18 | log só com acréscimos | OK | `test_formato_api_e_http` (`/api/state` antigo válido), `test_alertas_d14` (20 OK) |

## Extras do G2 (prioridade 2)
- `down`/`reset-data`/`publish`/`release` com o lock tomado → saem 3, nenhum `docker compose`; o `reset-data`
  fica pendente e roda no próximo `reconcile` (`TestQaLock`).
- `cancel` pela API → 202 + spawn `reconcile`; repetido → 202 `duplicate`; demanda inexistente 404 (`TestQaCancelApi`).
- `gitflow.after_review`: `prod.py update --auto` só com delivered + develop + `SQUAD_PROD_AUTOUPDATE != 0`,
  e antes do `reconcile` (`TestQaAfterReview`). Defeito `f6ed87f48c62` (`IndexError` no `print` final)
  **CORRIGIDO** pelo Orquestrador (`" ".join(c[2:])`); `test_defeito_print_nao_quebra` agora é teste de regressão e passa.

## Roteiro para a validação humana (CA3, CA6–CA10, CA13/CA15 reais, CA17)
1. `bash tests/squad/prova_produtivo_intacto.sh /tmp/fp-antes.json`
2. Publicar pelo Squad Control, conferir CA6/CA7/CA8/CA9/CA10, rodar `make e2e-teste` (CA17).
3. `bash tests/squad/prova_produtivo_intacto.sh /tmp/fp-depois.json --compare /tmp/fp-antes.json` → `RESULTADO: produtivo intacto`.
