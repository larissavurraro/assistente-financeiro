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
import tempfile
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Necessário para ambientes sem interface gráfica
import numpy as np

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
    
    # Verifica se todos os cabeçalhos esperados estão presentes
    for header in expected_headers:
        if header not in headers:
            logger.warning(f"Cabeçalho '{header}' não encontrado na planilha. Estrutura atual: {headers}")
    
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

logger.info(f"Estrutura da planilha: {HEADERS}")
logger.info(f"Índices: Data={DATA_IDX}, Categoria={CATEGORIA_IDX}, Descrição={DESCRICAO_IDX}, Responsável={RESPONSAVEL_IDX}, Valor={VALOR_IDX}")

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
    "ALIMENTAÇÃO": ["mercado", "supermercado", "pão", "leite", "feira", "comida", "restaurante", "lanche", "jantar", "almoço", "hamburguer", "refrigerante", "pizza", "ifood", "delivery"],
    "TRANSPORTE": ["uber", "99", "ônibus", "metro", "metrô", "trem", "corrida", "combustível", "gasolina", "estacionamento", "pedágio", "taxi", "táxi"],
    "LAZER": ["cinema", "netflix", "bar", "show", "festa", "lazer", "passeio", "viagem", "hotel", "streaming", "disney", "prime", "hbo"],
    "GASTOS FIXOS": ["aluguel", "condominio", "condomínio", "energia", "água", "internet", "luz", "iptu", "seguro", "parcela", "prestação", "financiamento"],
    "HIGIENE E SAÚDE": ["farmácia", "remédio", "hidratante", "médico", "consulta", "exame", "hospital", "dentista", "vitamina", "suplemento", "academia"]
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
        valor_limpo = ''.join(c for c in str(valor_str).replace("R$", "").strip() if c.isdigit() or c in '.,')
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

def gerar_grafico(tipo, titulo, dados, categorias=None, nome_arquivo=None):
    """
    Gera um gráfico e salva como imagem
    
    Args:
        tipo: 'barra', 'pizza', 'linha'
        titulo: Título do gráfico
        dados: Lista de valores
        categorias: Lista de categorias/labels
        nome_arquivo: Nome do arquivo (opcional)
        
    Returns:
        Caminho para o arquivo de imagem
    """
    plt.figure(figsize=(10, 6))
    plt.title(titulo)
    
    # Configurações para melhor visualização em dispositivos móveis
    plt.rcParams.update({'font.size': 14})
    
    if tipo == 'barra':
        if categorias:
            plt.bar(categorias, dados, color='skyblue')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
        else:
            plt.bar(range(len(dados)), dados, color='skyblue')
    
    elif tipo == 'pizza':
        if categorias:
            # Limita a 6 categorias para melhor visualização, agrupando o resto como "Outros"
            if len(categorias) > 6:
                top_indices = np.argsort(dados)[-5:]  # Top 5 categorias
                top_categorias = [categorias[i] for i in top_indices]
                top_dados = [dados[i] for i in top_indices]
                
                outros_valor = sum(d for i, d in enumerate(dados) if i not in top_indices)
                top_categorias.append('Outros')
                top_dados.append(outros_valor)
                
                categorias = top_categorias
                dados = top_dados
            
            plt.pie(dados, labels=categorias, autopct='%1.1f%%', startangle=90, shadow=True)
            plt.axis('equal')  # Garante que o gráfico de pizza seja circular
        else:
            plt.pie(dados, autopct='%1.1f%%', startangle=90, shadow=True)
            plt.axis('equal')
    
    elif tipo == 'linha':
        if categorias:
            plt.plot(categorias, dados, marker='o', linestyle='-', color='blue')
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
        else:
            plt.plot(dados, marker='o', linestyle='-', color='blue')
    
    # Gera um nome de arquivo único se não for fornecido
    if not nome_arquivo:
        nome_arquivo = f"grafico_{uuid.uuid4().hex}.png"
    
    caminho_arquivo = os.path.join(STATIC_DIR, nome_arquivo)
    plt.savefig(caminho_arquivo, dpi=100, bbox_inches='tight')
    plt.close()
    
    logger.info(f"Gráfico gerado: {caminho_arquivo}")
    return caminho_arquivo

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
        # Usa arquivos temporários para evitar problemas de permissão
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as temp_ogg:
            audio_path = temp_ogg.name
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
            wav_path = temp_wav.name
        
        # Baixa o arquivo de áudio
        response = requests.get(media_url)
        with open(audio_path, "wb") as f:
            f.write(response.content)
        
        logger.info(f"Áudio recebido e salvo: {audio_path}")
        
        # Tenta diferentes formatos de conversão
        try:
            # Tenta converter como formato padrão
            AudioSegment.from_file(audio_path).export(wav_path, format="wav")
            logger.info(f"Áudio convertido para WAV: {wav_path}")
        except Exception as e:
            logger.error(f"Erro na conversão padrão: {e}")
            try:
                # Tenta como MP4
                AudioSegment.from_file(audio_path, format="mp4").export(wav_path, format="wav")
                logger.info("Conversão alternativa bem-sucedida (mp4 -> wav)")
            except Exception as e2:
                logger.error(f"Erro na conversão MP4: {e2}")
                try:
                    # Tenta como MP3
                    AudioSegment.from_file(audio_path, format="mp3").export(wav_path, format="wav")
                    logger.info("Conversão alternativa bem-sucedida (mp3 -> wav)")
                except Exception as e3:
                    logger.error(f"Todas as tentativas de conversão falharam: {e3}")
                    return None
        
        # Carrega modelo pequeno para economizar recursos
        model = whisper.load_model("tiny")
        
        # Transcreve o áudio
        result = model.transcribe(wav_path, language="pt")
        texto = result["text"]
        
        logger.info(f"Transcrição concluída: {texto}")
        
        # Limpa arquivos temporários
        try:
            os.remove(audio_path)
            os.remove(wav_path)
        except Exception as e:
            logger.error(f"Erro ao limpar arquivos temporários: {e}")
        
        return texto
    except Exception as e:
        logger.error(f"Erro ao processar áudio: {e}")
        return None

