# Valkyrie Discord Bot

Bot de comunidade e jogo com garagem, loja, peças, corridas, empregos, crimes e economia.

## Requisitos

- Python 3.13 ou superior
- Um bot criado no Discord Developer Portal
- Intents **Message Content** e **Server Members** habilitadas no portal

## Instalação e execução

1. Instale as dependências: `pip install -r requirements.txt`
2. Cadastre `DISCORD_TOKEN` como segredo/variável de ambiente. Nunca coloque o token em um arquivo versionado.
3. Inicie o bot: `python run_bot.py`

O supervisor verifica a sintaxe antes de iniciar e reinicia falhas recuperáveis. Se o Discord rejeitar o token, encerra sem repetir tentativas; corrija o segredo e reinicie.

## Execução contínua no Replit

O workflow de desenvolvimento é útil para testes, mas não garante disponibilidade 24/7. Para manter o bot ligado continuamente, publique o processo em um deployment **VM / Reserved VM** no Replit, configure `DISCORD_TOKEN` nos Secrets do ambiente de produção e use `python run_bot.py` como comando de execução. O usuário precisa iniciar a publicação pelo painel do Replit.

## Dados locais

O SQLite `valkyrie.db` é criado durante a execução e fica fora do Git para não publicar dados de jogo. Faça cópias de segurança; a sincronização deste repositório não inclui o banco nem o token.
