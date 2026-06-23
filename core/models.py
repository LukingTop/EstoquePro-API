import requests
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from simple_history.models import HistoricalRecords


class SoftDeleteManager(models.Manager):
    """Manager customizado para retornar apenas registros ativos por padrão"""
    def get_queryset(self):
        return super().get_queryset().filter(ativo=True)


# ==========================================
# MODELOS
# ==========================================

class ModeloPlanilha(models.Model):
    """Tabela padronizada para os modelos de planilha, evitando erros de digitação"""
    nome = models.CharField(max_length=100, unique=True, verbose_name="Nome do Modelo")

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Modelo de Planilha"
        verbose_name_plural = "Modelos de Planilha"
        ordering = ['nome']


class Rua(models.Model):
    codigo = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Código da Rua"
    )
    
    ordem = models.IntegerField(default=0, verbose_name="Ordem de Exibição")

    
    modelo_planilha = models.ForeignKey(
        ModeloPlanilha,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="Modelo da Planilha"
    )

    # Controle de Soft Delete
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    # Managers
    objects = SoftDeleteManager()
    all_objects = models.Manager()  #

    def delete(self, *args, **kwargs):
        """Sobrescreve a exclusão física para apenas desativar o registro"""
        self.ativo = False
        self.save()

    def save(self, *args, **kwargs):
        if self.codigo and self.codigo.isdigit():
            self.ordem = int(self.codigo)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.codigo

    class Meta:
        verbose_name = "Rua"
        verbose_name_plural = "Ruas"
        ordering = ['ordem']


class Endereco(models.Model):
    rua = models.ForeignKey(
        Rua,
        on_delete=models.CASCADE,
        related_name='enderecos',
        verbose_name="Rua"
    )

    codigo = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Endereço"
    )

    rua_num = models.IntegerField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Rua"
    )

    predio_num = models.IntegerField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Prédio"
    )

    andar_num = models.IntegerField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Andar"
    )

    posicao_num = models.IntegerField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Posição"
    )

    # Controle de Soft Delete
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    
    ultima_contagem_em = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Última contagem registrada"
    )
    contagem_realizada = models.BooleanField(
        default=False,
        verbose_name="Já foi contado?"
    )

    # Managers
    objects = SoftDeleteManager()
    all_objects = models.Manager()

    def delete(self, *args, **kwargs):
        self.ativo = False
        self.save()

    def __str__(self):
        return self.codigo

    class Meta:
        verbose_name = "Endereço"
        verbose_name_plural = "Endereços"
        ordering = ['rua_num', 'predio_num', 'andar_num', 'posicao_num']


class PerfilOperador(models.Model):
    class Cargo(models.TextChoices):
        OPERADOR = 'OPERADOR', 'Operador (Apenas App)'
        LIDER = 'LIDER', 'Líder de Rua (App + Painel Básico)'
        GESTOR = 'GESTOR', 'Gestor de Estoque (Acesso Total)'

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="perfil",
        verbose_name="Utilizador"
    )
    
    cargo = models.CharField(
        max_length=20,
        choices=Cargo.choices,
        default=Cargo.OPERADOR,
        verbose_name="Nível de Acesso"
    )

    ruas_permitidas = models.ManyToManyField(
        Rua,
        blank=True,
        verbose_name="Ruas Autorizadas"
    )

    
    push_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Push Token (Expo)"
    )

    def __str__(self):
        return f"{self.user.username} ({self.get_cargo_display()})"

    class Meta:
        verbose_name = "Perfil de Operador"
        verbose_name_plural = "Perfis de Operadores"


class Produto(models.Model):
    codigo = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Código do Produto"
    )

    descricao = models.CharField(
        max_length=255,
        verbose_name="Descrição"
    )

    palletizacao = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Paletização"
    )

    valor_palete = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="Valor Palete"
    )

    pac = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="PAC"
    )

    material = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Material"
    )

    texto_breve_material = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Texto Breve Material"
    )

    tipo_pallet = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Tipo de Pallet"
    )

    tipo = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Tipo"
    )

    # Controle de Soft Delete
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    # Managers
    objects = SoftDeleteManager()
    all_objects = models.Manager()

    
    history = HistoricalRecords()

    def delete(self, *args, **kwargs):
        self.ativo = False
        self.save()

    def __str__(self):
        return f"{self.codigo} - {self.descricao}"

    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"


