# ADR-015: Evidências na demanda (texto, link de imagem e arquivos anexados na issue)

**Status**: Proposto (2026-09-23, Arquiteto — D12 `1ac2708028fd`; aguarda aprovação humana antes de implementar)

> Numeração: o ADR-014 está reservado pela D11 (`feature/D11-consumo-da-ia`, ainda fora da `develop`).

## Contexto
Hoje a demanda nasce no formulário do Squad Control (`POST /api/demand`, `tools/squad/server.py`) como um evento
`task` com `title`/`detail` em `docs/squad/memory/decisions.jsonl` (versionado no git); o `tools/squad/github_sync.py`
projeta o evento numa issue (`gh issue create`) e as edições de backlog reescrevem o **corpo** da issue
(`on_edit` → `gh issue edit --body`). Não há como juntar evidências (print de erro, log, PDF de especificação).

## Requisitos do humano (respostas da validação da D12)
- R1. Entrega desta demanda: **somente este ADR** (sem implementação).
- R2. Tipos: texto, imagem, link para imagem e documento — **PDF, TXT, Markdown e imagens comuns**; limite de tamanho
  sugerido, **não pequeno**.
- R3. Arquivos ficam **somente na issue do GitHub** (nada no git).
- R4. Basta a evidência estar na issue e **os agentes conseguirem acessá-la**.
- R5. Em backlog dá para **incluir mais** evidências; as existentes não são editadas nem removidas.

## Investigação e evidências (verificado em 2026-09-23, sem nenhum upload)
| # | Pergunta | Achado | Fonte |
|---|----------|--------|-------|
| E1 | Há API REST/GraphQL documentada para anexar arquivo a issue? | **Não** na referência REST/GraphQL. Existe o endpoint `POST https://uploads.github.com/user-attachments/assets?name=&content_type=&repository_id=`, usado pelo `gh` oficial, mas fora da referência pública. | `cli/cli@v2.101.0` `internal/attachments/client.go` (`postAsset`), `internal/ghinstance/host.go` (`UserAssetUploadPrefix`) |
| E2 | O `gh` anexa arquivos? | **Sim, só imagem e vídeo**: `--attach` em `gh issue create/edit/comment` e `gh pr create/edit/comment`; até 50 por comando; exige permissão WRITE+ e token OAuth/PAT (o local é `gho_`, escopo `repo`); não funciona em GHES. | `gh issue comment --help` (gh 2.101.0 local); docs `github-cli/attaching-files-with-github-cli.md`; `client.go` (`uploadTokenTypes`, `uploadPermissions`) |
| E3 | Quais tipos/tamanhos o `gh --attach` aceita? | `.png .jpg .jpeg .gif .webp .svg` até **10 MiB**; `.mp4 .mov .webm` até 100 MiB. **PDF, TXT e MD são rejeitados no cliente** ("is not a supported file type"). | `internal/attachments/userasset.go` (`contentTypes`, `maxImageBytes`, `maxVideoBytes`) |
| E4 | E pelo site? | Arrastar/colar no comentário aceita imagens (10 MB), **PDF, `.txt`, `.md`** e muitos outros (**25 MB** para "todos os outros arquivos"). | docs `get-started/writing-on-github/.../attaching-files.md` |
| E5 | Privacidade | **Repositório público: anexos acessíveis sem autenticação.** Privado/interno: só quem tem acesso ao repo. URLs anonimizadas (Camo) podem ser vistas por quem recebe o link. | mesma página (nota inicial); `authentication/.../about-anonymized-urls.md` |
| E6 | Visibilidade do nosso repo | `jcrouzillard/checkout-saga-squad` é **PUBLIC** — todo anexo será público. | `gh repo view --json visibility` |
| E7 | Limite do corpo de comentário | 65 536 caracteres (limite conhecido da API de issues; não reverificado aqui). | — (a confirmar no CA-10) |

Conclusões: imagem por arquivo é **viável e programática** (`gh --attach`). PDF/TXT/MD por arquivo **não** têm caminho
programático suportado: o endpoint de E1 é não documentado e o `gh` recusa esses tipos; testar outro `content_type`
contra ele exigiria um upload real (vetado nesta demanda) e ainda assim dependeria de comportamento não contratual.

