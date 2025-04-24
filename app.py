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
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

# Twilio config
twilio_sid = "ACaf30d619254ef0aeb126288b5e74118e"
twilio_token = "b0f2f008061c857624fa8516477a6226"
twilio_number = "whatsapp:+14155238886"
twilio_client = Client(twilio_sid, twilio_token)

# Login simples
USERNAME = "larissa"
PASSWORD = "1234"

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
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
            data_formatada = datetime.strptime(data, "%d/%m").strftime("%d/%m/%Y")
        except:
            data_formatada = datetime.today().strftime("%d/%m/%Y")

    sheet.append_row([data_formatada, categoria, descricao, responsavel, valor])
    print("Despesa cadastrada:", [data_formatada, categoria, descricao, responsavel, valor])

    resposta_texto = f"✅ Despesa registrada com sucesso!\n📅 {data_formatada}\n📂 {categoria}\n📝 {descricao}\n👤 {responsavel}\n💸 R$ {valor}"

    # Gerar resposta em áudio
    tts = gTTS(text=f"Despesa registrada com sucesso, {responsavel}! Categoria {categoria}, valor {valor} reais.", lang='pt')
    audio_filename = f"resposta_{uuid.uuid4().hex}.mp3"
    tts.save(audio_filename)

    # Converter para ogg
    ogg_filename = audio_filename.replace(".mp3", ".ogg")
    AudioSegment.from_file(audio_filename).export(ogg_filename, format="ogg")
    os.remove(audio_filename)

    # Enviar áudio pelo WhatsApp
    message = twilio_client.messages.create(
        body=resposta_texto,
        from_=twilio_number,
        to=from_number,
        media_url=[f"https://assistente-financeiro.onrender.com/static/{ogg_filename}"]
    )

    return Response("<Response><Message>✅ Despesa registrada com sucesso!</Message></Response>", mimetype="application/xml")

if __name__ == '__main__':
    app.run(debug=True)
