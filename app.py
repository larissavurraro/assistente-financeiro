from flask import Flask, render_template, request, redirect, url_for, session, Response, send_file
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import plotly.graph_objs as go
import plotly.io as pio
import os
import requests
import speech_recognition as sr
from pydub import AudioSegment
from twilio.rest import Client
from gtts import gTTS
import uuid
import json

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

# Autenticação Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = os.environ.get("GOOGLE_CREDS_JSON")
if json_creds:
    creds_dict = json.loads(json_creds)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    creds = ServiceAccountCredentials.from_json_keyfile_name("assistente-financeiro-457803-1e9f12a3cd87.json", scope)

client = gspread.authorize(creds)
spreadsheet = client.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

# Twilio config via variável de ambiente
twilio_sid = os.environ.get("TWILIO_SID")
twilio_token = os.environ.get("TWILIO_TOKEN")
twilio_number = os.environ.get("TWILIO_NUMBER")
twilio_client = Client(twilio_sid, twilio_token)

# Login simples
USERNAME = "larissa"
PASSWORD = "1234"

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    try:
        return processar_mensagem()
    except Exception as e:
        print("ERRO GERAL:", e)
        return Response("<Response><Message>❌ Erro interno ao processar a mensagem.</Message></Response>", mimetype="application/xml")

def processar_mensagem():
    msg = request.form.get("Body")
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    if media_url and media_type == "audio/ogg":
        ogg_path = "audio.ogg"
        wav_path = "audio.wav"
        response = requests.get(media_url)
        with open(ogg_path, "wb") as f:
            f.write(response.content)

        AudioSegment.from_file(ogg_path).export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)
            try:
                msg = recognizer.recognize_google(audio, language="pt-BR")
            except:
                return Response("<Response><Message>❌ Não consegui entender o áudio.</Message></Response>", mimetype="application/xml")
        os.remove(ogg_path)
        os.remove(wav_path)

    print("MENSAGEM RECEBIDA:", msg)

    partes = [p.strip() for p in msg.split(",")]
    if len(partes) != 5:
        return Response("<Response><Message>❌ Formato inválido. Envie assim: 27/04, mercado, compras, Larissa, 150</Message></Response>", mimetype="application/xml")

    data, categoria, descricao, responsavel, valor = partes
    if data.strip().lower() == "hoje":
        data_formatada = datetime.today().strftime("%d/%m/%Y")
    else:
        try:
            parsed_date = datetime.strptime(data, "%d/%m")
            parsed_date = parsed_date.replace(year=datetime.today().year)
            data_formatada = parsed_date.strftime("%d/%m/%Y")
        except:
            data_formatada = datetime.today().strftime("%d/%m/%Y")

    # Aplicar formatações
    categoria = categoria.upper()
    descricao = descricao.upper()
    responsavel = responsavel.upper()
    try:
        valor = float(valor)
        valor_formatado = f"R${valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        valor_formatado = valor

    sheet.append_row([data_formatada, categoria, descricao, responsavel, valor_formatado])
    print("Despesa cadastrada:", [data_formatada, categoria, descricao, responsavel, valor_formatado])

    resposta_texto = "✅ Despesa registrada com sucesso!\n"
    resposta_texto += f"📅 {data_formatada}\n"
    resposta_texto += f"📂 {categoria}\n"
    resposta_texto += f"📝 {descricao}\n"
    resposta_texto += f"👤 {responsavel}\n"
    resposta_texto += f"💸 {valor_formatado}"

    print("RESPOSTA TEXTO PARA WHATSAPP:\n", resposta_texto)

    # Gerar resposta em áudio e salvar na pasta /static
    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    audio_filename = os.path.join(static_dir, f"resposta_{uuid.uuid4().hex}.mp3")
    tts = gTTS(text=f"Despesa registrada com sucesso, {responsavel}! Categoria {categoria}, valor {valor_formatado}.", lang='pt')
    tts.save(audio_filename)

    # Converter para ogg
    ogg_filename = audio_filename.replace(".mp3", ".ogg")
    AudioSegment.from_file(audio_filename).export(ogg_filename, format="ogg")
    os.remove(audio_filename)

    # Enviar texto primeiro
    twilio_client.messages.create(
        body=resposta_texto,
        from_=twilio_number,
        to=from_number
    )

    # Depois enviar áudio
    twilio_client.messages.create(
        from_=twilio_number,
        to=from_number,
        media_url=[f"https://assistente-financeiro.onrender.com/{ogg_filename}"]
    )

    return Response("<Response></Response>", mimetype="application/xml")

if __name__ == '__main__':
    app.run(debug=True)
