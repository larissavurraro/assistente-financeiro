#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from flask import Flask, request, Response, send_from_directory
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import json, uuid, requests
from twilio.rest import Client
from pydub import AudioSegment
from gtts import gTTS
import whisper
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

# Diretório para arquivos estáticos
STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)

# URL base da aplicação
BASE_URL = os.environ.get("BASE_URL", "https://assistente-financeiro.onrender.com")

# Configuração do Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = os.environ.get("GOOGLE_CREDS_JSON")
if not json_creds:
    logger.error("Variável de ambiente GOOGLE_CREDS_JSON não configurada")
    raise ValueError("Variável de ambiente GOOGLE_CREDS_JSON não configurada")
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client_gs = gspread.authorize(creds)
spreadsheet = client_gs.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

# Verifica a estrutura da planilha para garantir ordem correta
def verificar_colunas():
    # Obtém os cabeçalhos da planilha
    headers = sheet.row_values(1)
    expected_headers = ["Data", "Categoria", "Descrição", "Responsável", "Valor"]
    
    # Se os cabeçalhos não existirem, cria-os
    if not headers:
        sheet.append_row(expected_headers)
        return expected_headers
    
    # Retorna os cabeçalhos existentes
    return headers

# Obtém os cabeçalhos para uso no código
HEADERS = verificar_colunas()
# Índices das colunas para acesso correto
DATA_IDX = HEADERS.index("Data") if "Data" in HEADERS else 0
CATEGORIA_IDX = HEADERS.index("Categoria") if "Categoria" in HEADERS else 1
DESCRICAO_IDX = HEADERS.index("Descrição") if "Descrição" in HEADERS else 2
RESPONSAVEL_IDX = HEADERS.index("Responsável") if "Responsável" in HEADERS else 3
VALOR_IDX = HEADERS.index("Valor") if "Valor" in HEADERS else 4

# Configuração do Twilio
twilio_sid = os.environ.get("TWILIO_SID")
twilio_token = os.environ.get("TWILIO_TOKEN")
twilio_number = os.environ.get("TWILIO_NUMBER")
if not all([twilio_sid, twilio_token, twilio_number]):
    logger.error("Variáveis de ambiente do Twilio não configuradas corretamente")
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
    """Converte string de valor para float, tratando formatos brasileiros"""
    if not valor_str or valor_str == "":
        return 0.0
    
    try:
        # Remove caracteres não numéricos, exceto ponto e vírgula
        valor_limpo = ''.join(c for c in str(valor_str).replace("R$", "") if c.isdigit() or c in '.,')
        # Trata formato brasileiro (vírgula como separador decimal)
        if ',' in valor_limpo:
            # Se tiver mais de uma vírgula, considera apenas a última
            if valor_limpo.count(',') > 1:
                partes = valor_limpo.split(',')
                valor_limpo = ''.join(partes[:-1]).replace('.', '') + '.' + partes[-1]
            else:
                valor_limpo = valor_limpo.replace('.', '').replace(',', '.')
        return float(valor_limpo)
    except Exception as e:
        logger.error(f"Erro ao converter valor '{valor_str}': {e}")
        return 0.0

def formatar_valor(valor):
    """Formata um valor float para o formato brasileiro de moeda"""
    return f"R${valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# Rota para servir arquivos estáticos
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)

def gerar_audio(texto):
    """Gera um arquivo de áudio a partir do texto e retorna o caminho"""
    try:
        audio_id = uuid.uuid4().hex
        mp3_path = os.path.join(STATIC_DIR, f"audio_{audio_id}.mp3")
        
        # Gera o áudio com gTTS
        tts = gTTS(text=texto, lang='pt')
        tts.save(mp3_path)
        
        logger.info(f"Áudio gerado com sucesso: {mp3_path}")
        return mp3_path
    except Exception as e:
        logger.error(f"Erro ao gerar áudio: {e}")
        return None

def enviar_mensagem_audio(from_number, texto):
    """Envia mensagem de texto e áudio via Twilio"""
    try:
        # Primeiro, envia a mensagem de texto
        text_message = twilio_client.messages.create(
            body=texto,
            from_=twilio_number,
            to=from_number
        )
        logger.info(f"Mensagem de texto enviada: {text_message.sid}")
        
        # Tenta gerar e enviar o áudio
        mp3_path = gerar_audio(texto)
        if mp3_path:
            # Caminho público para o arquivo
            audio_url = f"{BASE_URL}/static/{os.path.basename(mp3_path)}"
            
            # Envia mensagem de áudio
            audio_message = twilio_client.messages.create(
                from_=twilio_number,
                to=from_number,
                media_url=[audio_url]
            )
            logger.info(f"Mensagem de áudio enviada: {audio_message.sid}")
        
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")
        # Tenta enviar apenas texto em caso de falha
        try:
            twilio_client.messages.create(
                body=f"{texto}\n\n(Não foi possível gerar áudio)",
                from_=twilio_number,
                to=from_number
            )
        except Exception as e2:
            logger.error(f"Erro ao enviar mensagem de fallback: {e2}")
        
        return Response("<Response></Response>", mimetype="application/xml")

def processar_audio(media_url):
    """Processa um arquivo de áudio e retorna o texto transcrito"""
    try:
        audio_id = uuid.uuid4().hex
        audio_path = os.path.join(STATIC_DIR, f"received_{audio_id}.ogg")
        wav_path = os.path.join(STATIC_DIR, f"received_{audio_id}.wav")
        
        # Baixa o arquivo de áudio
        response = requests.get(media_url)
        with open(audio_path, "wb") as f:
            f.write(response.content)
        
        logger.info(f"Áudio recebido e salvo: {audio_path}")
        
        # Converte para WAV (formato aceito pelo Whisper)
        AudioSegment.from_file(audio_path).export(wav_path, format="wav")
        logger.info(f"Áudio convertido para WAV: {wav_path}")
        
        # Carrega modelo pequeno para economizar recursos
        model = whisper.load_model("tiny")
        
        # Transcreve o áudio
        result = model.transcribe(wav_path, language="pt")
        texto = result["text"]
        
        logger.info(f"Transcrição concluída: {texto}")
        
        # Limpa arquivos temporários
        os.remove(audio_path)
        os.remove(wav_path)
        
        return texto
    except Exception as e:
        logger.error(f"Erro ao processar áudio: {e}")
        return None

def gerar_resumo_geral(from_number):
    try:
        registros = sheet.get_all_records()
        total = 0.0
        for r in registros:
            valor = r.get("Valor", "0")
            valor_float = parse_valor(valor)
            total += valor_float
            
        logger.info(f"Resumo geral - Total calculado: {total}")
        resumo = f"📊 Resumo Geral:\n\nTotal registrado: {formatar_valor(total)}"
        return enviar_mensagem_audio(from_number, resumo)
    except Exception as e:
        logger.error(f"Erro ao gerar resumo geral: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo geral.</Message></Response>", mimetype="application/xml")

def gerar_resumo_hoje(from_number):
    try:
        hoje = datetime.today().strftime("%d/%m/%Y")
        registros = sheet.get_all_records()
        total = 0.0
        
        for r in registros:
            if r.get("Data") == hoje:
                valor_float = parse_valor(r.get("Valor", "0"))
                total += valor_float
                logger.info(f"Registro de hoje: {r.get('Descrição')} - {r.get('Valor')} - Convertido: {valor_float}")
        
        logger.info(f"Resumo hoje - Total calculado: {total}")
        resumo = f"📅 Resumo de Hoje ({hoje}):\n\nTotal registrado: {formatar_valor(total)}"
        return enviar_mensagem_audio(from_number, resumo)
    except Exception as e:
        logger.error(f"Erro ao gerar resumo de hoje: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo de hoje.</Message></Response>", mimetype="application/xml")

def gerar_resumo_categoria(from_number):
    try:
        registros = sheet.get_all_records()
        categorias = {}
        total_geral = 0.0

        for r in registros:
            categoria = r.get("Categoria", "OUTROS")
            valor_str = r.get("Valor", "0")
            valor = parse_valor(valor_str)
            categorias[categoria] = categorias.get(categoria, 0.0) + valor
            total_geral += valor
            logger.info(f"Categoria {categoria}: {valor_str} -> {valor}")

        texto = "📂 Resumo por Categoria:\n\n"
        for categoria, total in sorted(categorias.items(), key=lambda x: x[1], reverse=True):
            percentual = (total / total_geral * 100) if total_geral > 0 else 0
            texto += f"{categoria}: {formatar_valor(total)} ({percentual:.1f}%)\n"
        
        texto += f"\nTotal Geral: {formatar_valor(total_geral)}"
        logger.info(f"Resumo categorias - Total calculado: {total_geral}")
        
        return enviar_mensagem_audio(from_number, texto)
    except Exception as e:
        logger.error(f"Erro ao gerar resumo por categoria: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo por categoria.</Message></Response>", mimetype="application/xml")

