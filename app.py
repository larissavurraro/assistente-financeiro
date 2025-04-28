#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from flask import Flask, request, Response
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import json, uuid, requests
from twilio.rest import Client
from pydub import AudioSegment
from gtts import gTTS
import whisper

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

# Configuração do Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = os.environ.get("GOOGLE_CREDS_JSON")
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client_gs = gspread.authorize(creds)
spreadsheet = client_gs.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

# Configuração do Twilio
twilio_sid = os.environ.get("TWILIO_SID")
twilio_token = os.environ.get("TWILIO_TOKEN")
twilio_number = os.environ.get("TWILIO_NUMBER")
twilio_client = Client(twilio_sid, twilio_token)

# Palavras-chave para classificação automática
palavras_categoria = {
    "ALIMENTAÇÃO": ["mercado", "supermercado", "pão", "leite", "feira", "comida", "restaurante", "lanche", "jantar", "almoço", "hamburguer", "refrigerante"],
    "TRANSPORTE": ["uber", "99", "ônibus", "metro", "trem", "corrida", "combustível", "gasolina"],
    "LAZER": ["cinema", "netflix", "bar", "show", "festa", "lazer"],
    "GASTOS FIXOS": ["aluguel", "condominio", "energia", "água", "internet", "luz"],
    "HIGIENE E SAÚDE": ["farmácia", "remédio", "hidratante"]
}

def classificar_categoria(descricao):
    desc = descricao.lower()
    for categoria, palavras in palavras_categoria.items():
        if any(palavra in desc for palavra in palavras):
            return categoria.upper()
    return "OUTROS"

def parse_valor(valor_str):
    try:
        v = float(valor_str.replace("R$", "").replace(".", "").replace(",", "."))
    except:
        v = 0.0
    return v

def enviar_mensagem_audio(from_number, texto):
    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    audio_filename = os.path.join(static_dir, f"resumo_{uuid.uuid4().hex}.mp3")

    tts = gTTS(text=texto, lang='pt')
    tts.save(audio_filename)
    ogg_filename = audio_filename.replace(".mp3", ".ogg")
    AudioSegment.from_file(audio_filename).export(ogg_filename, format="ogg")
    os.remove(audio_filename)

    audio_url = f"https://assistente-financeiro.onrender.com/{ogg_filename}"

    twilio_client.messages.create(body=texto, from_=twilio_number, to=from_number)
    twilio_client.messages.create(from_=twilio_number, to=from_number, media_url=[audio_url])

    return Response("<Response></Response>", mimetype="application/xml")

def gerar_resumo_geral(from_number):
    registros = sheet.get_all_records()
    total = 0.0
    for r in registros:
        total += parse_valor(r.get("Valor", "0"))

    resumo = f"📊 Resumo Geral:\n\nTotal registrado: R${total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return enviar_mensagem_audio(from_number, resumo)

def gerar_resumo_hoje(from_number):
    hoje = datetime.today().strftime("%d/%m/%Y")
    registros = sheet.get_all_records()
    total = 0.0
    for r in registros:
        if r.get("Data") == hoje:
            total += parse_valor(r.get("Valor", "0"))

    resumo = f"📅 Resumo de Hoje ({hoje}):\n\nTotal registrado: R${total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return enviar_mensagem_audio(from_number, resumo)

def gerar_resumo_categoria(from_number):
    registros = sheet.get_all_records()
    categorias = {}

    for r in registros:
        categoria = r.get("Categoria", "OUTROS")
        valor = parse_valor(r.get("Valor", "0"))
        categorias[categoria] = categorias.get(categoria, 0.0) + valor

    texto = "📂 Resumo por Categoria:\n\n"
    for categoria, total in categorias.items():
        texto += f"{categoria}: R${total:,.2f}\n"

    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return enviar_mensagem_audio(from_number, texto)

def gerar_resumo(from_number, responsavel, dias, titulo):
    registros = sheet.get_all_records()
    limite = datetime.today() - timedelta(days=dias)
    total = 0.0

    for r in registros:
        try:
            data = datetime.strptime(r.get("Data", ""), "%d/%m/%Y")
        except:
            continue
        if data >= limite:
            if responsavel.upper() == "TODOS" or r.get("Responsável", "").upper() == responsavel.upper():
                total += parse_valor(r.get("Valor", "0"))

    resumo = f"📋 {titulo} ({responsavel.title()}):\n\nTotal: R${total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return enviar_mensagem_audio(from_number, resumo)

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    try:
        return processar_mensagem()
    except Exception as e:
        print("ERRO GERAL:", e)
        return Response("<Response><Message>❌ Erro interno ao processar a mensagem.</Message></Response>", mimetype="application/xml")

def processar_mensagem():
    msg = request.form.get("Body", "")
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    print("MENSAGEM ORIGINAL:", msg)

    if media_url and "audio" in media_type:
        ogg_path = "audio.ogg"
        wav_path = "audio.wav"
        try:
            response = requests.get(media_url)
            with open(ogg_path, "wb") as f:
                f.write(response.content)
            AudioSegment.from_file(ogg_path).export(wav_path, format="wav")

            model = whisper.load_model("base")
            result = model.transcribe(wav_path, language="pt")
            msg = result["text"]
            print("ÁUDIO RECONHECIDO:", msg)
        except Exception as err:
            print("ERRO AO PROCESSAR ÁUDIO:", err)
            return Response("<Response><Message>❌ Erro ao processar o áudio.</Message></Response>", mimetype="application/xml")
        finally:
            if os.path.exists(ogg_path): os.remove(ogg_path)
            if os.path.exists(wav_path): os.remove(wav_path)

    msg = msg.lower().strip()

    # Verifica se é pedido de resumo
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

    # Cadastro de despesa
    partes = [p.strip() for p in msg.split(",")]
    if len(partes) != 5:
        return Response("<Response><Message>❌ Formato inválido. Envie: Nome, data, categoria, descrição, valor</Message></Response>", mimetype="application/xml")

    responsavel, data, _, descricao, valor = partes

    if data.lower() == "hoje":
        data_formatada = datetime.today().strftime("%d/%m/%Y")
    else:
        try:
            parsed_date = datetime.strptime(data, "%d/%m")
            parsed_date = parsed_date.replace(year=datetime.today().year)
            data_formatada = parsed_date.strftime("%d/%m/%Y")
        except:
            data_formatada = datetime.today().strftime("%d/%m/%Y")

    categoria = classificar_categoria(descricao)
    descricao = descricao.upper()
    responsavel = responsavel.upper()
    try:
        valor_float = float(valor)
        valor_formatado = f"R${valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        valor_formatado = valor

    sheet.append_row([data_formatada, categoria, descricao, responsavel, valor_formatado])
    print("Despesa cadastrada:", [data_formatada, categoria, descricao, responsavel, valor_formatado])

    resposta_texto = (
        f"✅ Despesa registrada com sucesso!\n\n"
        f"📅 {data_formatada}\n"
        f"📂 {categoria}\n"
        f"📝 {descricao}\n"
        f"👤 {responsavel}\n"
        f"💸 {valor_formatado}"
    )

    return enviar_mensagem_audio(from_number, resposta_texto)

if __name__ == "__main__":
    app.run(debug=True)