def gerar_resumo_geral(from_number):
    try:
        registros = sheet.get_all_records()
        total = 0.0
        categorias = {}
        
        for r in registros:
            valor = r.get("Valor", "0")
            valor_float = parse_valor(valor)
            total += valor_float
            
            # Agrupa por categoria para o gráfico
            categoria = r.get("Categoria", "OUTROS")
            if categoria not in categorias:
                categorias[categoria] = 0
            categorias[categoria] += valor_float
            
        logger.info(f"Resumo geral - Total calculado: {total}")
        resumo = f"📊 Resumo Geral:\n\nTotal registrado: {formatar_valor(total)}"
        
        # Prepara dados para o gráfico
        categorias_ordenadas = [cat for cat, val in sorted(categorias.items(), key=lambda x: x[1], reverse=True)]
        valores_ordenados = [val for cat, val in sorted(categorias.items(), key=lambda x: x[1], reverse=True)]
        
        # Gera o gráfico
        caminho_grafico = gerar_grafico('pizza', 'Distribuição de Despesas', 
                                      valores_ordenados, categorias_ordenadas,
                                      f"geral_{uuid.uuid4().hex}.png")
        
        # Envia a mensagem de texto
        text_message = twilio_client.messages.create(
            body=resumo,
            from_=twilio_number,
            to=from_number
        )
        logger.info(f"Mensagem de texto enviada: {text_message.sid}")
        
        # Envia o gráfico
        grafico_url = f"{BASE_URL}/static/{os.path.basename(caminho_grafico)}"
        grafico_message = twilio_client.messages.create(
            body="📊 Distribuição de despesas por categoria",
            from_=twilio_number,
            to=from_number,
            media_url=[grafico_url]
        )
        logger.info(f"Gráfico enviado: {grafico_message.sid}")
        
        # Tenta gerar e enviar o áudio
        mp3_path = gerar_audio(resumo)
        if mp3_path:
            audio_url = f"{BASE_URL}/static/{os.path.basename(mp3_path)}"
            audio_message = twilio_client.messages.create(
                body="🔊 Resumo em áudio",
                from_=twilio_number,
                to=from_number,
                media_url=[audio_url]
            )
            logger.info(f"Mensagem de áudio enviada: {audio_message.sid}")
        
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro ao gerar resumo geral: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo geral.</Message></Response>", mimetype="application/xml")

