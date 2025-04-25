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

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = os.environ.get("GOOGLE_CREDS_JSON")
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

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
            print("ÁUDIO RECONHECIDO (Whisper):", msg)
        except Exception as err:
            print("ERRO AO PROCESSAR O ÁUDIO:", err)
            import traceback
            traceback.print_exc()
            return Response("<Response><Message>❌ Houve um erro ao processar o áudio.</Message></Response>", mimetype="application/xml")
        finally:
            if os.path.exists(ogg_path): os.remove(ogg_path)
            if os.path.exists(wav_path): os.remove(wav_path)

    partes = [p.strip() for p in msg.split(",")]

    if len(partes) < 2:
        return Response("<Response><Message>❌ Formato inválido. Envie algo como: Thiago, hoje, mercado, compras, 150</Message></Response>", mimetype="application/xml")

    responsavel = partes[0].upper()
    msg_conteudo = ",".join(partes[1:])

    if "resumo por categoria" in msg_conteudo.lower():
        return gerar_resumo_categoria(responsavel)
    if "resumo geral" in msg_conteudo.lower():
        return gerar_resumo_geral()
    if "últimos gastos" in msg_conteudo.lower():
        return listar_ultimos_gastos(responsavel)
    if "resumo hoje" in msg_conteudo.lower():
        return gerar_resumo_hoje()
    if "resumo" in msg_conteudo.lower() and "semana" in msg_conteudo.lower():
        return gerar_resumo(responsavel, dias=7, titulo="Gastos da Semana por Pessoa")
    if "resumo" in msg_conteudo.lower() and "mês" in msg_conteudo.lower():
        return gerar_resumo(responsavel, dias=30, titulo="Gastos do Mês por Pessoa")

    if len(partes) != 5:
        return Response("<Response><Message>❌ Formato inválido. Envie: Thiago, 27/04, mercado, compras, 150</Message></Response>", mimetype="application/xml")

    _, data, categoria, descricao, valor = partes

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

    resposta_texto = (
        f"✅ Despesa registrada com sucesso!\n"
        f"📅 {data_formatada}\n"
        f"📂 {categoria}\n"
        f"📝 {descricao}\n"
        f"👤 {responsavel}\n"
        f"💸 {valor_formatado}"
    )

    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    audio_filename = os.path.join(static_dir, f"resposta_{uuid.uuid4().hex}.mp3")
    tts = gTTS(text=f"Despesa registrada com sucesso, {responsavel}! Categoria {categoria}, valor {valor_formatado}.", lang='pt')
    tts.save(audio_filename)
    ogg_filename = audio_filename.replace(".mp3", ".ogg")
    AudioSegment.from_file(audio_filename).export(ogg_filename, format="ogg")
    os.remove(audio_filename)

    audio_url = f"https://assistente-financeiro.onrender.com/{ogg_filename}"

    twilio_client.messages.create(body=resposta_texto, from_=twilio_number, to=from_number)
    twilio_client.messages.create(from_=twilio_number, to=from_number, media_url=[audio_url])

    return Response("<Response></Response>", mimetype="application/xml")

def gerar_resumo(responsavel, dias, titulo):
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    df["DATA"] = pd.to_datetime(df["DATA"], dayfirst=True, errors="coerce")
    hoje = datetime.today()
    periodo = hoje - pd.Timedelta(days=dias)
    df_periodo = df[df["DATA"] >= periodo]
    df_filtrado = df_periodo[df_periodo["RESPONSAVEL"] == responsavel.upper()]

    if df_filtrado.empty:
        return Response(f"<Response><Message>ℹ️ Nenhum gasto encontrado para {responsavel} nos últimos {dias} dias.</Message></Response>", mimetype="application/xml")

    resumo = df_filtrado.groupby("CATEGORIA")["VALOR"].apply(
        lambda x: pd.to_numeric(x.replace("R$", "", regex=True)
                                .str.replace(".", "", regex=False)
                                .str.replace(",", ".", regex=False), errors="coerce").sum()
    ).reset_index()

    plt.figure(figsize=(6, 4))
    plt.bar(resumo["CATEGORIA"], resumo["VALOR"])
    plt.title(titulo + f" - {responsavel.title()}")
    plt.ylabel("Total (R$)")
    plt.grid(axis='y', linestyle='--', alpha=0.5)

    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    grafico_path = os.path.join(static_dir, f"grafico_{uuid.uuid4().hex}.png")
    plt.tight_layout()
    plt.savefig(grafico_path)
    plt.close()

    grafico_url = f"https://assistente-financeiro.onrender.com/{grafico_path}"
    twilio_client.messages.create(from_=twilio_number, to=request.form.get("From"), media_url=[grafico_url])

    return Response(f"<Response><Message>📊 Resumo enviado para {responsavel}!</Message></Response>", mimetype="application/xml")

