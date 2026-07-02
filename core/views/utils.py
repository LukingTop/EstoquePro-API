from django.utils import timezone
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from core.models import Produto, Contagem, TarefaRecontagem


# ============================================================
# FUNÇÕES DE VERIFICAÇÃO DE PERMISSÃO
# ============================================================

def is_gestor(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return hasattr(user, 'perfil') and user.perfil.cargo == 'GESTOR'


def is_lider_or_gestor(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return hasattr(user, 'perfil') and user.perfil.cargo in ['LIDER', 'GESTOR']


class LiderOrGestorMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_lider_or_gestor(self.request.user)


# ============================================================
# FUNÇÃO AUXILIAR
# ============================================================

def criar_tarefa_recontagem(contagem):
    try:
        produto = Produto.objects.get(codigo=contagem.codigo_produto)
    except Produto.DoesNotExist:
        return None

    tarefa_existente = TarefaRecontagem.objects.filter(
        endereco=contagem.endereco,
        produto=produto,
        status__in=[
            TarefaRecontagem.Status.PENDENTE,
            TarefaRecontagem.Status.EM_ANDAMENTO,
        ],
    ).first()

    if tarefa_existente:
        return tarefa_existente

    hoje = timezone.now().date()
    contagens_do_dia = Contagem.objects.filter(
        endereco=contagem.endereco,
        codigo_produto=produto.codigo,
        data_contagem=hoje,
        foi_descartada=False,
    )
    pallets = list(contagens_do_dia.values_list('pallets', flat=True))
    if len(pallets) >= 2:
        max_diff = max(pallets) - min(pallets)
    else:
        max_diff = 0

    if max_diff >= 10:
        criticidade = TarefaRecontagem.Criticidade.ALTA
    elif max_diff >= 5:
        criticidade = TarefaRecontagem.Criticidade.MEDIA
    else:
        criticidade = TarefaRecontagem.Criticidade.BAIXA

    return TarefaRecontagem.objects.create(
        endereco=contagem.endereco,
        produto=produto,
        criticidade=criticidade,
        observacao='Criada automaticamente por conflito.',
    )