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
* **Criação de Ciclos de Contagem:** Agende e configure contagens sequenciais por rua ou setor.
* **Exportação de Relatórios:** Gere planilhas Excel completas com contagens, avarias e registros de stage.
* **Acompanhamento em Tempo Real:** Visualize o progresso dos ciclos ativos e o histórico de contagens.
* **Filtros e Relatórios:** Views dedicadas para cálculo de ranking de operadores e métricas diárias.
* **Segurança de Produção:** Variáveis de ambiente configuradas, CORS protegido e tratamento de falhas em chamadas de API.

# 📋 Pré‑requisitos

* **Docker** e **Docker Compose** instalados ([Download Docker](https://docs.docker.com/get-docker/)).
* (Opcional) Python 3.13 e PostgreSQL se desejar rodar sem containers.

# 🔧 Configuração Inicial

1. **Clone o repositório:**
   ```bash
   git clone https://github.com/LukingTop/EstoquePro-Backend.git
   cd EstoquePro-Backend

 2. **Configure as variáveis de ambiente:**

bash
cp .env.example .env
Edite o arquivo .env com suas credenciais:

ini
SECRET_KEY='sua-chave-secreta'
DEBUG=True
DB_HOST=db
DB_NAME=estoquepro
DB_USER=postgres
DB_PASSWORD='sua-senha'
DB_PORT=5432
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,*

3. **Suba os containers (PostgreSQL + Django):**

bash
docker-compose up -d --build

4. **Execute as migrações do banco de dados:**

bash
docker-compose exec web python manage.py migrate

5. **Crie o superusuário (administrador):**

bash
docker-compose exec web python manage.py createsuperuser

6. **Acesse o painel administrativo:**

Abra http://localhost:8000/admin/ e faça login com o superusuário.

**🐳 Comandos Docker úteis**

Parar os containers: docker-compose down

Ver logs: docker-compose logs -f web

Acessar o shell do Django: docker-compose exec web python manage.py shell

📄 Licença
Este projeto é de uso interno da CargoPolo – Inventário Rotativo de Estoque. Todos os direitos reservados.