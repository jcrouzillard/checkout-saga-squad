# ADR-019: Demandas de bug — natureza ortogonal ao tipo, evidências mascaradas no git e reprodução antes da correção

**Status**: Proposto (2026-09-24, Arquiteto — D16 `841f9a27e64a`)
**Numeração**: 015 reservado para a D12 (PR aberto); 016–018 são D13–D15. Este é o próximo livre.
**Contrato**: [`docs/contracts/demandas-de-bug.md`](../contracts/demandas-de-bug.md).

## Contexto
O humano quer registrar **bugs** do produto e da operação, com anexos (só **logs e imagens**), guardados em
`docs/squad/<produto|operacao>/bugs` (no git; futuramente um NoSQL), podendo **gerar o bug a partir de um link** de
trace do Jaeger ou de painel/alerta do Grafana. Bug é **só do produtivo**; a única coisa obrigatória é a evidência;
o **QA escreve um teste que falha** antes da correção; os demais gates não mudam; e nada do que existe pode quebrar
(`kind` produto|operacao e sua validação).

Fatos verificados:
- `kind ∈ {produto, operacao}` é validado em `server.py` (criar e editar), `log.py --kind`, `triage.py`
  (`suggestedKind`), `github_sync.py` (`tipo:*` com troca exclusiva) e na UI (`KINDS`).
- O repositório `jcrouzillard/checkout-saga-squad` é **público**: tudo que entra no git fica público e no histórico.
- O teste (ADR-018) tem Jaeger/Grafana próprios em portas +10 000 e rede isolada; o Jaeger produtivo (`:16686`) só
  recebe traces do produtivo. Traces reais trazem `client.address`, `user_agent.original`, `network.peer.*`.
- O Grafana produtivo (`:3001`, acesso anônimo) **não tem regras de alerta** hoje; tem o dashboard `checkout-saga`.
- `gitflow.py` só auto-commita `docs/squad/memory/` e `docs/squad/inbox/`; o resto trava `clean_tree`.
- `gitflow.py` aplica o bloqueio "merge sem G3" e a revisão/atualização do produtivo somente a `feature/*`.

## Decisão
1. **Natureza ortogonal ao tipo**: campo novo `nature: "bug"` no evento `task` (ausente ≡ demanda comum) + objeto
   `bug` só com metadados. `kind` fica como está. Um bug é "bug de produto" ou "bug de operação".
2. **Evidências no git** em `docs/squad/<kind>/bugs/<demandId>/` (`bug.json` + `evidencias/`) e `index.jsonl`
   append-only; `gitflow.py` inclui essas pastas no `STATE`. Gravação atrás de uma interface `BugStore` para a futura
   troca por NoSQL. Nenhum byte no log.
3. **Duas etapas**: rascunho fora do git (`.squad/bug-drafts/`, validado e **mascarado** no servidor) → prévia →
   confirmação explícita do humano (produtivo + público/permanente) → gravação.
4. **Criar a partir de link** sem seguir a URL: o servidor extrai só o id (trace, painel, regra) e consulta as URLs
   fixas do produtivo; snapshot de trace por **allowlist** de atributos; logs dos containers do trace por
   `docker compose -p checkout-saga logs` (somente leitura), filtrados por `trace_id`.
5. **"Só produtivo" verificável**: porta/host do produtivo + existência do trace/painel/regra no produtivo;
   links do teste recusados; sem link, declaração do humano registrada em `verifiedBy`.
6. **Fluxo**: QA escreve e commita o teste que falha (red) → Arquiteto registra causa raiz e solução em
   `docs/architecture/bugs/D<n>.md` → G1 → correção (green) → G2/G3 iguais, com checagem red→green pelo Auditor.
   Branch `feature/<código>-bug-<slug>` da `develop`; `hotfix/*` só para defeito em versão publicada na `main`.
7. **GitHub**: label `tipo:bug` somada a `tipo:<kind>` (não entra na troca exclusiva).

## Consequências
- (+) Zero migração: eventos, rotas, labels e validações antigos inalterados; tudo é campo/rota/tipo novo.
- (+) Evidência versionada junto da demanda, legível por qualquer agente sem token (diferente do ADR-015).
- (+) Bug reproduzido por teste automatizado antes da correção vira regressão permanente.
- (−) Logs/imagens ficam **públicos e permanentes**; a máscara é por padrão (pode falhar em formatos novos) e imagens
  não são varridas — mitigado pela prévia e confirmação humana, limites pequenos e remoção de metadados.
- (−) O repositório cresce: limites por arquivo/bug e teto global de 200 MB até a migração para NoSQL.
- (−) Bug de operação e bug sem link dependem da declaração humana de "produtivo".

## Relação com o ADR-015 (D12)
O ADR-015 guarda evidências genéricas **só na issue** (nada no git, R3 da D12). Aqui o humano escolheu **o git** para
evidências de bug. As duas decisões convivem por finalidade (genérica × falha no produtivo) e compartilham as regras
de validação num módulo único (`tools/squad/evidence_rules.py`). Diferença deliberada: o ADR-015 **bloqueia** texto com
segredo; aqui logs são **mascarados** (a evidência é obrigatória e logs costumam conter tokens), com prévia ao humano.

## Alternativas
| Alternativa | Por que não |
|---|---|
| `kind: "bug"` | quebra a validação de tipo em 5 lugares e perde produto × operação (resposta 5) |
| `bug: true` | funciona, mas não evolui (ex. incidente) sem outro booleano |
| Evidências na issue (ADR-015) | contraria a resposta 2 (pasta no git) |
| Evidências fora do git (`~/.squad`) | não versiona nem é visível a outros agentes/máquinas; contraria a resposta 2 |
| Bloquear log com segredo | inviabilizaria registrar o bug, cuja evidência obrigatória é o próprio log |
| Branch `bugfix/*` | exigiria mudar o AGENTS.md e o `gitflow.py` (guard G3, revisão, `prod.py`) sem ganho |
| Seguir a URL colada | SSRF e sem garantia de produtivo |