def gerar_resumo_hoje(from_number):
    try:
        hoje = datetime.now().strftime("%d/%m/%Y")  # Usa now() em vez de today()
        registros = sheet.get_all_records()
        total = 0.0
        categorias_hoje = {}
        
        for r in registros:
            if r.get("Data") == hoje:
                valor_float = parse_valor(r.get("Valor", "0"))
                total += valor_float
                
                # Agrupa por categoria para o gráfico
                categoria = r.get("Categoria", "OUTROS")
                if categoria not in categorias_hoje:
                    categorias_hoje[categoria] = 0
                categorias_hoje[categoria] += valor_float
                
                logger.info(f"Registro de hoje: {r.get('Descrição')} - {r.get('Valor')} - Convertido: {valor_float}")
        
        logger.info(f"Resumo hoje - Total calculado: {total}")
        resumo = f"📅 Resumo de Hoje ({hoje}):\n\nTotal registrado: {formatar_valor(total)}"
        
        # Prepara dados para o gráfico
        if categorias_hoje:
            categorias_ordenadas = [cat for cat, val in sorted(categorias_hoje.items(), key=lambda x: x[1], reverse=True)]
            valores_ordenados = [val for cat, val in sorted(categorias_hoje.items(), key=lambda x: x[1], reverse=True)]
            
            # Gera o gráfico
            caminho_grafico = gerar_grafico('pizza', f'Despesas de Hoje ({hoje})', 
                                          valores_ordenados, categorias_ordenadas,
                                          f"hoje_{uuid.uuid4().hex}.png")
            
            # Envia a mensagem de texto
            text_message = twilio_client.messages.create(
                body=resumo,
                from_=twilio_number,
                to=from_number
            )
            logger.info(f"Mensagem de texto enviada: {text_message.sid}")
            
            # Envia o gráfico
            grafico_url = f"{BASE_URL}/static/{os.path.basename(caminho_grafico)}"
            grafico_message = twilio_client.messages.create(
                body="📊 Despesas de hoje por categoria",
                from_=twilio_number,
                to=from_number,
                media_url=[grafico_url]
            )
            logger.info(f"Gráfico enviado: {grafico_message.sid}")
        else:
            # Se não houver despesas hoje, apenas envia a mensagem de texto
            text_message = twilio_client.messages.create(
                body=f"{resumo}\n\nNão há despesas registradas para hoje.",
                from_=twilio_number,
                to=from_number
            )
            logger.info(f"Mensagem de texto enviada: {text_message.sid}")
        
        # Tenta gerar e enviar o áudio
        mp3_path = gerar_audio(resumo)
        if mp3_path:
            audio_url = f"{BASE_URL}/static/{os.path.basename(mp3_path)}"
            audio_message = twilio_client.messages.create(
                body="🔊 Resumo em áudio",
                from_=twilio_number,
                to=from_number,
                media_url=[audio_url]
            )
            logger.info(f"Mensagem de áudio enviada: {audio_message.sid}")
        
        return Response("<Response></Response>", mimetype="application/xml")
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
        
        # Prepara dados para o gráfico
        categorias_ordenadas = [cat for cat, val in sorted(categorias.items(), key=lambda x: x[1], reverse=True)]
        valores_ordenados = [val for cat, val in sorted(categorias.items(), key=lambda x: x[1], reverse=True)]
        
        for categoria, total in sorted(categorias.items(), key=lambda x: x[1], reverse=True):
            percentual = (total / total_geral * 100) if total_geral > 0 else 0
            texto += f"{categoria}: {formatar_valor(total)} ({percentual:.1f}%)\n"
        
        texto += f"\nTotal Geral: {formatar_valor(total_geral)}"
        logger.info(f"Resumo categorias - Total calculado: {total_geral}")
        
        # Gera o gráfico
        caminho_grafico = gerar_grafico('pizza', 'Despesas por Categoria', 
                                      valores_ordenados, categorias_ordenadas,
                                      f"categorias_{uuid.uuid4().hex}.png")
        
        # Envia a mensagem de texto
        text_message = twilio_client.messages.create(
            body=texto,
            from_=twilio_number,
            to=from_number
        )
        logger.info(f"Mensagem de texto enviada: {text_message.sid}")
        
        # Envia o gráfico
        grafico_url = f"{BASE_URL}/static/{os.path.basename(caminho_grafico)}"
        grafico_message = twilio_client.messages.create(
            body="📊 Gráfico de despesas por categoria",
            from_=twilio_number,
            to=from_number,
            media_url=[grafico_url]
        )
        logger.info(f"Gráfico enviado: {grafico_message.sid}")
        
        # Tenta gerar e enviar o áudio
        mp3_path = gerar_audio(texto)
        if mp3_path:
            audio_url = f"{BASE_URL}/static/{os.path.basename(mp3_path)}"
            audio_message = twilio_client.messages.create(
                body="🔊 Resumo em áudio",
                from_=twilio_number,
                to=from_number,
                media_url=[audio_url]
            )
            logger.info(f"Mensagem de áudio enviada: {audio_message.sid}")
        
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro ao gerar resumo por categoria: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo por categoria.</Message></Response>", mimetype="application/xml")

