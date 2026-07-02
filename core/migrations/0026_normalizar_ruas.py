from django.db import migrations

def normalizar_ruas(apps, schema_editor):
    Rua = apps.get_model('core', 'Rua')
    Endereco = apps.get_model('core', 'Endereco')
    ContagemSessao = apps.get_model('core', 'ContagemSessao')
    PerfilOperador = apps.get_model('core', 'PerfilOperador')

    # Lista todas as ruas cujo código é numérico e começa com zero
    ruas_zero = Rua.objects.filter(codigo__regex=r'^0\d+$')

    for rua_antiga in ruas_zero:
        # Determina o código normalizado (ex: '02' -> '2')
        codigo_novo = str(int(rua_antiga.codigo))

        # Cria (ou obtém) a rua com o código normalizado
        rua_nova, created = Rua.objects.get_or_create(codigo=codigo_novo)

        # Migra todos os endereços que apontam para a rua antiga
        Endereco.objects.filter(rua=rua_antiga).update(rua=rua_nova)

        # Migra a relação ManyToMany das sessões de contagem
        for sessao in ContagemSessao.objects.filter(ruas=rua_antiga):
            sessao.ruas.remove(rua_antiga)
            sessao.ruas.add(rua_nova)

        # Migra a relação ManyToMany dos perfis de operador
        for perfil in PerfilOperador.objects.filter(ruas_permitidas=rua_antiga):
            perfil.ruas_permitidas.remove(rua_antiga)
            perfil.ruas_permitidas.add(rua_nova)

        # Agora é seguro deletar a rua antiga
        rua_antiga.delete()

class Migration(migrations.Migration):

    dependencies = [
       ('core', '0025_contagemsessao_contagem_sessao_and_more'),
    ]

    operations = [
        migrations.RunPython(normalizar_ruas),
    ]