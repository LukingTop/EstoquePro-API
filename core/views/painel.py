from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, UpdateView
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from django.db import models
from django.db.models import Q, Sum, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
import requests
from django.http import HttpResponse
import pandas as pd
from django.conf import settings
from django.db import IntegrityError

from core.models import (
    Contagem,
    Produto,
    Rua,
    Endereco,
    TarefaRecontagem,
    ConfiguracaoSistema,
    ContagemSessao,
    Avaria,                    
)
from core.forms import ContagemEditForm
from core.views.utils import is_lider_or_gestor, LiderOrGestorMixin, criar_tarefa_recontagem


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


# ============================================================
# GESTÃO DE CONTAGENS
# ============================================================

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

        
        context['avarias'] = Avaria.objects.select_related('operador', 'produto').order_by('-data_hora')

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
@permission_classes([IsAuthenticated])
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
    return Response(resultados, status=200)


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
@permission_classes([IsAuthenticated])
def registrar_stage(request):
    dados = request.data
    local = (dados.get('local') or 'STAGE').strip()
    produto_codigo = dados.get('produto')
    quantidade = dados.get('quantidade')
    observacao_original = (dados.get('observacao') or '').strip()
    try:
        produto = Produto.objects.get(codigo=produto_codigo)
    except Produto.DoesNotExist:
        return Response({'erro': 'Produto não encontrado no sistema.'}, status=404)
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
        return Response({'sucesso': 'Registro de Stage salvo com sucesso.'}, status=201)
    except IntegrityError:
        return Response(
            {"error": "Você já registrou este produto no stage hoje."},
            status=400,
        )
    except Exception as e:
        return Response({'erro': f'Erro ao salvar contagem: {str(e)}'}, status=500)


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
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
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
@permission_classes([IsAuthenticated])
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
# CONVERSOR DE AVARIA
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def conversor_avaria_web(request):
    produtos = Produto.objects.all().order_by('codigo')
    return render(request, 'core/conversor_avaria.html', {'produtos': produtos})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
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
# CRIAÇÃO DE SESSÃO DE CONTAGEM
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def criar_sessao(request):
    ruas = sorted(
        Rua.objects.exclude(codigo__regex=r'^0\d+'), 
        key=lambda r: (r.codigo.isdigit(), int(r.codigo) if r.codigo.isdigit() else 0, r.codigo)
    )
    sessoes_origem = ContagemSessao.objects.filter(
        tipo__in=['PRIMEIRA', 'SEGUNDA']
    ).order_by('-criado_em')

    
    sessoes_ativas = ContagemSessao.objects.filter(ativo=True).annotate(
        total_enderecos=Count('ruas__enderecos', distinct=True),
        total_contagens=Count('contagem', distinct=True),
    ).order_by('-criado_em')

    if request.method == 'POST':
        titulo = request.POST.get('titulo', '').strip()
        ruas_ids = request.POST.getlist('ruas')
        tipo = request.POST.get('tipo')
        contagem_informada = request.POST.get('contagem_informada') == '1'
        sessao_origem_id = request.POST.get('sessao_origem')

        if not titulo:
            messages.error(request, 'Informe um título para a sessão.')
            return redirect('criar_sessao')
        if not ruas_ids:
            messages.error(request, 'Selecione pelo menos uma rua.')
            return redirect('criar_sessao')

        sessao = ContagemSessao.objects.create(
            titulo=titulo,
            criado_por=request.user,
            tipo=tipo,
            contagem_informada=contagem_informada,
            sessao_origem_id=sessao_origem_id or None,
        )
        sessao.ruas.set(ruas_ids)
        messages.success(request, f'Ciclo "{titulo}" criado com sucesso!')
        return redirect('detalhes_ciclo', sessao_id=sessao.id)

    context = {
        'ruas': ruas,
        'sessoes_origem': sessoes_origem,
        'sessoes_ativas': sessoes_ativas,
        'form_data': {
            'titulo': '',
            'ruas': [],
            'tipo': 'PRIMEIRA',
            'contagem_informada': False,
            'sessao_origem': '',
        }
    }
    return render(request, 'core/criar_sessao.html', context)


