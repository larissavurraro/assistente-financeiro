# modules/whatsapp_handler.py
from flask import Response
from twilio.rest import Client
import os
import requests
import tempfile
import uuid
from gtts import gTTS
from pydub import AudioSegment
import logging
import urllib.parse

logger = logging.getLogger(__name__)

class WhatsAppHandler:
    def __init__(self):
        try:
            # Configurar cliente Twilio
            twilio_sid = os.environ.get("TWILIO_SID")
            twilio_token = os.environ.get("TWILIO_TOKEN")
            self.twilio_number = os.environ.get("TWILIO_NUMBER")
            
            if not all([twilio_sid, twilio_token, self.twilio_number]):
                logger.warning("Credenciais Twilio incompletas nas variáveis de ambiente")
            
            self.twilio_client = Client(twilio_sid, twilio_token)
            
            # Configurar diretório para arquivos estáticos
            self.static_dir = "static"
            os.makedirs(self.static_dir, exist_ok=True)
            
            # URL base para arquivos estáticos
            self.base_url = os.environ.get("BASE_URL", "https://assistente-financeiro.onrender.com")
            
            logger.info("WhatsApp handler inicializado com sucesso")
        except Exception as e:
            logger.error(f"Erro ao inicializar WhatsApp handler: {str(e)}")
            raise
    
    def send_error_response(self, message):
        """Envia resposta de erro para o WhatsApp"""
        response = f"<Response><Message>{message}</Message></Response>"
        return Response(response, mimetype="application/xml")
    
    def send_message(self, to, message):
        """Envia mensagem de texto para o WhatsApp"""
        try:
            self.twilio_client.messages.create(
                from_=self.twilio_number,
                to=to,
                body=message
            )
            logger.info(f"Mensagem enviada para {to}")
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem: {str(e)}")
            return False
    
    def send_media(self, to, media_url, caption=None):
        """Envia mídia para o WhatsApp"""
        try:
            message_data = {
                "from_": self.twilio_number,
                "to": to,
                "media_url": [media_url]
            }
            
            if caption:
                message_data["body"] = caption
                
            self.twilio_client.messages.create(**message_data)
            logger.info(f"Mídia enviada para {to}")
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar mídia: {str(e)}")
            return False
    
    def send_message_with_audio(self, to, text_message, audio_text):
        """Envia mensagem de texto seguida de áudio para o WhatsApp"""
        try:
            # Gerar arquivo de áudio para a resposta
            audio_path = self._generate_audio(audio_text)
            if not audio_path:
                # Se falhar, enviar apenas a mensagem de texto
                return self.send_message(to, text_message)
            
            # URL pública para o arquivo de áudio
            audio_url = f"{self.base_url}/{audio_path}"
            
            # Enviar mensagem de texto primeiro
            self.send_message(to, text_message)
            
            # Enviar áudio em seguida
            self.send_media(to, audio_url)
            
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem com áudio: {str(e)}")
            return False
    
    def send_report(self, to, text_message, chart=None):
        """Envia relatório com texto e opcionalmente um gráfico"""
        try:
            # Enviar mensagem de texto primeiro
            self.send_message(to, text_message)
            
            # Se houver gráfico, enviar como imagem
            if chart:
                chart_path = os.path.join(self.static_dir, f"chart_{uuid.uuid4().hex}.png")
                chart.savefig(chart_path, bbox_inches="tight", dpi=300)
                chart_url = f"{self.base_url}/{chart_path}"
                
                self.send_media(to, chart_url, caption="Resumo gráfico de despesas")
            
            return True
        except Exception as e:
            logger.error(f"Erro ao enviar relatório: {str(e)}")
            return False
    
    def _generate_audio(self, text):
        """Gera arquivo de áudio a partir de texto"""
        try:
            # Nome de arquivo único para evitar conflitos
            audio_filename = os.path.join(self.static_dir, f"audio_{uuid.uuid4().hex}.mp3")
            ogg_filename = audio_filename.replace(".mp3", ".ogg")
            
            # Gerar MP3 com gTTS
            tts = gTTS(text=text, lang='pt')
            tts.save(audio_filename)
            
            # Converter para OGG (formato que o WhatsApp prefere)
            AudioSegment.from_file(audio_filename).export(ogg_filename, format="ogg")
            
            # Remover arquivo MP3 temporário
            if os.path.exists(audio_filename):
                os.remove(audio_filename)
            
            return ogg_filename
        except Exception as e:
            logger.error(f"Erro ao gerar áudio: {str(e)}")
            return None
