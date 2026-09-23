# ADR-008: Tipo de demanda e validação agêntica antes do início

**Status**: Aceito (2026-09-23, Arquiteto) — demanda D4 (`1cc732c62a2d`). Contrato: `docs/contracts/ui-demandas-v2.md`.

## Contexto
Demandas chegam vagas (D2, D3) e o Arquiteto só descobre as lacunas depois que a demanda foi iniciada, consumindo
tempo da squad. Além disso, não há distinção entre mudar o **produto** (checkout) e mudar a **fábrica** (Squad
Control, protocolo), o que define donos, gates e riscos diferentes.

## Decisão
1. Campo obrigatório `kind: produto | operacao` no registro; usado no roteamento do plantão e exibido no card/issue.
2. Validação agêntica **entre registrar e iniciar**, assíncrona e orientada a eventos: `pending.py` detecta demanda
   sem `validation`, o vigia do Orquestrador delega ao **Arquiteto em modo triagem** (prompt próprio, somente leitura),
   que registra `validation {status: ok|perguntas, questions[]}`; o humano responde com `clarification`.
3. **Não** criar um papel novo de Analista: esclarecer requisitos e escrever critérios já é responsabilidade do
   Arquiteto (o plantão já envia "critérios vagos → Arquiteto"); um papel novo exigiria definição, dono e gate
   próprios sem ganho real. O modo triagem se distingue por prompt, escopo somente leitura e saída única.
4. Uma rodada de perguntas; início liberado por `ok`, respostas ou override humano explícito com nota — regra
   aplicada no servidor, não só na UI.
5. Demandas anteriores à D4 (sem `kind`) seguem o fluxo antigo.

## Consequências
- (+) Lacunas descobertas em < 1 min, antes de gastar execução da squad; perguntas e respostas ficam auditáveis no log e na issue.
- (+) Roteamento explícito produto × operação.
- (+) O humano mantém o controle (override), coerente com os limites de autonomia.
- (−) Um passo a mais antes de iniciar; custo de uma execução curta de agente por demanda.
- (−) Depende do vigia ativo; mitigado com "Validação atrasada" + override após 3 min.

## Alternativas consideradas
- **Validação síncrona no `POST /api/demand`** (servidor chama o agente): bloqueia a requisição por dezenas de segundos e acopla o servidor ao fornecedor de IA.
- **Papel novo "Analista de demandas"**: mais separação, porém mais governança para uma tarefa que o Arquiteto já faz.
- **Validação por regras fixas** (tamanho do texto, palavras-chave): barata, mas não gera perguntas úteis.
- **Rodadas ilimitadas de perguntas**: mais precisão, risco de a demanda nunca começar.
