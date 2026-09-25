# ADR-023: Imagens na conversa com o Orquestrador — upload próprio, arquivo por hash fora do git, imagem entregue ao modelo pelo próprio CLI

**Status**: Proposto (2026-09-25, Arquiteto — D21 `71b7d9bc3313`)
**Numeração**: 020 = conversa (D17); 021 = ambiente e versão (D18); 022 = delegação (D19). Este é o próximo livre.
**Contrato**: [`docs/contracts/imagens-na-conversa.md`](../contracts/imagens-na-conversa.md).
**Estende**: ADR-020 (conversa somente leitura) e o contrato `ui-conversa-visual-v2.md` (D20, PR #191 em revisão).
**Reutiliza**: ADR-019 / `tools/squad/evidence_rules.py` (validação e remoção de metadados das imagens de bug, D16).

## Contexto
O humano quer mostrar ao Orquestrador um print (erro na tela, alerta, PR) em vez de descrevê-lo: colar com
Ctrl+V/Cmd+V, arrastar e soltar ou anexar por botão, ver miniatura com animação de envio, mandar texto + até 3 imagens,
e o Orquestrador **enxergar** a imagem. As imagens ficam no histórico e voltam ao recarregar. Regras da demanda: mesma
validação das evidências da D16 (PNG/JPEG/WEBP, ≤ 5 MB, tipo real pelos bytes, metadados removidos); texto dentro da
imagem é dado, nunca instrução; a conversa continua somente leitura. Resposta da triagem: **tem que funcionar nos dois
runners** (`claude` e `codex`).

Fatos verificados no código e nos CLIs locais (sem chamada ao modelo):
- `conversa.py` monta o turno por `build_cmd()`; Claude recebe a pergunta como argumento de `-p`; Codex como argumento
  final de `codex exec` / `codex exec resume <thread>`. O processo roda com `stdin=DEVNULL`.
- Todas as rotas `POST /api/conversas*` têm teto de **32 KB** checado pelo `Content-Length` **antes** de ler o corpo
  (`server.py do_POST`). Uma imagem de 5 MB não cabe; em base64 dentro do JSON da mensagem seria ≈ 20 MB para 3 imagens.
- `evidence_rules.py` já tem `image_kind()` (assinatura), `strip_image_metadata()` (PNG tEXt/iTXt/zTXt/eXIf/tIME;
  JPEG APP1–APP15/COM; WEBP EXIF/XMP), `MAX_IMAGE = 5 MB`, `sha256()`; `server._send_evidence()` já serve imagem com
  tipo correto, `nosniff` e CSP restrita.
- `claude` 2.1.280: `--input-format stream-json` (só com `--print` e `--output-format stream-json`) aceita a mensagem do
  usuário por stdin com blocos de conteúdo (texto e **imagem base64**), compatível com `--resume`.
- `codex-cli` 0.156.1: `codex exec -i/--image <FILE>...` e `codex exec resume … -i/--image <FILE>` anexam imagens ao
  prompt do turno. Em `exec` a opção é **variádica** (`<FILE>...`): sem cuidado ela engole o prompt posicional.
- O cwd do filho é `<DATA_ROOT>/.squad/conversas/.sessao/`; `.squad/` já está no `.gitignore`.

## Decisão
1. **Upload separado da mensagem.** Nova rota `POST /api/conversas/<id>/anexos` recebe **uma** imagem por requisição,
   corpo **binário cru** (sem multipart, sem base64), com teto próprio de 5 MB checado pelo `Content-Length` e
   `Content-Type` checado **antes** de ler o corpo (413/415 antecipados). A UI envia cada imagem assim que ela é colada,
   solta ou escolhida (progresso real via `XMLHttpRequest.upload.onprogress`). A mensagem continua pequena:
   `POST …/mensagens {"text", "attachments": ["<id>", …]}` — o teto de 32 KB das demais rotas não muda.
2. **Validação única, reaproveitada da D16.** Tipo real por `er.image_kind()` (PNG/JPEG/WEBP; nada de GIF, SVG, HEIC),
   ≤ 5 MB, `er.strip_image_metadata()` sempre, dimensões lidas do cabeçalho (≤ 8 000 px por lado — limite dos
   fornecedores). A extensão/nome do cliente nunca decide o tipo.
3. **Armazenamento por conteúdo, fora do git, por conversa**: `<DATA_ROOT>/.squad/conversas/<id>/anexos/<sha256>.<ext>`,
   `sha256` dos bytes **já sem metadados** (colar a mesma imagem duas vezes = um arquivo). O id do anexo é esse hash.
   Nada de caminho vindo do cliente; `<id>` e `<sha256>` validados por regex. Anexo não usado em mensagem é
   apagável pela UI (remover miniatura) e expira em 24 h.
4. **Registro**: a mensagem do humano ganha `attachments: [{id, mime, size, width, height, name}]` no `.jsonl`
   (só metadados; nunca bytes nem base64). Texto passa a ser opcional quando há imagem.
5. **A imagem chega ao modelo pelo próprio CLI, sem ferramenta nova e sem afrouxar o somente leitura:**
   - **Claude** — turno com imagem usa `--input-format stream-json` e escreve **uma** linha JSON no stdin (texto +
     blocos `image` base64 dos arquivos já limpos) e fecha o stdin; o resto do comando (`--tools Read Glob Grep`,
     negações, `--strict-mcp-config`, `--resume`/`--session-id`) é **idêntico**. Turno sem imagem continua exatamente
     como na D17 (`-p <prompt>`), sem regressão.
   - **Codex** — `--image=<caminho absoluto>` por imagem (forma com `=`, um valor por ocorrência) e o prompt depois de
     `--`, no 1º turno e no `exec resume`. O sandbox continua `read-only`.
   - Em ambos, o texto do turno carrega um bloco `<anexos_do_humano>` descrevendo as imagens como **dado**.
6. **Texto na imagem é dado.** O prompt `docs/squad/prompts/conversa.md` ganha a regra; e, sobretudo, a imagem não
   ganha poder: o modelo continua sem escrita, e ` ```destravar `/` ```delegar ` seguem validados pelo servidor e
   confirmados pelo humano (ADR-020/022). Uma proposta só é aceita se o humano pediu por texto (o servidor não muda;
   a regra é do prompt e a confirmação humana é a barreira).
7. **Sessão perdida (`sessionReset`)**: o histórico reinjetado cita as imagens antigas por marcador
   (`[imagem anexada: <nome> <largura>×<altura>]`); só as imagens **do turno atual** são reanexadas.
8. **UI sobre o visual v2 (D20)**: bandeja de miniaturas no compositor com animação de envio, botão anexar, colar,
   arrastar sobre o painel, remover, miniaturas no balão do humano e visualizador; a D20 deve estar integrada antes da
   implementação desta demanda.

## Consequências
- (+) Funciona igual nos dois runners, com a imagem entregue nativamente (sem depender de o modelo decidir ler um
  arquivo) e sem nenhuma permissão nova de leitura/escrita para o modelo.
- (+) Progresso de envio real, recusa antecipada (413/415) sem ler 5 MB à toa, e a rota de mensagens segue com 32 KB.
- (+) Reuso integral das regras da D16: um só lugar para mudar formatos e limites de imagem.
- (−) Dois caminhos de chamada do Claude (texto por argumento; imagem por stdin). Mitigação: `build_cmd` testável,
  critério de igualdade das demais flags e teste real com imagem de controle.
- (−) As imagens também ficam nas sessões locais dos fornecedores (`~/.claude/projects/<slug .sessao>/`,
  `~/.codex/sessions/`) e vão ao fornecedor de IA. Aviso na UI; conteúdo de imagem **não** é mascarado (sem OCR).
- (−) Remover EXIF de JPEG de celular apaga a orientação: a foto pode aparecer girada. Prints (o caso da demanda) não
  são afetados; corrigir orientação fica fora do escopo.
- (−) Espaço em disco: teto de 100 MB por conversa e 500 MB no total de anexos de conversas.

## Alternativas consideradas
- **Imagem em base64 dentro do `POST …/mensagens`** — exigiria subir o teto da rota para ~21 MB, sem progresso por
  imagem nem recusa antecipada por arquivo; mistura erro de imagem com erro de mensagem. Rejeitada.
- **Multipart/form-data** — o `cgi` saiu da stdlib (3.13) e o servidor é só stdlib; parser próprio é superfície de
  ataque sem ganho (uma imagem por requisição). Rejeitada.
- **Claude lendo o arquivo com a ferramenta Read** (caminho no prompt) — já permitido pelo `--add-dir`, mas depende de o
  modelo decidir ler, custa uma ida extra ao modelo e aparece como "consultando". Fica como **plano B** se o
  stream-json falhar numa versão do CLI (o contrato diz como detectar).
- **Guardar as imagens no git junto com a conversa** — conversas são apartadas e fora do git (ADR-020 §5). Rejeitada.
- **Só `claude`, e `codex` recusar imagem** — rejeitada pelo humano na triagem ("tem que funcionar nos dois").
- **Reencodar no navegador (canvas → PNG)** para tirar metadados e corrigir orientação — aumenta o tamanho de JPEGs e
  o servidor teria de validar de qualquer forma. Rejeitada nesta versão.