class Contagem(models.Model):
    operador = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        verbose_name="Operador"
    )
    endereco = models.ForeignKey(
        Endereco,
        on_delete=models.PROTECT,
        related_name='contagens',
        verbose_name="Endereço"
    )
    codigo_produto = models.CharField(
        max_length=100,
        verbose_name="Código do Produto"
    )
    descricao_produto = models.CharField(
        max_length=255,
        verbose_name="Descrição"
    )
    pallets = models.IntegerField(
        verbose_name="Quantidade de Pallets"
    )
    numero_contagem = models.IntegerField(
        default=1,
        verbose_name="Número da Contagem",
        help_text="Ex: 1 para primeira contagem, 2 para recontagem."
    )
    observacao = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observação"
    )
    historico_edicoes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Histórico de Edições"
    )
    data_hora = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Data/Hora da Contagem"
    )
    uuid_aparelho = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="UUID do Aparelho",
        help_text="ID único do celular/coletor que fez a contagem"
    )
    id_local = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="ID Local (Idempotência)",
        help_text="Evita duplicatas se a internet cair durante a sincronização."
    )
    em_conflito = models.BooleanField(
        default=False,
        verbose_name="Em Conflito",
        help_text="Indica se dois operadores contaram o mesmo endereço offline"
    )
    foi_descartada = models.BooleanField(
        default=False,
        verbose_name="Foi Descartada?",
        help_text="Marcado como True se a contagem perdeu um conflito e foi arquivada pelo gestor."
    )
    atualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contagens_editadas',
        verbose_name="Última edição por"
    )
    tarefa_recontagem = models.ForeignKey(
        'TarefaRecontagem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contagens_recontagem',
        verbose_name='Tarefa de Recontagem'
    )
    e_recontagem = models.BooleanField(
        default=False,
        verbose_name='É Recontagem'
    )
 
    data_contagem = models.DateField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Data da contagem"
    )

   
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        
        if self.data_hora and not self.data_contagem:
            self.data_contagem = self.data_hora.date()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.data_hora.strftime('%d/%m/%Y %H:%M')} - {self.endereco.codigo}"

    class Meta:
        verbose_name = "Contagem"
        verbose_name_plural = "Contagens"
        ordering = ['-data_hora']
        constraints = [
            models.UniqueConstraint(
                fields=['operador', 'endereco', 'codigo_produto', 'data_contagem'],
                name='unico_operador_endereco_produto_por_dia'
            )
        ]
        indexes = [
            models.Index(fields=['data_contagem', 'endereco', 'codigo_produto']),
            models.Index(fields=['operador', 'data_contagem']),
            models.Index(fields=['-data_hora']),
        ]


class TarefaRecontagem(models.Model):

    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em Andamento'
        CONCLUIDO = 'CONCLUIDO', 'Concluído'

   
    class Criticidade(models.TextChoices):
        BAIXA = 'BAIXA', 'Baixa'
        MEDIA = 'MEDIA', 'Média'
        ALTA = 'ALTA', 'Alta'

    endereco = models.ForeignKey(
        Endereco,
        on_delete=models.CASCADE,
        related_name='tarefas_recontagem'
    )

    produto = models.ForeignKey(
        Produto,
        on_delete=models.CASCADE,
        related_name='tarefas_recontagem'
    )

    criado_em = models.DateTimeField(
        auto_now_add=True
    )

    concluido_em = models.DateTimeField(
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE
    )

    
    criticidade = models.CharField(
        max_length=10,
        choices=Criticidade.choices,
        default=Criticidade.BAIXA,
        verbose_name="Criticidade"
    )

    responsavel = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tarefas_recontagem'
    )

    observacao = models.TextField(
        blank=True,
        null=True
    )

    def __str__(self):
        return (
            f"{self.endereco.codigo} - "
            f"{self.produto.codigo} - "
            f"{self.status}"
        )

    class Meta:
        verbose_name = "Tarefa de Recontagem"
        verbose_name_plural = "Tarefas de Recontagem"
        ordering = ['status', '-criado_em']



@receiver(post_save, sender=User)
def salvar_perfil_operador(sender, instance, **kwargs):
    if hasattr(instance, 'perfil'):
        instance.perfil.save()


@receiver(post_save, sender=TarefaRecontagem)
def notificar_nova_missao(sender, instance, created, **kwargs):
    if created and instance.responsavel:
        try:
            perfil = instance.responsavel.perfil
            if perfil.push_token:
                payload = {
                    "to": perfil.push_token,
                    "sound": "default",
                    "title": "🎯 Nova Missão Disponível",
                    "body": f"Recontagem gerada no endereço {instance.endereco.codigo}.",
                    "data": {
                        "tarefa_id": instance.id,
                        "screen": "missoes"
                    }
                }
                requests.post(
                    "https://exp.host/--/api/v2/push/send", 
                    json=payload, 
                    timeout=5
                )
        except Exception as e:
            print(f"Falha ao processar notificação push: {e}")
            
            
class ConfiguracaoSistema(models.Model):
    """Configurações globais do sistema, apenas um registro."""
    versao_minima_app = models.CharField(
        max_length=20,
        default='1.0.0',
        verbose_name='Versão mínima do App'
    )

    def save(self, *args, **kwargs):
        
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'Configuração (v{self.versao_minima_app})'

    class Meta:
        verbose_name = 'Configuração do Sistema'
        verbose_name_plural = 'Configurações do Sistema'