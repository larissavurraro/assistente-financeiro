#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request, Response, send_from_directory
import os
import json
import uuid
import tempfile
import requests
import gspread
import logging
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from twilio.rest import Client
from pydub import AudioSegment
from gtts import gTTS

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chave_secreta_temporaria')

# Diretório estático
STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)

# URL base da aplicação
BASE_URL = os.environ.get("BASE_URL", "https://assistente-financeiro.onrender.com")

# Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = os.environ.get("GOOGLE_CREDS_JSON")
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gs_client = gspread.authorize(creds)
spreadsheet = gs_client.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

# Twilio
twilio_sid = os.environ.get("TWILIO_SID")
twilio_token = os.environ.get("TWILIO_TOKEN")
twilio_number = os.environ.get("TWILIO_NUMBER")
twilio_client = Client(twilio_sid, twilio_token)

# Palavras-chave para classificação de categoria
palavras_categoria = {
    "ALIMENTAÇÃO": ["mercado", "supermercado", "pão", "leite", "feira", "comida", "restaurante", "lanche", "jantar", "almoço", "hamburguer", "refrigerante"],
    "TRANSPORTE": ["uber", "99", "ônibus", "metro", "metrô", "trem", "corrida", "combustível", "gasolina"],
    "LAZER": ["cinema", "netflix", "bar", "show", "festa", "lazer"],
    "GASTOS FIXOS": ["aluguel", "condominio", "condomínio", "energia", "água", "internet", "luz"],
    "HIGIENE E SAÚDE": ["farmácia", "remédio", "hidratante"]
}

def classificar_categoria(descricao):
    desc = descricao.lower()
    for categoria, palavras in palavras_categoria.items():
        if any(palavra in desc for palavra in palavras):
            return categoria
    return "OUTROS"

def parse_valor(valor_str):
    try:
        valor_str = valor_str.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
        return float(valor_str)
    except:
        return 0.0

def formatar_valor(valor):
    return f"R${valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def gerar_audio(texto):
    """Gera áudio TTS e salva no diretório static"""
    audio_id = uuid.uuid4().hex
    mp3_path = os.path.join(STATIC_DIR, f"audio_{audio_id}.mp3")
    tts = gTTS(text=texto, lang='pt')
    tts.save(mp3_path)
    return mp3_path

def enviar_mensagem_audio(from_number, texto):
    """Envia mensagem de texto + áudio para o WhatsApp"""
    # Envia mensagem de texto
    twilio_client.messages.create(body=texto, from_=twilio_number, to=from_number)
    
    # Envia áudio
    audio_path = gerar_audio(texto)
    audio_url = f"{BASE_URL}/static/{os.path.basename(audio_path)}"
    twilio_client.messages.create(from_=twilio_number, to=from_number, media_url=[audio_url])

    return Response("<Response></Response>", mimetype="application/xml")

def gerar_resumo_geral(from_number):
    registros = sheet.get_all_records()
    total = sum(parse_valor(r.get('Valor', '0')) for r in registros)
    texto = f"📊 Resumo Geral:\n\nTotal registrado: {formatar_valor(total)}"
    return enviar_mensagem_audio(from_number, texto)

def gerar_resumo_hoje(from_number):
    hoje = datetime.now().strftime("%d/%m/%Y")
    registros = sheet.get_all_records()
    total = sum(parse_valor(r.get('Valor', '0')) for r in registros if r.get('Data') == hoje)
    texto = f"📅 Resumo de Hoje ({hoje}):\n\nTotal registrado: {formatar_valor(total)}"
    return enviar_mensagem_audio(from_number, texto)

def gerar_resumo_categoria(from_number):
    registros = sheet.get_all_records()
    categorias = {}
    total_geral = 0

    for r in registros:
        categoria = r.get('Categoria', 'OUTROS')
        valor = parse_valor(r.get('Valor', '0'))
        categorias[categoria] = categorias.get(categoria, 0) + valor
        total_geral += valor

    texto = "📂 Resumo por Categoria:\n\n"
    for cat, total in sorted(categorias.items(), key=lambda x: x[1], reverse=True):
        percentual = (total / total_geral * 100) if total_geral else 0
        texto += f"{cat}: {formatar_valor(total)} ({percentual:.1f}%)\n"
    
    texto += f"\nTotal Geral: {formatar_valor(total_geral)}"
    return enviar_mensagem_audio(from_number, texto)

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    try:
        return processar_mensagem()
    except Exception as e:
        logger.error(f"Erro geral ao processar: {str(e)}")
        return Response("<Response><Message>❌ Erro interno ao processar sua mensagem.</Message></Response>", mimetype="application/xml")

