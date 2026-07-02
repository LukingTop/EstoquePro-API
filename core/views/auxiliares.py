from django.shortcuts import render


def aviso_sessao_concorrente(request):
    return render(request, 'core/aviso_concorrente.html')