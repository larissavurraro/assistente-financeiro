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
    
    # utils/helpers.py (continuação)
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(',', '.')
            try:
                return float(amount_str)
            except:
                pass
    
    # Procurar por números isolados como último recurso
    amount_match = re.search(r'(\d+(?:[,.]\d+)?)', text)
    if amount_match:
        amount_str = amount_match.group(1).replace(',', '.')
        try:
            return float(amount_str)
        except:
            pass
    
    return None

def parse_date_from_text(text):
    """Extrai e interpreta menções a datas em texto natural"""
    text = text.lower()
    
    # Data atual
    today = datetime.now()
    
    # Verificar termos comuns
    if 'hoje' in text:
        return today.strftime("%d/%m/%Y")
    elif 'ontem' in text:
        yesterday = today - timedelta(days=1)
        return yesterday.strftime("%d/%m/%Y")
    elif 'anteontem' in text:
        day_before_yesterday = today - timedelta(days=2)
        return day_before_yesterday.strftime("%d/%m/%Y")
    
    # Buscar padrões de data (dia/mês)
    date_pattern = r'(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?'
    match = re.search(date_pattern, text)
    
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        
        # Se o ano foi fornecido
        if match.group(3):
            year = int(match.group(3))
            # Ajustar ano abreviado (22 -> 2022)
            if year < 100:
                year += 2000
        else:
            year = today.year
        
        # Validar data
        try:
            date_obj = datetime(year, month, day)
            return date_obj.strftime("%d/%m/%Y")
        except ValueError:
            # Data inválida, retornar data atual
            return today.strftime("%d/%m/%Y")
    
    # Verificar menções a dias da semana
    days_of_week = {
        'segunda': 0, 'segunda-feira': 0,
        'terça': 1, 'terca': 1, 'terça-feira': 1, 'terca-feira': 1,
        'quarta': 2, 'quarta-feira': 2,
        'quinta': 3, 'quinta-feira': 3,
        'sexta': 4, 'sexta-feira': 4,
        'sábado': 5, 'sabado': 5,
        'domingo': 6
    }
    
    for day_name, day_offset in days_of_week.items():
        if day_name in text:
            # Calcular a data do próximo dia da semana mencionado
            today_weekday = today.weekday()
            days_ahead = day_offset - today_weekday
            
            if days_ahead <= 0:  # Se for hoje ou no passado, considerar a próxima semana
                days_ahead += 7
            
            next_day = today + timedelta(days=days_ahead)
            return next_day.strftime("%d/%m/%Y")
    
    # Se nenhuma data foi encontrada
    return today.strftime("%d/%m/%Y")

def sanitize_filename(filename):
    """Sanitiza um nome de arquivo removendo caracteres problemáticos"""
    # Remover caracteres não seguros para nomes de arquivo
    invalid_chars = '<>:"/\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    
    # Limitar tamanho e retornar
    return filename[:100]

def safe_divide(numerator, denominator):
    """Divisão segura que evita divisão por zero"""
    try:
        if denominator == 0:
            return 0
        return numerator / denominator
    except:
        return 0

def format_percentage(value, total):
    """Formata um valor como porcentagem de um total"""
    percentage = safe_divide(value, total) * 100
    return f"{percentage:.1f}%"

def get_month_name(month_number):
    """Retorna nome do mês em português a partir do número"""
    month_names = [
        "Janeiro", "Fevereiro", "Março", "Abril", 
        "Maio", "Junho", "Julho", "Agosto", 
        "Setembro", "Outubro", "Novembro", "Dezembro"
    ]
    
    try:
        # Ajustar para índice 0-based
        month_index = int(month_number) - 1
        if 0 <= month_index < 12:
            return month_names[month_index]
    except:
        pass
    
    return f"Mês {month_number}"
