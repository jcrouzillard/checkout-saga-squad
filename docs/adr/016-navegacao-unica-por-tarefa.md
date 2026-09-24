# ADR-016: Navegação única por tarefa, com a demanda como página central e rotas por hash

**Status**: Aceito (2026-09-24, Arquiteto — D13 `efe387a35d71`)

## Contexto
O Squad Control cresceu por incrementos (D3–D11) e hoje tem **dois menus sobrepostos** (abas no topo + menu lateral
de 7 itens), indicação de local contraditória, estado fora da URL (F5/Voltar perdem a tela) e o ciclo de uma demanda
espalhado por quatro telas (Demandas, Execuções, Evidências, Decisões) sem links entre elas. Execuções só mostra a
última demanda ativa. O humano pediu (D13) funcionalidades agrupadas, navegação fluida e "uma coisa levando a outra",
podendo reagrupar/renomear/remover telas sem perder funcionalidade.

## Decisão
1. **Um único menu primário** com 5 itens orientados a tarefa: Painel (inicial), Demandas, Squad, Auditoria, Produto.
   As abas do topo são removidas; Decisões/Evidências/Políticas viram abas locais de Auditoria; Agentes vira Squad;
   Observabilidade vira Produto; Execuções deixa de ser tela própria.
2. **A demanda é o objeto central** (OOUX): cada demanda tem página própria (`#/demandas/<Dn>`) com etapas, uma
   "Próxima ação", execução, gates, validação e registro. O Painel agrega "Precisa de você" com a mesma regra.
3. **Rotas por hash** no cliente (`#/…`, com seção e filtros), JS puro com `hashchange`, aliases para os nomes antigos.
   A URL é a fonte do estado de navegação (deep link, F5, Voltar).
4. Notificações e toasts apontam para o **item** (demanda/seção), não para uma tela.
5. Nenhuma mudança de API ou de regra de estado; tudo é derivado de `/api/state`. Detalhes em
   [`docs/contracts/ui-navegacao-squad-control.md`](../contracts/ui-navegacao-squad-control.md).

## Consequências
- (+) Menos opções no primeiro nível (Hick), local sempre inequívoco, links compartilháveis, jornada contínua de
  demanda → execução → gate → PR; demandas paralelas passam a ter tela de execução.
- (+) Corrige a decisão humana enviada ao gate global em vez do gate exibido.
- (−) Scripts de QA que clicam em `nav a[data-view]`/`.tabs` precisam ser atualizados.
- (−) `index.html` ganha um roteador simples e a página da demanda; o redesenho do polling precisa preservar seção,
  rolagem e `details` abertos.

## Alternativas
- **Manter abas + lateral e só renomear**: não resolve a duplicidade nem a falta de links entre telas.
- **Abas por etapa do ciclo (Validação, Execução, Revisão…)**: fragmenta a demanda de novo em várias telas.
- **Rotas por `pushState` (caminhos reais)**: exigiria o servidor devolver `index.html` para qualquer caminho
  (mudança em `tools/squad/**`); o hash atende sem servidor.
- **Biblioteca de roteamento/framework**: viola "sem dependências novas" e é desnecessária para 5 telas.
