# Bot de Controle de Despesas para WhatsApp

Este é um bot para WhatsApp que permite a você e seu noivo registrar despesas via mensagens de texto ou áudio, 
consultar relatórios e gerenciar suas finanças de forma simples e eficiente.

## Funcionalidades

- 📱 Registro de despesas via texto ou áudio
- 📊 Geração de relatórios personalizados
- 🔊 Respostas em áudio para confirmações
- 📈 Gráficos de despesas por categoria e usuário
- 🔍 Detecção automática de categorias
- 📅 Reconhecimento inteligente de datas

## Pré-requisitos

- Conta no Twilio WhatsApp Sandbox ou API Business do WhatsApp
- Conta no Google Sheets com API ativada
- Servidor para hospedagem (Heroku, PythonAnywhere, Render, etc.)
- Python 3.8+

## Configuração e Implantação

### 1. Preparar o Google Sheets

1. Acesse [Google Cloud Console](https://console.cloud.google.com/)
2. Crie um novo projeto
3. Ative a API do Google Sheets
4. Crie credenciais de Conta de Serviço
5. Faça download do arquivo JSON de credenciais
6. Crie uma planilha no Google Sheets e compartilhe com o email da conta de serviço (com permissão de editor)
7. Anote o ID da planilha (encontrado na URL)

### 2. Configurar o Twilio (para WhatsApp)

1. Crie uma conta no [Twilio](https://www.twilio.com/)
2. Na seção "Messaging", ative o Sandbox do WhatsApp
3. Anote o SID, Token e número de telefone do Twilio

### 3. Configurar Variáveis de Ambiente

Crie um arquivo `.env` com as seguintes variáveis:
