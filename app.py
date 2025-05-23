from flask import Flask, request, Response, send_from_directory
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os, json, uuid, requests, logging
from twilio.rest import Client
from pydub import AudioSegment
from gtts import gTTS
import whisper
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler

# Inicialização do Flask
app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

# Diretório para arquivos estáticos
STATIC_DIR = "static"
BASE_URL = os.environ.get("BASE_URL", "https://assistente-financeiro.onrender.com")
os.makedirs(STATIC_DIR, exist_ok=True)

# Logger
logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)

# Autenticação com Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
json_creds = os.environ.get("GOOGLE_CREDS_JSON")
creds_dict = json.loads(json_creds)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key("1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
sheet = spreadsheet.sheet1

# Autenticação Twilio
twilio_sid = os.environ.get("TWILIO_SID")
twilio_token = os.environ.get("TWILIO_TOKEN")
twilio_number = os.environ.get("TWILIO_NUMBER")
twilio_client = Client(twilio_sid, twilio_token)

# Mapeamento de número para responsável
responsaveis_por_numero = {
    "whatsapp:+5511975220021": "LARISSA",
    "whatsapp:+5511977052756": "THIAGO"
}

def enviar_lembrete():
    try:
        contatos = [
            {
                "nome": "Larissa",
                "numero": "whatsapp:+5511975220021"
            },
            {
                "nome": "Thiago",
                "numero": "whatsapp:+5511977052756"
            }
        ]

        for contato in contatos:
            if contato["nome"].upper() == "LARISSA":
                mensagem = "🔔 Oi Larissa! Já cadastrou suas despesas de hoje? 📝"
            elif contato["nome"].upper() == "THIAGO":
                mensagem = "🔔 Oi Thiago! Já cadastrou suas despesas de hoje? 💸"
            else:
                mensagem = "🔔 Lembrete: não esqueça de registrar suas despesas hoje! 😉"

            twilio_client.messages.create(
                body=mensagem,
                from_=twilio_number,
                to=contato["numero"]
            )
            logger.info(f"Lembrete enviado para {contato['nome']} ({contato['numero']})")

    except Exception as e:
        logger.error(f"Erro ao enviar lembretes personalizados: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(enviar_lembrete, 'cron', hour=20, minute=0)  # Ajuste o horário aqui se quiser
scheduler.start()

# Funções auxiliares
def parse_valor(valor_str):
    try:
        return float(str(valor_str).replace("R$", "").replace(".", "").replace(",", ".").strip())
    except:
        return 0.0

def formatar_valor(valor):
    return f"R${valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

palavras_categoria = {
    "alimentação": ["mercado", "supermercado", "pão", "leite", "feira", "comida","alimentação","almoço","janta","jantar"],
    "transporte": ["uber", "99", "ônibus", "metro", "trem", "corrida", "combustível", "gasolina"],
    "lazer": ["cinema", "netflix", "bar", "show", "festa", "lazer"],
    "fixos": ["aluguel", "condominio", "energia", "água", "internet", "luz"],
    "saúde": ["farmácia", "higiene", "produto de limpeza", "remédio"]
}

def classificar_categoria(descricao):
    desc = descricao.lower()
    for categoria, palavras in palavras_categoria.items():
        if any(palavra in desc for palavra in palavras):
            return categoria.upper()
    return "OUTROS"

def gerar_audio(texto):
    """Gera um arquivo de áudio a partir do texto e retorna o caminho"""
    try:
        audio_id = uuid.uuid4().hex
        mp3_path = os.path.join(STATIC_DIR, f"audio_{audio_id}.mp3")
        tts = gTTS(text=texto, lang='pt')
        tts.save(mp3_path)
        logger.info(f"Áudio gerado com sucesso: {mp3_path}")
        return mp3_path
    except Exception as e:
        logger.error(f"Erro ao gerar áudio: {e}")
        return None

def enviar_mensagem_audio(from_number, texto):
    try:
        twilio_client.messages.create(
            body=texto,
            from_=twilio_number,
            to=from_number
        )
        mp3_path = gerar_audio(texto)
        if mp3_path:
            audio_url = f"{BASE_URL}/static/{os.path.basename(mp3_path)}"
            twilio_client.messages.create(
                from_=twilio_number,
                to=from_number,
                media_url=[audio_url]
            )
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")
        return Response("<Response></Response>", mimetype="application/xml")

import subprocess

def convert_to_wav(input_path, output_path):
    try:
        result = subprocess.run([
            "ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", output_path
        ], capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Erro na conversão com ffmpeg: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"Falha ao executar ffmpeg: {e}")
        return False

def processar_audio(media_url):
    try:
        audio_id = uuid.uuid4().hex
        audio_path = os.path.join(STATIC_DIR, f"received_{audio_id}.ogg")
        wav_path = os.path.join(STATIC_DIR, f"received_{audio_id}.wav")

        # Baixa o arquivo de áudio
        response = requests.get(media_url)
        if response.status_code != 200:
            logger.error(f"Erro ao baixar áudio: status {response.status_code}")
            return None

        with open(audio_path, "wb") as f:
            f.write(response.content)
        logger.info(f"Áudio salvo em: {audio_path}")

        # Converte para WAV
        sucesso = convert_to_wav(audio_path, wav_path)
        if not sucesso:
            return None

        # Transcreve com Whisper
        model = whisper.load_model("tiny")
        result = model.transcribe(wav_path, language="pt")
        texto = result["text"]

        os.remove(audio_path)
        os.remove(wav_path)

        logger.info(f"Transcrição: {texto}")
        return texto.strip()

    except Exception as e:
        logger.error(f"Erro ao processar áudio: {e}")
        return None

def gerar_grafico(tipo, titulo, dados, categorias=None, nome_arquivo=None):
    try:
        plt.figure(figsize=(10, 6))
        plt.title(titulo)
        plt.rcParams.update({'font.size': 14})

        if tipo == 'barra':
            plt.bar(categorias, dados)
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
        elif tipo == 'pizza':
            if len(categorias) > 6:
                top_indices = np.argsort(dados)[-5:]
                top_categorias = [categorias[i] for i in top_indices]
                top_dados = [dados[i] for i in top_indices]
                outros_valor = sum(d for i, d in enumerate(dados) if i not in top_indices)
                top_categorias.append('Outros')
                top_dados.append(outros_valor)
                categorias = top_categorias
                dados = top_dados
            plt.pie(dados, labels=categorias, autopct='%1.1f%%', startangle=90, shadow=True)
            plt.axis('equal')
        elif tipo == 'linha':
            plt.plot(categorias, dados, marker='o', linestyle='-')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()

        if not nome_arquivo:
            nome_arquivo = f"grafico_{uuid.uuid4().hex}.png"
        caminho_arquivo = os.path.join(STATIC_DIR, nome_arquivo)
        
        # Garantir que o diretório existe
        os.makedirs(os.path.dirname(caminho_arquivo), exist_ok=True)
        
        plt.savefig(caminho_arquivo, dpi=100, bbox_inches='tight')
        plt.close()
        logger.info(f"Gráfico gerado com sucesso: {caminho_arquivo}")
        return caminho_arquivo
    except Exception as e:
        logger.error(f"Erro ao gerar gráfico: {e}")
        return None

def enviar_mensagens_twilio(from_number, texto, grafico_url=None):
    """Função auxiliar para enviar mensagens via Twilio com tratamento de erros"""
    try:
        # Enviar mensagem de texto
        msg_text = twilio_client.messages.create(
            body=texto,
            from_=twilio_number,
            to=from_number
        )
        logger.info(f"Mensagem de texto enviada: {msg_text.sid}")
        
        # Se houver gráfico, enviar como mídia
        if grafico_url:
            msg_media = twilio_client.messages.create(
                body="📊 Gráfico de despesas",
                from_=twilio_number,
                to=from_number,
                media_url=[grafico_url]
            )
            logger.info(f"Mensagem com mídia enviada: {msg_media.sid}")
        
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar mensagens via Twilio: {e}")
        return False

def gerar_resumo_geral(from_number):
    try:
        logger.info(f"Gerando resumo geral para {from_number}")
        registros = sheet.get_all_records()
        total = 0.0
        categorias = {}

        for r in registros:
            valor = r.get("Valor", "0")
            valor_float = parse_valor(valor)
            total += valor_float
            categoria = r.get("Categoria", "OUTROS")
            categorias[categoria] = categorias.get(categoria, 0) + valor_float

        resumo = f"📊 Resumo Geral:\n\nTotal registrado: {formatar_valor(total)}"
        
        # Verificar se há categorias para evitar erro ao gerar gráfico vazio
        if not categorias:
            twilio_client.messages.create(
                body=resumo + "\n\nNão há despesas registradas.",
                from_=twilio_number,
                to=from_number
            )
            return Response("<Response></Response>", mimetype="application/xml")
            
        categorias_ordenadas = sorted(categorias.items(), key=lambda x: x[1], reverse=True)
        labels = [cat for cat, _ in categorias_ordenadas]
        valores = [val for _, val in categorias_ordenadas]
        
        grafico_path = gerar_grafico('pizza', 'Distribuição de Despesas', valores, labels)
        
        if not grafico_path:
            # Se falhar ao gerar o gráfico, enviar apenas o texto
            twilio_client.messages.create(body=resumo, from_=twilio_number, to=from_number)
            return Response("<Response></Response>", mimetype="application/xml")
            
        grafico_url = f"{BASE_URL}/static/{os.path.basename(grafico_path)}"
        
        # Enviar mensagens
        sucesso = enviar_mensagens_twilio(from_number, resumo, grafico_url)
        
        if not sucesso:
            # Tentar enviar apenas o texto como fallback
            twilio_client.messages.create(
                body=resumo + "\n\n(Não foi possível gerar o gráfico)",
                from_=twilio_number,
                to=from_number
            )
            
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro no resumo geral: {e}")
        try:
            twilio_client.messages.create(
                body="❌ Erro ao gerar resumo geral. Por favor, tente novamente mais tarde.",
                from_=twilio_number,
                to=from_number
            )
        except:
            pass
        return Response("<Response><Message>❌ Erro no resumo geral.</Message></Response>", mimetype="application/xml")

def gerar_resumo_hoje(from_number):
    try:
        logger.info(f"Gerando resumo de hoje para {from_number}")
        hoje = datetime.now().strftime("%d/%m/%Y")
        registros = sheet.get_all_records()
        total = 0.0
        categorias = {}

        for r in registros:
            if r.get("Data") == hoje:
                valor = parse_valor(r.get("Valor", "0"))
                total += valor
                categoria = r.get("Categoria", "OUTROS")
                categorias[categoria] = categorias.get(categoria, 0) + valor

        resumo = f"📅 Resumo de Hoje ({hoje}):\n\nTotal registrado: {formatar_valor(total)}"
        
        if not categorias:
            resumo += "\n\nNão há despesas registradas para hoje."
            twilio_client.messages.create(body=resumo, from_=twilio_number, to=from_number)
            return Response("<Response></Response>", mimetype="application/xml")
            
        categorias_ordenadas = sorted(categorias.items(), key=lambda x: x[1], reverse=True)
        labels = [cat for cat, _ in categorias_ordenadas]
        valores = [val for _, val in categorias_ordenadas]
        
        grafico_path = gerar_grafico('pizza', f'Despesas de Hoje ({hoje})', valores, labels)
        
        if not grafico_path:
            # Se falhar ao gerar o gráfico, enviar apenas o texto
            twilio_client.messages.create(body=resumo, from_=twilio_number, to=from_number)
            return Response("<Response></Response>", mimetype="application/xml")
            
        grafico_url = f"{BASE_URL}/static/{os.path.basename(grafico_path)}"
        
        # Enviar mensagens
        sucesso = enviar_mensagens_twilio(from_number, resumo, grafico_url)
        
        if not sucesso:
            # Tentar enviar apenas o texto como fallback
            twilio_client.messages.create(
                body=resumo + "\n\n(Não foi possível gerar o gráfico)",
                from_=twilio_number,
                to=from_number
            )
            
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro no resumo de hoje: {e}")
        try:
            twilio_client.messages.create(
                body="❌ Erro ao gerar resumo de hoje. Por favor, tente novamente mais tarde.",
                from_=twilio_number,
                to=from_number
            )
        except:
            pass
        return Response("<Response><Message>❌ Erro no resumo de hoje.</Message></Response>", mimetype="application/xml")

def gerar_resumo_categoria(from_number):
    try:
        logger.info(f"Gerando resumo por categoria para {from_number}")
        registros = sheet.get_all_records()
        categorias = {}
        total = 0.0

        for r in registros:
            valor = parse_valor(r.get("Valor", "0"))
            categoria = r.get("Categoria", "OUTROS")
            categorias[categoria] = categorias.get(categoria, 0) + valor
            total += valor

        if not categorias:
            twilio_client.messages.create(
                body="📂 Resumo por Categoria:\n\nNão há despesas registradas.",
                from_=twilio_number,
                to=from_number
            )
            return Response("<Response></Response>", mimetype="application/xml")

        resumo = "📂 Resumo por Categoria:\n\n"
        for cat, val in sorted(categorias.items(), key=lambda x: x[1], reverse=True):
            percentual = (val / total) * 100 if total > 0 else 0
            resumo += f"{cat}: {formatar_valor(val)} ({percentual:.1f}%)\n"
        resumo += f"\nTotal Geral: {formatar_valor(total)}"

        labels = list(categorias.keys())
        valores = list(categorias.values())
        
        grafico_path = gerar_grafico('pizza', 'Despesas por Categoria', valores, labels)
        
        if not grafico_path:
            # Se falhar ao gerar o gráfico, enviar apenas o texto
            twilio_client.messages.create(body=resumo, from_=twilio_number, to=from_number)
            return Response("<Response></Response>", mimetype="application/xml")
            
        grafico_url = f"{BASE_URL}/static/{os.path.basename(grafico_path)}"
        
        # Enviar mensagens
        sucesso = enviar_mensagens_twilio(from_number, resumo, grafico_url)
        
        if not sucesso:
            # Tentar enviar apenas o texto como fallback
            twilio_client.messages.create(
                body=resumo + "\n\n(Não foi possível gerar o gráfico)",
                from_=twilio_number,
                to=from_number
            )
            
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro no resumo por categoria: {e}")
        try:
            twilio_client.messages.create(
                body="❌ Erro ao gerar resumo por categoria. Por favor, tente novamente mais tarde.",
                from_=twilio_number,
                to=from_number
            )
        except:
            pass
        return Response("<Response><Message>❌ Erro no resumo por categoria.</Message></Response>", mimetype="application/xml")

def gerar_resumo_mensal(from_number):
    try:
        logger.info(f"Gerando resumo mensal para {from_number}")
        registros = sheet.get_all_records()
        hoje = datetime.now()
        dias = {}

        for r in registros:
            data_str = r.get("Data", "")
            if not data_str:
                continue
            try:
                data = datetime.strptime(data_str, "%d/%m/%Y")
                if data.month == hoje.month and data.year == hoje.year:
                    dia = data.day
                    valor = parse_valor(r.get("Valor", "0"))
                    dias[dia] = dias.get(dia, 0) + valor
            except Exception as e:
                logger.warning(f"Erro ao processar data '{data_str}': {e}")
                continue

        if not dias:
            twilio_client.messages.create(
                body=f"📅 Resumo do mês de {hoje.strftime('%B/%Y')}:\n\nNão há despesas registradas para este mês.",
                from_=twilio_number,
                to=from_number
            )
            return Response("<Response></Response>", mimetype="application/xml")

        labels = [f"{dia}/{hoje.month}" for dia in sorted(dias.keys())]
        valores = [dias[dia] for dia in sorted(dias.keys())]
        total = sum(valores)
        
        resumo = f"📅 Resumo do mês de {hoje.strftime('%B/%Y')}:\n\nTotal: {formatar_valor(total)}\nDias com despesas: {len(dias)}"
        
        if dias:
            dia_maior = max(dias, key=dias.get)
            resumo += f"\nDia com maior gasto: {dia_maior}/{hoje.month} - {formatar_valor(dias[dia_maior])}"

        grafico_path = gerar_grafico('linha', f'Despesas diárias - {hoje.strftime("%B/%Y")}', valores, labels)
        
        if not grafico_path:
            # Se falhar ao gerar o gráfico, enviar apenas o texto
            twilio_client.messages.create(body=resumo, from_=twilio_number, to=from_number)
            return Response("<Response></Response>", mimetype="application/xml")
            
        grafico_url = f"{BASE_URL}/static/{os.path.basename(grafico_path)}"
        
        # Enviar mensagens
        sucesso = enviar_mensagens_twilio(from_number, resumo, grafico_url)
        
        if not sucesso:
            # Tentar enviar apenas o texto como fallback
            twilio_client.messages.create(
                body=resumo + "\n\n(Não foi possível gerar o gráfico)",
                from_=twilio_number,
                to=from_number
            )
            
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro no resumo mensal: {e}")
        try:
            twilio_client.messages.create(
                body="❌ Erro ao gerar resumo mensal. Por favor, tente novamente mais tarde.",
                from_=twilio_number,
                to=from_number
            )
        except:
            pass
        return Response("<Response><Message>❌ Erro no resumo mensal.</Message></Response>", mimetype="application/xml")

def gerar_resumo(from_number, responsavel, dias, titulo):
    try:
        logger.info(f"Gerando {titulo} para {responsavel} (últimos {dias} dias)")
        registros = sheet.get_all_records()
        limite = datetime.now() - timedelta(days=dias)
        total = 0.0
        categorias = {}
        contador = 0
        
        # Log para depuração
        logger.info(f"Total de registros na planilha: {len(registros)}")

        for r in registros:
            # Log detalhado para depuração
            logger.debug(f"Processando registro: {r}")
            
            data_str = r.get("Data", "")
            if not data_str:
                continue
                
            try:
                try:
                    data = datetime.strptime(data_str, "%d/%m/%Y")
                except ValueError:
                    data = datetime.strptime(data_str, "%Y-%m-%d")
            except Exception as err:
                logger.warning(f"Formato de data inválido: {data_str} | Erro: {err}")
                continue

            # Normaliza o responsável para comparação
            resp_registro = r.get("Responsável", "").strip().upper()
            resp_solicitado = responsavel.strip().upper()
            
            # Log para depuração da comparação
            logger.debug(f"Comparando responsáveis: '{resp_registro}' com '{resp_solicitado}'")
            
            # Verifica se a data está no período e se o responsável corresponde
            if data >= limite and (resp_solicitado == "TODOS" or resp_registro == resp_solicitado):
                valor = parse_valor(r.get("Valor", "0"))
                total += valor
                categoria = r.get("Categoria", "OUTROS")
                categorias[categoria] = categorias.get(categoria, 0) + valor
                contador += 1
                logger.debug(f"Registro contabilizado: {data_str}, {resp_registro}, {valor}")
            else:
                logger.debug(f"Registro ignorado: data={data >= limite}, resp={resp_solicitado == 'TODOS' or resp_registro == resp_solicitado}")

        # Log do resultado final
        logger.info(f"Resumo para {responsavel}: {contador} registros, total {total}")
        
        resumo = f"📋 {titulo} ({responsavel.title()}):\n\nTotal: {formatar_valor(total)}\nRegistros: {contador}"

        if not categorias:
            resumo += "\n\nNão há despesas registradas neste período."
            twilio_client.messages.create(body=resumo, from_=twilio_number, to=from_number)
            return Response("<Response></Response>", mimetype="application/xml")

        categorias_ordenadas = sorted(categorias.items(), key=lambda x: x[1], reverse=True)
        labels = [cat for cat, _ in categorias_ordenadas]
        valores = [val for _, val in categorias_ordenadas]
        
        grafico_path = gerar_grafico('pizza', f'{titulo} - {responsavel.title()}', valores, labels)
        
        if not grafico_path:
            # Se falhar ao gerar o gráfico, enviar apenas o texto
            twilio_client.messages.create(body=resumo, from_=twilio_number, to=from_number)
            return Response("<Response></Response>", mimetype="application/xml")
            
        grafico_url = f"{BASE_URL}/static/{os.path.basename(grafico_path)}"
        
        # Enviar mensagens
        sucesso = enviar_mensagens_twilio(
            from_number, 
            resumo, 
            grafico_url
        )
        
        if not sucesso:
            # Tentar enviar apenas o texto como fallback
            twilio_client.messages.create(
                body=resumo + "\n\n(Não foi possível gerar o gráfico)",
                from_=twilio_number,
                to=from_number
            )
            
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro no resumo personalizado: {e}")
        try:
            twilio_client.messages.create(
                body=f"❌ Erro ao gerar {titulo.lower()}. Por favor, tente novamente mais tarde.",
                from_=twilio_number,
                to=from_number
            )
        except:
            pass
        return Response(f"<Response><Message>❌ Erro ao gerar {titulo.lower()}.</Message></Response>", mimetype="application/xml")
        
@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    try:
        return processar_mensagem()
    except Exception as e:
        logger.error(f"Erro interno: {e}")
        return Response("<Response><Message>❌ Erro interno ao processar.</Message></Response>", mimetype="application/xml")

def processar_mensagem():
    msg = request.form.get("Body", "")
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    logger.info(f"Mensagem recebida de {from_number}: {msg}")

    if media_url and "audio" in (media_type or ""):
        try:
            msg = processar_audio(media_url)
            if not msg:
                return Response("<Response><Message>❌ Não foi possível entender o áudio.</Message></Response>", mimetype="application/xml")
        except Exception as e:
            logger.error(f"Erro ao processar o áudio: {e}")
            return Response("<Response><Message>❌ Erro ao processar o áudio.</Message></Response>", mimetype="application/xml")

    msg = (msg or "").lower()

    # Comandos de ajuda e resumos
    if "ajuda" in msg:
        texto_ajuda = (
            "🤖 *Assistente Financeiro - Comandos disponíveis:*\n\n"
            "📌 *Registrar despesas:*\n"
            "`hoje, uber, 25`\n"
            "(ou use uma data como `27/04`)\n\n"
            "📊 *Ver resumos:*\n"
            "- resumo geral\n"
            "- resumo hoje\n"
            "- resumo do mês\n"
            "- resumo da semana\n"
            "- resumo por categoria\n"
            "- resumo da Larissa\n"
            "- resumo do Thiago"
        )
        twilio_client.messages.create(body=texto_ajuda, from_=twilio_number, to=from_number)
        return Response("<Response></Response>", mimetype="application/xml")

    if "resumo geral" in msg:
        return gerar_resumo_geral(from_number)
    if "resumo hoje" in msg:
        return gerar_resumo_hoje(from_number)
    if "resumo por categoria" in msg:
        return gerar_resumo_categoria(from_number)
    if "resumo do mês" in msg:
        return gerar_resumo_mensal(from_number)
    if "resumo da semana" in msg:
        return gerar_resumo(from_number, "TODOS", 7, "Resumo da Semana")
    if "resumo da larissa" in msg:
        return gerar_resumo(from_number, "LARISSA", 30, "Resumo do Mês")
    if "resumo do thiago" in msg:
        return gerar_resumo(from_number, "THIAGO", 30, "Resumo do Mês")

    # Registro de despesa simplificado: "hoje, descrição, valor"
    partes = [p.strip() for p in msg.split(",")]
    if len(partes) != 3:
        return Response("<Response><Message>❌ Formato inválido. Envie: hoje, descrição, valor</Message></Response>", mimetype="application/xml")

    data, descricao, valor = partes

    # Detecta o responsável pelo número
    # Detecta o responsável pelo número
    responsavel = responsaveis_por_numero.get(from_number, "DESCONHECIDO")

    # Trata a data
    if data.lower() == "hoje":
        data_formatada = datetime.today().strftime("%d/%m/%Y")
    else:
        try:
            data_formatada = datetime.strptime(data, "%d/%m").replace(year=datetime.today().year).strftime("%d/%m/%Y")
        except:
            data_formatada = datetime.today().strftime("%d/%m/%Y")

    # Classifica a categoria pela descrição
    categoria = classificar_categoria(descricao)

    # Normaliza os dados
    descricao = descricao.upper()
    responsavel = responsavel.upper()
    valor_float = parse_valor(valor)
    valor_formatado = formatar_valor(valor_float)

    # Salva na planilha
    sheet.append_row([data_formatada, categoria, descricao, responsavel, valor_formatado])

    # Envia a confirmação
    resposta = (
        f"✅ Despesa registrada!\n"
        f"📅 Data: {data_formatada}\n"
        f"📂 Categoria: {categoria}\n"
        f"📝 Descrição: {descricao}\n"
        f"👤 Responsável: {responsavel}\n"
        f"💰 Valor: {valor_formatado}"
    )

    twilio_client.messages.create(body=resposta, from_=twilio_number, to=from_number)
    return Response("<Response></Response>", mimetype="application/xml")

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory(STATIC_DIR, path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
