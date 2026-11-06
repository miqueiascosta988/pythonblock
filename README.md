# Bloqueios Guesty – 360 Suítes (Python + GitHub Actions)

Substitui o cenário do Make. Todo dia às 07:00 (Brasília) lê os bloqueios manuais da Guesty (subconta 360 Suítes),
atualiza as abas **Bloqueios**, **Reservas**, **Painel** e **Log** da planilha e, conforme o modo, corrige o motivo na Guesty.
Às 09:00 envia as notificações ao Slack (segunda e sexta; opcionalmente CRÍTICAS todo dia).
A planilha continua sendo quem decide a severidade, o responsável e o texto; o Python só lê, grava e envia.

## Como funciona

| Arquivo | Papel |
|---|---|
| `bloqueios/guesty.py` | token (com cache), unidades, calendário, checagem de reserva, PUT do motivo |
| `bloqueios/classificar.py` | regras do Gabarito, status, decisão de correções (porte fiel dos Codes C e E do Make) |
| `bloqueios/run.py` | orquestra a leitura diária |
| `bloqueios/slack.py` | envia o que a planilha marcou como "Enviar agora? = SIM" e registra na aba Envios |
| `.github/workflows/` | agendamentos (UTC: 10:00 e 12:00) e testes |

## Travas de segurança (nesta ordem)

1. `Painel!B3` = **SIMULAÇÃO**: calcula e registra, não altera a Guesty.
2. Mesmo em **AUTOMÁTICO**, o PUT só acontece se a variável do repositório `ALLOW_PUT` for `true`.
3. Limite de correções por execução (`Painel!B6`, padrão 3) e releitura do bloqueio logo antes do PUT.
4. Não corrige onde há reserva confirmada sobreposta, e confere o resultado depois do PUT.
5. Se a leitura da Guesty vier incompleta, não marca nada como removido e não atualiza a aba Reservas.
6. Em erro, `Painel!B4` recebe "ERRO …" e o Slack não envia nada com dados velhos.

## Configuração (uma vez)

**1. Conta de serviço do Google** (não é o e-mail de usuário; ela termina em `.iam.gserviceaccount.com`)
Google Cloud Console → crie/escolha um projeto → *APIs e serviços* → ative **Google Sheets API** →
*IAM e administrador* → *Contas de serviço* → criar → aba *Chaves* → *Adicionar chave* → JSON.
Abra a planilha → *Compartilhar* → cole o e-mail da conta de serviço como **Editor**.
Se o Workspace bloquear a criação de chaves, peça ao administrador a liberação da política de chaves de conta de serviço.

**2. App do Slack**
api.slack.com/apps → novo app → *OAuth & Permissions* → escopos de bot `chat:write`, `channels:read`, `groups:read`
→ instalar no workspace → copie o *Bot User OAuth Token* (`xoxb-…`) → convide o bot (`/invite @app`) em cada canal de destino.
Para canais privados e DMs, use o **ID** do canal/usuário na coluna "Canal Slack" do Direcionamento.

**3. Repositório PRIVADO no GitHub** → *Settings → Secrets and variables → Actions*

Secrets: `SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` (conteúdo inteiro do arquivo), `GUESTY_CLIENT_ID`,
`GUESTY_CLIENT_SECRET`, `SLACK_BOT_TOKEN`.
Variables (opcionais): `ALLOW_PUT` (`true` só quando for liberar correções reais), `SLACK_CRITICA_DIARIA` (`true` para CRÍTICAS diárias),
`GUESTY_CONTA` (padrão `360 Suítes`).

> A Guesty limita quantos tokens cada client ID pode emitir por dia (hoje, 5 por 24 h). O token é guardado em cache
> entre execuções. Se o Make (cenário de renovação de token) usar o **mesmo** client ID, some as emissões dele.
> Não rode a leitura dezenas de vezes no mesmo dia em testes.

## Publicar

```bash
cd bloqueios-guesty
git init
git add -A
git commit -m "Leitura diária de bloqueios Guesty + notificações Slack"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/bloqueios-guesty.git
git push -u origin main
```

Nas próximas alterações: `git add -A`, `git commit -m "descrição"`, `git push`.

## Primeiros testes (nesta ordem)

1. *Actions → Testes* roda sozinho no push: deve ficar verde.
2. *Actions → Bloqueios Guesty - leitura diária → Run workflow* com **dry_run = true** e `unidades = SE2407,SL616`.
   Lê só essas unidades, imprime o resumo e não grava nada. Confira o log.
3. Rode de novo com **dry_run = false**, ainda com `unidades`: grava na planilha **de teste** (use uma cópia, com seu `SHEET_ID`).
4. Rode completo (sem `unidades`) em SIMULAÇÃO. Confira Bloqueios, Reservas, Painel e Log.
5. *Bloqueios Guesty - notificações → Run workflow* com **dry_run = true** (lista o que seria enviado).
   Com `Parametros!B7 = TESTE` e `B8` preenchido, tudo vai para o canal de teste.
6. Só depois: `Painel!B3 = AUTOMÁTICO` **e** `ALLOW_PUT = true`, com o limite em 3, e confira a Guesty a cada rodada.

Local (VS Code): `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt`,
crie um `.env` (nunca vai ao Git) com as mesmas variáveis dos secrets e rode `python -m bloqueios.run --dry-run`. Testes: `pytest`.

## Desligar o Make

Desative o cenário diário antigo (6918350), o 6725778 e o rascunho "Esboço Bloqueios" antes de ligar este fluxo.
Dois processos escrevendo na mesma planilha, um deles corrigindo motivos na Guesty, é o pior cenário.

## Limites conhecidos

- O GitHub agenda em UTC e pode atrasar alguns minutos. Se a leitura das 07:00 atrasar muito, o envio das 09:00 se recusa a rodar
  (a leitura precisa ser de hoje) e o workflow fica vermelho.
- O texto "Notificado em" e a janela de lembretes continuam como estão na planilha; este projeto não os alterou.
- Falha de agendamento: o GitHub avisa por e-mail quem editou o cron por último. Confira se esse e-mail é lido.
