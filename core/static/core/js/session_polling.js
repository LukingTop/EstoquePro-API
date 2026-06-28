// Verifica a cada 30 segundos se a sessão ainda é válida
setInterval(function() {
    fetch('/admin/', { credentials: 'include' })
        .then(response => {
            if (response.redirected && response.url.includes('/admin/login/')) {
                window.location.href = response.url;
            }
        })
        .catch(() => {});
}, 10000);