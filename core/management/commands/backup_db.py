import os
import subprocess
import zipfile
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Cria um backup compactado do banco de dados PostgreSQL'

    def handle(self, *args, **options):
        # Coleta as configurações do banco de dados principal no settings.py
        db_settings = settings.DATABASES['default']
        db_name = db_settings.get('NAME')
        db_user = db_settings.get('USER')
        db_password = db_settings.get('PASSWORD')
        db_host = db_settings.get('HOST', '127.0.0.1')
        db_port = db_settings.get('PORT', '5432')

        if not db_name or not db_user:
            self.stderr.write(self.style.ERROR('Configurações do banco de dados incompletas no settings.py!'))
            return

        # Pasta de destino dos backups
        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Nomes dos arquivos com timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sql_name = f'backup_{timestamp}.sql'
        sql_path = os.path.join(backup_dir, sql_name)
        zip_name = f'backup_{timestamp}.zip'
        zip_path = os.path.join(backup_dir, zip_name)

        # Prepara as variáveis de ambiente para passar a senha de forma segura pro pg_dump
        env = os.environ.copy()
        if db_password:
            env['PGPASSWORD'] = str(db_password)

        # Comando do pg_dump
        comando_pg_dump = [
            'pg_dump',
            '-h', str(db_host),
            '-p', str(db_port),
            '-U', str(db_user),
            '-d', str(db_name),
            '-f', sql_path,
            '--clean' # Adiciona comandos DROP TABLE antes dos CREATE TABLE no backup
        ]

        try:
            # 1. Executa o pg_dump para criar o arquivo .sql
            subprocess.run(comando_pg_dump, env=env, check=True, capture_output=True)

            # 2. Cria o arquivo ZIP com o .sql dentro
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(sql_path, arcname=sql_name)
            
            # 3. Remove o arquivo .sql bruto, deixando apenas o ZIP
            if os.path.exists(sql_path):
                os.remove(sql_path)
            
            tamanho = os.path.getsize(zip_path)
            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Backup PostgreSQL criado com sucesso: {zip_name} '
                    f'({tamanho / 1024 / 1024:.2f} MB)'
                )
            )

            # Remove backups antigos (mantém apenas os últimos 7 dias)
            self._limpar_backups_antigos(backup_dir)

        except subprocess.CalledProcessError as e:
            self.stderr.write(self.style.ERROR(f'Erro no pg_dump: {e.stderr.decode("utf-8")}'))
            if os.path.exists(sql_path):
                os.remove(sql_path) # Limpa o arquivo sql quebrado se der erro
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Erro ao criar backup: {e}'))

    def _limpar_backups_antigos(self, backup_dir):
        """Remove backups com mais de 7 dias"""
        agora = datetime.now()
        arquivos = os.listdir(backup_dir)
        
        for arquivo in arquivos:
            if not arquivo.endswith('.zip'):
                continue
                
            caminho = os.path.join(backup_dir, arquivo)
            data_modificacao = datetime.fromtimestamp(os.path.getmtime(caminho))
            
            if (agora - data_modificacao).days > 7:
                os.remove(caminho)
                self.stdout.write(f'🗑️ Backup antigo removido: {arquivo}')