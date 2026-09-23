# Desafio (texto extraído do PDF original)

```text
                                                                                     Desafio Técnico | Checkout Saga com Squad Agêntica



                                Desafio Técnico Sênior
    Checkout Distribuído com Saga e Squad Agêntica Autônoma
    Objetivo do desafio
    Avaliar arquitetura distribuída, consistência por Saga, tratamento de falhas, observabilidade, containerização e uso prático de
    agentes de IA orquestrados entre si para construção autônoma do projeto por uma squad agêntica.



1. Contexto
Um e-commerce precisa processar pedidos envolvendo os domínios de Pedido, Estoque, Pagamento e Envio. O
processamento deve ser conduzido por uma arquitetura baseada em Saga, garantindo consistência entre os
serviços participantes.
Além da implementação da solução, espera-se que o projeto seja construído por uma squad agêntica de IA,
composta por múltiplos agentes especializados que atuem de forma coordenada para projetar, implementar, validar
e evoluir a solução.
•      Projetar arquiteturas distribuídas.
•      Implementar mecanismos de consistência distribuída.
•      Tratar falhas e cenários de recuperação.
•      Definir uma estratégia de observabilidade.
•      Utilizar IA Generativa de forma avançada através de uma squad agêntica.
•      Demonstrar governança e orquestração de agentes especializados.



2. Problema de negócio
O fluxo esperado para o checkout é:
1.     Cliente realiza POST /orders.
2.     Pedido é criado.
3.     Estoque é reservado.
4.     Pagamento é autorizado.
5.     Envio é gerado quando aplicável.
6.     Pedido é confirmado ou cancelado.

Posteriormente, o cliente deve conseguir consultar o status atualizado através de GET /orders/{orderId}.



3. Requisitos funcionais obrigatórios
•      Criar pedido.
•      Reservar estoque.
•      Autorizar pagamento.
•      Gerar envio quando aplicável.
•      Confirmar pedido.
•      Cancelar pedido.
•      Consultar status do pedido.




                                                          Corporativo | Interno
                                                                                  Desafio Técnico | Checkout Saga com Squad Agêntica

4. APIs disponíveis
Domínio                      Operações esperadas
Pedido                       POST /orders; GET /orders/{orderId}
Estoque                      reserve; release
Pagamento                    authorize; refund
Envio                        solicitar entrega do pedido; explicar o que acontece caso dê erro na solicitação de entrega do pedido




5. Eventos de domínio
•      order.created
•      inventory.reserved
•      payment.authorized
•      shipment.created
•      order.confirmed
•      order.canceled

    Expectativa
    O candidato pode utilizar mensageria real ou simular sua implementação localmente, desde que a arquitetura demonstre
    claramente a publicação e o consumo de eventos.




6. Requisitos não funcionais obrigatórios
•      Idempotência.
•      Retries.
•      Timeouts.
•      Recuperação após falhas.
•      Rastreabilidade ponta a ponta.
•      Publicação de eventos.

Esses requisitos devem estar descritos no desenho arquitetural e evidenciados na implementação.



7. Cenários de falha obrigatórios
•      Falha no pagamento.
•      Falha no envio.
•      Timeout em qualquer etapa.
•      Reinício inesperado do coordenador da Saga.

Explique quais mecanismos permitem a continuidade da operação e quais compensações serão executadas em
cada cenário.



8. Squad agêntica obrigatória
Além da solução técnica, o candidato deverá projetar e demonstrar uma squad agêntica responsável pela
construção autônoma do projeto. A squad deve possuir agentes especializados com papéis claramente definidos.
    Agente                             Responsabilidades esperadas
    Agente Arquiteto                   Arquitetura da solução; bounded contexts; estratégia Saga; modelagem dos eventos.


                                                        Corporativo | Interno
                                                                            Desafio Técnico | Checkout Saga com Squad Agêntica

    Agente Desenvolvedor Backend   Implementação dos serviços; APIs; mensageria; persistência.
    Agente DevOps                  Dockerfiles; Docker Compose; infraestrutura local; pipelines.
    Agente QA                      Testes automatizados; testes de integração; testes dos fluxos de falha.
    Agente Observabilidade         Logs; traces; métricas; dashboards.
                                   Delegação das atividades; coordenação entre agentes; consolidação dos artefatos;
    Orquestrador da Squad
                                   controle do fluxo de execução.


O candidato pode propor outros agentes além dos listados, desde que justifique seu papel e sua interação com o
restante da squad.
Espera-se que o candidato demonstre essa habilidade independente do modelo utilizado no case, dado que a
empresa pode optar por usar determinado fornecedor agêntico de acordo com a estratégia.



9. Sugestão de Ferramentas de IA para utilizar no case
É esperado o uso de uma ou mais das seguintes IAs:
•     Microsoft Copilot.
•     Devin.
•     Claude Code.

Além do uso das ferramentas, o candidato deve explicar:
•     Como os agentes foram estruturados.
•     Como ocorre a comunicação entre eles.
•     Como ocorre a passagem de contexto.
•     Como o conhecimento compartilhado é armazenado.
•     Como conflitos são resolvidos.
•     Como evitar decisões conflitantes ou divergentes.



10. Desenho arquitetural esperado
Visão                                  Elementos obrigatórios
Arquitetura de negócio                 Pedido, Estoque, Pagamento, Envio e Saga.
Arquitetura técnica                    APIs, banco(s), broker de mensagens, containers e observabilidade.
                                       Agentes, fluxos de delegação, orquestrador, memória compartilhada, ferramentas
Arquitetura agêntica
                                       utilizadas e limites de autonomia.




11. Containerização
A solução deve ser entregue containerizada e deve existir uma forma única de iniciar o ambiente, como Docker
Compose ou equivalente funcional.
•     Todos os componentes necessários para execução local devem estar disponíveis via containers.
•     O candidato pode optar por monólito modular ou múltiplos serviços, desde que justifique tecnicamente a
      decisão.
•     Devem ser entregues Dockerfile(s), docker-compose.yml e README de execução.




                                                   Corporativo | Interno
                                                                                  Desafio Técnico | Checkout Saga com Squad Agêntica

Entrevistador


12. Pergunta arquitetural obrigatória
    Pergunta para resposta do candidato
    Caso sua solução seja inicialmente executada em um único container, o que seria necessário para evoluir para uma
    arquitetura totalmente distribuída executando cada componente em containers independentes?


•      Banco de dados.
•      Descoberta de serviços.
•      Comunicação síncrona.
•      Comunicação assíncrona.
•      Observabilidade.
•      Escalabilidade.
•      Resiliência.



13. O que esperamos avaliar
•      Arquitetura completa.
•      Modelo de persistência.
•      Estratégia de consistência.
•      Tratamento de falhas.
•      Observabilidade.
•      Compensações de negócio.
•      Uso avançado de IA na engenharia de software.
•      Governança de agentes.
•      Colaboração humano + IA.
•      Arquiteturas agênticas escaláveis.



14. Entregáveis obrigatórios
Categoria                        Entregáveis
Código-fonte                     Código completo da solução, APIs, serviços e testes.
                                 Dockerfile(s), docker-compose.yml, scripts de provisionamento e configurações de
Infraestrutura
                                 observabilidade.
Arquitetura                      Diagramas da solução, da Saga e da squad agêntica.
                                 Prompt principal, objetivo, responsabilidades, ferramentas, entradas e saídas, regras de decisão
Agentes de IA
                                 e fluxo de interação com os demais agentes.
                                 Histórico ou registros de execução dos agentes, decisões arquiteturais tomadas e resultados
Evidências
                                 produzidos por cada agente.
                                 README com visão geral, arquitetura, como executar, como testar, como reproduzir cenários de
Documento técnico
                                 falha e como a squad agêntica opera.




15. Critérios de diferenciação
•      Uso de MCP Servers.
•      Multi-Agent Systems.
•      Memory Layer.

                                                        Corporativo | Interno
                                                                        Desafio Técnico | Checkout Saga com Squad Agêntica

•   Event Driven Agents.
•   Agent-to-Agent Protocols.
•   OpenTelemetry.
•   GitHub Copilot Coding Agent.
•   Claude Code Workflows.
•   Devin Autonomous Sessions.
•   Avaliação automática de qualidade gerada pelos agentes.
•   Auto-correção e auto-recuperação da squad.



16. Observações finais para o candidato
O foco do desafio não é apenas entregar código funcional. Também será avaliada a clareza das decisões, a
rastreabilidade entre requisitos e implementação, o tratamento de falhas e a capacidade de organizar um processo
de construção com agentes de IA de forma autônoma, controlada e auditável.




                                                Corporativo | Interno
```
