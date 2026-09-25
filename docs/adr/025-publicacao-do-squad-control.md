# ADR-025: Publicação do Squad Control por um supervisor local (automática após merge e botão "Publicar")

**Status**: Proposto (2026-09-25, Arquiteto, D24 `cf7a120591b0`)
**Numeração**: 024 é a plataforma multiproduto. A D23 (F2a), em paralelo, não cria ADR. Este é o próximo livre.
**Contrato**: [`docs/contracts/publicacao-do-squad-control.md`](../contracts/publicacao-do-squad-control.md).
**Relaciona-se com**: ADR-018 (travas do produtivo), ADR-020 (conversa), ADR-021 (ambiente e versão, selo do menu),
ADR-024 §3 (`[env.prod] kind = "process"`, `update = "restart"`).

## Contexto
Merges que mudam `squad-control/**` ou `tools/squad/**` não chegam ao painel da porta 7070. O `prod.py` só cuida do
Compose do checkout e registra "Produtivo atualizado: nada a reiniciar" (ressalva R10 do G1-D15). Aconteceu na D19 e
na D21. Pedido do humano: reinício automático na versão nova em até 1 min, com as travas do ADR-018, um ponto seguro
(sem resposta da conversa em andamento) ou aviso, evento no log, aviso no painel e um botão **"Publicar Squad
Control"**. Ele delegou ao Orquestrador a forma de rodar. Decisão do Orquestrador (`fd0c2871d359`): supervisor em
segundo plano com logs em arquivo, `make squad` continua funcionando, o automático espera o ponto seguro até um limite
curto e o botão pede confirmação.

O código hoje condiciona a solução assim:
- O servidor (`server.py`) é iniciado à mão (`make squad`) em primeiro plano. Não tem supervisor, pidfile nem tratamento
  de `SIGTERM`. Ele serve `squad-control/` do disco, então depois de um `git pull` a tela nova convive com a API
  antiga (ADR-021).
- **O merge só entra na cópia principal quando o plantão roda `gitflow.py review-sync`** (`pending.py` → LLM do
  Orquestrador). O plantão roda a cada 180 s por padrão e mais o tempo do LLM, o que já estoura o prazo de 1 min.
  Portanto o prazo exige que o próprio publicador detecte o avanço da `origin/develop`.
- A cópia principal quase sempre está suja, mas só em `docs/squad/**` (log, `github-sync.json`). Ela também recebe
  commits locais de memória ("Sincronização da memória da squad") que o `sync_develop` rebaseia e envia.
- `GET /api/conversas` já devolve `busy` (`Engine.busy()`, D17), inclusive no servidor que está no ar hoje. Os turnos
  da conversa rodam em subprocessos `start_new_session=True`. Na subida, `Store.recover()` fecha como `interrompida`
  os turnos que ficaram abertos.
- `instance.py` (D18) já calcula versão e "desatualizado". O selo do rodapé do menu é o lugar natural do aviso e do
  botão.
- O ADR-024 prevê `kind = "process"` com um atualizador próprio, fora do `prod.py`, com as mesmas guardas.

## Decisão
1. **Supervisor portátil em Python stdlib**: `tools/squad/publisher.py`, um processo em segundo plano. Uma instância
   por cópia principal é garantida por `flock` em `.squad/squad-control/supervisor.lock`, e o pidfile fica ao lado,
   só como informação. O servidor roda como processo filho, com stdout e stderr em
   `.squad/squad-control/server.log` (rotação em 5 MB, 3 arquivos). O supervisor tem log próprio,
   `publisher.log`. O supervisor lê a configuração de um dicionário com as chaves do `[env.prod]` do ADR-024
   (`kind="process"`, `command`, `ports.control=7070`, `health="/api/instance"`, `update="restart"`). Na F2b a
   fonte passa a ser o `product.toml` do `squad-platform`, sem outra mudança.
   `make squad` passa a iniciar o supervisor, ou mostrar o estado dele se já estiver no ar, e devolve o terminal. O
   modo antigo continua em `make squad-primeiro-plano`, e `python3 tools/squad/server.py --port N` continua valendo
   para testes e worktrees (pedido de mudança ao DevOps).
2. **Gatilhos**: (a) **automático**. A cada 15 s o supervisor lê `git ls-remote origin refs/heads/develop` e só faz
   `fetch` quando o SHA muda. Ele avança a cópia principal com `git merge --ff-only origin/develop` e sem autostash,
   para nunca mexer no log vivo. Publica quando o código em `tools/squad/` e `squad-control/` do HEAD difere do que
   está no ar. O `review-sync` do plantão continua registrando `delivered`, e o pull dele vira no-op. (b) **botão**.
   `POST /api/squad-control/publish` grava um pedido em arquivo, que o supervisor lê a cada 2 s. (c) **subida do
   supervisor**.
3. **Travas (as do ADR-018, adaptadas a processo)**: só a cópia principal em `develop`; só fast-forward (HEAD à frente
   da `origin/develop` apenas com commits que tocam só `docs/squad/**`; divergência espera o `review-sync`); nenhuma
   mudança rastreada em `tools/squad/` ou `squad-control/`; lock; porta 7070 só com a cópia principal; nenhum dado é
   apagado.
4. **Saúde em quatro pontos**: *antes* (o servidor atual responde, o que é só registrado, pois pode ser justamente o
   quebrado); *pré-voo* (`py_compile` e a subida de um **candidato** em porta livre, com dados sintéticos
   descartáveis, `SQUAD_ENV=teste` e sem efeitos colaterais, antes de derrubar o atual); *depois* (na 7070,
   `/api/instance` com `commitFull` = alvo e `environment.name = produtivo`, mais `/api/state`, `/api/live` e `/`, em até
   20 s); *estabilidade* (o processo continua vivo 10 s depois). O candidato não usa os dados reais porque a subida
   roda `Store.recover()`, que fecharia como `interrompida` o turno em andamento do servidor atual.
