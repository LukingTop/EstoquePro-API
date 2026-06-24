import json
from datetime import timedelta
from django.contrib import admin
from django.utils.html import format_html
from django.contrib.auth.models import Group
from django.contrib import messages
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.apps import apps
from django.contrib.admin.exceptions import NotRegistered
from django_apscheduler.models import DjangoJob, DjangoJobExecution
from auditlog.admin import LogEntryAdmin
from auditlog.models import LogEntry
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User


try:
    # --- Tradução do Audit Log ---
    audit_app = apps.get_app_config('auditlog')
    audit_app.verbose_name = "Auditoria do Sistema"

    LogEntry._meta.verbose_name = "Entrada de Log"
    LogEntry._meta.verbose_name_plural = "Entradas de Log"

    # Traduz o filtro "Action" e as opções dele
    LogEntry._meta.get_field('action').verbose_name = 'Ação'
    LogEntry._meta.get_field('action').choices = [
        (0, 'Criar'),
        (1, 'Atualizar'),
        (2, 'Deletar'),
        (3, 'Acessar'),
    ]

    # Traduz os outros filtros
    LogEntry._meta.get_field('content_type').verbose_name = 'Tipo de Recurso'
    LogEntry._meta.get_field('cid').verbose_name = 'ID de Correlação'

    # TRADUÇÃO DOS FILTROS CUSTOMIZADOS 
    log_admin = admin.site._registry.get(LogEntry)
    if log_admin:
        for item in log_admin.list_filter:
            if isinstance(item, type) and issubclass(item, admin.SimpleListFilter):
                if getattr(item, 'title', '') == 'Resource Type':
                    item.title = 'Tipo de Recurso'
                elif getattr(item, 'title', '') == 'Correlation ID':
                    item.title = 'ID de Correlação'

    # Traduz os processos em segundo plano
    apscheduler_app = apps.get_app_config('django_apscheduler')
    apscheduler_app.verbose_name = "Processos em Segundo Plano"

    DjangoJob._meta.verbose_name = "Tarefa Automática"
    DjangoJob._meta.verbose_name_plural = "Tarefas Automáticas"
    DjangoJobExecution._meta.verbose_name = "Execução de Tarefa"
    DjangoJobExecution._meta.verbose_name_plural = "Histórico de Execuções"
except LookupError:
    pass

# 2. Esconde as abas nativas para evitar acidentes por parte da gerência

for model in [Group, DjangoJob, DjangoJobExecution]:
    try:
        admin.site.unregister(model)
    except NotRegistered:
        pass

