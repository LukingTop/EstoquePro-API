import json
from datetime import timedelta, datetime
from django.contrib import admin
from django.utils.html import format_html
from django.contrib.auth.models import Group
from django.contrib import messages
from django.db.models import Count, Sum, IntegerField
from django.db.models.functions import TruncDate, Cast
from django.utils import timezone
from django.apps import apps
from django.contrib.admin.exceptions import NotRegistered
from django_apscheduler.models import DjangoJob, DjangoJobExecution
from auditlog.admin import LogEntryAdmin
from auditlog.models import LogEntry
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import path
from django.shortcuts import render, redirect
from .forms import RecontagemPorRuaIntervaloForm


# ============================================================
# ADMIN CUSTOMIZADO DO LOG ENTRY 
# ============================================================
class CustomLogEntryAdmin(LogEntryAdmin):
    list_filter = (('timestamp', admin.DateFieldListFilter), 'action', 'content_type')

# ============================================================
# TRADUÇÕES E CONFIGURAÇÕES INICIAIS
# ============================================================
try:
    audit_app = apps.get_app_config('auditlog')
    audit_app.verbose_name = "Auditoria do Sistema"

    LogEntry._meta.verbose_name = "Entrada de Log"
    LogEntry._meta.verbose_name_plural = "Entradas de Log"

    LogEntry._meta.get_field('action').verbose_name = 'Ação'
    LogEntry._meta.get_field('action').choices = [
        (0, 'Criar'),
        (1, 'Atualizar'),
        (2, 'Deletar'),
        (3, 'Acessar'),
    ]

    LogEntry._meta.get_field('content_type').verbose_name = 'Tipo de Recurso'
    LogEntry._meta.get_field('cid').verbose_name = 'ID de Correlação'

    apscheduler_app = apps.get_app_config('django_apscheduler')
    apscheduler_app.verbose_name = "Processos em Segundo Plano"

    DjangoJob._meta.verbose_name = "Tarefa Automática"
    DjangoJob._meta.verbose_name_plural = "Tarefas Automáticas"
    DjangoJobExecution._meta.verbose_name = "Execução de Tarefa"
    DjangoJobExecution._meta.verbose_name_plural = "Histórico de Execuções"
except LookupError:
    pass

# ============================================================
# SUBSTITUI O ADMIN PADRÃO DO LOG ENTRY
# ============================================================
try:
    admin.site.unregister(LogEntry)
except NotRegistered:
    pass
admin.site.register(LogEntry, CustomLogEntryAdmin)

# ============================================================
# OCULTA MODELOS INDESEJADOS
# ============================================================
for model in [Group, DjangoJob, DjangoJobExecution]:
    try:
        admin.site.unregister(model)
    except NotRegistered:
        pass

try:
    admin.site.unregister(User)
except NotRegistered:
    pass
admin.site.register(User, UserAdmin)

# ============================================================
# IMPORTA OS MODELOS LOCAIS
# ============================================================
from .models import (
    Rua,
    Endereco,
    PerfilOperador,
    Produto,
    Contagem,
    TarefaRecontagem,
    ConfiguracaoSistema,
    ModeloPlanilha,
    ContagemSessao
)

# ============================================================
# FUNÇÃO AUXILIAR PARA REGISTRAR SEM ERRO DE DUPLICIDADE
# ============================================================
def safe_register(model, admin_class):
    try:
        admin.site.unregister(model)
    except NotRegistered:
        pass
    admin.site.register(model, admin_class)

# ============================================================
# DEMAIS CLASSES DE ADMIN 
# ============================================================
class RuaAdmin(admin.ModelAdmin):
    list_display = ('id', 'codigo')
    search_fields = ('codigo',)
    ordering = ['ordem']
    fields = ('codigo',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Exclui apenas ruas sem endereço associado
        return qs.filter(enderecos__isnull=False).distinct()

class EnderecoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'rua', 'predio_num', 'andar_num', 'posicao_num')
    search_fields = ('codigo',)
    list_filter = ('rua',)
    ordering = ('rua_num', 'predio_num', 'andar_num', 'posicao_num')

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

