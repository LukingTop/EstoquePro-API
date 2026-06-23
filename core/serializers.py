from rest_framework import serializers
from .models import (
    Contagem,
    Produto,
    Rua,
    Endereco,
    TarefaRecontagem   
)


class RuaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rua
        fields = '__all__'


class EnderecoSerializer(serializers.ModelSerializer):
    rua_codigo = serializers.CharField(source='rua.codigo', read_only=True)
    predio = serializers.IntegerField(source='predio_num', read_only=True)
    posicao = serializers.IntegerField(source='posicao_num', read_only=True)
    andar = serializers.IntegerField(source='andar_num', read_only=True)

    class Meta:
        model  = Endereco
        fields = [
            'id', 'rua', 'rua_codigo', 'codigo',
            'predio', 'posicao', 'andar',
            'rua_num', 'predio_num', 'andar_num', 'posicao_num',
        ]


class ProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Produto
        fields = '__all__'


class ContagemSerializer(serializers.ModelSerializer):
    operador = serializers.StringRelatedField(read_only=True)
    endereco = serializers.SlugRelatedField(
        slug_field='codigo',
        queryset=Endereco.objects.all()
    )
    endereco_codigo = serializers.CharField(
        source='endereco.codigo',
        read_only=True
    )
    rua_codigo = serializers.CharField(
        source='endereco.rua.codigo',
        read_only=True
    )

    class Meta:
        model = Contagem
        fields = '__all__'
        read_only_fields = (
            'operador',
            'data_hora',
            'atualizado_por',
            'historico_edicoes',
            'em_conflito',
        )


class TarefaRecontagemSerializer(serializers.ModelSerializer):
    endereco_str = serializers.CharField(source='endereco.codigo', read_only=True)
    produto_str = serializers.CharField(source='produto.codigo', read_only=True)
    descricao_str = serializers.CharField(source='produto.descricao', read_only=True)

    class Meta:
        model = TarefaRecontagem
        fields = '__all__'