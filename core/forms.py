from django import forms
from .models import Contagem


_INPUT  = 'w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition'
_AREA   = _INPUT + ' resize-none'


class ContagemEditForm(forms.ModelForm):
    """
    Formulário de edição de Contagem restrito aos campos
    que o gestor pode alterar: código do produto, pallets e observação.
    O campo descricao_produto NÃO é editável aqui — fica como referência
    somente-leitura no template.
    """

    class Meta:
        model  = Contagem
        fields = ['codigo_produto', 'pallets', 'observacao']
        labels = {
            'codigo_produto': 'Código do Produto',
            'pallets':        'Quantidade de Pallets',
            'observacao':     'Observação',
        }
        widgets = {
            'codigo_produto': forms.TextInput(attrs={
                'class':       _INPUT,
                'placeholder': 'Ex: ABC123',
            }),
            'pallets': forms.NumberInput(attrs={
                'class':       _INPUT,
                'min':         '0',
                'placeholder': 'Ex: 40',
            }),
            'observacao': forms.Textarea(attrs={
                'class':       _AREA,
                'rows':        '4',
                'placeholder': 'Observações opcionais…',
            }),
        }


class RecontagemPorRuaIntervaloForm(forms.Form):
    rua_codigo = forms.CharField(
        label='Código da Rua',
        max_length=50,
        required=True,
        help_text='Exemplo: "21" para a rua 21.'
    )
    endereco_inicio = forms.CharField(
        label='Endereço Inicial',
        max_length=6,
        required=False,
        help_text='Opcional. Ex: "21001"'
    )
    endereco_fim = forms.CharField(
        label='Endereço Final',
        max_length=6,
        required=False,
        help_text='Opcional. Ex: "21010"'
    )