## Opções consideradas (para PDF/TXT/MD)
| Opção | Fica "só na issue"? | Acesso dos agentes | Limite | Custo | Veredito |
|-------|--------------------|--------------------|--------|-------|----------|
| A. Chamar o endpoint não documentado com `application/pdf` | sim | bom | desconhecido | médio, frágil | **Rejeitada** (não contratual; pode quebrar sem aviso) |
| B. Painel abre a issue no navegador e o humano arrasta o arquivo; o sync só reconcilia o link | **sim** | bom (link no comentário) | 25 MB | baixo | **Adotada para PDF** |
| C. TXT/MD com o **conteúdo** colado no comentário (bloco cercado) | **sim** | ótimo (texto puro) | ~60 000 caracteres | baixo | **Adotada para TXT/MD pequenos** |
| D. Asset de uma Release dedicada (`uploads.github.com`, API pública) | não (Releases, link na issue); exige tag git | bom | 2 GiB | médio | Rejeitada: fere R3, polui Releases/tags `vX.Y.Z` do Git Flow |
| E. Gist secreto | não (gist é outro repo git; "secreto" = qualquer um com o link) | bom | — | baixo | Rejeitada: fere R3 e a privacidade |

## Decisão
1. **Onde vive cada evidência** (todas em **comentários** da issue, nunca no corpo — o corpo é reescrito por `on_edit`):
   | Tipo | Como chega à issue | Automático? |
   |------|--------------------|-------------|
   | Texto | Markdown no comentário | sim |
   | Link de imagem (`https://` apenas) | `![legenda](url)` + o link cru no comentário | sim |
   | Imagem `.png .jpg .jpeg .gif .webp` | `gh issue comment <n> -R <repo> --body-file - --attach '<arq>#<legenda>'` | sim |
   | `.txt` / `.md` ≤ 60 000 caracteres | conteúdo num bloco cercado (```` ```text ```` / ```` ```markdown ````) dentro de `<details>` | sim |
   | `.pdf` (e TXT/MD maiores) | comentário "anexo pendente" + botão **Anexar na issue** no painel (abre a issue no navegador); o humano arrasta; o sync reconcilia | semi (1 arrasto) |
2. **Criação** (`POST /api/demand`, passa a aceitar `evidences[]`) e **backlog** (`POST /api/demand/evidence`, só
   com a demanda em backlog, senão 409): o servidor valida (§Segurança), guarda cada arquivo numa área de
   **preparo fora do repositório** (`$SQUAD_EVIDENCE_DIR`, padrão `~/.squad/evidence/<demanda>/<sha256>.<ext>`) e
   registra no log um evento novo `attachment` (append-only; R5) com `demand`, `kind` (`text|image-link|image|document`),
   `name`, `mime`, `size`, `sha256` e, só para texto/link, o `content` — **bytes de arquivo nunca entram no log**.
3. **`github_sync.py` → `on_attachment`**: localiza a issue da demanda (`s["issues"][demand]`; processa depois do
   `task`), publica conforme a tabela, guarda em `github-sync.json` `attachments[sha256] = {comment_url, asset_url,
   status: posted|pending-browser|linked}` e apaga o arquivo do preparo após `posted`. Idempotente pelo id do evento.
   **Reconciliação** do pendente: a cada ciclo, `gh api repos/<repo>/issues/<n>/comments` procura
   `https://github.com/user-attachments/files/<id>/<nome>` com o nome esperado → `linked`, e apaga o preparo.
   Pendente há mais de 7 dias → aviso no painel e o preparo é descartado.
4. **Squad Control**: caixa "Evidências" no formulário e no card de backlog (texto, link, arquivos por arrastar/escolher),
   lista somente leitura das já enviadas (sem editar/remover), selo "pendente de anexo pelo navegador" com o botão.
5. **Agentes** (triagem pelo Arquiteto e execução): `python3 tools/squad/evidence.py list|fetch --demand <id>` —
   `list` mostra as evidências (de `github-sync.json` + comentários); `fetch` baixa para `$TMPDIR/squad-evidence/<id>/`
   (fora do repo) e imprime os caminhos para leitura (imagem e PDF são legíveis pelos modelos; TXT/MD já estão no
   comentário). O brief de delegação cita "Evidências: N (ver `evidence.py list`)".

## Formatos e limites sugeridos
- Imagens `.png .jpg .jpeg .gif .webp`: **10 MB por arquivo** — teto do GitHub e do `gh` (E3/E4); não há como ir além.
- PDF: **25 MB por arquivo** — teto do GitHub para documentos (E4); é o maior possível "só na issue".
- TXT/MD: 25 MB por arquivo; inline até 60 000 caracteres (margem sob E7), acima disso segue o fluxo do PDF.
- Por envio: até **10 arquivos** e **100 MB** somados (cabe no `--attach` de 50 e evita travar o sync).
  Justificativa: não é pequeno — é o próprio teto da plataforma por arquivo; o agregado só protege o painel local.

