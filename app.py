# app.py
from flask import Flask, request, Response
import os
import json
import uuid
import requests
from datetime import datetime
import logging
import traceback
from modules.google_sheets import GoogleSheetsManager
from modules.whatsapp_handler import WhatsAppHandler
from modules.speech_processor import SpeechProcessor
from modules.expense_processor import ExpenseProcessor
from modules.response_generator import ResponseGenerator
from modules.report_generator import ReportGenerator

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "chave_secreta_temporaria")

# Inicializar módulos
sheets_manager = GoogleSheetsManager()
speech_processor = SpeechProcessor()
expense_processor = ExpenseProcessor()
whatsapp_handler = WhatsAppHandler()
response_generator = ResponseGenerator()
report_generator = ReportGenerator(sheets_manager)

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """Endpoint para receber mensagens do WhatsApp via Twilio"""
    try:
        # Extrair informações da mensagem
        message_body = request.form.get("Body", "")
        from_number = request.form.get("From", "")
        media_url = request.form.get("MediaUrl0")
        media_type = request.form.get("MediaContentType0")
        
        logger.info(f"Mensagem recebida de {from_number}: {message_body[:50]}...")
        
        # Processar áudio se houver
        if media_url and "audio" in media_type:
            try:
                message_body = speech_processor.transcribe_audio(media_url)
                logger.info(f"Áudio transcrito: {message_body[:50]}...")
            except Exception as e:
                logger.error(f"Erro ao processar áudio: {str(e)}")
                return whatsapp_handler.send_error_response("Não foi possível processar o áudio. Tente novamente ou envie o texto.")
        
        # Identificar usuário pelo número
        user_type = identify_user(from_number)
        if not user_type:
            return whatsapp_handler.send_error_response("Número não autorizado para usar este bot.")
        
        # Verificar se é um comando de resumo
        if "resumo" in message_body.lower() or "relatório" in message_body.lower():
            return process_report_request(message_body, from_number, user_type)
        
        # Processar como registro de despesa
        return process_expense(message_body, from_number, user_type)
        
    except Exception as e:
        logger.error(f"Erro geral: {str(e)}")
        traceback.print_exc()
        return whatsapp_handler.send_error_response("Ocorreu um erro ao processar sua solicitação.")

def identify_user(phone_number):
    """Identifica o usuário pelo número do telefone"""
    users = {
        os.environ.get("whatsapp:+5511975220021"): "Larissa",
        os.environ.get("whatsapp:+5511977052756"): "Thiago"
    }
    return users.get(phone_number)

def process_expense(message_body, from_number, user_type):
    """Processa o registro de uma despesa"""
    try:
        # Extrair dados da despesa da mensagem
        expense_data = expense_processor.extract_expense_data(message_body)
        
        if not expense_data:
            # Verificar se é um formato simplificado
            expense_data = expense_processor.extract_simple_format(message_body)
            
        if not expense_data:
            return whatsapp_handler.send_error_response(
                "Não consegui entender os detalhes da despesa. Por favor, envie no formato:\n"
                "'Gastei X reais com Y' ou 'X reais para Y'"
            )
            
        # Adicionar informação do usuário
        expense_data["user"] = user_type
        expense_data["timestamp"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Registrar na planilha
        result = sheets_manager.add_expense(expense_data)
        
        if not result["success"]:
            logger.error(f"Erro ao salvar na planilha: {result['error']}")
            return whatsapp_handler.send_error_response("Não foi possível registrar a despesa. Tente novamente mais tarde.")
        
        # Gerar resposta
        text_response = response_generator.generate_expense_confirmation(expense_data)
        audio_response = response_generator.generate_audio_confirmation(expense_data)
        
        # Enviar respostas
        whatsapp_handler.send_message_with_audio(from_number, text_response, audio_response)
        return Response("", status=200)
        
    except Exception as e:
        logger.error(f"Erro ao processar despesa: {str(e)}")
        return whatsapp_handler.send_error_response("Houve um erro ao processar a despesa.")

def process_report_request(message_body, from_number, user_type):
    """Processa solicitação de relatório/resumo"""
    try:
        # Extrair parâmetros da solicitação de relatório
        params = report_generator.extract_report_parameters(message_body, user_type)
        
        # Gerar relatório
        report_data = report_generator.generate_report(params)
        
        if not report_data["success"]:
            return whatsapp_handler.send_error_response(f"Erro ao gerar relatório: {report_data['error']}")
        
        # Gerar resposta textual
        text_response = response_generator.generate_report_response(report_data)
        
        # Gerar gráfico se solicitado
        chart = None
        if "gráfico" in message_body.lower() or "grafico" in message_body.lower():
            chart = report_generator.generate_chart(report_data)
        
        # Enviar resposta
        whatsapp_handler.send_report(from_number, text_response, chart)
        return Response("", status=200)
        
    except Exception as e:
        logger.error(f"Erro ao processar solicitação de relatório: {str(e)}")
        return whatsapp_handler.send_error_response("Não foi possível gerar o relatório solicitado.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
