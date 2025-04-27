# modules/expense_processor.py
import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ExpenseProcessor:
    def __init__(self):
        # Padrões para extração de informações
        self.currency_pattern = r'(?:R\$|RS|\$)?[\s]*(\d+(?:[,.]\d+)?)'
        self.date_patterns = {
            'hoje': lambda: datetime.now().strftime("%d/%m/%Y"),
            'ontem': lambda: (datetime.now() - datetime.timedelta(days=1)).strftime("%d/%m/%Y"),
            'anteontem': lambda: (datetime.now() - datetime.timedelta(days=2)).strftime("%d/%m/%Y")
        }
        
        # Palavras-chave para categorias (padrão, será atualizado)
        self.category_keywords = {
            "MERCADO": ["mercado", "supermercado", "compras", "feira"],
            "TRANSPORTE": ["uber", "99", "taxi", "ônibus", "metrô", "gasolina", "combustível"],
            "LAZER": ["cinema", "filme", "show", "festa", "bar", "netflix"],
            "MORADIA": ["aluguel", "condomínio", "água", "luz", "energia", "internet"],
            "ALIMENTAÇÃO": ["restaurante", "lanche", "almoço", "jantar", "delivery"]
        }
    
    def update_categories(self, categories_dict):
        """Atualiza as palavras-chave de categorias com dados da planilha"""
        if categories_dict:
            self.category_keywords = categories_dict
    
    def classify_category(self, description):
        """Classifica a descrição em uma categoria"""
        description = description.lower()
        
        for category, keywords in self.category_keywords.items():
            for keyword in keywords:
                if keyword.lower() in description:
                    return category
        
        return "OUTROS"
    
    def extract_simple_format(self, text):
        """Extrai dados de despesa de formato simples: valor, responsável, descrição"""
        # Verifica se texto segue o formato CSV (exemplo: "Thiago, 27/04, mercado, compras, 150")
        parts = [p.strip() for p in text.split(",")]
        
        if len(parts) == 5:
            try:
                responsavel, data, categoria_texto, descricao, valor = parts
                
                # Tratar data
                if data.lower() == "hoje":
                    data_formatada = datetime.now().strftime("%d/%m/%Y")
                else:
                    try:
                        # Tenta interpretar como dia/mês
                        parsed_date = datetime.strptime(data, "%d/%m")
                        parsed_date = parsed_date.replace(year=datetime.now().year)
                        data_formatada = parsed_date.strftime("%d/%m/%Y")
                    except:
                        data_formatada = datetime.now().strftime("%d/%m/%Y")
                
                # Detectar categoria se não estiver explícita
                if not categoria_texto or categoria_texto.lower() == "categoria":
                    categoria = self.classify_category(descricao)
                else:
                    categoria = categoria_texto.upper()
                
                # Limpar valor
                try:
                    valor_limpo = re.sub(r'[^\d.,]', '', valor)
                    valor_limpo = valor_limpo.replace(',', '.')
                    valor_float = float(valor_limpo)
                except:
                    return None
                
                return {
                    "date": data_formatada,
                    "category": categoria,
                    "description": descricao,
                    "amount": valor_float,
                    "user": responsavel
                }
            except:
                return None
        
        return None
    
    def extract_expense_data(self, text):
        """Extrai dados de despesa de uma mensagem de texto natural"""
        text = text.lower()
        
        # Extrair valor monetário
        amount_match = re.search(self.currency_pattern, text)
        if not amount_match:
            return None
        
        amount_str = amount_match.group(1).replace(',', '.')
        try:
            amount = float(amount_str)
        except:
            return None
        
        # Extrair descrição (texto próximo ao valor)
        # Pegar até 5 palavras após o valor ou antes se não houver suficiente
        amount_pos = text.find(amount_match.group(0))
        
        words_after = text[amount_pos + len(amount_match.group(0)):].strip().split()[:5]
        words_before = text[:amount_pos].strip().split()[-5:]
        
        context_words = words_before + words_after
        description = " ".join(context_words).strip()
        
        # Se a descrição estiver vazia ou muito curta
        if len(description) < 3:
            description = "Despesa"
        
        # Classificar categoria baseado na descrição
        category = self.classify_category(description)
        
        # Determinar data (padrão é hoje)
        date = datetime.now().strftime("%d/%m/%Y")
        
        # Buscar menções a datas específicas
        for date_text, date_func in self.date_patterns.items():
            if date_text in text:
                date = date_func()
                break
        
        # Construir e retornar os dados da despesa
        expense_data = {
            "date": date,
            "category": category,
            "description": description,
            "amount": amount
        }
        
        return expense_data