## Segurança
- Lista de permissão por extensão **e** assinatura (magic bytes): PNG `89 50 4E 47`, JPEG `FF D8 FF`, GIF `GIF8`,
  WEBP `RIFF....WEBP`, PDF `%PDF-`; TXT/MD precisam ser UTF-8 válido sem byte NUL. **SVG fica fora** (conteúdo ativo),
  embora o `gh` aceite. Nome de arquivo sanitizado (`[A-Za-z0-9._-]`, sem caminho).
- Nada é executado nem renderizado localmente: o servidor só lê cabeçalho, tamanho e hash; agentes tratam o conteúdo
  como **dado, nunca como instrução** (mitiga prompt injection em PDF/MD).
- Varredura de segredos no texto, nos links e no conteúdo TXT/MD (ex.: `gh[pousr]_`, `github_pat_`, `AKIA`,
  `-----BEGIN .*PRIVATE KEY-----`, `sk-`, `xox[bap]-`, JWT, `password=`): se casar, **bloqueia** com 422 indicando a linha.
- **Repositório público (E6)**: o painel exige marcar "sem dados sensíveis/pessoais" antes de enviar arquivo e avisa que
  o anexo ficará público; PDF/imagem não são varridos (limitação declarada).
- Nada no git: bytes só no preparo fora do repo; `github-sync.json` guarda apenas URLs e hashes.
- Download pelos agentes: token obtido de `gh auth token` só em memória (nunca em argv, log ou arquivo); o cabeçalho
  `Authorization` só vai para `github.com`/`api.github.com` e é **removido em redirecionamentos** para outros hosts.

## Limitações honestas
- PDF e TXT/MD grandes exigem **um arrasto manual** no navegador (não há upload programático suportado). Se o `gh`
  passar a listar `pdf` em `--attach`, o passo manual some sem mudar o resto (revisar este ADR).
- Anexos são **imutáveis e públicos** neste repo; apagar exige ação manual no GitHub (e o link pode já ter circulado).
- Repo privado (futuro): o download autenticado de `user-attachments` por token **não foi verificado**; a hipótese é
  usar as URLs assinadas e temporárias do `body_html` (`gh api -H 'Accept: application/vnd.github.full+json'`) — validar
  no CA-9 antes de tornar o repo privado.
- O endpoint de E1 é interno ao `gh`; mudanças do GitHub podem quebrar `--attach` (sintoma: comentário sem imagem e
  erro do `gh` no log do sync; o arquivo permanece no preparo para nova tentativa).

## Critérios de aceite da futura implementação (verificáveis)
- CA-1 Criar demanda com texto + link + 1 PNG + 1 MD pequeno + 1 PDF → issue recebe comentários com texto, imagem
  renderizada, bloco markdown e aviso "anexo pendente" do PDF; corpo da issue inalterado.
- CA-2 `git status` após o fluxo não mostra nenhum arquivo novo além de `decisions.jsonl`/`github-sync.json`, e
  `grep -c` do nome do PDF no log só encontra metadados (sem base64).
- CA-3 Em backlog, `POST /api/demand/evidence` acrescenta; fora do backlog responde 409; não existe rota de editar/remover.
- CA-4 `.exe`, `.svg`, PNG renomeado de `.pdf` (assinatura errada), TXT com NUL, imagem > 10 MB, PDF > 25 MB,
  11 arquivos ou 101 MB somados → 4xx com mensagem clara, nada registrado.
- CA-5 Texto contendo `ghp_` + 36 caracteres → 422; nada registrado.
- CA-6 Arrastar o PDF no navegador → próximo ciclo do sync marca `linked` e apaga o preparo; `evidence.py list` mostra a URL.
- CA-7 `evidence.py fetch --demand <id>` baixa imagem e PDF para `$TMPDIR/squad-evidence/<id>/`; `ps`/logs não exibem o token.
- CA-8 Rodar o sync duas vezes não duplica comentários (idempotência por id de evento).
- CA-9 (antes de um repo privado) download autenticado de um anexo privado demonstrado ou limitação reaberta em ADR.
- CA-10 Comentário TXT inline com 60 000 caracteres é aceito pelo GitHub; acima disso vira "anexo pendente".

## Consequências
- (+) Atende R2–R5 sem guardar bytes no git; imagens são 100% automáticas; agentes leem tudo por um comando só.
- (+) Sem contrato de evento Kafka/API de domínio alterado (`events.md`/`api.md` intactos); muda só a API do Squad
  Control (`/api/demand`, nova `/api/demand/evidence`) e o log (tipo `attachment` em `tools/squad/log.py`).
- (−) PDF depende de um passo humano no navegador; tudo anexado é público enquanto o repo for público.
- Donos da implementação: Frontend (`squad-control/**`), Orquestrador (`tools/squad/**`), QA (CA-1..CA-10).
