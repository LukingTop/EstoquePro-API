# 📦 EstoquePro - Backend (API & Painel Web)

Este é o repositório do backend do sistema **EstoquePro**, responsável por gerenciar a inteligência de dados, autenticação de usuários e fornecer um painel administrativo completo para os gestores de estoque. A API RESTful foi construída para se comunicar perfeitamente com o [Aplicativo Mobile do EstoquePro](https://github.com/LukingTop/EstoquePro-APP).

# 🚀 Tecnologias Utilizadas

* **Python & Django:** Framework principal.
* **Django Rest Framework (DRF):** Construção da API para o aplicativo.
* **PostgreSQL:** Banco de dados relacional.
* **Docker & Docker Compose:** Conteinerização para padronização de ambiente.
* **SimpleJWT:** Autenticação baseada em tokens (Access/Refresh).
* **Jazzmin:** Interface administrativa customizada e responsiva.
* **Sentry:** Monitoramento de erros e performance em tempo real.
* **WhiteNoise:** Gerenciamento de arquivos estáticos em produção.

# ⚙️ Funcionalidades

* **Autenticação Segura:** Login via JWT para os operadores do aplicativo.
* **Painel de Gestão:** Interface web administrativa para criação de usuários, missões e acompanhamento do progresso das contagens.
* **Filtros e Relatórios:** Views dedicadas para cálculo de ranking de operadores e métricas diárias.
* **Segurança de Produção:** Variáveis de ambiente configuradas, CORS protegido e tratamento de falhas em chamadas de API.

# 🛠️ Como rodar o projeto localmente (com Docker)

Pré-requisito: Tenha o **Docker** e o **Docker Desktop** instalados na sua máquina. Não é necessário instalar Python ou PostgreSQL nativamente.

**1. Clone este repositório:**

```bash

# Configure as variáveis de ambiente:

cp .env.example .env

# Abra o arquivo .env e preencha as variáveis de ambiente necessárias.

#Suba os containers (Banco de Dados + API):

docker compose up --build

#Em um novo terminal, rode as migrações do banco de dados:

docker compose exec web python manage.py migrate

# Crie o seu usuário administrador:

docker compose exec web python manage.py createsuperuser

