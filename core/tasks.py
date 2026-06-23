from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore, register_events
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)

def executar_backup_automatizado():
    """Função que chama o seu Management Command customizado"""
    print(f"[{datetime.now()}] Iniciando rotina automática de backup...")
    try:
        call_command('backup_db')
    except Exception as e:
        logger.error(f"Falha no backup automatizado: {e}")

def start_scheduler():
    """Inicializa o agendador de tarefas em segundo plano"""
    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(DjangoJobStore(), "default")

    # Configura para rodar o backup todos os dias às 03:00 da manhã
    scheduler.add_job(
        executar_backup_automatizado,
        trigger="cron",
        hour=3,
        minute=0,
        id="backup_diario_sqlite",
        max_instances=1,
        replace_existing=True,
    )

    register_events(scheduler)
    scheduler.start()
    print("⏰ Agendador de rotinas internas ativado com sucesso.")