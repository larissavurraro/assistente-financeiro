# modules/google_sheets.py
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class GoogleSheetsManager:
    def __init__(self):
        try:
            # Inicializar conexão com Google Sheets
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            
            # Obter credenciais do ambiente (mais seguro que hardcoded)
            json_creds = os.environ.get("GOOGLE_CREDS_JSON")
            if not json_creds:
                raise ValueError("Credenciais do Google não encontradas nas variáveis de ambiente")
                
            creds_dict = json.loads(json_creds)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            self.client = gspread.authorize(creds)
            
            # Abrir planilha
            sheet_id = os.environ.get("SHEET_ID", "1vKrmgkMTDwcx5qufF-YRvsXSk99J1Vq9-LwuQINwcl8")
            self.spreadsheet = self.client.open_by_key(sheet_id)
            
            # Garantir que as abas necessárias existam
            self._ensure_worksheets_exist()
            
            logger.info("Conexão com Google Sheets estabelecida com sucesso")
        except Exception as e:
            logger.error(f"Erro ao inicializar Google Sheets: {str(e)}")
            raise
    
    def _ensure_worksheets_exist(self):
        """Garante que todas as abas necessárias existam na planilha"""
        required_sheets = ["Despesas", "Categorias"]
        existing_sheets = [sheet.title for sheet in self.spreadsheet.worksheets()]
        
        for sheet_name in required_sheets:
            if sheet_name not in existing_sheets:
                self.spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)
                
                # Se for a aba de despesas, adicionar cabeçalhos
                if sheet_name == "Despesas":
                    headers = ["Data", "Categoria", "Descrição", "Valor", "Responsável", "Timestamp"]
                    self.spreadsheet.worksheet(sheet_name).append_row(headers)
                
                # Se for a aba de categorias, adicionar categorias padrão
                if sheet_name == "Categorias":
                    categories = [
                        ["MERCADO", "mercado, supermercado, pão, leite, feira, comida"],
                        ["TRANSPORTE", "uber, 99, ônibus, metro, trem, corrida, combustível, gasolina"],
                        ["LAZER", "cinema, netflix, bar, show, festa, lazer"],
                        ["MORADIA", "aluguel, condominio, energia, água, internet, luz"],
                        ["REFEIÇÃO", "restaurante, lanche, jantar, almoço, hamburguer, pizza"]
                    ]
                    for category in categories:
                        self.spreadsheet.worksheet(sheet_name).append_row(category)
    
    def add_expense(self, expense_data):
        """Adiciona uma nova despesa à planilha"""
        try:
            sheet = self.spreadsheet.worksheet("Despesas")
            
            # Formatar dados para inserção
            date = expense_data.get("date", datetime.now().strftime("%d/%m/%Y"))
            category = expense_data.get("category", "OUTROS")
            description = expense_data.get("description", "").upper()
            
            # Formatar valor como moeda
            try:
                amount = float(expense_data.get("amount", 0))
                formatted_amount = f"R${amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except:
                formatted_amount = str(expense_data.get("amount", "0"))
            
            # Obter responsável
            user = expense_data.get("user", "").upper()
            
            # Timestamp
            timestamp = expense_data.get("timestamp", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
            
            # Adicionar linha à planilha
            row = [date, category, description, formatted_amount, user, timestamp]
            sheet.append_row(row)
            
            logger.info(f"Despesa adicionada com sucesso: {row}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Erro ao adicionar despesa: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_expenses(self, filters=None):
        """Obtém despesas da planilha com filtros opcionais"""
        try:
            sheet = self.spreadsheet.worksheet("Despesas")
            data = sheet.get_all_records()
            
            # Converter para DataFrame para facilitar análise
            df = pd.DataFrame(data)
            
            # Se não houver dados
            if df.empty:
                return {"success": True, "data": [], "total": 0}
            
            # Aplicar filtros se existirem
            if filters:
                # Filtro por mês
                if "month" in filters:
                    df["Data"] = pd.to_datetime(df["Data"], format="%d/%m/%Y", errors="coerce")
                    df = df[df["Data"].dt.month == filters["month"]]
                
                # Filtro por usuário
                if "user" in filters:
                    df = df[df["Responsável"] == filters["user"].upper()]
                
                # Filtro por categoria
                if "category" in filters:
                    df = df[df["Categoria"] == filters["category"].upper()]
                
                # Filtro por data inicial e final
                if "start_date" in filters and "end_date" in filters:
                    df["Data"] = pd.to_datetime(df["Data"], format="%d/%m/%Y", errors="coerce")
                    start = pd.to_datetime(filters["start_date"], format="%d/%m/%Y")
                    end = pd.to_datetime(filters["end_date"], format="%d/%m/%Y")
                    df = df[(df["Data"] >= start) & (df["Data"] <= end)]
            
            # Calcular totais
            total = 0
            for valor in df["Valor"]:
                try:
                    # Extrair valor numérico de strings como "R$123,45"
                    valor_limpo = valor.replace("R$", "").replace(".", "").replace(",", ".")
                    total += float(valor_limpo)
                except:
                    pass
            
            # Agrupar por categoria
            category_totals = {}
            for cat in df["Categoria"].unique():
                cat_total = 0
                for valor in df[df["Categoria"] == cat]["Valor"]:
                    try:
                        valor_limpo = valor.replace("R$", "").replace(".", "").replace(",", ".")
                        cat_total += float(valor_limpo)
                    except:
                        pass
                category_totals[cat] = cat_total
            
            # Agrupar por responsável
            user_totals = {}
            for user in df["Responsável"].unique():
                user_total = 0
                for valor in df[df["Responsável"] == user]["Valor"]:
                    try:
                        valor_limpo = valor.replace("R$", "").replace(".", "").replace(",", ".")
                        user_total += float(valor_limpo)
                    except:
                        pass
                user_totals[user] = user_total
            
            return {
                "success": True,
                "data": df.to_dict("records"),
                "total": total,
                "category_totals": category_totals,
                "user_totals": user_totals
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter despesas: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_categories(self):
        """Obtém as categorias e suas palavras-chave da planilha"""
        try:
            sheet = self.spreadsheet.worksheet("Categorias")
            data = sheet.get_all_records()
            
            # Converter para dicionário {categoria: palavras-chave}
            categories = {}
            for row in data:
                category = list(row.values())[0]  # Primeira coluna é a categoria
                keywords = list(row.values())[1]  # Segunda coluna são as palavras-chave
                categories[category] = [kw.strip() for kw in keywords.split(",")]
            
            return {"success": True, "categories": categories}
        except Exception as e:
            logger.error(f"Erro ao obter categorias: {str(e)}")
            return {"success": False, "error": str(e)}
