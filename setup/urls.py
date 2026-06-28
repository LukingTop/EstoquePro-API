from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.templatetags.static import static
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
import os
import socket
from django.conf import settings
from django.contrib.auth import views as auth_views


urlpatterns = [
    
    path('', RedirectView.as_view(url='admin/', permanent=False)),
    path('admin/', admin.site.urls),
    
    path('logout/', auth_views.LogoutView.as_view(next_page='/admin/login/'), name='logout'),

    
    path('api/v1/', include('core.urls')),
    path('api/v1/token/', TokenObtainPairView.as_view(), name='token_obtain_pair_v1'),
    path('api/v1/token/refresh/', TokenRefreshView.as_view(), name='token_refresh_v1'),

    
    path('api/', include('core.urls')),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair_legacy'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh_legacy'),

   
    path('favicon.ico', RedirectView.as_view(url=static('core/favicon.ico'))),
]

def obter_ip_local():
    """Descobre o IP da máquina na rede local de forma dinâmica."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if os.environ.get('RUN_MAIN') == 'true' or not settings.DEBUG:
    
    
    try:
        from core.tasks import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"Aviso: Não foi possível iniciar o agendador. Erro: {e}")
    
    
    ip_rede = obter_ip_local()
    
    print("\n=======================================================")
    print("🚀 ESTOQUEPRO INICIADO!")
    print(f"👉 Painel no PC:    http://127.0.0.1:8000/api/painel/")
    print(f"👉 Link para o App: http://{ip_rede}:8000/api/painel/")
    print("=======================================================\n")