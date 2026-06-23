import pandas as pd
from django.shortcuts import render
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from datetime import datetime
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, UpdateView
from .forms import ContagemEditForm
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes, authentication_classes, action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.db import IntegrityError
from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from .models import (
    Contagem,
    Produto,
    Rua,
    Endereco,
    TarefaRecontagem,
    ConfiguracaoSistema,
)

from .serializers import (
    ContagemSerializer,
    ProdutoSerializer,
    RuaSerializer,
    EnderecoSerializer,
    TarefaRecontagemSerializer,
)

# ============================================================
# FUNÇÕES DE VERIFICAÇÃO DE PERMISSÃO 
# ============================================================

def is_gestor(user):
    """Acesso total: Apenas Gestores e Superusuários (Admin)"""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return hasattr(user, 'perfil') and user.perfil.cargo == 'GESTOR'


def is_lider_or_gestor(user):
    """Acesso parcial: Líderes, Gestores e Superusuários"""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return hasattr(user, 'perfil') and user.perfil.cargo in ['LIDER', 'GESTOR']


class LiderOrGestorMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin reutilizável para as views baseadas em classe (List/Update)"""
    def test_func(self):
        return is_lider_or_gestor(self.request.user)


# ============================================================
# FUNÇÃO AUXILIAR: Cria tarefa de recontagem se não existir
# ============================================================

def criar_tarefa_recontagem(contagem):
    """
    Cria uma tarefa de recontagem para o endereço/produto de uma
    contagem conflitante, caso ainda não exista tarefa pendente.
    A criticidade é calculada automaticamente com base na diferença
    de pallets entre as contagens conflitantes do dia.
    """
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


# ============================================================
# VIEWSETS
# ============================================================

class ContagemViewSet(viewsets.ModelViewSet):
    queryset = (
        Contagem.objects
        .filter(foi_descartada=False)
        .select_related('operador', 'endereco', 'endereco__rua')  
        .order_by('-data_hora')
    )
    serializer_class = ContagemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        id_local = request.data.get('id_local')
        if id_local:
            existente = Contagem.objects.filter(id_local=id_local, operador=request.user).first()
            if existente:
                serializer = self.get_serializer(existente)
                return Response(serializer.data, status=status.HTTP_200_OK)

        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError as e:
            if 'unico_operador_endereco_produto_por_dia' in str(e):
                return Response(
                    {"error": "Você já contou este produto neste endereço hoje."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            raise

    def perform_create(self, serializer):
        endereco_codigo = self.request.data.get('endereco')
        codigo_produto = self.request.data.get('codigo_produto')
        hoje = timezone.now().date()
        conflito = (
            Contagem.objects.filter(
                endereco__codigo=endereco_codigo,
                codigo_produto=codigo_produto,
                data_hora__date=hoje,
                foi_descartada=False,
            )
            .exclude(operador=self.request.user)
            .exists()
        )
        observacao = self.request.data.get('observacao', '')
        if conflito:
            alerta = "\n\n[ALERTA] Contagem realizada por outro operador para este endereço/produto na mesma data."
            observacao = (observacao or '') + alerta
        nova_contagem = serializer.save(
            operador=self.request.user,
            em_conflito=conflito,
            observacao=observacao,
        )
        if conflito:
            criar_tarefa_recontagem(nova_contagem)

    def perform_update(self, serializer):
        instance = serializer.instance
        campos_auditoria = ['codigo_produto', 'descricao_produto', 'pallets', 'endereco']
        alteracoes = []
        for campo in campos_auditoria:
            if campo not in serializer.validated_data:
                continue
            valor_novo = serializer.validated_data[campo]
            if campo == 'endereco':
                valor_antigo = instance.endereco.codigo
                valor_novo = valor_novo.codigo
            else:
                valor_antigo = getattr(instance, campo)
            if str(valor_antigo) != str(valor_novo):
                alteracoes.append(f"{campo}: '{valor_antigo}' -> '{valor_novo}'")
        if alteracoes:
            timestamp = timezone.localtime().strftime("%d/%m/%Y %H:%M:%S")
            novo_log = f"[{timestamp}] | OPERADOR: @{self.request.user.username} | ALTERAÇÕES: " + " | ".join(alteracoes)
            historico_atual = instance.historico_edicoes or ""
            historico_completo = f"{historico_atual}\n{novo_log}".strip()
            serializer.save(atualizado_por=self.request.user, historico_edicoes=historico_completo)
        else:
            serializer.save(atualizado_por=self.request.user)


class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.all()
    serializer_class = ProdutoSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None


class RuaViewSet(viewsets.ModelViewSet):
    serializer_class = RuaSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Rua.objects.all()
        if hasattr(user, 'perfil'):
            return user.perfil.ruas_permitidas.all()
        return Rua.objects.none()


class EnderecoViewSet(viewsets.ModelViewSet):
    serializer_class = EnderecoSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = Endereco.objects.select_related('rua')
        rua_codigo = self.request.query_params.get('rua_codigo')
        if rua_codigo:
            qs = qs.filter(rua__codigo=rua_codigo)
        return qs.order_by(
            'rua_num',
            F('predio_num').asc(nulls_last=True),
            F('andar_num').asc(nulls_last=True),
            F('posicao_num').asc(nulls_last=True),
            'codigo',
        )


class TarefaRecontagemViewSet(viewsets.ModelViewSet):
    serializer_class = TarefaRecontagemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            TarefaRecontagem.objects
            .select_related('endereco', 'produto', 'responsavel')
            .filter(status__in=[TarefaRecontagem.Status.PENDENTE, TarefaRecontagem.Status.EM_ANDAMENTO])
            .order_by(
                'endereco__rua_num',
                'endereco__predio_num',
                'endereco__andar_num',
                'endereco__posicao_num',
            )
        )

    def perform_update(self, serializer):
        tarefa = serializer.save()
        if tarefa.status == TarefaRecontagem.Status.CONCLUIDO:
            tarefa.concluido_em = timezone.now()
            tarefa.save(update_fields=['concluido_em'])

    @action(detail=True, methods=['post'])
    def assumir(self, request, pk=None):
        tarefa = self.get_object()
        tarefa.responsavel = request.user
        tarefa.status = TarefaRecontagem.Status.EM_ANDAMENTO
        tarefa.save()
        return Response({'sucesso': True})


# ============================================================
# IMPORTAÇÃO DE PRODUTOS E ENDEREÇOS
# ============================================================

@csrf_exempt
@user_passes_test(is_gestor, login_url='/admin/login/')
def importar_produtos(request):
    context = {'msg': ''}
    if request.method == 'POST' and request.FILES.getlist('file'):
        arquivos = request.FILES.getlist('file')
        arquivos_sucesso = 0
        erros = []
        for arquivo in arquivos:
            print(f"\n--- INICIANDO LEITURA DO ARQUIVO: {arquivo.name} ---")
            try:
                xls = pd.ExcelFile(arquivo, engine='openpyxl')
                enderecos_encontrados = set()
                lista_df_produtos = []
                for aba in xls.sheet_names:
                    df_temp = pd.read_excel(xls, sheet_name=aba)
                    colunas = [str(c).upper().replace(' ', '').replace('_', '').replace('Ç', 'C')
                               .replace('Ã', 'A').replace('Á', 'A').replace('É', 'E').replace('Í', 'I')
                               .replace('Ó', 'O').replace('Ú', 'U') for c in df_temp.columns]
                    df_temp.columns = colunas
                    df_temp = df_temp.loc[:, ~df_temp.columns.duplicated()].copy()
                    colunas = list(df_temp.columns)
                    if 'ENDERECO' in colunas:
                        enderecos = df_temp['ENDERECO'].dropna().astype(str)
                        for endereco in enderecos:
                            endereco = endereco.strip()
                            if endereco.endswith('.0'): endereco = endereco[:-2]
                            if endereco and endereco.lower() != 'nan':
                                enderecos_encontrados.add(endereco)
                    col_codigo = 'CODIGO' if 'CODIGO' in colunas else ('CODPRODUTO' if 'CODPRODUTO' in colunas else ('COD' if 'COD' in colunas else None))
                    col_desc = 'DESCRICAO' if 'DESCRICAO' in colunas else None
                    if col_codigo and col_desc:
                        cols_to_keep = [col_codigo, col_desc]
                        opcionais = ['PALETIZACAO', 'TIPO', 'VALORPALETE', 'PAC', 'MATERIAL', 'TEXTOBREVEMATERIAL', 'TIPOPALLET']
                        for op in opcionais:
                            if op in colunas: cols_to_keep.append(op)
                        df_filtrado = df_temp[cols_to_keep].copy()
                        df_filtrado.rename(columns={col_codigo: 'CODIGO_PADRAO', col_desc: 'DESCRICAO_PADRAO'}, inplace=True)
                        lista_df_produtos.append(df_filtrado)
                enderecos_ignorados = set()
                for endereco_codigo in enderecos_encontrados:
                    if len(endereco_codigo) == 5:
                        rua_codigo_str = endereco_codigo[0]
                        predio_str = endereco_codigo[1]
                        posicao_str = endereco_codigo[2:]
                    elif len(endereco_codigo) == 6:
                        rua_codigo_str = endereco_codigo[:2]
                        predio_str = endereco_codigo[2]
                        posicao_str = endereco_codigo[3:]
                    else:
                        enderecos_ignorados.add(endereco_codigo)
                        continue
                    rua, _ = Rua.objects.get_or_create(codigo=rua_codigo_str)
                    r_num = int(rua_codigo_str) if rua_codigo_str.isdigit() else None
                    p_num = int(predio_str) if predio_str.isdigit() else None
                    pos_num = int(posicao_str) if posicao_str.isdigit() else None
                    Endereco.objects.get_or_create(codigo=endereco_codigo, defaults={
                        'rua': rua,
                        'rua_num': r_num,
                        'predio_num': p_num,
                        'andar_num': 0,
                        'posicao_num': pos_num,
                    })
                if enderecos_ignorados:
                    exemplos = list(enderecos_ignorados)[:3]
                    erros.append(f"⚠️ Aviso: {len(enderecos_ignorados)} endereço(s) ignorado(s) por formato inválido "
                                 f"(Exemplos: {', '.join(exemplos)}). O sistema espera 5 ou 6 caracteres.")
                if lista_df_produtos:
                    df_produtos = pd.concat(lista_df_produtos, ignore_index=True).drop_duplicates(subset=['CODIGO_PADRAO'])
                    mapeamento_opcional = {
                        'PALETIZACAO': 'palletizacao',
                        'TIPO': 'tipo',
                        'PAC': 'pac',
                        'MATERIAL': 'material',
                        'TEXTOBREVEMATERIAL': 'texto_breve_material',
                        'TIPOPALLET': 'tipo_pallet',
                    }
                    for _, row in df_produtos.iterrows():
                        codigo = str(row.get('CODIGO_PADRAO', '')).strip()
                        descricao = str(row.get('DESCRICAO_PADRAO', '')).strip()
                        if codigo.endswith('.0'): codigo = codigo[:-2]
                        if codigo and codigo.lower() != 'nan' and descricao and descricao.lower() != 'nan':
                            defaults = {'descricao': descricao}
                            for col_ex, col_mod in mapeamento_opcional.items():
                                if col_ex in row:
                                    val = str(row[col_ex]).strip()
                                    if val and val.lower() != 'nan':
                                        defaults[col_mod] = val
                            if 'VALORPALETE' in row:
                                val = str(row['VALORPALETE']).strip()
                                if val and val.lower() != 'nan':
                                    try:
                                        val = val.replace(',', '.').replace('R$', '').replace(' ', '')
                                        defaults['valor_palete'] = float(val)
                                    except ValueError:
                                        pass
                            Produto.objects.update_or_create(codigo=codigo, defaults=defaults)
                arquivos_sucesso += 1
            except Exception as e:
                erro_msg = f'Erro no arquivo {arquivo.name}: {str(e)}'
                print(f"\n!!! ERRO FATAL: {erro_msg}")
                erros.append(erro_msg)
        if arquivos_sucesso > 0:
            context['msg'] = f'{arquivos_sucesso} planilha(s) processada(s) com sucesso! '
        if erros:
            context['msg'] += " | ".join(erros)
    return render(request, 'core/importar.html', context)


# ============================================================
# EXPORTAÇÃO
# ============================================================

@user_passes_test(is_gestor, login_url='/admin/login/')
def exportar_contagens(request):
    contagens = (
        Contagem.objects
        .filter(foi_descartada=False)
        .select_related('operador', 'endereco', 'endereco__rua')
        .order_by('-data_hora')
    )
    dados = []
    for c in contagens:
        dados.append({
            'ID': c.id,
            'Operador': c.operador.username,
            'Rua': c.endereco.rua.codigo,
            'Endereço': c.endereco.codigo,
            'Prédio': c.endereco.predio_num,
            'Posição': c.endereco.posicao_num,
            'Código Produto': c.codigo_produto,
            'Descrição': c.descricao_produto,
            'Pallets': c.pallets,
            'Observação': c.observacao,
            'Data e Hora': c.data_hora.strftime('%d/%m/%Y %H:%M:%S'),
        })
    df = pd.DataFrame(dados)
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="Contagens_Consolidadas.xlsx"'
    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Base Consolidada')

    
    LogEntry.objects.create(
        action=LogEntry.Action.ACCESS,
        content_type=ContentType.objects.get_for_model(Contagem),
        object_repr="Exportação Completa de Contagens",
        actor=request.user,
        changes={'action': 'exportar', 'tipo': 'completa', 'formato': 'xlsx'},
    )

    return response


# ============================================================
# EXPORTAÇÃO POR PERÍODO
# ============================================================

@user_passes_test(is_gestor, login_url='/admin/login/')
def selecionar_periodo_exportacao(request):
    if request.method == 'POST':
        data_inicio = request.POST.get('data_inicio')
        data_fim = request.POST.get('data_fim')
        contagens = (
            Contagem.objects
            .filter(data_hora__date__range=[data_inicio, data_fim], foi_descartada=False)
            .select_related('operador', 'endereco', 'endereco__rua')
            .order_by('-data_hora')
        )
        dados = []
        for c in contagens:
            dados.append({
                'ID': c.id,
                'Operador': c.operador.username,
                'Rua': c.endereco.rua.codigo,
                'Endereço': c.endereco.codigo,
                'Prédio': c.endereco.predio_num,
                'Posição': c.endereco.posicao_num,
                'Código Produto': c.codigo_produto,
                'Descrição': c.descricao_produto,
                'Pallets': c.pallets,
                'Observação': c.observacao,
                'Data e Hora': c.data_hora.strftime('%d/%m/%Y %H:%M:%S'),
            })
        df = pd.DataFrame(dados)
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="Contagens_{data_inicio}_ate_{data_fim}.xlsx"'
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Base Consolidada')

        
        LogEntry.objects.create(
            action=LogEntry.Action.ACCESS,
            content_type=ContentType.objects.get_for_model(Contagem),
            object_repr=f"Exportação de Contagens ({data_inicio} a {data_fim})",
            actor=request.user,
            changes={'action': 'exportar', 'tipo': 'periodo', 'inicio': data_inicio, 'fim': data_fim, 'formato': 'xlsx'},
        )

        return response
    return render(request, 'core/exportar_periodo.html')


# ============================================================
# DASHBOARD
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def dashboard(request):
    hoje = timezone.localdate()
    base_qs = Contagem.objects.filter(foi_descartada=False)
    produtividade = base_qs.values('operador__username').annotate(total=Sum('pallets')).order_by('-total')
    diario = base_qs.annotate(date=TruncDate('data_hora')).values('date').annotate(total=Count('id')).order_by('date')
    total_pallets   = base_qs.aggregate(total=Sum('pallets'))['total'] or 0
    total_contagens = base_qs.count()
    contagens_hoje  = base_qs.filter(data_hora__date=hoje).count()
    operadores_ativos = base_qs.filter(data_hora__date=hoje).values('operador').distinct().count()
    registros_editados = base_qs.exclude(historico_edicoes__isnull=True).exclude(historico_edicoes='').count()
    context = {
        'produtividade': list(produtividade),
        'diario': list(diario),
        'total_pallets': total_pallets,
        'total_contagens': total_contagens,
        'contagens_hoje': contagens_hoje,
        'operadores_ativos': operadores_ativos,
        'registros_editados': registros_editados,
    }
    return render(request, 'core/dashboard.html', context)


# ============================================================
# PAINEL DE GESTÃO (TELA INICIAL)
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def painel_gestao(request):
    return render(request, 'core/painel.html')

class ContagemListView(LiderOrGestorMixin, ListView):
    model = Contagem
    template_name = 'core/gestao_contagens.html'
    context_object_name = 'contagens'
    paginate_by = 30
    ordering = ['data_hora']

    def get_queryset(self):
        qs = super().get_queryset().filter(foi_descartada=False).select_related('operador', 'endereco', 'endereco__rua')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(operador__username__icontains=q) |
                Q(endereco__codigo__icontains=q) |
                Q(codigo_produto__icontains=q) |
                Q(descricao_produto__icontains=q)
            )
        rua_id = self.request.GET.get('rua_id')
        if rua_id:
            qs = qs.filter(endereco__rua_id=rua_id)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        context['rua_id'] = self.request.GET.get('rua_id', '')
        ruas_qs = Rua.objects.all()
        ruas_list = sorted(ruas_qs, key=lambda r: int(r.codigo) if r.codigo.isdigit() else r.codigo)
        context['ruas'] = ruas_list
        context['total_pallets'] = self.get_queryset().aggregate(total=Sum('pallets')).get('total') or 0
        return context


class ContagemUpdateView(LiderOrGestorMixin, UpdateView):
    model = Contagem
    form_class = ContagemEditForm
    template_name = 'core/editar_contagem.html'
    success_url = reverse_lazy('lista_contagens')

    def form_valid(self, form):
        if form.changed_data:
            original = Contagem.objects.get(pk=self.object.pk)
            alteracoes = []
            for campo in form.changed_data:
                valor_antigo = getattr(original, campo)
                valor_novo = form.cleaned_data.get(campo)
                alteracoes.append(f"{campo}: '{valor_antigo}' -> '{valor_novo}'")
            timestamp = timezone.localtime().strftime("%d/%m/%Y %H:%M:%S")
            novo_log = f"[{timestamp}] | OPERADOR (Painel): @{self.request.user.username} | ALTERAÇÕES: " + " | ".join(alteracoes)
            historico_atual = original.historico_edicoes or ""
            historico_completo = f"{historico_atual}\n{novo_log}".strip()
            self.object = form.save(commit=False)
            self.object.historico_edicoes = historico_completo
            self.object.save()
        else:
            self.object = form.save()
        messages.success(self.request, f'Contagem #{self.object.pk} atualizada com sucesso.')
        return redirect(self.success_url)


@login_required
@user_passes_test(lambda u: u.is_staff)
def deletar_contagem(request, pk):
    if request.method == 'POST':
        contagem = get_object_or_404(Contagem, pk=pk)
        contagem.delete()
        messages.success(request, 'Contagem excluída com sucesso.')
    return redirect('lista_contagens')


# ============================================================
# SINCRONIZAÇÃO OFFLINE
# ============================================================

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def sincronizar_contagens_offline(request):
    dados = request.data.get('contagens', [])
    hoje = timezone.now().date()
    resultados = {"salvas_com_sucesso": 0, "marcadas_com_conflito": 0, "erros": 0}
    for item in dados:
        endereco_codigo = item.get('endereco_codigo')
        codigo_produto = item.get('codigo_produto')
        pallets = item.get('pallets')
        uuid_aparelho = item.get('uuid_aparelho')
        try:
            endereco = Endereco.objects.get(codigo=endereco_codigo)
            contagem_existente = Contagem.objects.filter(
                endereco=endereco,
                codigo_produto=codigo_produto,
                data_hora__date=hoje,
                foi_descartada=False,
            ).exclude(uuid_aparelho=uuid_aparelho).first()
            nova_contagem = Contagem(
                operador=request.user,
                endereco=endereco,
                codigo_produto=codigo_produto,
                descricao_produto=item.get('descricao_produto', 'Sincronizado Offline'),
                pallets=pallets,
                uuid_aparelho=uuid_aparelho,
                observacao="Sincronização Offline",
                em_conflito=bool(contagem_existente),
            )
            nova_contagem.save()
            if contagem_existente and not contagem_existente.em_conflito:
                contagem_existente.em_conflito = True
                contagem_existente.observacao = f"Conflito detectado com o aparelho {uuid_aparelho}"
                contagem_existente.save()
                criar_tarefa_recontagem(contagem_existente)
                criar_tarefa_recontagem(nova_contagem)
            if nova_contagem.em_conflito:
                resultados["marcadas_com_conflito"] += 1
            else:
                resultados["salvas_com_sucesso"] += 1
        except Endereco.DoesNotExist:
            resultados["erros"] += 1
    return Response(resultados, status=status.HTTP_200_OK)


# ============================================================
# RESOLUÇÃO DE CONFLITOS
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def resolucao_conflitos(request):
    contagens_em_conflito = Contagem.objects.filter(em_conflito=True).select_related(
        'endereco', 'endereco__rua', 'operador'
    ).order_by('endereco__codigo', 'codigo_produto', '-data_hora')
    conflitos_agrupados = {}
    for c in contagens_em_conflito:
        chave = f"{c.endereco.codigo}_{c.codigo_produto}"
        if chave not in conflitos_agrupados:
            conflitos_agrupados[chave] = {
                'endereco': c.endereco.codigo,
                'produto_codigo': c.codigo_produto,
                'produto_descricao': c.descricao_produto,
                'registros': [],
            }
        conflitos_agrupados[chave]['registros'].append(c)
    context = {
        'conflitos_agrupados': conflitos_agrupados.values(),
        'total_conflitos': len(conflitos_agrupados),
    }
    return render(request, 'core/resolucao_conflitos.html', context)


@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def resolver_conflito(request, contagem_id):
    if request.method == 'POST':
        contagem_vencedora = get_object_or_404(Contagem, id=contagem_id)
        Contagem.objects.filter(
            endereco=contagem_vencedora.endereco,
            codigo_produto=contagem_vencedora.codigo_produto,
            em_conflito=True,
        ).exclude(id=contagem_id).update(
            em_conflito=False,
            foi_descartada=True,
            observacao="[REJEITADA] Esta contagem foi descartada pelo gestor na resolução de conflitos.",
        )
        contagem_vencedora.em_conflito = False
        contagem_vencedora.observacao = "Resolvido pelo Gestor via Painel"
        contagem_vencedora.save()
        messages.success(request, "Conflito resolvido! A contagem selecionada foi mantida e as incorretas foram arquivadas.")
    return redirect('resolucao_conflitos')


# ============================================================
# STAGE 
# ============================================================

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def registrar_stage(request):
    dados = request.data
    local = (dados.get('local') or 'STAGE').strip()
    produto_codigo = dados.get('produto')
    quantidade = dados.get('quantidade')
    observacao_original = (dados.get('observacao') or '').strip()
    try:
        produto = Produto.objects.get(codigo=produto_codigo)
    except Produto.DoesNotExist:
        return Response({'erro': 'Produto não encontrado no sistema.'}, status=status.HTTP_404_NOT_FOUND)
    rua_stage, _ = Rua.objects.get_or_create(codigo='STAGE')
    endereco_stage, _ = Endereco.objects.get_or_create(
        codigo='STAGE',
        defaults={'rua': rua_stage, 'predio_num': 0, 'posicao_num': 0},
    )
    observacao_final = f"[{local}] {observacao_original}".strip()
    try:
        Contagem.objects.create(
            operador=request.user,
            endereco=endereco_stage,
            codigo_produto=produto.codigo,
            descricao_produto=produto.descricao,
            pallets=quantidade,
            observacao=observacao_final,
        )
        return Response({'sucesso': 'Registro de Stage salvo com sucesso.'}, status=status.HTTP_201_CREATED)
    except IntegrityError:
        return Response(
            {"error": "Você já registrou este produto no stage hoje."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        return Response({'erro': f'Erro ao salvar contagem: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ============================================================
# CRIAÇÃO DE TAREFAS DE RECONTAGEM EM LOTE
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def criar_recontagem_lote(request):
    if request.method == 'POST':
        contagem_id = request.POST.get('contagem_id')
        escopo = request.POST.get('escopo')  

        if not contagem_id:
            messages.error(request, "Selecione um registro base.")
            return redirect('criar_recontagem_lote')

        try:
            contagem_base = Contagem.objects.select_related('endereco', 'operador').get(pk=contagem_id)
        except Contagem.DoesNotExist:
            messages.error(request, "Registro base não encontrado.")
            return redirect('criar_recontagem_lote')

        try:
            produto = Produto.objects.get(codigo=contagem_base.codigo_produto)
        except Produto.DoesNotExist:
            messages.error(request, f"Produto '{contagem_base.codigo_produto}' não encontrado no sistema.")
            return redirect('criar_recontagem_lote')

       
        if escopo == 'todos':
            enderecos_ids = Contagem.objects.filter(
                codigo_produto=produto.codigo,
                foi_descartada=False
            ).values_list('endereco_id', flat=True).distinct()
            enderecos_alvo = list(Endereco.objects.filter(id__in=enderecos_ids))
        else:
            
            enderecos_alvo = [contagem_base.endereco]

        if not enderecos_alvo:
            messages.warning(request, f"Nenhum endereço encontrado contendo o produto {produto.codigo}.")
            return redirect('criar_recontagem_lote')

        tarefas_criadas = 0
        for endereco in enderecos_alvo:
            tarefa_existe = TarefaRecontagem.objects.filter(
                endereco=endereco,
                produto=produto,
                status__in=['PENDENTE', 'EM_ANDAMENTO'],
            ).exists()
            if not tarefa_existe:
                TarefaRecontagem.objects.create(
                    endereco=endereco,
                    produto=produto,
                    status='PENDENTE',
                    observacao=f"Missão gerada a partir da contagem #{contagem_base.id}."
                )
                tarefas_criadas += 1

        if tarefas_criadas > 0:
            messages.success(request, f"Sucesso! {tarefas_criadas} missões criadas para o produto {produto.codigo}.")
        else:
            messages.info(request, f"As missões para o produto {produto.codigo} já estavam ativas nesses endereços.")

        return redirect('criar_recontagem_lote')

    
    contagens = Contagem.objects.filter(foi_descartada=False) \
        .select_related('endereco', 'operador') \
        .order_by('-data_hora')[:1000]  
    return render(request, 'core/recontagem_produto.html', {'contagens': contagens})


# ============================================================
# RANKING DIÁRIO
# ============================================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def ranking_diario(request):
    hoje = timezone.localdate()
    ranking = (
        Contagem.objects
        .filter(data_hora__date=hoje, foi_descartada=False)   
        .values('operador__username')
        .annotate(total_pallets=Sum('pallets'))
        .order_by('-total_pallets')
    )
    return Response({
        'ranking': list(ranking),
        'operador_logado': request.user.username,
        'meta_diaria': 150,
    })


# ============================================================
# PRODUTIVIDADE DIÁRIA DO OPERADOR
# ============================================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def produtividade_diaria(request):
    hoje = timezone.localdate()
    operador = request.user
    total_pallets = (
        Contagem.objects
        .filter(operador=operador, data_hora__date=hoje, foi_descartada=False)   
        .aggregate(total=Sum('pallets'))['total'] or 0
    )
    missoes_concluidas = (
        TarefaRecontagem.objects
        .filter(responsavel=operador, status='CONCLUIDO')
        .count()
    )
    return Response({
        'total_pallets': total_pallets,
        'missoes_concluidas': missoes_concluidas,
    })

# ============================================================
# PUSH TOKEN
# ============================================================

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def atualizar_push_token(request):
    token = request.data.get('token')
    if token:
        perfil = request.user.perfil
        perfil.push_token = token
        perfil.save()
        return Response({"status": "Token atualizado com sucesso"})
    return Response({"error": "Token não fornecido"}, status=400)


# ============================================================
# VERSÃO MÍNIMA DO APP
# ============================================================

@api_view(['GET'])
@permission_classes([AllowAny])
def versao_minima_app(request):
    config = ConfiguracaoSistema.load()
    return Response({'versao_minima': config.versao_minima_app})