# utils/helpers.py
import re
import os
import tempfile
import uuid
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def create_temp_directory():
    """Cria um diretório temporário para arquivos"""
    temp_dir = os.path.join(tempfile.gettempdir(), f"whatsapp_bot_{uuid.uuid4().hex}")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def extract_amount_from_text(text):
    """Extrai valor monetário de um texto"""
    # Padrões para valores monetários em português
    patterns = [
        r'R\$\s*(\d+(?:[,.]\d+)?)',  # R$ 100 ou R$ 100,50
        r'(\d+(?:[,.]\d+)?)\s*reais', # 100 reais ou 100,50 reais
        r'(\d+(?:[,.]\d+)?)(?:\s+(?:pila|conto)s?)',  # 100 pilas ou 100 contos
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text
