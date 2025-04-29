#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request, Response, send_from_directory
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import json
import uuid
import requests
from twilio.rest import Client
from pydub import AudioSegment
from gtts import gTTS
import whisper
import logging
import tempfile
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Necessário para servidores sem interface gráfica
import numpy as np

# Configurações iniciais
app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "https://assistente-financeiro.onrender.com")

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuração do Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = os.environ.get("GOOGLE_CREDS_JSON")
if not json_creds:
    raise ValueError("Variável GOOGLE_CREDS_JSON não configurada.")
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client_gs = gspread.authorize(creds)
spreadsheet = client_gs.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

# Configuração do Twilio
twilio_sid = os.environ.get("TWILIO_SID")
twilio_token = os.environ.get("TWILIO_TOKEN")
twilio_number = os.environ.get("TWILIO_NUMBER")
if not all([twilio_sid, twilio_token, twilio_number]):
    raise ValueError("Credenciais Twilio não configuradas.")
twilio_client = Client(twilio_sid, twilio_token)

# Palavras-chave de categorias
palavras_categoria = {
    "ALIMENTAÇÃO": ["mercado", "supermercado", "pão", "leite", "feira", "comida", "restaurante", "lanche", "jantar", "almoço", "hamburguer", "refrigerante", "pizza", "ifood", "delivery"],
    "TRANSPORTE": ["uber", "99", "ônibus", "metrô", "trem", "corrida", "gasolina", "combustível", "taxi", "táxi", "estacionamento"],
    "LAZER": ["cinema", "netflix", "bar", "show", "festa", "lazer", "viagem", "hotel"],
    "GASTOS FIXOS": ["aluguel", "condominio", "energia", "água", "internet", "luz", "iptu"],
    "HIGIENE E SAÚDE": ["farmácia", "remédio", "hospital", "dentista", "consulta", "médico"]
}

# Funções auxiliares
def classificar_categoria(descricao):
    desc = descricao.lower()
    for categoria, palavras in palavras_categoria.items():
        if any(p in desc for p in palavras):
            return categoria
    return "OUTROS"

def parse_valor(valor_str):
    try:
        valor = valor_str.replace("R$", "").replace(".", "").replace(",", ".").strip()
        return float(valor)
    except:
        return 0.0

def formatar_valor(valor):
    return f"R${valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# Funções de envio
def gerar_audio(texto):
    nome_arquivo = f"audio_{uuid.uuid4().hex}.mp3"
    caminho = os.path.join(STATIC_DIR, nome_arquivo)
    gTTS(text=texto, lang="pt").save(caminho)
    return caminho

def enviar_mensagem_audio(numero, texto):
    caminho_audio = gerar_audio(texto)
    url_audio = f"{BASE_URL}/static/{os.path.basename(caminho_audio)}"
    twilio_client.messages.create(body=texto, from_=twilio_number, to=numero)
    twilio_client.messages.create(from_=twilio_number, to=numero, media_url=[url_audio])
    return Response("<Response></Response>", mimetype="application/xml")

def gerar_grafico(tipo, titulo, categorias, valores):
    nome_arquivo = f"grafico_{uuid.uuid4().hex}.png"
    caminho = os.path.join(STATIC_DIR, nome_arquivo)
    plt.figure(figsize=(8,5))
    plt.title(titulo)
    
    if tipo == "pizza":
        plt.pie(valores, labels=categorias, autopct='%1.1f%%', startangle=140)
        plt.axis('equal')
    elif tipo == "barra":
        plt.bar(categorias, valores, color="skyblue")
        plt.xticks(rotation=45, ha="right")
    
    plt.tight_layout()
    plt.savefig(caminho)
    plt.close()
    return caminho

# Processamento de mensagens
def processar_audio(media_url):
    try:
        ogg_path = tempfile.mktemp(suffix=".ogg")
        wav_path = tempfile.mktemp(suffix=".wav")
        r = requests.get(media_url)
        with open(ogg_path, "wb") as f:
            f.write(r.content)
        AudioSegment.from_file(ogg_path).export(wav_path, format="wav")
        model = whisper.load_model("tiny")
        result = model.transcribe(wav_path, language="pt")
        os.remove(ogg_path)
        os.remove(wav_path)
        return result["text"]
    except:
        return None

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    try:
        return processar_mensagem()
    except Exception as e:
        logger.error(f"Erro geral: {e}")
        return Response("<Response><Message>❌ Erro interno no sistema.</Message></Response>", mimetype="application/xml")

