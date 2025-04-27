# modules/speech_processor.py
import os
import requests
import whisper
import tempfile
from pydub import AudioSegment
import logging

logger = logging.getLogger(__name__)

class SpeechProcessor:
    def __init__(self):
        # Inicializar modelo Whisper (pode ser "tiny", "base", "small", "medium", "large")
        model_size = os.environ.get("WHISPER_MODEL", "base")
        try:
            logger.info(f"Carregando modelo Whisper {model_size}...")
            self.model = whisper.load_model(model_size)
            logger.info("Modelo Whisper carregado com sucesso")
        except Exception as e:
            logger.error(f"Erro ao carregar modelo Whisper: {str(e)}")
            self.model = None
    
    def transcribe_audio(self, audio_url):
        """Transcreve áudio de URL para texto"""
        if not self.model:
            raise ValueError("Modelo de reconhecimento de fala não inicializado")
        
        temp_dir = tempfile.mkdtemp()
        ogg_path = os.path.join(temp_dir, "audio.ogg")
        wav_path = os.path.join(temp_dir, "audio.wav")
        
        try:
            # Baixar o arquivo de áudio
            logger.info(f"Baixando áudio de {audio_url}")
            response = requests.get(audio_url)
            
            if response.status_code != 200:
                raise Exception(f"Falha ao baixar áudio: status {response.status_code}")
            
            # Salvar o arquivo
            with open(ogg_path, "wb") as f:
                f.write(response.content)
            
            # Converter OGG para WAV (formato aceito pelo Whisper)
            logger.info("Convertendo OGG para WAV")
            AudioSegment.from_file(ogg_path).export(wav_path, format="wav")
            
            # Transcrever usando Whisper
            logger.info("Transcrevendo áudio com Whisper")
            result = self.model.transcribe(wav_path, language="pt")
            transcribed_text = result["text"]
            
            logger.info(f"Transcrição concluída: {transcribed_text[:50]}...")
            return transcribed_text
            
        except Exception as e:
            logger.error(f"Erro durante a transcrição de áudio: {str(e)}")
            raise
        finally:
            # Limpar arquivos temporários
            try:
                if os.path.exists(ogg_path):
                    os.remove(ogg_path)
                if os.path.exists(wav_path):
                    os.remove(wav_path)
                os.rmdir(temp_dir)
            except Exception as e:
                logger.warning(f"Erro ao limpar arquivos temporários: {str(e)}")