def gerar_resumo(from_number, responsavel, dias, titulo):
    try:
        registros = sheet.get_all_records()
        limite = datetime.today() - timedelta(days=dias)
        total = 0.0
        contagem = 0

        for r in registros:
            try:
                data_str = r.get("Data", "")
                if not data_str:
                    continue
                    
                data = datetime.strptime(data_str, "%d/%m/%Y")
                resp = r.get("Responsável", "").upper()
                
                if data >= limite and (responsavel.upper() == "TODOS" or resp == responsavel.upper()):
                    valor = parse_valor(r.get("Valor", "0"))
                    total += valor
                    contagem += 1
                    logger.info(f"Resumo {responsavel} - Registro: {data_str}, {resp}, {r.get('Valor')} -> {valor}")
            except Exception as err:
                logger.error(f"Erro ao processar registro para resumo: {err}")
                continue

        logger.info(f"Resumo {responsavel} - {dias} dias - Total calculado: {total} ({contagem} registros)")
        resumo = f"📋 {titulo} ({responsavel.title()}):\n\n"
        resumo += f"Total: {formatar_valor(total)}\n"
        resumo += f"Registros: {contagem}"
        
        return enviar_mensagem_audio(from_number, resumo)
    except Exception as e:
        logger.error(f"Erro ao gerar resumo {titulo}: {e}")
        return Response(f"<Response><Message>❌ Erro ao gerar o {titulo.lower()}.</Message></Response>", mimetype="application/xml")

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    try:
        return processar_mensagem()
    except Exception as e:
        logger.error(f"ERRO GERAL: {e}")
        return Response("<Response><Message>❌ Erro interno ao processar a mensagem.</Message></Response>", mimetype="application/xml")

def processar_mensagem():
    msg = request.form.get("Body", "")
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    logger.info(f"MENSAGEM RECEBIDA - De: {from_number}, Conteúdo: {msg}, Tipo de mídia: {media_type}")

    if not from_number:
        return Response("<Response><Message>❌ Número de origem não identificado.</Message></Response>", mimetype="application/xml")

    # Processamento de áudio
    if media_url and "audio" in media_type:
        logger.info(f"Processando áudio de {from_number}: {media_url}")
        texto_transcrito = processar_audio(media_url)
        
        if texto_transcrito:
            msg = texto_transcrito
            logger.info(f"Áudio transcrito com sucesso: {msg}")
        else:
            return Response("<Response><Message>❌ Não foi possível processar o áudio. Por favor, envie uma mensagem de texto.</Message></Response>", mimetype="application/xml")

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
        valor_float = parse_valor(valor)
        valor_formatado = formatar_valor(valor_float)
    except:
        valor_formatado = valor

    try:
        # Prepara a linha conforme a ordem das colunas na planilha
        nova_linha = [""] * len(HEADERS)
        nova_linha[DATA_IDX] = data_formatada
        nova_linha[CATEGORIA_IDX] = categoria
        nova_linha[DESCRICAO_IDX] = descricao
        nova_linha[RESPONSAVEL_IDX] = responsavel
        nova_linha[VALOR_IDX] = valor_formatado
        
        # Adiciona a despesa na planilha
        sheet.append_row(nova_linha)
        logger.info(f"Despesa cadastrada: {nova_linha}")

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
        logger.error(f"Erro ao cadastrar despesa: {e}")
        return Response("<Response><Message>❌ Erro ao cadastrar a despesa. Tente novamente.</Message></Response>", mimetype="application/xml")

@app.route("/")
def index():
    """Página inicial simples para verificar se o serviço está funcionando"""
    return """
    <html>
        <head><title>Assistente Financeiro</title></head>
        <body>
            <h1>Assistente Financeiro</h1>
            <p>Serviço ativo e funcionando!</p>
            <p>Hora atual do servidor: {}</p>
        </body>
    </html>
    """.format(datetime.now().strftime("%d/%m/%Y %H:%M:%S"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