class ProdutoAdmin(admin.ModelAdmin):
    list_display = (
        'codigo', 'descricao', 'palletizacao', 'valor_palete', 'pac'
    )
    search_fields = ('codigo', 'descricao')
    ordering = []  

    fieldsets = (
        (None, {
            'fields': ('codigo', 'descricao')
        }),
        ('Dados de Paletização', {
            'fields': (
                'palletizacao', 'valor_palete', 'pac',
            )
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            codigo_int=Cast('codigo', output_field=IntegerField())
        ).order_by('codigo_int', 'codigo')

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

    def status_conflito(self, obj):
        if getattr(obj, 'foi_descartada', False):
            return format_html('<span style="color: #6b7280; font-weight: bold;">{}</span>', '🗑️ DESCARTADA')
        if getattr(obj, 'em_conflito', False):
            return format_html('<span style="color: #dc2626; font-weight: bold; animation: pulse 1s infinite;">{}</span>', '⚠️ CONFLITO')
        return format_html('<span style="color: #16a34a; font-weight: bold;">{}</span>', '✓ OK')
    status_conflito.short_description = "Status"
    status_conflito.admin_order_field = 'em_conflito'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.operador = request.user
        super().save_model(request, obj, form, change)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial['operador'] = request.user
        return initial

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

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['operador'].required = False
        return form

    class Media:
        js = ('core/js/admin_contagem.js',)

class TarefaRecontagemAdmin(admin.ModelAdmin):
    list_display = ('id', 'endereco', 'produto', 'status', 'criticidade', 'responsavel', 'criado_em')
    list_filter = ('status', 'criticidade', 'criado_em')
    search_fields = ('endereco__codigo', 'produto__codigo', 'produto__descricao')
    actions = ['criar_recontagem_por_rua_intervalo_action']

    def criar_recontagem_por_rua_intervalo_action(self, request, queryset):
        return redirect('admin:criar_recontagem_por_rua_intervalo')
    criar_recontagem_por_rua_intervalo_action.short_description = "Criar recontagem por rua/intervalo"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'criar-recontagem-rua-intervalo/',
                self.admin_site.admin_view(self.criar_recontagem_por_rua_intervalo_view),
                name='criar_recontagem_por_rua_intervalo',
            ),
        ]
        return custom_urls + urls

    def criar_recontagem_por_rua_intervalo_view(self, request):
        if request.method == 'POST':
            form = RecontagemPorRuaIntervaloForm(request.POST)
            if form.is_valid():
                rua_codigo = form.cleaned_data['rua_codigo']
                end_inicio = form.cleaned_data['endereco_inicio']
                end_fim = form.cleaned_data['endereco_fim']

                try:
                    rua = Rua.objects.get(codigo=rua_codigo)
                except Rua.DoesNotExist:
                    messages.error(request, f'Rua "{rua_codigo}" não encontrada.')
                    return redirect('admin:criar_recontagem_por_rua_intervalo')

                contagens = Contagem.objects.filter(
                    foi_descartada=False,
                    endereco__rua=rua
                )

                if end_inicio and end_fim:
                    contagens = contagens.filter(endereco__codigo__range=[end_inicio, end_fim])
                elif end_inicio:
                    contagens = contagens.filter(endereco__codigo__gte=end_inicio)
                elif end_fim:
                    contagens = contagens.filter(endereco__codigo__lte=end_fim)

                pares = contagens.values('endereco_id', 'codigo_produto').distinct()
                criadas = 0
                for par in pares:
                    try:
                        produto = Produto.objects.get(codigo=par['codigo_produto'])
                    except Produto.DoesNotExist:
                        continue

                    endereco = Endereco.objects.get(pk=par['endereco_id'])
                    existe = TarefaRecontagem.objects.filter(
                        endereco=endereco,
                        produto=produto,
                        status__in=[TarefaRecontagem.Status.PENDENTE, TarefaRecontagem.Status.EM_ANDAMENTO]
                    ).exists()

                    if not existe:
                        TarefaRecontagem.objects.create(
                            endereco=endereco,
                            produto=produto,
                            status=TarefaRecontagem.Status.PENDENTE,
                            observacao=f'Criada em lote via admin (Rua {rua_codigo})'
                        )
                        criadas += 1

                if criadas:
                    messages.success(request, f'{criadas} missões de recontagem criadas com sucesso.')
                else:
                    messages.info(request, 'Nenhuma missão nova – já existem tarefas pendentes.')

                return redirect('admin:core_tarefarecontagem_changelist')
        else:
            form = RecontagemPorRuaIntervaloForm()

        context = {
            'title': 'Criar Recontagem por Rua/Intervalo',
            'form': form,
            'opts': TarefaRecontagem._meta,
            'site_header': self.admin_site.site_header,
            'site_title': self.admin_site.site_title,
            'has_permission': True,
        }
        return render(
            request,
            'admin/core/tarefarecontagem/criar_recontagem_por_rua_intervalo.html',
            context
        )

# ============================================================
# REGISTRO SEGURO DE TODOS OS MODELOS
# ============================================================
safe_register(Rua, RuaAdmin)
safe_register(Endereco, EnderecoAdmin)
safe_register(PerfilOperador, PerfilOperadorAdmin)
safe_register(Produto, ProdutoAdmin)
safe_register(Contagem, ContagemAdmin)
safe_register(TarefaRecontagem, TarefaRecontagemAdmin)

# ============================================================
# DASHBOARD GERENCIAL
# ============================================================
original_index = admin.site.index

def dashboard_index(request, extra_context=None):
    extra_context = extra_context or {}

    total_ok = Contagem.objects.filter(em_conflito=False, foi_descartada=False).count()
    total_conflito = Contagem.objects.filter(em_conflito=True).count()
    total_descartado = Contagem.objects.filter(foi_descartada=True).count()
    extra_context['grafico_conflitos_data'] = json.dumps([total_ok, total_conflito, total_descartado])

    produtividade = Contagem.objects.values('operador__username') \
        .annotate(total=Count('id')).order_by('-total')[:5]
    extra_context['grafico_produtividade_labels'] = json.dumps([p['operador__username'] for p in produtividade])
    extra_context['grafico_produtividade_data'] = json.dumps([p['total'] for p in produtividade])

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

class ContagemSessaoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'criado_por', 'ativo', 'criado_em', 'inicio', 'fim')
    list_filter = ('ativo',)
    filter_horizontal = ('ruas',)
    fields = ('titulo', 'ruas', 'ativo')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.criado_por = request.user
        super().save_model(request, obj, form, change)

ContagemSessao._meta.verbose_name = "Sessão de Contagem"
ContagemSessao._meta.verbose_name_plural = "Sessões de Contagem"
        
safe_register(ContagemSessao, ContagemSessaoAdmin)

admin.site.index = dashboard_index