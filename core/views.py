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
    Avaria
)

from .serializers import (
    ContagemSerializer,
    ProdutoSerializer,
    RuaSerializer,
    EnderecoSerializer,
    TarefaRecontagemSerializer,
    AvariaSerializer
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
    authentication_classes = [SessionAuthentication, JWTAuthentication]   
    pagination_class = None

    def get_queryset(self):
        qs = Endereco.objects.select_related('rua')
        user = self.request.user

        if not user.is_staff and hasattr(user, 'perfil'):
            qs = qs.filter(rua__in=user.perfil.ruas_permitidas.all())

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

        COLUNAS_DESEJADAS = ['COD', 'DESCRICAO', 'PALETIZACAO', 'VALORPALETE', 'PAC']

        for arquivo in arquivos:
            nome_arquivo = str(arquivo.name)
            print(f"\n--- INICIANDO LEITURA DO ARQUIVO: {nome_arquivo} ---")
            try:
                enderecos_encontrados = set()
                abas_importadas = 0

                if nome_arquivo.lower().endswith('.csv'):
                    # Lê o conteúdo bruto do arquivo
                    raw_bytes = arquivo.read()
                    # Tenta decodificar com várias codificações
                    codificacoes = ['utf-8', 'latin-1', 'iso-8859-1', 'windows-1252', 'cp1252', 'utf-16']
                    texto = None
                    cod_usada = None
                    for cod in codificacoes:
                        try:
                            texto = raw_bytes.decode(cod)
                            cod_usada = cod
                            break
                        except UnicodeDecodeError:
                            continue
                    if texto is None:
                        raise Exception("Não foi possível decodificar o arquivo CSV com as codificações suportadas.")

                    # Usa StringIO para simular um arquivo de texto
                    from io import StringIO
                    df = pd.read_csv(
                        StringIO(texto),
                        dtype=str,
                        sep=';',
                        skip_blank_lines=True,
                    )
                    lista_dfs = [('CSV', df)]
                else:
                    xls = pd.ExcelFile(arquivo, engine='openpyxl')
                    lista_dfs = [(aba, pd.read_excel(xls, sheet_name=aba, dtype=str)) for aba in xls.sheet_names]

                for nome_aba, df in lista_dfs:
                    colunas_originais = [str(c).strip() for c in df.columns]
                    norm_map = {}
                    for c in colunas_originais:
                        norm = c.upper().replace(' ', '').replace('_', '').replace('Ç', 'C') \
                                 .replace('Ã', 'A').replace('Á', 'A').replace('É', 'E').replace('Í', 'I') \
                                 .replace('Ó', 'O').replace('Ú', 'U')
                        norm_map[norm] = c

                    # ---- COLETA DE ENDEREÇOS ----
                    if 'ENDERECO' in norm_map:
                        col_end = norm_map['ENDERECO']
                        enderecos = df[col_end].dropna().astype(str)
                        for endereco in enderecos:
                            endereco = endereco.strip()
                            if endereco.endswith('.0'):
                                endereco = endereco[:-2]
                            if endereco and endereco.lower() != 'nan':
                                enderecos_encontrados.add(endereco)

                    # ---- VERIFICA SE TEM AS 5 COLUNAS ----
                    if not all(col in norm_map for col in COLUNAS_DESEJADAS):
                        continue

                    colunas_orig = [norm_map[col] for col in COLUNAS_DESEJADAS]
                    df_trab = df[colunas_orig].copy()
                    df_trab.columns = ['CODIGO_PADRAO', 'DESCRICAO_PADRAO', 'PALETIZACAO', 'VALORPALETE', 'PAC']

                    for _, row in df_trab.iterrows():
                        codigo = str(row['CODIGO_PADRAO']).strip()
                        descricao = str(row['DESCRICAO_PADRAO']).strip()
                        if codigo.endswith('.0'):
                            codigo = codigo[:-2]
                        if not codigo or codigo.lower() == 'nan' or not descricao or descricao.lower() == 'nan':
                            continue

                        defaults = {'descricao': descricao}

                        val = str(row.get('PALETIZACAO', '')).strip()
                        if val and val.lower() != 'nan':
                            defaults['palletizacao'] = val

                        val = str(row.get('PAC', '')).strip()
                        if val and val.lower() != 'nan':
                            defaults['pac'] = val

                        val_str = str(row.get('VALORPALETE', '')).strip()
                        if val_str and val_str.lower() != 'nan':
                            try:
                                val_str = val_str.replace(',', '.').replace('R$', '').replace(' ', '')
                                defaults['valor_palete'] = float(val_str)
                            except ValueError:
                                pass

                        # Limpa campos que não devem ser preenchidos
                        defaults['material'] = ''
                        defaults['texto_breve_material'] = ''
                        defaults['tipo_pallet'] = ''

                        Produto.objects.update_or_create(codigo=codigo, defaults=defaults)

                    abas_importadas += 1

                # ---- PROCESSAMENTO DOS ENDEREÇOS ----
                enderecos_ignorados = set()
                for codigo_original in enderecos_encontrados:
                    if len(codigo_original) == 5:
                        codigo_parse = '0' + codigo_original
                    elif len(codigo_original) == 6:
                        codigo_parse = codigo_original
                    else:
                        enderecos_ignorados.add(codigo_original)
                        continue

                    rua_codigo_str = codigo_parse[:2]
                    predio_str     = codigo_parse[2]
                    andar_str      = codigo_parse[3]
                    posicao_str    = codigo_parse[4:]

                    rua, _ = Rua.objects.get_or_create(codigo=rua_codigo_str)
                    r_num   = int(rua_codigo_str) if rua_codigo_str.isdigit() else None
                    p_num   = int(predio_str)     if predio_str.isdigit() else None
                    a_num   = int(andar_str)      if andar_str.isdigit() else 0
                    pos_num = int(posicao_str)    if posicao_str.isdigit() else None

                    Endereco.objects.update_or_create(
                        codigo=codigo_original,
                        defaults={
                            'rua': rua,
                            'rua_num': r_num,
                            'predio_num': p_num,
                            'andar_num': a_num,
                            'posicao_num': pos_num,
                        },
                    )

                if enderecos_ignorados:
                    exemplos = list(enderecos_ignorados)[:3]
                    erros.append(
                        f"⚠️ Aviso: {len(enderecos_ignorados)} endereço(s) ignorado(s) por formato inválido "
                        f"(Exemplos: {', '.join(exemplos)}). O sistema espera 5 ou 6 caracteres."
                    )

                if abas_importadas > 0:
                    arquivos_sucesso += 1
                else:
                    erros.append(f"ℹ️ Nenhuma aba de produtos encontrada em {nome_arquivo}.")

            except Exception as e:
                erro_msg = f'Erro no arquivo {nome_arquivo}: {str(e)}'
                print(f"\n!!! ERRO FATAL: {erro_msg}")
                erros.append(erro_msg)

        if arquivos_sucesso > 0:
            context['msg'] = f'{arquivos_sucesso} planilha(s) processada(s) com sucesso! '
        if erros:
            context['msg'] += " | ".join(erros)

    return render(request, 'core/importar.html', context)


# ============================================================
# EXPORTAÇÃO COMPLETA
# ============================================================

@user_passes_test(is_gestor, login_url='/admin/login/')
def exportar_contagens(request):
    contagens = (
        Contagem.objects
        .filter(foi_descartada=False)
        .select_related('operador', 'endereco', 'endereco__rua', 'atualizado_por')
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
            'Recontagem Solicitada': 'Sim' if c.e_recontagem else 'Não',
            'Recontado Por': c.operador.username if c.e_recontagem else '-',
            'Observação': c.observacao,
            'Editado': 'Sim' if c.atualizado_por else 'Não',
            'Editado Por': c.atualizado_por.username if c.atualizado_por else '-',
            'Data e Hora': timezone.localtime(c.data_hora).strftime('%d/%m/%Y %H:%M:%S'),
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
            .select_related('operador', 'endereco', 'endereco__rua', 'atualizado_por')
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
                'Recontagem Solicitada': 'Sim' if c.e_recontagem else 'Não',
                'Recontado Por': c.operador.username if c.e_recontagem else '-',
                'Observação': c.observacao,
                'Editado': 'Sim' if c.atualizado_por else 'Não',
                'Editado Por': c.atualizado_por.username if c.atualizado_por else '-',
                'Data e Hora': timezone.localtime(c.data_hora).strftime('%d/%m/%Y %H:%M:%S'),
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
# PAINEL DE GESTÃO 
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

        data_filtrada = self.request.GET.get('data_filtro', '').strip()
        if data_filtrada:
            qs = qs.filter(data_hora__date=data_filtrada)

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
        context['data_filtrada'] = self.request.GET.get('data_filtro', '')

        ruas_qs = Rua.objects.all()
        ruas_list = sorted(
            ruas_qs,
            key=lambda r: (r.codigo.isdigit(), int(r.codigo) if r.codigo.isdigit() else 0, r.codigo)
        )
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
# RECONTAGEM
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def criar_missoes(request):
    ruas = sorted(
        Rua.objects.all(),
        key=lambda r: (r.codigo.isdigit(), int(r.codigo) if r.codigo.isdigit() else 0, r.codigo)
    )
    contagens = (
        Contagem.objects
        .filter(foi_descartada=False)
        .select_related('endereco', 'operador')
        .order_by('-data_hora')[:1000]
    )

    if request.method == 'POST':
        if 'contagem_id' in request.POST:
            contagem_id = request.POST.get('contagem_id')
            escopo = request.POST.get('escopo', 'unico')

            if not contagem_id:
                messages.error(request, "Selecione um registro base.")
                return redirect('criar_missoes')

            try:
                contagem_base = Contagem.objects.select_related('endereco', 'operador').get(pk=contagem_id)
            except Contagem.DoesNotExist:
                messages.error(request, "Registro base não encontrado.")
                return redirect('criar_missoes')

            try:
                produto = Produto.objects.get(codigo=contagem_base.codigo_produto)
            except Produto.DoesNotExist:
                messages.error(request, f"Produto '{contagem_base.codigo_produto}' não encontrado.")
                return redirect('criar_missoes')

            if escopo == 'todos':
                enderecos_ids = Contagem.objects.filter(
                    codigo_produto=produto.codigo,
                    foi_descartada=False
                ).values_list('endereco_id', flat=True).distinct()
                enderecos_alvo = list(Endereco.objects.filter(id__in=enderecos_ids))
            else:
                enderecos_alvo = [contagem_base.endereco]

            if not enderecos_alvo:
                messages.warning(request, f"Nenhum endereço encontrado para o produto {produto.codigo}.")
                return redirect('criar_missoes')

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

            if tarefas_criadas:
                messages.success(request, f"{tarefas_criadas} missões criadas para o produto {produto.codigo}.")
            else:
                messages.info(request, f"As missões para o produto {produto.codigo} já estão ativas.")
            return redirect('criar_missoes')

        if 'rua_codigo' in request.POST:
            rua_codigo = request.POST.get('rua_codigo', '').strip()
            end_inicio = request.POST.get('endereco_inicio', '').strip()
            end_fim = request.POST.get('endereco_fim', '').strip()

            if not rua_codigo:
                messages.error(request, 'Informe o código da rua.')
                return redirect('criar_missoes')

            contagens_qs = Contagem.objects.filter(
                foi_descartada=False,
                endereco__rua__codigo=rua_codigo
            )
            if end_inicio and end_fim:
                contagens_qs = contagens_qs.filter(endereco__codigo__range=[end_inicio, end_fim])
            elif end_inicio:
                contagens_qs = contagens_qs.filter(endereco__codigo__gte=end_inicio)
            elif end_fim:
                contagens_qs = contagens_qs.filter(endereco__codigo__lte=end_fim)

            pares = contagens_qs.values('endereco_id', 'codigo_produto').distinct()
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
                        observacao=f'Criada em lote via painel (Rua {rua_codigo})'
                    )
                    criadas += 1
            if criadas:
                messages.success(request, f'{criadas} missões de recontagem criadas para a rua {rua_codigo}.')
            else:
                messages.info(request, 'Nenhuma missão nova foi criada.')
            return redirect('criar_missoes')

    return render(request, 'core/criar_missoes.html', {
        'ruas': ruas,
        'contagens': contagens,
    })


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


# ============================================================
# AVARIA
# ============================================================

class AvariaViewSet(viewsets.ModelViewSet):
    queryset = Avaria.objects.all()
    serializer_class = AvariaSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(operador=self.request.user)


@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def conversor_avaria_web(request):
    produtos = Produto.objects.all().order_by('codigo')
    return render(request, 'core/conversor_avaria.html', {'produtos': produtos})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def conversao_avaria(request):
    codigo = request.query_params.get('codigo')
    quantidade = request.query_params.get('quantidade')
    tipo_unidade = request.query_params.get('tipo_unidade')

    try:
        produto = Produto.objects.get(codigo=codigo)
    except Produto.DoesNotExist:
        return Response({'erro': 'Produto não encontrado'}, status=404)

    try:
        qtd = float(quantidade)
    except (TypeError, ValueError):
        return Response({'erro': 'Quantidade inválida'}, status=400)

    packs_por_pallet = produto.packs_por_pallet
    unidades_por_pack = produto.unidades_por_pack

    resultado = {
        'produto': produto.codigo,
        'descricao': produto.descricao,
        'quantidade_original': qtd,
        'tipo_original': tipo_unidade,
    }

    if tipo_unidade == 'pallet':
        if packs_por_pallet and unidades_por_pack:
            total_unidades = qtd * packs_por_pallet * unidades_por_pack
        elif unidades_por_pack:
            return Response({'erro': 'Faltam dados de conversão (packs por pallet não definido)'}, 400)
        else:
            return Response({'erro': 'Produto sem dados de conversão'}, 400)
        resultado['total_unidades'] = total_unidades
        resultado['total_packs'] = qtd * packs_por_pallet
        resultado['total_pallets'] = qtd
    elif tipo_unidade == 'pack':
        if unidades_por_pack:
            total_unidades = qtd * unidades_por_pack
        else:
            return Response({'erro': 'Produto sem unidades por pack'}, 400)
        resultado['total_unidades'] = total_unidades
        if packs_por_pallet:
            resultado['total_pallets'] = qtd / packs_por_pallet
        resultado['total_packs'] = qtd
    elif tipo_unidade == 'unidade':
        resultado['total_unidades'] = qtd
        if unidades_por_pack:
            resultado['total_packs'] = qtd / unidades_por_pack
        if packs_por_pallet and unidades_por_pack:
            resultado['total_pallets'] = qtd / (packs_por_pallet * unidades_por_pack)
    else:
        return Response({'erro': 'Tipo de unidade inválido'}, 400)

    return Response(resultado)


# ============================================================
# AVISO DE SESSÃO CONCORRENTE
# ============================================================

def aviso_sessao_concorrente(request):
    return render(request, 'core/aviso_concorrente.html')