def gerar_resumo_mensal(from_number):
    try:
        registros = sheet.get_all_records()
        hoje = datetime.now()
        primeiro_dia_mes = hoje.replace(day=1)
        
        # Agrupa por dia do mês
        dias = {}
        for r in registros:
            try:
                data_str = r.get("Data", "")
                if not data_str:
                    continue
                
                data = datetime.strptime(data_str, "%d/%m/%Y")
                
                # Verifica se é do mês atual
                if data.month == hoje.month and data.year == hoje.year:
                    dia = data.day
                    valor = parse_valor(r.get("Valor", "0"))
                    
                    if dia not in dias:
                        dias[dia] = 0
                    dias[dia] += valor
            except Exception as err:
                logger.error(f"Erro ao processar registro para resumo mensal: {err}")
                continue
        
        # Prepara dados para o gráfico
        dias_ordenados = sorted(dias.keys())
        valores_diarios = [dias.get(dia, 0) for dia in dias_ordenados]
        labels_dias = [f"{dia}/{hoje.month}" for dia in dias_ordenados]
        
        # Calcula total do mês
        total_mes = sum(valores_diarios)
        
        # Gera o texto do resumo
        texto = f"📅 Resumo do mês de {hoje.strftime('%B/%Y')}:\n\n"
        texto += f"Total até agora: {formatar_valor(total_mes)}\n"
        texto += f"Dias com despesas: {len(dias_ordenados)}\n"
        
        if dias_ordenados:
            dia_maior_gasto = max(dias.items(), key=lambda x: x[1])
            texto += f"Dia com maior gasto: {dia_maior_gasto[0]}/{hoje.month} - {formatar_valor(dia_maior_gasto[1])}\n"
        
        # Gera o gráfico
        caminho_grafico = gerar_grafico('linha', f'Despesas diárias - {hoje.strftime("%B/%Y")}', 
                                      valores_diarios, labels_dias,
                                      f"mensal_{uuid.uuid4().hex}.png")
        
        # Envia a mensagem de texto
        text_message = twilio_client.messages.create(
            body=texto,
            from_=twilio_number,
            to=from_number
        )
        logger.info(f"Mensagem de texto enviada: {text_message.sid}")
        
        # Envia o gráfico
        grafico_url = f"{BASE_URL}/static/{os.path.basename(caminho_grafico)}"
        grafico_message = twilio_client.messages.create(
            body="📊 Gráfico de despesas diárias do mês",
            from_=twilio_number,
            to=from_number,
            media_url=[grafico_url]
        )
        logger.info(f"Gráfico enviado: {grafico_message.sid}")
        
        # Tenta gerar e enviar o áudio
        mp3_path = gerar_audio(texto)
        if mp3_path:
            audio_url = f"{BASE_URL}/static/{os.path.basename(mp3_path)}"
                        audio_message = twilio_client.messages.create(
                body="🔊 Resumo em áudio",
                from_=twilio_number,
                to=from_number,
                media_url=[audio_url]
            )
            logger.info(f"Mensagem de áudio enviada: {audio_message.sid}")
        
        return Response("<Response></Response>", mimetype="application/xml")
    except Exception as e:
        logger.error(f"Erro ao gerar resumo mensal: {e}")
        return Response("<Response><Message>❌ Erro ao gerar o resumo mensal.</Message></Response>", mimetype="application/xml")

