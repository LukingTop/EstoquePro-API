from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import IntegrityError
from django.db import models
from django.utils import timezone
from django.db.models import F

from core.models import (
    Contagem,
    Produto,
    Rua,
    Endereco,
    TarefaRecontagem,
    Avaria,
    ContagemSessao,
)
from core.serializers import (
    ContagemSerializer,
    ProdutoSerializer,
    RuaSerializer,
    EnderecoSerializer,
    TarefaRecontagemSerializer,
    AvariaSerializer,
    ContagemSessaoSerializer,
)
from core.views.utils import criar_tarefa_recontagem
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication


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

        # Registrar início da sessão
        sessao_id = self.request.data.get('sessao')
        if sessao_id:
            try:
                sessao = ContagemSessao.objects.get(pk=sessao_id)
                if not sessao.inicio:
                    sessao.inicio = timezone.now()
                    sessao.save()
            except ContagemSessao.DoesNotExist:
                pass

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


class AvariaViewSet(viewsets.ModelViewSet):
    queryset = Avaria.objects.all()
    serializer_class = AvariaSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(operador=self.request.user)


class ContagemSessaoViewSet(viewsets.ModelViewSet):
    queryset = ContagemSessao.objects.all()
    serializer_class = ContagemSessaoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ContagemSessao.objects.all()
        if not self.request.user.is_staff:
            qs = qs.filter(ativo=True)
        return qs

    @action(detail=True, methods=['patch'])
    def finalizar(self, request, pk=None):
        sessao = self.get_object()
        if not sessao.fim:
            sessao.fim = timezone.now()
            sessao.ativo = False
            sessao.save()
        return Response({'status': 'finalizada'})

    @action(detail=False, methods=['get'])
    def comparar(self, request):
        """Compara as contagens de uma sessão origem (1ª, 2ª, 3ª)"""
        sessao_id = request.query_params.get('sessao_id')
        if not sessao_id:
            return Response({'erro': 'sessao_id é obrigatório'}, status=400)

        base = ContagemSessao.objects.get(pk=sessao_id)
        sessoes = ContagemSessao.objects.filter(
            models.Q(pk=base.pk) | models.Q(sessao_origem=base)
        ).order_by('tipo')

        comparativo = {}
        for sessao in sessoes:
            contagens = Contagem.objects.filter(sessao=sessao, foi_descartada=False)
            for c in contagens:
                chave = f"{c.endereco.codigo}_{c.codigo_produto}"
                if chave not in comparativo:
                    comparativo[chave] = {
                        'endereco': c.endereco.codigo,
                        'codigo_produto': c.codigo_produto,
                        'descricao_produto': c.descricao_produto,
                        'contagens': {}
                    }
                comparativo[chave]['contagens'][sessao.titulo] = c.pallets

        return Response(list(comparativo.values()))

    @action(detail=True, methods=['patch'])
    def validar(self, request, pk=None):
        """Admin escolhe qual sessão é a correta"""
        sessao = self.get_object()
        if sessao.sessao_origem:
            sessao.sessao_origem.sessao_validada = sessao
            sessao.sessao_origem.save()
        else:
            sessao.sessao_validada = sessao
            sessao.save()
        return Response({'status': 'validada'})