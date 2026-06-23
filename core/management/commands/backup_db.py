import os
import shutil
import zipfile
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Cria um backup compactado do banco de dados SQLite'

    def handle(self, *args, **options):
        # Caminho do banco de dados
        db_path = os.path.join(settings.BASE_DIR, 'db.sqlite3')
        
        if not os.path.exists(db_path):
            self.stderr.write(self.style.ERROR('Banco de dados não encontrado!'))
            return

        # Pasta de destino dos backups
        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Nome do arquivo com timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_name = f'backup_{timestamp}.zip'
        zip_path = os.path.join(backup_dir, zip_name)

        try:
            # Cria o arquivo ZIP com o banco de dados dentro
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(db_path, arcname='db.sqlite3')
            
            tamanho = os.path.getsize(zip_path)
            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Backup criado com sucesso: {zip_name} '
                    f'({tamanho / 1024:.1f} KB)'
                )
            )

            # Remove backups antigos (mantém apenas os últimos 7 dias)
            self._limpar_backups_antigos(backup_dir)

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