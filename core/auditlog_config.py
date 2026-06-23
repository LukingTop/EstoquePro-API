from auditlog.registry import auditlog
from .models import Contagem, Produto, Rua, Endereco, TarefaRecontagem, ConfiguracaoSistema

# Registra os modelos que terão todas as ações registradas
auditlog.register(Contagem)
auditlog.register(Produto)
auditlog.register(Rua)
auditlog.register(Endereco)
auditlog.register(TarefaRecontagem)
auditlog.register(ConfiguracaoSistema)