# Funções novas para resumo por categoria, geral e últimos gastos
def gerar_resumo_categoria(responsavel):
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    df = df[df["RESPONSAVEL"] == responsavel.upper()]

    if df.empty:
        return Response(f"<Response><Message>ℹ️ Nenhum gasto encontrado para {responsavel}.</Message></Response>", mimetype="application/xml")

    resumo = df.groupby("CATEGORIA")["VALOR"].apply(
        lambda x: pd.to_numeric(x.replace("R$", "", regex=True)
                                .str.replace(".", "", regex=False)
                                .str.replace(",", ".", regex=False), errors="coerce").sum()
    ).reset_index()

    plt.figure(figsize=(6, 4))
    plt.pie(resumo["VALOR"], labels=resumo["CATEGORIA"], autopct='%1.1f%%')
    plt.title(f"Resumo por Categoria - {responsavel.title()}")

    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    grafico_path = os.path.join(static_dir, f"grafico_{uuid.uuid4().hex}.png")
    plt.tight_layout()
    plt.savefig(grafico_path)
    plt.close()

    grafico_url = f"https://assistente-financeiro.onrender.com/{grafico_path}"
    twilio_client.messages.create(from_=twilio_number, to=request.form.get("From"), media_url=[grafico_url])

    return Response(f"<Response><Message>📊 Resumo de categoria enviado para {responsavel}!</Message></Response>", mimetype="application/xml")

def gerar_resumo_geral():
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)

    resumo = df.groupby("RESPONSAVEL")["VALOR"].apply(
        lambda x: pd.to_numeric(x.replace("R$", "", regex=True)
                                .str.replace(".", "", regex=False)
                                .str.replace(",", ".", regex=False), errors="coerce").sum()
    ).reset_index()

    plt.figure(figsize=(6, 4))
    plt.bar(resumo["RESPONSAVEL"], resumo["VALOR"])
    plt.title("Resumo Geral de Gastos")
    plt.ylabel("Total (R$)")
    plt.grid(axis='y', linestyle='--', alpha=0.5)

    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    grafico_path = os.path.join(static_dir, f"grafico_{uuid.uuid4().hex}.png")
    plt.tight_layout()
    plt.savefig(grafico_path)
    plt.close()

    grafico_url = f"https://assistente-financeiro.onrender.com/{grafico_path}"
    twilio_client.messages.create(from_=twilio_number, to=request.form.get("From"), media_url=[grafico_url])

    return Response("<Response><Message>📊 Resumo geral enviado!</Message></Response>", mimetype="application/xml")

def listar_ultimos_gastos(responsavel):
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    df = df[df["RESPONSAVEL"] == responsavel.upper()]
    df = df.sort_values("DATA", ascending=False)
    ultimos = df.head(5)

    if ultimos.empty:
        return Response(f"<Response><Message>ℹ️ Nenhuma despesa encontrada para {responsavel}.</Message></Response>", mimetype="application/xml")

    resposta = "\n".join([
        f"{row['DATA']} - {row['CATEGORIA']}: {row['VALOR']}"
        for idx, row in ultimos.iterrows()
    ])

    return Response(f"<Response><Message>🧾 Últimos gastos de {responsavel}:\n{resposta}</Message></Response>", mimetype="application/xml")

def gerar_resumo_hoje():
    dados = sheet.get_all_records()
    df = pd.DataFrame(dados)
    df["DATA"] = pd.to_datetime(df["DATA"], dayfirst=True, errors="coerce")
    hoje = datetime.today().strftime("%d/%m/%Y")
    df = df[df["DATA"].dt.strftime("%d/%m/%Y") == hoje]

    if df.empty:
        return Response("<Response><Message>ℹ️ Nenhum gasto registrado hoje.</Message></Response>", mimetype="application/xml")

    resumo = df.groupby("RESPONSAVEL")["VALOR"].apply(
        lambda x: pd.to_numeric(x.replace("R$", "", regex=True)
                                .str.replace(".", "", regex=False)
                                .str.replace(",", ".", regex=False), errors="coerce").sum()
    ).reset_index()

    plt.figure(figsize=(6, 4))
    plt.bar(resumo["RESPONSAVEL"], resumo["VALOR"])
    plt.title("Resumo de Gastos de Hoje")
    plt.ylabel("Total (R$)")
    plt.grid(axis='y', linestyle='--', alpha=0.5)

    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    grafico_path = os.path.join(static_dir, f"grafico_{uuid.uuid4().hex}.png")
    plt.tight_layout()
    plt.savefig(grafico_path)
    plt.close()

    grafico_url = f"https://assistente-financeiro.onrender.com/{grafico_path}"
    twilio_client.messages.create(from_=twilio_number, to=request.form.get("From"), media_url=[grafico_url])

    return Response("<Response><Message>📊 Resumo de hoje enviado!</Message></Response>", mimetype="application/xml")

if __name__ == '__main__':
    app.run(debug=True)
