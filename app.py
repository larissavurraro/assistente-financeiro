from flask import Flask, request, Response
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os, json, uuid, requests
from twilio.rest import Client
from pydub import AudioSegment
from gtts import gTTS
import whisper
import matplotlib.pyplot as plt
import pandas as pd

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

# Twilio
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
    msg = request.form.get("Body", "")
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    print("MENSAGEM ORIGINAL:", msg)

    # Reconhecimento de áudio
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

    partes = [p.strip() for p in msg.split(",")]
    if len(partes) < 2:
        return Response("<Response><Message>❌ Envie: Nome, hoje, mercado, compras, 150 ou peça um resumo</Message></Response>", mimetype="application/xml")

    responsavel = partes[0].upper()
    conteudo = ",".join(partes[1:]).lower()

    # Comandos especiais
    if "resumo por categoria" in conteudo:
        return gerar_resumo_categoria(responsavel)
    if "resumo geral" in conteudo:
        return gerar_resumo_geral()
    if "resumo hoje" in conteudo:
        return gerar_resumo_hoje()
    if "resumo" in conteudo and "semana" in conteudo:
        return gerar_resumo(responsavel, dias=7, titulo="Gastos da Semana")
    if "resumo" in conteudo and "mês" in conteudo:
        return gerar_resumo(responsavel, dias=30, titulo="Gastos do Mês")

    # Cadastro de despesa
    if len(partes) != 5:
        return Response("<Response><Message>❌ Formato inválido. Envie: Nome, data, categoria, descrição, valor</Message></Response>", mimetype="application/xml")

    _, data, categoria, descricao, valor = partes

    # Data
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
    try:
        valor_float = float(valor)
        valor_formatado = f"R${valor_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        valor_formatado = valor

    sheet.append_row([data_formatada, categoria, descricao, responsavel, valor_formatado])
    print("Despesa cadastrada:", [data_formatada, categoria, descricao, responsavel, valor_formatado])

    resposta = (
        f"✅ Despesa registrada!\n"
        f"📅 {data_formatada}\n"
        f"📂 {categoria}\n"
        f"📝 {descricao}\n"
        f"👤 {responsavel}\n"
        f"💸 {valor_formatado}"
    )

    audio_path = os.path.join("static", f"resposta_{uuid.uuid4().hex}.mp3")
    tts = gTTS(text=f"Despesa registrada com sucesso, {responsavel}! Categoria {categoria}, valor {valor_formatado}.", lang="pt")
    tts.save(audio_path)
    ogg_path = audio_path.replace(".mp3", ".ogg")
    AudioSegment.from_file(audio_path).export(ogg_path, format="ogg")
    os.remove(audio_path)

    audio_url = f"https://assistente-financeiro.onrender.com/{ogg_path}"

    twilio_client.messages.create(body=resposta, from_=twilio_number, to=from_number)
    twilio_client.messages.create(from_=twilio_number, to=from_number, media_url=[audio_url])

    return Response("<Response></Response>", mimetype="application/xml")

# Funções de resumo

def gerar_resumo(responsavel, dias, titulo):
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    df["DATA"] = pd.to_datetime(df["DATA"], dayfirst=True, errors="coerce")
    df = df[df["RESPONSAVEL"] == responsavel]
    df = df[df["DATA"] >= datetime.today() - pd.Timedelta(days=dias)]

    if df.empty:
        return Response(f"<Response><Message>ℹ️ Sem gastos de {responsavel} nos últimos {dias} dias.</Message></Response>", mimetype="application/xml")

    df["VALOR"] = df["VALOR"].str.replace("R$", "").str.replace(".", "").str.replace(",", ".").astype(float)
    resumo = df.groupby("CATEGORIA")["VALOR"].sum().reset_index()

    plt.figure(figsize=(6, 4))
    plt.bar(resumo["CATEGORIA"], resumo["VALOR"])
    plt.title(f"{titulo} - {responsavel}")
    plt.ylabel("R$")
    plt.tight_layout()

    path = os.path.join("static", f"grafico_{uuid.uuid4().hex}.png")
    plt.savefig(path)
    plt.close()

    url = f"https://assistente-financeiro.onrender.com/{path}"
    twilio_client.messages.create(from_=twilio_number, to=request.form.get("From"), media_url=[url])

    return Response("<Response><Message>📊 Resumo enviado!</Message></Response>", mimetype="application/xml")

def gerar_resumo_categoria(responsavel):
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    df = df[df["RESPONSAVEL"] == responsavel]
    if df.empty:
        return Response("<Response><Message>ℹ️ Nenhum gasto encontrado.</Message></Response>", mimetype="application/xml")

    df["VALOR"] = df["VALOR"].str.replace("R$", "").str.replace(".", "").str.replace(",", ".").astype(float)
    resumo = df.groupby("CATEGORIA")["VALOR"].sum()

    plt.pie(resumo, labels=resumo.index, autopct="%1.1f%%")
    plt.title(f"Por categoria - {responsavel}")

    path = os.path.join("static", f"grafico_{uuid.uuid4().hex}.png")
    plt.savefig(path)
    plt.close()

    url = f"https://assistente-financeiro.onrender.com/{path}"
    twilio_client.messages.create(from_=twilio_number, to=request.form.get("From"), media_url=[url])
    return Response("<Response><Message>📊 Enviado com sucesso!</Message></Response>", mimetype="application/xml")

def gerar_resumo_geral():
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    df["VALOR"] = df["VALOR"].str.replace("R$", "").str.replace(".", "").str.replace(",", ".").astype(float)
    resumo = df.groupby("RESPONSAVEL")["VALOR"].sum().reset_index()

    plt.bar(resumo["RESPONSAVEL"], resumo["VALOR"])
    plt.title("Resumo Geral")
    plt.ylabel("R$")

    path = os.path.join("static", f"geral_{uuid.uuid4().hex}.png")
    plt.savefig(path)
    plt.close()

    url = f"https://assistente-financeiro.onrender.com/{path}"
    twilio_client.messages.create(from_=twilio_number, to=request.form.get("From"), media_url=[url])
    return Response("<Response><Message>📊 Resumo geral enviado!</Message></Response>", mimetype="application/xml")

def gerar_resumo_hoje():
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    df["DATA"] = pd.to_datetime(df["DATA"], dayfirst=True, errors="coerce")
    hoje = datetime.today().strftime("%d/%m/%Y")
    df = df[df["DATA"].dt.strftime("%d/%m/%Y") == hoje]

    if df.empty:
        return Response("<Response><Message>ℹ️ Nenhum gasto hoje.</Message></Response>", mimetype="application/xml")

    df["VALOR"] = df["VALOR"].str.replace("R$", "").str.replace(".", "").str.replace(",", ".").astype(float)
    resumo = df.groupby("RESPONSAVEL")["VALOR"].sum().reset_index()

    plt.bar(resumo["RESPONSAVEL"], resumo["VALOR"])
    plt.title("Gastos de Hoje")
    plt.ylabel("R$")

    path = os.path.join("static", f"hoje_{uuid.uuid4().hex}.png")
    plt.savefig(path)
    plt.close()

    url = f"https://assistente-financeiro.onrender.com/{path}"
    twilio_client.messages.create(from_=twilio_number, to=request.form.get("From"), media_url=[url])
    return Response("<Response><Message>📊 Resumo de hoje enviado!</Message></Response>", mimetype="application/xml")

if __name__ == "__main__":
    app.run(debug=True)
