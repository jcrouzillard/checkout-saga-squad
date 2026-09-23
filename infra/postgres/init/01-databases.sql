-- Cria um database por serviço (database-per-service), todos de
-- propriedade do usuário "checkout" (criado via POSTGRES_USER/POSTGRES_PASSWORD
-- no docker-compose.yml). Executado automaticamente pela imagem oficial do
-- Postgres a partir de /docker-entrypoint-initdb.d na primeira inicialização
-- do volume de dados.
CREATE DATABASE saga      OWNER checkout;
CREATE DATABASE orders    OWNER checkout;
CREATE DATABASE inventory OWNER checkout;
CREATE DATABASE payments  OWNER checkout;
CREATE DATABASE shipping  OWNER checkout;
