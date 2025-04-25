from flask import Flask, render_template, request, redirect, url_for, session, Response, send_file
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os, json, uuid, requests
from twilio.rest import Client
from pydub import AudioSegment
from gtts import gTTS
import speech_recognition as sr
import matplotlib.pyplot as plt
import pandas as pd

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

# Autenticação Google Sheets via variável de ambiente
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = os.environ.get("GOOGLE_CREDS_JSON")
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# ID da planilha correta
spreadsheet = client.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

# Twilio (via variáveis de ambiente no Render)
twilio_sid = os.environ.get("TWILIO_SID")
twilio_token = os.environ.get("TWILIO_TOKEN")
twilio_number = os.environ.get("TWILIO_NUMBER")
twilio_client = Client(twilio_sid, twilio_token)

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    try:
        return processar_mensagem()
    except Exception as e:
        print("ERRO GERAL:", e)
        import traceback
        traceback.print_exc()
        return Response("<Response><Message>❌ Erro interno ao processar a mensagem.</Message></Response>", mimetype="application/xml")

def processar_mensagem():
    msg = request.form.get("Body")
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    print("MEDIA URL:", media_url)
    print("MEDIA TYPE:", media_type)

    if media_url and "audio" in media_type:
        ogg_path = "audio.ogg"
        wav_path = "audio.wav"

        try:
            response = requests.get(media_url)
            with open(ogg_path, "wb") as f:
                f.write(response.content)

            AudioSegment.from_file(ogg_path).export(wav_path, format="wav")
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio = recognizer.record(source)
                try:
                    msg = recognizer.recognize_google(audio, language="pt-BR")
                    print("ÁUDIO RECONHECIDO:", msg)
                except Exception as err:
                    print("ERRO AO RECONHECER ÁUDIO:", err)
                    import traceback
                    traceback.print_exc()
                    return Response("<Response><Message>❌ Não consegui entender o áudio.</Message></Response>", mimetype="application/xml")
        except Exception as err:
            print("ERRO AO PROCESSAR O ÁUDIO:", err)
            import traceback
            traceback.print_exc()
            return Response("<Response><Message>❌ Houve um erro ao processar o áudio.</Message></Response>", mimetype="application/xml")
        finally:
            if os.path.exists(ogg_path): os.remove(ogg_path)
            if os.path.exists(wav_path): os.remove(wav_path)

    if "resumo" in msg.lower() and "semana" in msg.lower():
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        df["DATA"] = pd.to_datetime(df["DATA"], dayfirst=True, errors="coerce")
        hoje = datetime.today()
        semana_passada = hoje - pd.Timedelta(days=7)
        df_semana = df[df["DATA"] >= semana_passada]

        resumo = df_semana.groupby("RESPONSAVEL")["VALOR"].apply(
            lambda x: pd.to_numeric(x.replace("R$", "", regex=True)
                                    .str.replace(".", "", regex=False)
                                    .str.replace(",", ".", regex=False), errors="coerce").sum()
        ).reset_index()

        plt.figure(figsize=(6, 4))
        plt.bar(resumo["RESPONSAVEL"], resumo["VALOR"], color=["#A5D6A7", "#81C784"])
        plt.title("Gastos da Semana por Pessoa")
        plt.ylabel("Total (R$)")
        plt.grid(axis='y', linestyle='--', alpha=0.5)

        static_dir = "static"
        os.makedirs(static_dir, exist_ok=True)
        grafico_path = os.path.join(static_dir, f"grafico_{uuid.uuid4().hex}.png")
        plt.tight_layout()
        plt.savefig(grafico_path)
        plt.close()

        grafico_url = f"https://assistente-financeiro.onrender.com/{grafico_path}"
        twilio_client.messages.create(
            from_=twilio_number,
            to=from_number,
            media_url=[grafico_url]
        )

        return Response("<Response><Message>📊 Aqui está o resumo da semana!</Message></Response>", mimetype="application/xml")

    if "resumo" in msg.lower() and "mês" in msg.lower():
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        df["DATA"] = pd.to_datetime(df["DATA"], dayfirst=True, errors="coerce")

        hoje = datetime.today()
        mes_passado = hoje - pd.Timedelta(days=30)
        df_mes = df[df["DATA"] >= mes_passado]

        resumo = df_mes.groupby("RESPONSAVEL")["VALOR"].apply(
            lambda x: pd.to_numeric(x.replace("R$", "", regex=True)
                                    .str.replace(".", "", regex=False)
                                    .str.replace(",", ".", regex=False), errors="coerce").sum()
        ).reset_index()

        plt.figure(figsize=(6, 4))
        plt.bar(resumo["RESPONSAVEL"], resumo["VALOR"], color=["#FFD54F", "#4FC3F7"])
        plt.title("💸 Gastos do Mês por Pessoa")
        plt.ylabel("Total (R$)")
        plt.grid(axis='y', linestyle='--', alpha=0.5)

        static_dir = "static"
        os.makedirs(static_dir, exist_ok=True)
        grafico_path = os.path.join(static_dir, f"grafico_{uuid.uuid4().hex}.png")
        plt.tight_layout()
        plt.savefig(grafico_path)
        plt.close()

        grafico_url = f"https://assistente-financeiro.onrender.com/{grafico_path}"
        twilio_client.messages.create(
            from_=twilio_number,
            to=from_number,
            media_url=[grafico_url]
        )

        return Response("<Response><Message>📊 Aqui está o resumo do mês!</Message></Response>", mimetype="application/xml")

    print("MENSAGEM RECEBIDA:", msg)
    partes = [p.strip() for p in msg.split(",")]
    if len(partes) != 5:
        return Response("<Response><Message>❌ Formato inválido. Envie assim: 27/04, mercado, compras, Larissa, 150</Message></Response>", mimetype="application/xml")

    data, categoria, descricao, responsavel, valor = partes

    if data.lower() == "hoje":
        data_formatada = datetime.today().strftime("%d/%m/%Y")
    else:
        try:
            parsed_date = datetime.strptime(data, "%d/%m")
            parsed_date = parsed_date.replace(year=datetime.today().year)
            data_formatada = parsed_date.strftime("%d/%m/%Y")
        except:
            data_formatada = datetime.today().strftime("%d/%m/%Y")

    categoria = categoria.upper()
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
        f"✅ Despesa registrada com sucesso!\n"
        f"📅 {data_formatada}\n"
        f"📂 {categoria}\n"
        f"📝 {descricao}\n"
        f"👤 {responsavel}\n"
        f"💸 {valor_formatado}"
    )

    print("RESPOSTA TEXTO:", resposta_texto)

    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    audio_filename = os.path.join(static_dir, f"resposta_{uuid.uuid4().hex}.mp3")
    tts = gTTS(text=f"Despesa registrada com sucesso, {responsavel}! Categoria {categoria}, valor {valor_formatado}.", lang='pt')
    tts.save(audio_filename)

    ogg_filename = audio_filename.replace(".mp3", ".ogg")
    AudioSegment.from_file(audio_filename).export(ogg_filename, format="ogg")
    os.remove(audio_filename)

    audio_url = f"https://assistente-financeiro.onrender.com/{ogg_filename}"
    print("ÁUDIO:", audio_url)

    twilio_client.messages.create(
        body=resposta_texto,
        from_=twilio_number,
        to=from_number
    )
    twilio_client.messages.create(
        from_=twilio_number,
        to=from_number,
        media_url=[audio_url]
    )

    return Response("<Response></Response>", mimetype="application/xml")

if __name__ == '__main__':
    app.run(debug=True)
