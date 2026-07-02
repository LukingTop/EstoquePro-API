import pandas as pd
from io import StringIO
from django.shortcuts import render           
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Sum
from core.models import Contagem, Produto, Rua, Endereco, Avaria
from core.views.utils import is_gestor          
from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType


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
                    raw_bytes = arquivo.read()
                    codificacoes = ['utf-8', 'latin-1', 'iso-8859-1', 'windows-1252', 'cp1252', 'utf-16']
                    texto = None
                    for cod in codificacoes:
                        try:
                            texto = raw_bytes.decode(cod)
                            break
                        except UnicodeDecodeError:
                            continue
                    if texto is None:
                        raise Exception("Não foi possível decodificar o arquivo CSV com as codificações suportadas.")

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

                    if 'ENDERECO' in norm_map:
                        col_end = norm_map['ENDERECO']
                        enderecos = df[col_end].dropna().astype(str)
                        for endereco in enderecos:
                            endereco = endereco.strip()
                            if endereco.endswith('.0'):
                                endereco = endereco[:-2]
                            if endereco and endereco.lower() != 'nan':
                                enderecos_encontrados.add(endereco)

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

                        defaults['material'] = ''
                        defaults['texto_breve_material'] = ''
                        defaults['tipo_pallet'] = ''

                        Produto.objects.update_or_create(codigo=codigo, defaults=defaults)

                    abas_importadas += 1

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
                    # Normaliza o código da rua removendo zeros à esquerda (ex.: "02" -> "2")
                    if rua_codigo_str.isdigit():
                        rua_codigo_str = str(int(rua_codigo_str))

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
    # Contagens (
    contagens = (
        Contagem.objects
        .filter(foi_descartada=False)
        .exclude(endereco__codigo='STAGE')
        .select_related('operador', 'endereco', 'endereco__rua', 'atualizado_por')
        .order_by('-data_hora')
    )
    dados_contagens = []
    for c in contagens:
        dados_contagens.append({
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

    # Avarias
    avarias = (
        Avaria.objects
        .select_related('operador', 'produto')
        .order_by('-data_hora')
    )
    dados_avarias = []
    for a in avarias:
        dados_avarias.append({
            'ID': a.id,
            'Operador': a.operador.username,
            'Código Produto': a.codigo_produto,
            'Descrição': a.descricao_produto,
            'Quantidade': f"{a.quantidade} {a.get_tipo_unidade_display()}",
            'Observação': a.observacao or '',
            'Data e Hora': timezone.localtime(a.data_hora).strftime('%d/%m/%Y %H:%M:%S'),
        })

    # Stage 
    stage_contagens = (
        Contagem.objects
        .filter(endereco__codigo='STAGE', foi_descartada=False)
        .select_related('operador')
        .order_by('-data_hora')
    )
    dados_stage = []
    for s in stage_contagens:
        dados_stage.append({
            'ID': s.id,
            'Operador': s.operador.username,
            'Código Produto': s.codigo_produto,
            'Descrição': s.descricao_produto,
            'Pallets': s.pallets,
            'Observação': s.observacao or '',
            'Data e Hora': timezone.localtime(s.data_hora).strftime('%d/%m/%Y %H:%M:%S'),
        })

    df_contagens = pd.DataFrame(dados_contagens)
    df_avarias = pd.DataFrame(dados_avarias)
    df_stage = pd.DataFrame(dados_stage)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="Contagens_Avarias_Stage_Consolidadas.xlsx"'

    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df_contagens.to_excel(writer, index=False, sheet_name='Contagens')
        df_avarias.to_excel(writer, index=False, sheet_name='Avarias')
        df_stage.to_excel(writer, index=False, sheet_name='Stage')

    LogEntry.objects.create(
        action=LogEntry.Action.ACCESS,
        content_type=ContentType.objects.get_for_model(Contagem),
        object_repr="Exportação Completa (Contagens + Avarias + Stage)",
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

        # Contagens no período 
        contagens = (
            Contagem.objects
            .filter(data_hora__date__range=[data_inicio, data_fim], foi_descartada=False)
            .exclude(endereco__codigo='STAGE')
            .select_related('operador', 'endereco', 'endereco__rua', 'atualizado_por')
            .order_by('-data_hora')
        )
        dados_contagens = []
        for c in contagens:
            dados_contagens.append({
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

        # Avarias no período
        avarias = (
            Avaria.objects
            .filter(data_hora__date__range=[data_inicio, data_fim])
            .select_related('operador', 'produto')
            .order_by('-data_hora')
        )
        dados_avarias = []
        for a in avarias:
            dados_avarias.append({
                'ID': a.id,
                'Operador': a.operador.username,
                'Código Produto': a.codigo_produto,
                'Descrição': a.descricao_produto,
                'Quantidade': f"{a.quantidade} {a.get_tipo_unidade_display()}",
                'Observação': a.observacao or '',
                'Data e Hora': timezone.localtime(a.data_hora).strftime('%d/%m/%Y %H:%M:%S'),
            })

        # Stage no período
        stage_contagens = (
            Contagem.objects
            .filter(data_hora__date__range=[data_inicio, data_fim], endereco__codigo='STAGE', foi_descartada=False)
            .select_related('operador')
            .order_by('-data_hora')
        )
        dados_stage = []
        for s in stage_contagens:
            dados_stage.append({
                'ID': s.id,
                'Operador': s.operador.username,
                'Código Produto': s.codigo_produto,
                'Descrição': s.descricao_produto,
                'Pallets': s.pallets,
                'Observação': s.observacao or '',
                'Data e Hora': timezone.localtime(s.data_hora).strftime('%d/%m/%Y %H:%M:%S'),
            })

        df_contagens = pd.DataFrame(dados_contagens)
        df_avarias = pd.DataFrame(dados_avarias)
        df_stage = pd.DataFrame(dados_stage)

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="Contagens_Avarias_Stage_{data_inicio}_ate_{data_fim}.xlsx"'

        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            df_contagens.to_excel(writer, index=False, sheet_name='Contagens')
            df_avarias.to_excel(writer, index=False, sheet_name='Avarias')
            df_stage.to_excel(writer, index=False, sheet_name='Stage')

        LogEntry.objects.create(
            action=LogEntry.Action.ACCESS,
            content_type=ContentType.objects.get_for_model(Contagem),
            object_repr=f"Exportação Período ({data_inicio} a {data_fim}) - Contagens + Avarias + Stage",
            actor=request.user,
            changes={'action': 'exportar', 'tipo': 'periodo', 'inicio': data_inicio, 'fim': data_fim, 'formato': 'xlsx'},
        )

        return response

    return render(request, 'core/exportar_periodo.html')