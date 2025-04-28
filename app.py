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

# Dicionário com palavras-chave para classificação automática de categoria
palavras_categoria = {
    "mercado": ["mercado", "supermercado", "pão", "leite", "feira", "comida"],
    "transporte": ["uber", "99", "ônibus", "metro", "trem", "corrida", "combustível", "gasolina"],
    "lazer": ["cinema", "netflix", "bar", "show", "festa", "lazer"],
    "moradia": ["aluguel", "condominio", "energia", "água", "internet", "luz"],
    "refeição": ["restaurante", "lanche", "jantar", "almoço", "hamburguer", "pizza"]
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
    except Exception as e:
        v = 0.0
    return v

def send_summary_response(summary_text, from_number):
    # Gera áudio da mensagem resumo
    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    audio_filename = os.path.join(static_dir, f"resposta_{uuid.uuid4().hex}.mp3")
    tts = gTTS(text=summary_text, lang='pt')
    tts.save(audio_filename)
    ogg_filename = audio_filename.replace(".mp3", ".ogg")
    AudioSegment.from_file(audio_filename).export(ogg_filename, format="ogg")
    os.remove(audio_filename)
    audio_url = f"https://assistente-financeiro.onrender.com/{ogg_filename}"
    
    # Envia a mensagem de texto e áudio via Twilio
    twilio_client.messages.create(body=summary_text, from_=twilio_number, to=from_number)
    twilio_client.messages.create(from_=twilio_number, to=from_number, media_url=[audio_url])
    return Response("<Response></Response>", mimetype="application/xml")

def gerar_resumo_geral(from_number):
    records = sheet.get_all_records()
    total = 0.0
    for r in records:
        total += parse_valor(r.get("Valor", "0"))
    summary_text = f"Resumo Geral:\nTotal de despesas registradas: R${total:,.2f}."
    return send_summary_response(summary_text, from_number)

def gerar_resumo_hoje(from_number):
    hoje = datetime.today().strftime("%d/%m/%Y")
    records = sheet.get_all_records()
    total = 0.0
    for r in records:
        if r.get("Data") == hoje:
            total += parse_valor(r.get("Valor", "0"))
    summary_text = f"Resumo de Hoje ({hoje}):\nTotal de despesas registradas: R${total:,.2f}."
    return send_summary_response(summary_text, from_number)

def gerar_resumo_categoria(from_number, categoria_param="todos"):
    records = sheet.get_all_records()
    categorias = {}
    for r in records:
        categoria = r.get("Categoria", "").upper()
        valor = parse_valor(r.get("Valor", "0"))
        if categoria not in categorias:
            categorias[categoria] = 0.0
        categorias[categoria] += valor
    summary_text = "Resumo por Categoria:\n"
    for cat, total in categorias.items():
        summary_text += f"{cat}: R${total:,.2f}\n"
    return send_summary_response(summary_text, from_number)

def gerar_resumo(from_number, responsavel, dias, titulo):
    records = sheet.get_all_records()
    total = 0.0
    limite = datetime.today() - timedelta(days=int(dias))
    for r in records:
        if r.get("Responsavel", "").upper() == responsavel.upper() or responsavel.upper() == "TODOS":
            try:
                data = datetime.strptime(r.get("Data", ""), "%d/%m/%Y")
            except Exception as e:
                continue
            if data >= limite:
                total += parse_valor(r.get("Valor", "0"))
    summary_text = f"{titulo} para {responsavel.upper()}:\nDespesas nos últimos {dias} dias: R${total:,.2f}."
    return send_summary_response(summary_text, from_number)

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

    # Processa áudio se enviado
    if media_url and media_type and "audio" in media_type:
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

    msg = msg.lower().strip()

    # Verifica se a mensagem é uma solicitação de resumo
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

    # Se não for um comando de resumo, trata o cadastro de despesa.
    # Formato esperado: Responsavel, Data, (Categoria desconsiderada), Descrição, Valor
    partes = [p.strip() for p in msg.split(",")]
    if len(partes) != 5:
        return Response("<Response><Message>❌ Formato inválido. Envie: Thiago, 27/04, mercado, compras, 150</Message></Response>", mimetype="application/xml")

    responsavel, data, _, descricao, valor = partes

    # Tratar a data
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

    # Registra a despesa na planilha
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

    # Geração do áudio de confirmação
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

if __name__ == "__main__":
    app.run(debug=True)
