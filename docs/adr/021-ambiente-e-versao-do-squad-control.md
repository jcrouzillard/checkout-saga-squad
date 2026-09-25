# ADR-021: Ambiente e versão do próprio Squad Control, sempre visíveis no rodapé do menu

**Status**: Proposto (2026-09-24, Arquiteto — D18 `b72a6bd8caf3`)
**Numeração**: 020 fica reservado para a D17 (em paralelo). Este é o próximo livre.
**Contrato**: [`docs/contracts/ui-ambiente-e-versao.md`](../contracts/ui-ambiente-e-versao.md).

## Contexto
O humano quer ver **em que ambiente o Squad Control está rodando** e **qual versão está no ar**, sempre visível
(sugestão: rodapé do menu à esquerda). Respostas (`e7df6310d4b6`): (1) só o ambiente **do próprio Squad Control**,
não os do checkout (o Painel já tem o cartão "Ambientes" da D15), lembrando que o Squad Control tem **teste apartado**;
(2) versão = **combinação** de última tag de release, versão do `pom.xml` e commit; (3) sempre visível.

Fatos verificados (2026-09-24):
- Rodam hoje 3 instâncias de `tools/squad/server.py`: a da cópia principal `plankton/` (`develop`, porta padrão 7070,
  `make squad`) e duas de validação a partir do worktree `plankton-d16` (portas 7170 e 7128), uma com
  `SQUAD_ROOT_DATA` apontando para **dados sintéticos** e outra para a **cópia principal**. Nada as distingue na tela.
- Não existe `SQUAD_ENV` nem convenção de porta para o teste do Squad Control; `plankton-teste/` é o worktree do
  **checkout** de teste (ADR-018), não roda Squad Control.
- O servidor **não recarrega** Python, mas serve `squad-control/` **do disco** a cada pedido: depois de um merge, a
  tela pode ser nova e a API antiga — já causou confusão.
- `git describe --tags` **falha** em `develop`: `v1.0.0` (`d63f7d6`) não é ancestral de `develop`. A tag tem de ser
  lida por ordenação de versão (`git tag --sort=-v:refname`), não por alcance.
- A cópia principal recebe commits frequentes que **só mexem na memória** ("Sincronização da memória da squad") e fica
  com `docs/squad/memory/github-sync.json` modificado quase sempre; comparar o HEAD inteiro marcaria "desatualizado"
  e "sujo" o tempo todo.
- `/api/state.version` e `/api/live.version` já existem e significam **versão dos dados** (D14/ADR-017).

## Decisão
1. **Ambiente** = `produtivo` | `teste` | `desconhecido`, por regra determinística: `SQUAD_ENV` (se válida) vence;
   senão, `produtivo` somente se o código roda da cópia principal (worktree em `develop`, mesma resolução de
   `testenv.main_root()`), na porta 7070 e com dados da própria cópia; qualquer outra instância é `teste`; sem git e
   sem `SQUAD_ENV` → `desconhecido`. O selo mostra também **de onde vêm os dados** quando o teste usa os da cópia
   principal (risco de gravar no log real).
2. **Versão** = `<tag> · <pom> · <sha7>` (ex.: `v1.0.0 · 1.1.0-SNAPSHOT · 91e3a64`), calculada **uma vez, na subida**
   do servidor. Estados derivados: **alterações locais** (árvore suja só em `tools/squad/` e `squad-control/`) e
   **desatualizado — reinicie** (o código dessas pastas no HEAD atual difere do que subiu). Verificação do HEAD com
   cache de 30 s, fora do `/api/live`.
3. **API**: objeto novo `instance` em `/api/state` e rota `GET /api/instance`. O nome `version` **não** é reutilizado.
   Só acréscimo; `/api/live` não muda (orçamento de 300 ms e 64 KB do ADR-017).
4. **UI**: selo fixo no **rodapé do menu** (≥ 900 px, grudado no fim da coluna); abaixo de 900 px, selo compacto no
   cabeçalho, junto à marca. Texto sempre (nunca só cor), detalhe completo ao abrir o selo. Tema Grafite (ADR-017),
   menu único (ADR-016).

## Consequências
- O humano distingue produtivo × teste de relance e sabe quando precisa reiniciar após um merge.
- Custo: ~5 chamadas `git` na subida e no máximo 1 (`git diff --quiet`) a cada 30 s, sob demanda.
- Uma instância de teste deixa de parecer o produtivo; subir o teste passa a exigir nada (inferência) ou `SQUAD_ENV`.

## Alternativas rejeitadas
- **`git describe`**: falha em `develop` hoje (tag fora da história).
- **HEAD inteiro para "desatualizado"**: falso positivo a cada sincronização da memória.
- **Campo no `/api/live`**: roda a cada 1,5 s; o dado muda raramente.
- **Ambiente por porta apenas**: 7070 pode ser usada por um worktree; a origem do código é o que importa.
- **Mostrar os ambientes do checkout**: fora do pedido (resposta 1); já existe o cartão da D15.
