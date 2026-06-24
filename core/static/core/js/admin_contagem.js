(function () {
    console.log('[admin_contagem] Script carregado.');

    function setup() {
        // ── 1. Bloquear campo Operador ─────────────────────────────────
        var operadorField = document.getElementById('id_operador');
        if (operadorField) {
            operadorField.disabled = true;
            operadorField.style.backgroundColor = '#f3f4f6';
            operadorField.style.color = '#6b7280';
            operadorField.style.pointerEvents = 'none';
            console.log('[admin_contagem] Campo Operador desabilitado.');
        }

        // ── 2. Tornar descrição readonly e preencher automaticamente ────
        var codigoField = document.getElementById('id_codigo_produto');
        var descricaoField = document.getElementById('id_descricao_produto');

        if (!codigoField || !descricaoField) {
            setTimeout(setup, 300);
            return;
        }

        // Torna a descrição apenas leitura
        descricaoField.readOnly = true;
        descricaoField.style.backgroundColor = '#f3f4f6';
        descricaoField.style.color = '#374151';
        descricaoField.style.cursor = 'not-allowed';
        console.log('[admin_contagem] Campo descrição agora é somente leitura.');

        function construirMapa() {
            var options = codigoField.querySelectorAll('option');
            var produtos = {};
            for (var i = 0; i < options.length; i++) {
                var texto = options[i].textContent || options[i].innerText || '';
                var partes = texto.split(' – ');
                if (partes.length > 1) {
                    produtos[options[i].value] = partes[1].trim();
                }
            }
            return produtos;
        }

        var ultimoValor = codigoField.value;

        setInterval(function () {
            var valorAtual = codigoField.value;
            if (valorAtual !== ultimoValor) {
                ultimoValor = valorAtual;
                var produtos = construirMapa();
                if (produtos[valorAtual]) {
                    descricaoField.value = produtos[valorAtual];
                    console.log('[admin_contagem] Descrição preenchida:', valorAtual);
                } else {
                    descricaoField.value = '';
                    console.log('[admin_contagem] Código sem descrição:', valorAtual);
                }
            }
        }, 500);

        
        var form = document.querySelector('form');
        if (form) {
            form.addEventListener('submit', function () {
                if (operadorField) {
                    operadorField.disabled = false;
                }
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setup);
    } else {
        setup();
    }
})();