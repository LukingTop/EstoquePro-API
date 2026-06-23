# 📦 EstoquePro - Backend (API & Painel Web)

Este é o repositório do backend do sistema **EstoquePro**, responsável por gerenciar a inteligência de dados, autenticação de usuários e fornecer um painel administrativo completo para os gestores de estoque. A API RESTful foi construída para se comunicar perfeitamente com o [https://github.com/LukingTop/EstoquePro-APP]

# 🚀 Tecnologias Utilizadas

* **Python & Django:** Framework principal.
* **Django Rest Framework (DRF):** Construção da API para o aplicativo.
* **PostgreSQL:** Banco de dados relacional.
* **SimpleJWT:** Autenticação baseada em tokens (Access/Refresh).
* **Jazzmin:** Interface administrativa customizada e responsiva.
* **Sentry:** Monitoramento de erros e performance em tempo real.
* **WhiteNoise:** Gerenciamento de arquivos estáticos em produção.

# ⚙️ Funcionalidades

* **Autenticação Segura:** Login via JWT para os operadores do aplicativo.
* **Painel de Gestão:** Interface web administrativa para criação de usuários, missões e acompanhamento do progresso das contagens.
* **Filtros e Relatórios:** Views dedicadas para cálculo de ranking de operadores e métricas diárias.
* **Segurança de Produção:** Variáveis de ambiente configuradas, CORS protegido e tratamento de falhas em chamadas de API.

# 🛠️ Como rodar o projeto localmente

**1. Clone este repositório:**

```bash

git clone [https://github.com/LukingTop/EstoquePro-API]

cd estoquepro-api

python -m venv venv

# No Windows:

venv\Scripts\activate

# No Linux/Mac:

source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env

python manage.py migrate

python manage.py createsuperuser

python manage.py runserver