# ============================================================
# DETALHES DO CICLO (ACOMPANHAMENTO)
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def detalhes_ciclo(request, sessao_id):
    sessao = get_object_or_404(ContagemSessao, id=sessao_id)
    ruas_ids = sessao.ruas.values_list('id', flat=True)
    total_enderecos = Endereco.objects.filter(rua_id__in=ruas_ids, ativo=True).count()
    contagens = Contagem.objects.filter(sessao=sessao, foi_descartada=False)
    enderecos_contados = contagens.values('endereco').distinct().count()
    percentual = int((enderecos_contados / total_enderecos) * 100) if total_enderecos else 0

    context = {
        'sessao': sessao,
        'total_enderecos': total_enderecos,
        'enderecos_contados': enderecos_contados,
        'percentual': percentual,
        'ultimas_contagens': contagens.select_related('endereco', 'operador').order_by('-data_hora')[:10],
    }
    return render(request, 'core/detalhes_ciclo.html', context)


# ============================================================
# COMPARAÇÃO DE SESSÕES
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def comparar_sessoes(request):
    sessoes_disponiveis = ContagemSessao.objects.filter(
        tipo='PRIMEIRA'
    ).order_by('-criado_em')

    context = {
        'sessoes_disponiveis': sessoes_disponiveis,
    }

    sessao_id = request.GET.get('sessao_id')
    if sessao_id:
        try:
            cookies = request.COOKIES
            csrf_token = request.META.get('CSRF_COOKIE', '')
            headers = {'X-CSRFToken': csrf_token, 'Referer': request.build_absolute_uri('/')}
            api_url = request.build_absolute_uri(f'/api/v1/sessoes/comparar/?sessao_id={sessao_id}')
            response = requests.get(api_url, cookies=cookies, headers=headers)
            response.raise_for_status()
            comparativo = response.json()
        except Exception as e:
            messages.error(request, f'Erro ao carregar comparação: {str(e)}')
            comparativo = []

        context['sessao_id'] = sessao_id
        context['comparativo'] = comparativo
        context['sessao_base'] = ContagemSessao.objects.get(pk=sessao_id)

        sessoes_filhas = ContagemSessao.objects.filter(
            models.Q(pk=sessao_id) | models.Q(sessao_origem_id=sessao_id)
        ).order_by('tipo')
        context['sessoes_filhas'] = sessoes_filhas

    return render(request, 'core/comparar_sessoes.html', context)


# ============================================================
# VALIDAÇÃO DE SESSÃO
# ============================================================

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def validar_sessao(request, sessao_id):
    if request.method == 'POST':
        try:
            sessao = ContagemSessao.objects.get(pk=sessao_id)
            if sessao.sessao_origem:
                sessao.sessao_origem.sessao_validada = sessao
                sessao.sessao_origem.save()
            else:
                sessao.sessao_validada = sessao
                sessao.save()
            messages.success(request, f'Sessão "{sessao.titulo}" validada como correta!')
        except ContagemSessao.DoesNotExist:
            messages.error(request, 'Sessão não encontrada.')
    return redirect('comparar_sessoes')

@user_passes_test(is_lider_or_gestor, login_url='/admin/login/')
def exportar_ciclo(request, sessao_id):
    sessao = get_object_or_404(ContagemSessao, id=sessao_id)
    contagens = (
        Contagem.objects
        .filter(sessao=sessao, foi_descartada=False)
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
            'Observação': c.observacao or '',
            'Data e Hora': timezone.localtime(c.data_hora).strftime('%d/%m/%Y %H:%M:%S'),
        })
    df = pd.DataFrame(dados)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f"Contagens_Ciclo_{sessao.titulo.replace(' ', '_')}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Contagens do Ciclo')
    return response