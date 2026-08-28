# Sincronizador Garmin → Supabase

Puxa sono, frequência cardíaca de repouso e peso do Garmin Connect e grava no
schema `saude` do Supabase, alimentando o painel automaticamente.

## O que ele faz e o que não faz

Preenche **sono_min**, **fc_repouso** e **peso_kg**.

Nunca toca em calorias, proteína, água, cafeína, treino, checklist, registro de
crises ou saúde sexual. Esses são seus, digitados na mão, e o script foi escrito
para não destruí-los.

O peso só é preenchido quando o campo ainda está vazio — você pesa na Omron, que
não sincroniza com o Garmin, então o valor que você digitou sempre vence.

Rodar duas vezes no mesmo dia não duplica nada. A gravação é idempotente.

## Configuração

```bash
cp .env.example .env
# preencha o .env
pip install -r requirements.txt
python sync_garmin.py
```

### A chave do Supabase

O script usa a **service_role key**, não a publishable. Ela ignora o RLS, o que é
necessário para gravar em nome do seu usuário sem fazer login.

Isso significa que ela é uma credencial séria: quem tiver essa chave lê e escreve
qualquer tabela do projeto, incluindo os dados dos outros aplicativos que moram
lá. Ela nunca pode ir para o frontend, nem para repositório público, nem para
uma conversa de chat.

Pegue em: Supabase → Project Settings → API Keys → `service_role`.

### O login do Garmin

Na primeira execução o Garmin pode pedir verificação em duas etapas. Rode uma vez
no terminal, de forma interativa, para resolver isso. Depois o token fica salvo
em `GARMIN_TOKEN_DIR` e as execuções seguintes não pedem mais nada.

Se o token expirar, o script refaz o login sozinho.

## Uso

```bash
python sync_garmin.py                  # ontem e hoje
python sync_garmin.py --dias 7         # última semana
python sync_garmin.py --data 2026-08-26   # um dia específico
```

Use `--dias 30` uma vez para preencher o histórico desde o início do plano.

## Agendar no Coolify

1. Nova aplicação → **Dockerfile**, apontando para este repositório
2. Em **Environment Variables**, adicione as cinco do `.env`
3. Em **Storages**, monte um volume persistente em `/data/garmin-token` — sem
   isso o login é refeito a cada execução
4. Em **Scheduled Tasks**, crie uma tarefa:
   - Comando: `python sync_garmin.py --dias 3`
   - Frequência: `0 7 * * *` (todo dia às 7h)

Três dias de janela em vez de um porque o Garmin às vezes demora a consolidar o
sono da noite anterior. Reprocessar não causa dano.

## Se algo falhar

O script continua mesmo quando um bloco falha — se o sono não vier, ele ainda
grava a frequência cardíaca. Cada falha aparece no log com o dia e o motivo.

Sai com código 1 se houve qualquer erro, então o Coolify marca a execução como
falha e você fica sabendo.