admin.site.unregister(User)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Idêntico ao UserAdmin padrão, mas sem o texto de instrução na tela de criação."""
    add_form_template = None


from .models import (
    Rua,
    Endereco,
    PerfilOperador,
    Produto,
    Contagem,
    TarefaRecontagem,
    ConfiguracaoSistema,
    ModeloPlanilha,
)


@admin.register(Rua)
class RuaAdmin(admin.ModelAdmin):
    list_display = ('id', 'codigo')
    search_fields = ('codigo',)
    ordering = ['ordem']
    fields = ('codigo',)           


@admin.register(Endereco)
class EnderecoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'rua', 'predio_num', 'andar_num', 'posicao_num')
    search_fields = ('codigo',)
    list_filter = ('rua',)
    ordering = ('rua_num', 'predio_num', 'andar_num', 'posicao_num')


@admin.register(PerfilOperador)
class PerfilOperadorAdmin(admin.ModelAdmin):
    list_display = ('user', 'cargo', 'exibir_ruas')
    search_fields = ('user__username',)
    list_filter = ('cargo',)
    filter_horizontal = ('ruas_permitidas',)

    fields = ('user', 'cargo', 'ruas_permitidas')

    def exibir_ruas(self, obj):
        return ", ".join([r.codigo for r in obj.ruas_permitidas.all()])
    exibir_ruas.short_description = "Ruas Autorizadas"

    
    def has_add_permission(self, request):
        return False


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'descricao')
    search_fields = ('codigo', 'descricao')
    ordering = ['codigo']
    fields = ('codigo', 'descricao')   


@admin.register(Contagem)
class ContagemAdmin(admin.ModelAdmin):
    list_display = (
        'operador',
        'atualizado_por',
        'endereco',
        'codigo_produto',
        'pallets',
        'status_conflito',
        'data_hora',
    )

    list_filter = (
        'foi_descartada',
        'em_conflito',
        'operador',
        'atualizado_por',
        'data_hora',
    )

    search_fields = (
        'codigo_produto',
        'descricao_produto',
        'operador__username',
        'endereco__codigo',
    )

    list_select_related = ('operador', 'atualizado_por', 'endereco')

    readonly_fields = (
        'atualizado_por',
        'historico_edicoes',
        'data_hora',
    )

   
    fields = (
        'operador',
        'endereco',
        'codigo_produto',
        'descricao_produto',
        'pallets',
        'observacao',
        'em_conflito',
        'foi_descartada',
        'historico_edicoes',
        'data_hora',
        'atualizado_por',
    )

    ordering = (
        'endereco__rua_num',
        'endereco__predio_num',
        'endereco__andar_num',
        'endereco__posicao_num',
    )

    # =====================
    # AÇÕES EM MASSA 
    # =====================
    actions = ['validar_contagens', 'descartar_contagens']

    def validar_contagens(self, request, queryset):
        atualizadas = queryset.filter(em_conflito=True).update(
            em_conflito=False,
            observacao="[VALIDADA PELO GESTOR] Conflito resolvido em massa."
        )
        if atualizadas:
            messages.success(request, f'{atualizadas} contagem(ns) validada(s) com sucesso.')
        else:
            messages.warning(request, 'Nenhuma contagem selecionada estava em conflito.')
    validar_contagens.short_description = "✅ Validar (Resolve Conflito)"

    def descartar_contagens(self, request, queryset):
        atualizadas = queryset.update(
            em_conflito=False,
            foi_descartada=True,
            observacao="[DESCARTADA PELO GESTOR] Rejeitada em massa."
        )
        messages.success(request, f'{atualizadas} contagem(ns) descartada(s) com sucesso.')
    descartar_contagens.short_description = "🗑️ Descartar (Rejeitar Permanentemente)"

    # =====================
    # EXIBIÇÃO DO STATUS 
    # =====================
    def status_conflito(self, obj):
        if getattr(obj, 'foi_descartada', False):
            return format_html(
                '<span style="color: #6b7280; font-weight: bold;">{}</span>',
                '🗑️ DESCARTADA'
            )
        if getattr(obj, 'em_conflito', False):
            return format_html(
                '<span style="color: #dc2626; font-weight: bold; animation: pulse 1s infinite;">{}</span>',
                '⚠️ CONFLITO'
            )
        return format_html(
            '<span style="color: #16a34a; font-weight: bold;">{}</span>',
            '✓ OK'
        )
    status_conflito.short_description = "Status"
    status_conflito.admin_order_field = 'em_conflito'

    # =====================
    # PREENCHE AUTOMATICAMENTE O OPERADOR AO CRIAR
    # =====================
    def save_model(self, request, obj, form, change):
        if not change:                     # só na criação
            obj.operador = request.user
        super().save_model(request, obj, form, change)

    # =====================
    # DEFINE O VALOR INICIAL DO CAMPO 'operador' PARA O USUÁRIO LOGADO
    # =====================
    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial['operador'] = request.user
        return initial

    # =====================
    # TRANSFORMA 'codigo_produto' EM UM SELECT COM TODOS OS PRODUTOS
    # =====================
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'codigo_produto':
            from .models import Produto
            produtos = Produto.objects.all().order_by('codigo')
            choices = [(p.codigo, f"{p.codigo} – {p.descricao}") for p in produtos]
            from django import forms
            field = forms.ChoiceField(
                choices=[('', '---------')] + choices,
                label=db_field.verbose_name,
                required=not db_field.blank,
                help_text=db_field.help_text,
            )
            return field
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    # Torna o campo operador não obrigatório, pois será preenchido pelo save_model
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['operador'].required = False
        return form

    # =====================
    # ARQUIVO JS PARA AUTO‑PREENCHER A DESCRIÇÃO E DESABILITAR O CAMPO OPERADOR
    # =====================
    class Media:
        js = ('core/js/admin_contagem.js',)


@admin.register(TarefaRecontagem)
class TarefaRecontagemAdmin(admin.ModelAdmin):
    list_display = ('id', 'endereco', 'produto', 'status', 'criticidade', 'responsavel', 'criado_em')
    list_filter = ('status', 'criticidade', 'criado_em')
    search_fields = ('endereco__codigo', 'produto__codigo')


# @admin.register(ConfiguracaoSistema)
# class ConfiguracaoSistemaAdmin(admin.ModelAdmin):
#     list_display = ('versao_minima_app',)
#     fields = ('versao_minima_app',)
#     def has_delete_permission(self, request, obj=None):
#         return False
#     def has_add_permission(self, request):
#         if ConfiguracaoSistema.objects.exists():
#             return False
#         return True


# =========================================================
# DASHBOARD GERENCIAL 
# =========================================================

original_index = admin.site.index

def dashboard_index(request, extra_context=None):
    extra_context = extra_context or {}

    # 1. Taxa de Conflitos 
    total_ok = Contagem.objects.filter(em_conflito=False, foi_descartada=False).count()
    total_conflito = Contagem.objects.filter(em_conflito=True).count()
    total_descartado = Contagem.objects.filter(foi_descartada=True).count()
    extra_context['grafico_conflitos_data'] = json.dumps([total_ok, total_conflito, total_descartado])

    # 2. Produtividade por Operador 
    produtividade = Contagem.objects.values('operador__username') \
        .annotate(total=Count('id')).order_by('-total')[:5]

    extra_context['grafico_produtividade_labels'] = json.dumps([p['operador__username'] for p in produtividade])
    extra_context['grafico_produtividade_data'] = json.dumps([p['total'] for p in produtividade])

    # 3. Pallets Movimentados na Semana 
    hoje = timezone.now().date()
    sete_dias_atras = hoje - timedelta(days=6)

    pallets_qs = Contagem.objects.filter(data_hora__date__gte=sete_dias_atras) \
        .annotate(data=TruncDate('data_hora')) \
        .values('data') \
        .annotate(total_pallets=Sum('pallets')) \
        .order_by('data')

    dias_labels = []
    pallets_data = []

    for i in range(7):
        dia_atual = sete_dias_atras + timedelta(days=i)
        dias_labels.append(dia_atual.strftime('%d/%m'))

        total = next((item['total_pallets'] for item in pallets_qs if item['data'] == dia_atual), 0)
        pallets_data.append(total or 0)

    extra_context['grafico_pallets_labels'] = json.dumps(dias_labels)
    extra_context['grafico_pallets_data'] = json.dumps(pallets_data)

    return original_index(request, extra_context)


admin.site.index = dashboard_index