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
if not json_creds:
    raise ValueError("Variável de ambiente GOOGLE_CREDS_JSON não configurada")
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
    raise ValueError("Variáveis de ambiente do Twilio não configuradas corretamente")
twilio_client = Client(twilio_sid, twilio_token)

# Palavras-chave para classificação automática
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
            return categoria.upper()
    return "OUTROS"

def parse_valor(valor_str):
    try:
        # Remove caracteres não numéricos, exceto ponto e vírgula
        valor_limpo = ''.join(c for c in valor_str.replace("R$", "") if c.isdigit() or c in '.,')
        v = float(valor_limpo.replace(".", "").replace(",", "."))
        return v
    except:
        return 0.0

def formatar_valor(valor):
    """Formata um valor float para o formato brasileiro de moeda"""
    return f"R${valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def enviar_mensagem_audio(from_number, texto):
    try:
        static_dir = "static"
        os.makedirs(static_dir, exist_ok=True)
        audio_id = uuid.uuid4().hex
        audio_filename = os.path.join(static_dir, f"resumo_{audio_id}.mp3")
        ogg_filename = os.path.join(static_dir, f"resumo_{audio_id}.ogg")

        tts = gTTS(text=texto, lang='pt')
        tts.save(audio_filename)
        
        # Converte para OGG
        AudioSegment.from_file(audio_filename).export(ogg_filename, format="ogg")
        
        # Remove o arquivo MP3 após conversão
        if os.path.exists(audio_filename):
            os.remove(audio_filename)

        # URL completa para o arquivo de áudio
        base_url = "https://assistente-financeiro.onrender.com"
        audio_url = f"{base_url}/{ogg_filename}"

        # Envia mensagem de texto
        twilio_client.messages.create(body=texto, from_=twilio_number, to=from_number)
        
        # Envia mensagem de áudio
        twilio_client.messages.create(from_=twilio_number, to=from_number, media_url=[audio_url])

        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        print(f"Erro ao enviar mensagem de áudio: {e}")
        # Envia apenas texto em caso de falha no áudio
        twilio_client.messages.create(body=f"{texto}\n\n(Não foi possível gerar áudio)", from_=twilio_number, to=from_number)
        return Response("<Response></Response>", mimetype="application/xml")

def gerar_resumo_geral(from_number):
    try:
        registros = sheet.get_all_records()
        total = sum(parse_valor(r.get("Valor", "0")) for r in registros)
        resumo = f"📊 Resumo Geral:\n\nTotal registrado: {formatar_valor(total)}"
        return enviar_mensagem_audio(from_number, resumo)
    except Exception as e:
        print(f"Erro ao gerar resumo geral: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo geral.</Message></Response>", mimetype="application/xml")

def gerar_resumo_hoje(from_number):
    try:
        hoje = datetime.today().strftime("%d/%m/%Y")
        registros = sheet.get_all_records()
        total = sum(parse_valor(r.get("Valor", "0")) for r in registros if r.get("Data") == hoje)
        resumo = f"📅 Resumo de Hoje ({hoje}):\n\nTotal registrado: {formatar_valor(total)}"
        return enviar_mensagem_audio(from_number, resumo)
    except Exception as e:
        print(f"Erro ao gerar resumo de hoje: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo de hoje.</Message></Response>", mimetype="application/xml")

def gerar_resumo_categoria(from_number):
    try:
        registros = sheet.get_all_records()
        categorias = {}

        for r in registros:
            categoria = r.get("Categoria", "OUTROS")
            valor = parse_valor(r.get("Valor", "0"))
            categorias[categoria] = categorias.get(categoria, 0.0) + valor

        texto = "📂 Resumo por Categoria:\n\n"
        for categoria, total in sorted(categorias.items(), key=lambda x: x[1], reverse=True):
            texto += f"{categoria}: {formatar_valor(total)}\n"

        return enviar_mensagem_audio(from_number, texto)
    except Exception as e:
        print(f"Erro ao gerar resumo por categoria: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo por categoria.</Message></Response>", mimetype="application/xml")

def gerar_resumo(from_number, responsavel, dias, titulo):
    try:
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

        resumo = f"📋 {titulo} ({responsavel.title()}):\n\nTotal: {formatar_valor(total)}"
        return enviar_mensagem_audio(from_number, resumo)
    except Exception as e:
        print(f"Erro ao gerar resumo {titulo}: {e}")
        return Response(f"<Response><Message>❌ Erro ao gerar o {titulo.lower()}.</Message></Response>", mimetype="application/xml")

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    try:
        return processar_mensagem()
    except Exception as e:
        print(f"ERRO GERAL: {e}")
        return Response("<Response><Message>❌ Erro interno ao processar a mensagem.</Message></Response>", mimetype="application/xml")

