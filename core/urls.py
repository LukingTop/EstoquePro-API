from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.views.generic import RedirectView
from .views import ContagemListView, ContagemUpdateView, deletar_contagem
from . import views

router = DefaultRouter()

router.register(
    r'contagens',
    views.ContagemViewSet,
    basename='contagem'
)

router.register(
    r'produtos',
    views.ProdutoViewSet,
    basename='produto'
)

router.register(
    r'ruas',
    views.RuaViewSet,
    basename='rua'
)

router.register(
    r'enderecos',
    views.EnderecoViewSet,
    basename='endereco'
)

router.register(
    r'tarefas-recontagem',
    views.TarefaRecontagemViewSet,
    basename='tarefas-recontagem'
)

router.register(r'avarias', views.AvariaViewSet, basename='avaria')

router.register(r'sessoes', views.ContagemSessaoViewSet, basename='sessoes')


urlpatterns = [
    # 1. Redireciona quem acessar a raiz exata (/) para o painel de gestão
    path(
        '', 
        RedirectView.as_view(pattern_name='painel_gestao', permanent=False), 
        name='redirecionar_raiz'
    ),

    # 2. Mantém o funcionamento do aplicativo no celular (rotas da API)
    path(
        '',
        include(router.urls)
    ),

    path(
        'painel/', 
        views.painel_gestao, 
        name='painel_gestao'
    ),


    path(
        'importar-produtos/',
        views.importar_produtos,
        name='importar_produtos'
    ),

    path(
        'exportar/',
        views.exportar_contagens,
        name='exportar_contagens'
    ),
    
    path(
        'exportar-periodo/',
        views.selecionar_periodo_exportacao,
        name='selecionar_periodo_exportacao'
    ),
    
    path(
        'gestao/',
        ContagemListView.as_view(),
        name='lista_contagens'
    ),
    
    path(
        'gestao/<int:pk>/editar/',
        ContagemUpdateView.as_view(),
        name='editar_contagem'
    ),
    
    path(
        'gestao/<int:pk>/deletar/',
        deletar_contagem,
        name='deletar_contagem'
    ),
    
    path('config/versao-minima/', views.versao_minima_app, name='versao_minima_app'),
    
    path('ranking-diario/', views.ranking_diario, name='ranking_diario'),
    
    path('operador/atualizar-token/', views.atualizar_push_token, name='atualizar_push_token'),
    
    path('criar-missoes/', views.criar_missoes, name='criar_missoes'),
    
    path('contagens-stage/', views.registrar_stage, name='registrar_stage'),

    path('api/sync/', views.sincronizar_contagens_offline, name='sincronizar_offline'),

    path('conflitos/', views.resolucao_conflitos, name='resolucao_conflitos'),

    path('conflitos/resolver/<int:contagem_id>/', views.resolver_conflito, name='resolver_conflito'),
    
    path('operador/produtividade-diaria/', views.produtividade_diaria, name='produtividade_diaria'),
    
    # API de conversão (usada pelo JavaScript do conversor)
    path('conversao-avaria/', views.conversao_avaria, name='conversao_avaria'),
    
    path('criar-sessao/', views.criar_sessao, name='criar_sessao'),

    path('validar-sessao/<int:sessao_id>/', views.validar_sessao, name='validar_sessao'),
    
    path('comparar-sessoes/', views.comparar_sessoes, name='comparar_sessoes'),
    
    path('gestao/ciclo/<int:sessao_id>/', views.detalhes_ciclo, name='detalhes_ciclo'),
    
    path('gestao/ciclo/<int:sessao_id>/exportar/', views.exportar_ciclo, name='exportar_ciclo'),

    # Página HTML do conversor (acessada pelo painel)
    path('conversor-avaria/', views.conversor_avaria_web, name='conversor_avaria_web'),
    
    path('sessao-concorrente/', views.aviso_sessao_concorrente, name='aviso_concorrente'),

    path(
        'dashboard/',
        views.dashboard,
        name='dashboard'
    ),
]