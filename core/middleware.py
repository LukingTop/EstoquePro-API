from django.contrib.auth import logout
from django.shortcuts import redirect

class SingleSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and hasattr(request.user, 'perfil'):
            stored_key = request.user.perfil.current_session_key
            if stored_key and stored_key != request.session.session_key:
                logout(request)
                return redirect('aviso_concorrente')   
        return self.get_response(request)