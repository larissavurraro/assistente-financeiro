# utils/error_handler.py
import logging
import traceback
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class ErrorHandler:
    def __init__(self):
        # Configurar diretório para logs de erro
        self.error_log_dir = "error_logs"
        os.makedirs(self.error_log_dir, exist_ok=True)
    
    def log_error(self, error_message, context=None):
        """Registra erro detalhado em arquivo e log"""
        try:
            # Gerar timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Capturar stack trace
            stack_trace = traceback.format_exc()
            
            # Criar mensagem de erro detalhada
            error_details = [
                f"=== ERRO REGISTRADO EM {timestamp} ===",
                f"Mensagem: {error_message}",
                ""
            ]
            
            if context:
                error_details.append("Contexto:")
                for key, value in context.items():
                    error_details.append(f"  {key}: {value}")
                error_details.append("")
            
            error_details.append("Stack Trace:")
            error_details.append(stack_trace)
            error_details.append("=" * 50)
            
            # Registrar no console
            logger.error(error_message)
            if context:
                logger.error(f"Contexto: {context}")
            
            # Registrar em arquivo
            log_filename = os.path.join(self.error_log_dir, f"error_log_{datetime.now().strftime('%Y%m%d')}.txt")
            with open(log_filename, "a") as f:
                f.write("\n".join(error_details) + "\n\n")
            
            return f"Erro registrado: {error_message}"
        except Exception as e:
            # Se falhar o registro de erro, pelo menos logar no console
            logger.critical(f"Falha ao registrar erro: {str(e)}")
            logger.critical(f"Erro original: {error_message}")
            return f"Erro não registrado adequadamente: {error_message}"

# Instanciar tratador de erros global
error_handler = ErrorHandler()

def handle_error(error_message, context=None):
    """Função para registrar erros de qualquer parte do código"""
    return error_handler.log_error(error_message, context)
