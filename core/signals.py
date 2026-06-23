from django.contrib.auth.models import User
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.contenttypes.models import ContentType

from auditlog.registry import auditlog
from auditlog.models import LogEntry

from .models import (
    PerfilOperador, Contagem, Endereco,
    Produto, Rua, TarefaRecontagem, ConfiguracaoSistema
)


# ==========================================
# 1. REGISTRO AUTOMÁTICO DE MODELOS 
# ==========================================

auditlog.register(Contagem)
auditlog.register(Produto)
auditlog.register(Rua)
auditlog.register(Endereco)
auditlog.register(TarefaRecontagem)
auditlog.register(ConfiguracaoSistema)


# ==========================================
# 2. SINAIS EXISTENTES 
# ==========================================

@receiver(post_save, sender=User)
def criar_perfil_operador(sender, instance, created, **kwargs):
    if created:
        PerfilOperador.objects.get_or_create(
            user=instance,
            defaults={'cargo': PerfilOperador.Cargo.OPERADOR}
        )


def atualizar_cache_endereco(endereco):
    """Recalcula os campos de cache do Endereço com base nas contagens válidas."""
    ultima = (
        Contagem.objects
        .filter(endereco=endereco, foi_descartada=False)
        .order_by('-data_hora')
        .first()
    )
    endereco.ultima_contagem_em = ultima.data_hora if ultima else None
    endereco.contagem_realizada = ultima is not None
    endereco.save(update_fields=['ultima_contagem_em', 'contagem_realizada'])


@receiver(post_save, sender=Contagem)
def cache_endereco_ao_salvar_contagem(sender, instance, **kwargs):
    atualizar_cache_endereco(instance.endereco)


@receiver(post_delete, sender=Contagem)
def cache_endereco_ao_deletar_contagem(sender, instance, **kwargs):
    atualizar_cache_endereco(instance.endereco)


# ==========================================
# 3. LOGIN E LOGOUT
# ==========================================

@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    LogEntry.objects.create(
        action=LogEntry.Action.CREATE,  #
        content_type=ContentType.objects.get_for_model(user),
        object_pk=user.pk,
        object_repr=str(user),
        actor=user,
        changes={'action': 'login', 'ip': request.META.get('REMOTE_ADDR')},
    )


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    if user:  
        LogEntry.objects.create(
            action=LogEntry.Action.DELETE,  
            content_type=ContentType.objects.get_for_model(user),
            object_pk=user.pk,
            object_repr=str(user),
            actor=user,
            changes={'action': 'logout', 'ip': request.META.get('REMOTE_ADDR')},
        )