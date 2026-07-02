from core.views.utils import (
    is_gestor,
    is_lider_or_gestor,
    LiderOrGestorMixin,
    criar_tarefa_recontagem,
)

from core.views.viewsets import (
    ContagemViewSet,
    ProdutoViewSet,
    RuaViewSet,
    EnderecoViewSet,
    TarefaRecontagemViewSet,
    AvariaViewSet,
    ContagemSessaoViewSet,
)

from core.views.importacao_exportacao import (
    importar_produtos,
    exportar_contagens,
    selecionar_periodo_exportacao,
)

from core.views.painel import (
    dashboard,
    painel_gestao,
    ContagemListView,
    ContagemUpdateView,
    deletar_contagem,
    sincronizar_contagens_offline,
    resolucao_conflitos,
    resolver_conflito,
    registrar_stage,
    criar_missoes,
    ranking_diario,
    produtividade_diaria,
    atualizar_push_token,
    versao_minima_app,
    conversor_avaria_web,
    conversao_avaria,
    criar_sessao,
    detalhes_ciclo, 
    exportar_ciclo,           
    comparar_sessoes,      
    validar_sessao,         
)

from core.views.auxiliares import (
    aviso_sessao_concorrente,
)