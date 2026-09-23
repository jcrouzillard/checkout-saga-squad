# Contrato de UI — Emojis por papel nos cards de agentes (D3, `62f458c8038b`, prioridade alta)

> Dono da implementação: agente **Frontend** (`squad-control/**`). Escopo: somente apresentação em
> `squad-control/index.html` (constante `AGENTS`, avatar `av()`, `renderSquadStrip()`, gaveta e aba Agentes).

## Mapa papel → emoji (fixo)

| Chave `AGENTS` | Emoji | Motivo |
|----------------|-------|--------|
| `orquestrador` | 🎼 | regência/coordenação |
| `arquiteto` | 📐 | desenho e contratos |
| `devops` | ⚙️ | infraestrutura |
| `observabilidade` | 🔭 | observar o sistema |
| `backend` | 🧩 | serviços que se encaixam |
| `frontend` | 🎨 | interface |
| `qa` | 🧪 | testes |
| `auditor` | 🛡️ | gatekeeper/proteção |
| `humano` | 👤 | pessoa (neutro) |
| desconhecido | — | cai no comportamento atual: iniciais (`ini`) ou `?` |

Implementação sugerida: novo campo `emoji` em cada entrada de `AGENTS`; `av()` usa `m.emoji` quando existir, senão `m.ini`.

## Critérios de aceite

| # | Critério | Verificação |
|---|----------|-------------|
| CA1 | Cada agente conhecido mostra **exatamente** o emoji do mapa acima; um emoji por papel, sem repetição. | Inspeção visual + `grep emoji squad-control/index.html` |
| CA2 | **Mesmo emoji** em todos os lugares onde o avatar aparece: card da faixa "Squad ao vivo", gaveta do agente e aba Agentes (fonte única: `AGENTS[x].emoji` via `av()`). | Abrir os três pontos para 2 agentes |
| CA3 | Acessibilidade: o emoji fica dentro de elemento com `aria-hidden="true"`; o **nome do agente continua como texto** visível; tooltips/`title` existentes inalterados. | DOM / leitor de tela |
| CA4 | Papel desconhecido (chave fora de `AGENTS`) continua renderizando sem erro com o fallback atual (`?`/iniciais); nenhum `undefined` na tela. | Injetar evento com `agent: "xyz"` no console |
| CA5 | Layout preservado: a 1440 px com 8 cards, nome (com reticências quando longo) e o **indicador de status (dot)** continuam visíveis em todos os cards; o avatar mantém o tamanho atual (sem quebra de linha nem altura maior do card). A 390 px nada transborda horizontalmente. | DevTools 1440 e 390 |
| CA6 | Emoji renderiza com fonte de sistema (sem biblioteca/imagem/fonte externa nova); cores e identidade visual do resto do painel inalteradas. | `git diff` sem novos `<script src>`/`<link>` |
| CA7 | Escopo: diff restrito a `squad-control/index.html`; nenhuma mudança em API, servidor, `tools/squad/log.py`, formato do `decisions.jsonl` ou outros arquivos. Funcionalidades existentes (gaveta, gates, aprovação humana, feed, abas) funcionam como antes. | `git diff --stat` + smoke manual das abas |
| CA8 | Iniciais (`ini`) continuam no código (usadas em outros pontos, p.ex. passos da linha do tempo) — não remover o campo. | `grep 'ini:'` |