def processar_mensagem():
    msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")
    
    logger.info(f"Mensagem recebida de {from_number}: {msg}")
    logger.info(f"Tipo de mídia: {media_type}")
    
    # Se for áudio, tenta transcrever
    if media_url and "audio" in media_type.lower():
        transcricao = processar_audio_twilio(media_url)
        if transcricao:
            msg = transcricao.strip()
        else:
            return Response("<Response><Message>❌ Não consegui processar seu áudio. Por favor, envie por texto.</Message></Response>", mimetype="application/xml")

    msg = msg.lower()

    # Comandos de resumo
    if "resumo geral" in msg:
        return gerar_resumo_geral(from_number)
    if "resumo hoje" in msg:
        return gerar_resumo_hoje(from_number)
    if "resumo por categoria" in msg:
        return gerar_resumo_categoria(from_number)
    if "resumo da larissa" in msg:
        return gerar_resumo(from_number, "LARISSA", 30, "Resumo do Mês")
    if "resumo do thiago" in msg:
        return gerar_resumo(from_number, "THIAGO", 30, "Resumo do Mês")
    if "resumo do mês" in msg:
        return gerar_resumo(from_number, "TODOS", 30, "Resumo do Mês")
    if "resumo da semana" in msg:
        return gerar_resumo(from_number, "TODOS", 7, "Resumo da Semana")

    # Cadastro de despesa: formato esperado -> Nome, data, categoria, descrição, valor
    partes = [p.strip() for p in msg.split(",")]
    if len(partes) != 5:
        return Response(
            "<Response><Message>❌ Formato inválido. Envie: Nome, data, categoria, descrição, valor</Message></Response>", 
            mimetype="application/xml"
        )

    responsavel, data, categoria_input, descricao, valor = partes

    # Ajustar data
    if data.lower() == "hoje":
        data_formatada = datetime.now().strftime("%d/%m/%Y")
    else:
        try:
            parsed_date = datetime.strptime(data, "%d/%m")
            parsed_date = parsed_date.replace(year=datetime.now().year)
            data_formatada = parsed_date.strftime("%d/%m/%Y")
        except:
            data_formatada = datetime.now().strftime("%d/%m/%Y")

    # Ajustar categoria
    if categoria_input and categoria_input.upper() != "OUTROS":
        categoria = categoria_input.upper()
    else:
        categoria = classificar_categoria(descricao)

    descricao = descricao.upper()
    responsavel = responsavel.upper()

    # Ajustar valor
    valor_float = parse_valor(valor)
    valor_formatado = formatar_valor(valor_float)

    # Preparar nova linha
    nova_linha = [""] * len(HEADERS)
    nova_linha[DATA_IDX] = data_formatada
    nova_linha[CATEGORIA_IDX] = categoria
    nova_linha[DESCRICAO_IDX] = descricao
    nova_linha[RESPONSAVEL_IDX] = responsavel
    nova_linha[VALOR_IDX] = valor_formatado

    # Inserir na planilha
    try:
        sheet.append_row(nova_linha)
        logger.info(f"Despesa cadastrada: {nova_linha}")

        resposta = (
            f"✅ Despesa registrada com sucesso!\n\n"
            f"📅 {data_formatada}\n"
            f"📂 Categoria: {categoria}\n"
            f"📝 Descrição: {descricao}\n"
            f"👤 Responsável: {responsavel}\n"
            f"💸 Valor: {valor_formatado}"
        )

        return enviar_mensagem_audio(from_number, resposta)
    except Exception as e:
        logger.error(f"Erro ao registrar despesa: {str(e)}")
        return Response("<Response><Message>❌ Erro ao registrar a despesa. Tente novamente.</Message></Response>", mimetype="application/xml")

@app.route("/")
def index():
    """Página inicial simples para verificar se o serviço está funcionando"""
    return """
    <html>
        <head><title>Assistente Financeiro</title></head>
        <body>
            <h1>Assistente Financeiro</h1>
            <p>✅ Serviço ativo e funcionando!</p>
            <p>⏰ Hora atual do servidor: {}</p>
        </body>
    </html>
    """.format(datetime.now().strftime("%d/%m/%Y %H:%M:%S"))

@app.route("/test-audio")
def test_audio():
    """Rota de teste para verificar a geração de áudio"""
    texto = "Este é um teste do sistema de áudio do Assistente Financeiro. Tudo está funcionando corretamente."
    audio_path = gerar_audio(texto)
    if audio_path:
        return f"""
        <html>
            <head><title>Teste de Áudio</title></head>
            <body>
                <h1>Teste de Geração de Áudio</h1>
                <p>✅ Áudio gerado com sucesso!</p>
                <audio controls>
                    <source src="/static/{os.path.basename(audio_path)}" type="audio/mpeg">
                    Seu navegador não suporta áudio.
                </audio>
                <p><a href="/static/{os.path.basename(audio_path)}" download>Clique para baixar o áudio</a></p>
            </body>
        </html>
        """
    else:
        return "❌ Falha ao gerar o áudio."

if __name__ == "__main__":
    # Pega a porta definida na variável de ambiente (Render.com, Heroku) ou usa 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
