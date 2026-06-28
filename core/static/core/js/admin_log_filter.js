document.addEventListener('DOMContentLoaded', function() {
    // Aguarda o DOM carregar completamente
    setTimeout(function() {
        // Busca o link cujo texto contenha "Escolher data"
        const link = Array.from(document.querySelectorAll('a')).find(a => a.textContent.includes('Escolher data'));
        if (!link) return;

        // Cria o campo de data
        const input = document.createElement('input');
        input.type = 'date';
        input.style.width = '100%';
        input.style.padding = '4px';
        input.style.boxSizing = 'border-box';

        // Se já houver uma data na URL, preenche o campo
        const urlParams = new URLSearchParams(window.location.search);
        const currentDate = urlParams.get('date');
        if (currentDate) input.value = currentDate;

        // Substitui o link pelo input
        link.parentNode.replaceChild(input, link);

        // Ao selecionar uma data, redireciona
        input.addEventListener('change', function() {
            const url = new URL(window.location);
            if (this.value) {
                url.searchParams.set('date', this.value);
            } else {
                url.searchParams.delete('date');
            }
            window.location = url.toString();
        });
    }, 200);
});