def gerar_resumo(from_number, responsavel, dias, titulo):
    try:
        registros = sheet.get_all_records()
        limite = datetime.now() - timedelta(days=dias)  # Usa now() em vez de today()
        total = 0.0
        contagem = 0
        categorias_resp = {}
        
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
                    
                    # Agrupa por categoria para o gráfico
                    categoria = r.get("Categoria", "OUTROS")
                    if categoria not in categorias_resp:
                        categorias_resp[categoria] = 0
                    categorias_resp[categoria] += valor
                    
                    logger.info(f"Resumo {responsavel} - Registro: {data_str}, {resp}, {r.get('Valor')} -> {valor}")
            except Exception as err:
                logger.error(f"Erro ao processar registro para resumo: {err}")
                continue

        logger.info(f"Resumo {responsavel} - {dias} dias - Total calculado: {total} ({contagem} registros)")
        resumo = f"📋 {titulo} ({responsavel.title()}):\n\n"
        resumo += f"Total: {formatar_valor(total)}\n"
        resumo += f"Registros: {contagem}"
        
        # Prepara dados para o gráfico
        if categorias_resp:
            categorias_ordenadas = [cat for cat, val in sorted(categorias_resp.items(), key=lambda x: x[1], reverse=True)]
            valores_ordenados = [val for cat, val in sorted(categorias_resp.items(), key=lambda x: x[1], reverse=True)]
            
            # Gera o gráfico
            caminho_grafico = gerar_grafico('pizza', f'{titulo} - {responsavel.title()}', 
                                          valores_ordenados, categorias_ordenadas,
                                          f"resumo_{responsavel.lower()}_{uuid.uuid4().hex}.png")
            
            # Envia a mensagem de texto
            text_message = twilio_client.messages.create(
                body=resumo,
                from_=twilio_number,
                to=from_number
            )
            logger.info(f"Mensagem de texto enviada: {text_message.sid}")
            
            # Envia o gráfico
            grafico_url = f"{BASE_URL}/static/{os.path.basename(caminho_grafico)}"
            grafico_message = twilio_client.messages.create(
                body=f"📊 Gráfico de despesas - {titulo} ({responsavel.title()})",
                from_=twilio_number,
                to=from_number,
                media_url=[grafico_url]
            )
            logger.info(f"Gráfico enviado: {grafico_message.sid}")
        else:
            # Se não houver despesas, apenas envia a mensagem de texto
            text_message = twilio_client.messages.create(
                body=resumo,
                from_=twilio_number,
                to=from_number
            )
            logger.info(f"Mensagem de texto enviada: {text_message.sid}")
        
        # Tenta gerar e enviar o áudio
        mp3_path = gerar_audio(resumo)
        if mp3_path:
            audio_url = f"{BASE_URL}/static/{os.path.basename(mp3_path)}"
            audio_message = twilio_client.messages.create(
                body="🔊 Resumo em áudio",
                from_=twilio_number,
                to=from_number,
                media_url=[audio_url]
            )
            logger.info(f"Mensagem de áudio enviada: {audio_message.sid}")
        
        return Response("<Response></Response>", mimetype="application/xml")
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
    msg = request.form.get("Body", "").strip()  # Adiciona strip() aqui para remover espaços
    from_number = request.form.get("From")
    media_url = request.form.get("MediaUrl0")
    media_type = request.form.get("MediaContentType0")

    # Log detalhado de todos os parâmetros recebidos
    logger.info(f"MENSAGEM RECEBIDA - De: {from_number}")
    logger.info(f"Conteúdo: {msg}")
    logger.info(f"Tipo de mídia: {media_type}")
    logger.info(f"URL da mídia: {media_url}")
    
    # Log de todos os parâmetros para depuração
    for key, value in request.form.items():
        logger.info(f"Parâmetro: {key} = {value}")

    if not from_number:
        return Response("<Response><Message>❌ Número de origem não identificado.</Message></Response>", mimetype="application/xml")

    # Processamento de áudio
    if media_url and media_type and ("audio" in media_type.lower() or "voice" in media_type.lower()):
        logger.info(f"Processando áudio de {from_number}: {media_url}")
        texto_transcrito = processar_audio(media_url)
        
        if texto_transcrito:
            msg = texto_transcrito.strip()
            logger.info(f"Áudio transcrito com sucesso: {msg}")
            # Envia confirmação da transcrição para o usuário
            twilio_client.messages.create(
                body=f"🎤 Transcrição do áudio:\n\n"{msg}"",
                from_=twilio_number,
                to=from_number
            )
        else:
            return Response("<Response><Message>❌ Não foi possível processar o áudio. Por favor, envie uma mensagem de texto.</Message></Response>", mimetype="application/xml")

    msg = msg.lower().strip()

    # Comandos de ajuda
    if msg in ["ajuda", "help", "comandos"]:
        texto_ajuda = (
            "📋 Comandos disponíveis:\n\n"
            "• resumo geral - Mostra o total de todas as despesas (com gráfico)\n"
            "• resumo hoje - Mostra as despesas de hoje (com gráfico)\n"
            "• resumo por categoria - Mostra despesas agrupadas por categoria (com gráfico)\n"
            "• resumo mensal - Mostra as despesas diárias do mês atual (com gráfico)\n"
            "• resumo da larissa - Mostra despesas da Larissa no último mês (com gráfico)\n"
            "• resumo do thiago - Mostra despesas do Thiago no último mês (com gráfico)\n"
            "• resumo do mês - Mostra despesas do mês atual (com gráfico)\n"
            "• resumo da semana - Mostra despesas dos últimos 7 dias (com gráfico)\n\n"
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
    if "resumo mensal" in msg:
        return gerar_resumo_mensal(from_number)
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
    logger.info(f"Dados recebidos: Responsável={responsavel}, Data={data}, Categoria={categoria_input}, Descrição={descricao}, Valor={valor}")

    # Processamento da data
    if data.lower() == "hoje":
        data_formatada = datetime.now().strftime("%d/%m/%Y")  # Usa now() em vez de today()
    else:
        try:
            # Tenta interpretar a data no formato dd/mm
            parsed_date = datetime.strptime(data, "%d/%m")
            parsed_date = parsed_date.replace(year=datetime.now().year)
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
                    data_formatada = datetime.now().strftime("%d/%m/%Y")
            except:
                data_formatada = datetime.now().strftime("%d/%m/%Y")
    
    logger.info(f"Data formatada: {data_formatada}")

    # Determina a categoria (usa a informada ou classifica automaticamente)
    if categoria_input.strip() and categoria_input.upper() != "OUTROS":
        categoria = categoria_input.upper()
    else:
        categoria = classificar_categoria(descricao)
    
    logger.info(f"Categoria determinada: {categoria}")
    
    descricao = descricao.upper()
    responsavel = responsavel.upper()
    
    # Processamento do valor
    try:
        valor_float = parse_valor(valor)
        valor_formatado = formatar_valor(valor_float)
        logger.info(f"Valor processado: {valor} -> {valor_float} -> {valor_formatado}")
    except:
        valor_formatado = valor
        logger.warning(f"Falha ao processar valor: {valor}")

    try:
        # Prepara a linha conforme a ordem das colunas na planilha
        nova_linha = [""] * len(HEADERS)
        nova_linha[DATA_IDX] = data_formatada
        nova_linha[CATEGORIA_IDX] = categoria
        nova_linha[DESCRICAO_IDX] = descricao
        nova_linha[RESPONSAVEL_IDX] = responsavel
        nova_linha[VALOR_IDX] = valor_formatado
        
        # Log detalhado da linha que será inserida
        logger.info(f"Nova linha preparada: {nova_linha}")
        logger.info(f"Índices usados: Data={DATA_IDX}, Categoria={CATEGORIA_IDX}, Descrição={DESCRICAO_IDX}, Responsável={RESPONSAVEL_IDX}, Valor={VALOR_IDX}")
        
        # Adiciona a despesa na planilha
        sheet.append_row(nova_linha)
        logger.info(f"Despesa cadastrada com sucesso: {nova_linha}")

        resposta_texto = (
            f"✅ Despesa registrada com sucesso!\n\n"
            f"📅 Data: {data_formatada}\n"
            f"📂 Categoria: {categoria}\n"
            f"📝 Descrição: {descricao}\n"
            f"👤 Responsável: {responsavel}\n"
            f"💸 Valor: {valor_formatado}"
        )

        return enviar_mensagem_audio(from_number, resposta_texto)
    except Exception as e:
        logger.error(f"Erro ao cadastrar despesa: {e}")
        return Response("<Response><Message>❌ Erro ao cadastrar a despesa. Tente novamente.</Message></Response>", mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