5. **Rollback sem mexer na cópia principal**: se a checagem *depois* falha, o supervisor sobe o commit anterior a
   partir do worktree destacado `<pai>/plankton-squad-prev`, com `SQUAD_ENV=produtivo`, `SQUAD_ROOT_DATA=<cópia
   principal>` e `SQUAD_PUBLISH_REVERTED=<sha falho>`. O selo mostra "revertido". O supervisor não tenta de novo o
   mesmo SHA sozinho, só quando chega um SHA novo ou quando o humano aperta o botão. Se o anterior também falhar, o
   próprio supervisor serve na 7070 uma **página de manutenção** estática com o erro e o caminho dos logs.
6. **Ponto seguro**: `busy` lido de `GET /api/conversas`, rota já existente. O automático espera até **20 s**
   (`SQUAD_PUBLISH_SAFE_WAIT_S`) e, durante a espera, o painel mostra um aviso com contagem regressiva. No fim do
   prazo o supervisor reinicia. O botão com resposta em andamento abre uma confirmação com duas saídas: "Publicar
   agora" interrompe a resposta, e "Publicar quando a resposta terminar" espera até 10 min.
7. **Parada graciosa**: o servidor passa a tratar `SIGTERM`. Ele para de aceitar conexões e encerra o turno ativo
   como `interrompida` com `code = "reinicio_publicacao"`, preservando o texto já recebido e matando o subprocesso do
   runner. O supervisor espera 8 s e então manda `SIGKILL`. SSE e `/api/live` caem. A tela reconecta sozinha e
   **recarrega sozinha** quando o `commitFull` do servidor muda, desde que não haja rascunho. Com rascunho, mostra uma
   faixa "Recarregar".
8. **Eventos (só acréscimo)**: `squad-publish-requested` (agent `humano`), `squad-updated`, `squad-update-failed`,
   `squad-server-crashed`. **Estado ao vivo** no arquivo `.squad/squad-control/status.json`, exposto em
   `GET /api/squad-control/publication` e num objeto pequeno `publication` (≤ 1 KB) no `/api/live`.
9. **O supervisor se atualiza**: quando `publisher.py` muda num merge publicado com sucesso, o supervisor valida o
   código novo num subprocesso (`publisher.py selftest`) e faz `os.execv` de si mesmo. O servidor filho não reinicia.
   Se o `selftest` falha, o supervisor antigo continua e grava `squad-update-failed` com `phase = "supervisor"`.

## Consequências
- (+) A função nova aparece em ≤ 1 min sem terminal: ~15 s de detecção, ~5 s de pré-voo, até 20 s de ponto seguro e
  ~5 s de troca e saúde. A tela nunca mais fica nova com a API velha por horas.
- (+) Um servidor quebrado não fica no ar: o pré-voo pega erro de sintaxe e de import antes de derrubar o atual, e a
  checagem *depois* dispara o rollback.
- (+) Alinhado ao ADR-024: é o atualizador `kind = "process"` que a separação só vai reconfigurar.
- (−) Existe uma janela de ~3 a 5 s com a 7070 fora do ar a cada publicação. É aceitável para uso local de um humano.
- (−) Uma resposta da conversa pode ser cortada depois de 20 s. O texto parcial fica salvo e o painel oferece
  "Reenviar".
- (−) O publicador passa a escrever na cópia principal (`merge --ff-only`). Mitigado pelas travas, pela ausência de
  autostash e porque o `sync_develop` do `review-sync` fica idempotente.
- (−) No modo revertido, o que o servidor dispara (`testenv.py`) roda o código anterior. Isso é aceitável porque é
  temporário e fica visível no selo.
- (−) O supervisor não sobrevive a um reboot da máquina: após reiniciar, é preciso rodar `make squad`, como hoje.
  O plantão, a cada ciclo, só sobe o supervisor se a 7070 estiver livre (`publisher.py ensure`).

## Alternativas consideradas
- **launchd/systemd**: sobrevive ao reboot, mas só funciona em uma plataforma, exige um plist fora do repositório e
  não conhece ponto seguro nem rollback. A plataforma do ADR-024 precisa ser portátil. Rejeitada; o reboot fica como
  melhoria futura.
- **supervisord/pm2/honcho**: dependência externa sem ganho sobre stdlib. Rejeitada.
- **Hot reload (`importlib.reload`/`execv` do próprio servidor)**: não há rollback se o código novo não importa, e o
  estado em memória (turnos, caches) fica inconsistente. Rejeitada.
- **Blue/green com troca de porta (proxy na 7070)**: elimina a janela de 3 a 5 s, mas exige um proxy HTTP/SSE e
  dois servidores sobre os mesmos dados (conflito com `recover()` e o log). Rejeitada; o candidato do pré-voo cobre o
  risco principal sem compartilhar dados.
- **Rodar sempre de um worktree imutável por versão**: resolveria a "tela nova com API velha", mas `te_spawn` e as
  ferramentas partiriam de um worktree destacado, e o ADR-021 marcaria "teste". Rejeitada; o worktree fica só para o
  rollback.
- **Rollback com `git checkout` na cópia principal**: viola o "só avanço simples" e deixa a `develop` destacada.
  Rejeitada.
- **Esperar o `review-sync` do plantão**: não cumpre 1 min (180 s mais o LLM). Rejeitada como gatilho único, mas
  continua como caminho paralelo e idempotente.
- **Nunca cortar a resposta (esperar indefinidamente)**: conflita com o prazo. Rejeitada para o automático; o botão
  oferece essa espera.