def processar_mensagem():
    msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")
    
    if media_url and ("audio" in media_type.lower() or "voice" in media_type.lower()):
        texto = processar_audio(media_url)
        if texto:
            msg = texto.strip()
            twilio_client.messages.create(body=f"🎤 Transcrição:\n\n{msg}", from_=twilio_number, to=from_number)
        else:
            return Response("<Response><Message>❌ Áudio inválido.</Message></Response>", mimetype="application/xml")
    
    if msg in ["ajuda", "comandos"]:
        return enviar_mensagem_audio(from_number, "Comandos:\n- resumo geral\n- resumo hoje\n- resumo categoria\n- resumo mês\n- resumo larissa\n- resumo thiago\nPara registrar despesa: Nome, data, categoria, descrição, valor")
    
    if "resumo geral" in msg:
        return gerar_resumo_geral(from_number)
    if "resumo hoje" in msg:
        return gerar_resumo_hoje(from_number)
    if "resumo categoria" in msg:
        return gerar_resumo_categoria(from_number)
    if "resumo mês" in msg:
        return gerar_resumo_mensal(from_number)
    if "resumo larissa" in msg:
        return gerar_resumo_por_responsavel(from_number, "LARISSA")
    if "resumo thiago" in msg:
        return gerar_resumo_por_responsavel(from_number, "THIAGO")
    
    # Registro de despesa
    partes = [p.strip() for p in msg.split(",")]
    if len(partes) != 5:
        return Response("<Response><Message>❌ Envie no formato: Nome, data, categoria, descrição, valor.</Message></Response>", mimetype="application/xml")
    
    responsavel, data, categoria, descricao, valor = partes
    if data.lower() == "hoje":
        data_formatada = datetime.now().strftime("%d/%m/%Y")
    else:
        try:
            data_formatada = datetime.strptime(data, "%d/%m").replace(year=datetime.now().year).strftime("%d/%m/%Y")
        except:
            data_formatada = datetime.now().strftime("%d/%m/%Y")
    
    categoria = categoria if categoria else classificar_categoria(descricao)
    valor_float = parse_valor(valor)
    valor_formatado = formatar_valor(valor_float)
    
    nova_linha = [data_formatada, categoria.upper(), descricao.upper(), responsavel.upper(), valor_formatado]
    sheet.append_row(nova_linha)
    
    resposta = (
        f"✅ Despesa registrada!\n\n"
        f"📅 {data_formatada}\n"
        f"📂 {categoria}\n"
        f"📝 {descricao}\n"
        f"👤 {responsavel}\n"
        f"💸 {valor_formatado}"
    )
    
    return enviar_mensagem_audio(from_number, resposta)

# Funções de resumo
def gerar_resumo_geral(numero):
    registros = sheet.get_all_records()
    total = sum(parse_valor(r["Valor"]) for r in registros)
    categorias = {}
    for r in registros:
        categorias[r["Categoria"]] = categorias.get(r["Categoria"], 0) + parse_valor(r["Valor"])
    
    categorias_list = sorted(categorias.items(), key=lambda x: x[1], reverse=True)
    labels, valores = zip(*categorias_list) if categorias_list else ([], [])
    caminho = gerar_grafico("pizza", "Despesas Gerais", labels, valores)
    
    resumo = f"📊 Total de despesas: {formatar_valor(total)}"
    twilio_client.messages.create(body=resumo, from_=twilio_number, to=numero)
    twilio_client.messages.create(from_=twilio_number, to=numero, media_url=[f"{BASE_URL}/static/{os.path.basename(caminho)}"])
    return Response("<Response></Response>", mimetype="application/xml")

# Outras funções como gerar_resumo_hoje, gerar_resumo_categoria, gerar_resumo_mensal, gerar_resumo_por_responsavel seguem a mesma lógica.