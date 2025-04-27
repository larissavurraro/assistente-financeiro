# modules/report_generator.py
import re
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
import logging
import os

# Importar estilo do Matplotlib para gráficos mais bonitos
try:
    plt.style.use('ggplot')
except:
    pass

# Configurar para usar fonte que suporta caracteres especiais
plt.rcParams['font.family'] = 'DejaVu Sans'

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self, sheets_manager):
        self.sheets_manager = sheets_manager
    
    def extract_report_parameters(self, message, user_type):
        """Extrai parâmetros de filtragem do texto da mensagem"""
        message = message.lower()
        
        # Inicializar parâmetros padrão
        params = {
            "month": datetime.now().month,
            "year": datetime.now().year,
            "user": None,
            "category": None,
            "include_chart": False
        }
        
        # Extrair período (mês)
        if "mês passado" in message or "mes passado" in message:
            params["month"] = datetime.now().month - 1 if datetime.now().month > 1 else 12
            params["year"] = datetime.now().year if datetime.now().month > 1 else datetime.now().year - 1
        
        # Detectar se é para mostrar apenas despesas do usuário
        if "meus gastos" in message or "minhas despesas" in message:
            params["user"] = user_type
        
        # Detectar categoria específica
        category_match = re.search(r'categoria\s+(\w+)', message)
        if category_match:
            params["category"] = category_match.group(1).upper()
        
        # Verificar se deve incluir gráfico
        if "gráfico" in message or "grafico" in message:
            params["include_chart"] = True
        
        return params
    
    def generate_report(self, params):
        """Gera um relatório baseado nos parâmetros fornecidos"""
        try:
            # Construir filtros para consulta
            filters = {}
            
            if "month" in params:
                filters["month"] = params["month"]
            
            if "user" in params and params["user"]:
                filters["user"] = params["user"]
            
            if "category" in params and params["category"]:
                filters["category"] = params["category"]
            
            # Obter dados da planilha
            result = self.sheets_manager.get_expenses(filters)
            
            if not result.get("success"):
                return result
            
            # Determinar período para exibição
            month_names = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", 
                          "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
            
            month_index = params.get("month", datetime.now().month) - 1
            year = params.get("year", datetime.now().year)
            period = f"{month_names[month_index]} de {year}"
            
            # Adicionar informação do período
            result["period"] = period
            
            return result
        except Exception as e:
            logger.error(f"Erro ao gerar relatório: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def generate_chart(self, report_data):
        """Gera um gráfico visual baseado nos dados do relatório"""
        try:
            if not report_data.get("success") or report_data.get("total", 0) == 0:
                return None
            
            # Criar figura com dois subplots
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
            
            # Dados para gráficos
            category_totals = report_data.get("category_totals", {})
            user_totals = report_data.get("user_totals", {})
            
            # 1. Gráfico de pizza para categorias
            if category_totals:
                labels = list(category_totals.keys())
                values = list(category_totals.values())
                explode = [0.1 if i == values.index(max(values)) else 0 for i in range(len(values))]
                
                ax1.pie(values, explode=explode, labels=labels, autopct='%1.1f%%', 
                       shadow=True, startangle=90)
                ax1.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle
                ax1.set_title('Despesas por Categoria')
            
            # 2. Gráfico de barras para pessoas
            if user_totals:
                users = []
                amounts = []
                for user, amount in user_totals.items():
                    user_name = "Você" if user.lower() == "você" else "Noivo" if user.lower() == "noivo" else user
                    users.append(user_name)
                    amounts.append(amount)
                
                bars = ax2.bar(users, amounts, color=['#3498db', '#e74c3c'])
                
                # Adicionar valores acima das barras
                for bar in bars:
                    height = bar.get_height()
                    ax2.annotate(f'R${height:.2f}'.replace('.', ','),
                                xy=(bar.get_x() + bar.get_width() / 2, height),
                                xytext=(0, 3),  # 3 points vertical offset
                                textcoords="offset points",
                                ha='center', va='bottom')
                
                ax2.set_title('Despesas por Pessoa')
                ax2.set_ylabel('Valor (R$)')
            
            # Título geral
            period = report_data.get("period", "atual")
            fig.suptitle(f'Resumo de Despesas - {period}', fontsize=16)
            
            # Ajustar layout
            plt.tight_layout()
            fig.subplots_adjust(top=0.88)
            
            return fig
        except Exception as e:
            logger.error(f"Erro ao gerar gráfico: {str(e)}")
            return None
