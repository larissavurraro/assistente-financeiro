# modules/response_generator.py
import locale
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Tentar configurar locale para português brasileiro
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'Portuguese_Brazil')
    except:
        logger.warning("Não foi possível configurar o locale para português brasileiro")

class ResponseGenerator:
    def __init__(self):
        pass
        
    def format_currency(self, value):
        """Formata um valor para formato de moeda brasileira"""
        try:
            return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except:
            return f"R$ {value}"
            
    def format_date(self, date_str):
        """Formata uma data para exibição amigável"""
        try:
            if isinstance(date_str, str):
                date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            else:
                date_obj = date_str
            return date_obj.strftime("%d/%m/%Y")
        except:
            return date_str
    
    def generate_expense_confirmation(self, expense_data):
        """Gera mensagem de confirmação para despesa registrada"""
        try:
            formatted_amount = self.format_currency(expense_data.get("amount", 0))
            category = expense_data.get("category", "").upper()
            description = expense_data.get("description", "").capitalize()
            date = self.format_date(expense_data.get("date", datetime.now().strftime("%d/%m/%Y")))
            user = expense_data.get("user", "").capitalize()
            
            confirmation = (
                "✅ Despesa registrada com sucesso!\n\n"
                "📅 Data: {date}\n"
                "📂 Categoria: {category}\n"
                "📝 Descrição: {description}\n"
                "👤 Responsável: {user}\n"
                "💰 Valor: {formatted_amount}\n\n"
                "Para ver um resumo, envie "resumo dos gastos"."
            )
            
            return confirmation
        except Exception as e:
            logger.error(f"Erro ao gerar confirmação: {str(e)}")
            return "✅ Despesa registrada com sucesso!"
    
    def generate_audio_confirmation(self, expense_data):
        """Gera texto para confirmar despesa via áudio (mais natural)"""
        try:
            amount = expense_data.get("amount", 0)
            formatted_amount = self.format_currency(amount)
            category = expense_data.get("category", "").lower()
            user = expense_data.get("user", "").capitalize()
            
            # Criar texto natural para áudio
            audio_text = f"Despesa registrada com sucesso, {user}! "
            
            # Adicionar descrição do valor de forma natural
            if amount == 1:
                audio_text += f"Valor de um real na categoria {category}."
            else:
                audio_text += f"Valor de {formatted_amount} na categoria {category}."
            
            return audio_text
        except Exception as e:
            logger.error(f"Erro ao gerar texto para áudio: {str(e)}")
            return "Despesa registrada com sucesso!"
    
    def generate_report_response(self, report_data):
        """Gera relatório textual de despesas"""
        try:
            if not report_data.get("success"):
                return f"❌ Erro ao gerar relatório: {report_data.get('error', 'Erro desconhecido')}"
            
            # Extrair dados do relatório
            total = report_data.get("total", 0)
            user_totals = report_data.get("user_totals", {})
            category_totals = report_data.get("category_totals", {})
            period = report_data.get("period", "atual")
            recent_expenses = report_data.get("recent_expenses", [])
            
            # Gerar cabeçalho do relatório
            report = f"📊 *Relatório Financeiro - Período {period}*\n\n"
            
            # Total geral
            report += f"💰 *Total Geral: {self.format_currency(total)}*\n\n"
            
            # Totais por pessoa
            if user_totals:
                report += "*Despesas por Pessoa:*\n"
                for user, amount in user_totals.items():
                    user_name = "Você" if user.lower() == "você" else "Seu Noivo" if user.lower() == "noivo" else user
                    report += f"• {user_name}: {self.format_currency(amount)}\n"
                report += "\n"
            
            # Totais por categoria
            if category_totals:
                report += "*Despesas por Categoria:*\n"
                # Ordenar categorias pelo valor (maior primeiro)
                for category, amount in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
                    report += f"• {category}: {self.format_currency(amount)}\n"
                report += "\n"
            
            # Listar despesas recentes
            if recent_expenses:
                report += "*Despesas Recentes:*\n"
                for i, expense in enumerate(recent_expenses[:5], 1):
                    date = self.format_date(expense.get("date", ""))
                    description = expense.get("description", "").capitalize()
                    amount = self.format_currency(expense.get("amount", 0))
                    user = expense.get("user", "").capitalize()
                    
                    report += f"{i}. {date} - {description} ({amount}) - {user}\n"
            
            # Adicionar dicas
            report += "\n💡 *Dicas:*\n"
            report += "• Para ver apenas seus gastos: "resumo dos meus gastos"\n"
            report += "• Para ver gastos por categoria: "resumo categoria alimentação"\n"
            report += "• Para ver relatório com gráfico: "resumo com gráfico"\n"
            
            return report
        except Exception as e:
            logger.error(f"Erro ao gerar resposta de relatório: {str(e)}")
            return "Não foi possível gerar o relatório completo."