def processar_mensagem():
    msg = request.form.get("Body", "")
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    print(f"MENSAGEM ORIGINAL: {msg}")
    print(f"DE: {from_number}")

    if not from_number:
        return Response("<Response><Message>❌ Número de origem não identificado.</Message></Response>", mimetype="application/xml")

    # Processamento de áudio
    if media_url and "audio" in media_type:
        ogg_path = f"audio_{uuid.uuid4().hex}.ogg"
        wav_path = f"audio_{uuid.uuid4().hex}.wav"
        try:
            response = requests.get(media_url)
            with open(ogg_path, "wb") as f:
                f.write(response.content)
            AudioSegment.from_file(ogg_path).export(wav_path, format="wav")

            model = whisper.load_model("base")
            result = model.transcribe(wav_path, language="pt")
            msg = result["text"]
            print(f"ÁUDIO RECONHECIDO: {msg}")
        except Exception as err:
            print(f"ERRO AO PROCESSAR ÁUDIO: {err}")
            return Response("<Response><Message>❌ Erro ao processar o áudio. Por favor, envie uma mensagem de texto.</Message></Response>", mimetype="application/xml")
        finally:
            # Limpeza de arquivos temporários
            if os.path.exists(ogg_path): 
                os.remove(ogg_path)
            if os.path.exists(wav_path): 
                os.remove(wav_path)

    msg = msg.lower().strip()

    # Comandos de ajuda
    if msg in ["ajuda", "help", "comandos"]:
        texto_ajuda = (
            "📋 Comandos disponíveis:\n\n"
            "• resumo geral - Mostra o total de todas as despesas\n"
            "• resumo hoje - Mostra as despesas de hoje\n"
            "• resumo por categoria - Mostra despesas agrupadas por categoria\n"
            "• resumo da larissa - Mostra despesas da Larissa no último mês\n"
            "• resumo do thiago - Mostra despesas do Thiago no último mês\n"
            "• resumo do mês - Mostra despesas do mês atual\n"
            "• resumo da semana - Mostra despesas dos últimos 7 dias\n\n"
            "Para registrar uma despesa, envie:\n"
            "Nome, data, categoria, descrição, valor"
        )
        return enviar_mensagem_audio(from_number, texto_ajuda)

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
        return Response(
            "<Response><Message>❌ Formato inválido. Envie: Nome, data, categoria, descrição, valor\n\nExemplo: Thiago, hoje, alimentação, mercado, 150,00</Message></Response>", 
            mimetype="application/xml"
        )

    responsavel, data, categoria_input, descricao, valor = partes

    # Processamento da data
    if data.lower() == "hoje":
        data_formatada = datetime.today().strftime("%d/%m/%Y")
    else:
        try:
            # Tenta interpretar a data no formato dd/mm
            parsed_date = datetime.strptime(data, "%d/%m")
            parsed_date = parsed_date.replace(year=datetime.today().year)
            data_formatada = parsed_date.strftime("%d/%m/%Y")
        except:
            try:
                # Tenta interpretar outros formatos comuns
                for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %m %Y"]:
                    try:
                        parsed_date = datetime.strptime(data, fmt)
                        data_formatada = parsed_date.strftime("%d/%m/%Y")
                        break
                    except:
                        continue
                else:
                    # Se nenhum formato funcionar, usa a data de hoje
                    data_formatada = datetime.today().strftime("%d/%m/%Y")
            except:
                data_formatada = datetime.today().strftime("%d/%m/%Y")

    # Determina a categoria (usa a informada ou classifica automaticamente)
    if categoria_input.strip() and categoria_input.upper() != "OUTROS":
        categoria = categoria_input.upper()
    else:
        categoria = classificar_categoria(descricao)
    
    descricao = descricao.upper()
    responsavel = responsavel.upper()
    
    # Processamento do valor
    try:
        # Tenta converter para float, removendo caracteres não numéricos
        valor_limpo = ''.join(c for c in valor if c.isdigit() or c in '.,')
        valor_float = float(valor_limpo.replace(".", "").replace(",", "."))
        valor_formatado = formatar_valor(valor_float)
    except:
        valor_formatado = valor

    try:
        # Adiciona a despesa na planilha
        sheet.append_row([data_formatada, categoria, descricao, responsavel, valor_formatado])
        print(f"Despesa cadastrada: {[data_formatada, categoria, descricao, responsavel, valor_formatado]}")

        resposta_texto = (
            f"✅ Despesa registrada com sucesso!\n\n"
            f"📅 {data_formatada}\n"
            f"📂 {categoria}\n"
            f"📝 {descricao}\n"
            f"👤 {responsavel}\n"
            f"💸 {valor_formatado}"
        )

        return enviar_mensagem_audio(from_number, resposta_texto)
    except Exception as e:
        print(f"Erro ao cadastrar despesa: {e}")
        return Response("<Response><Message>❌ Erro ao cadastrar a despesa. Tente novamente.</Message></Response>", mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
