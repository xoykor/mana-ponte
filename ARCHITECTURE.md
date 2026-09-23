# Arquitetura do ManaPonte

Este arquivo é a referência de alto nível para a arquitetura atual de produção.

## 1. Objetivo

O ManaPonte resolve descoberta e contato entre jogadores: encontrar quem possui ou procura uma impressão específica de Magic: The Gathering, filtrando por carta, edição, idioma, localidade, modalidade e outros atributos.

Pagamento, frete, escrow e processamento financeiro estão fora do MVP.

## 2. Topologia de produção

    Internet
       |
       v
    Cloudflare
       |
       +-- Static Assets
       |      |
       |      +-- public/index.html
       |      +-- public/anuncios.html
       |      +-- public/perfil.html
       |      +-- public/anuncio.html
       |      +-- CSS e JavaScript
       |
       +-- Worker
              |
              +-- /api/auth/*
              +-- /api/cards
              +-- /api/sets
              +-- /api/listings/*
              +-- /api/wants/*
              +-- /api/matches
              +-- /api/users/*
              |
              +-- binding DB -> Cloudflare D1
              |
              +-- fetch -> Scryfall API

Não existe VPS na rota de produção.

## 3. Princípios arquiteturais

1. Frontend e API de produção são same-origin no mesmo Worker.
2. D1 é a fonte persistente da aplicação.
3. Scryfall é fonte externa de metadados de cartas e URLs de imagem.
4. Nenhum byte de imagem é armazenado pelo ManaPonte.
5. cards.id é o identificador local usado por anúncios e desejos.
6. scryfall_id identifica uma impressão.
7. oracle_id agrupa reimpressões da mesma carta conceitual.
8. autoria de anúncios e desejos vem sempre da sessão.
9. token bruto de sessão nunca é persistido.
10. operações mutáveis autenticadas exigem CSRF.
11. o backend Python/SQLite não é produção; é legado/local.
12. mudanças estruturais no D1 devem entrar por migrations versionadas.

## 4. Runtime Cloudflare

Diretório: cloudflare-worker/.

Entrada: src/index.js.

O roteador separa dois fluxos:

- caminhos iniciados por /api/ são tratados pelo Worker;
- todo o restante é delegado ao binding ASSETS.

wrangler.jsonc define:

- name: mana-ponte;
- main: src/index.js;
- assets.directory: ../public;
- assets.binding: ASSETS;
- run_worker_first para /api/*;
- D1 binding DB;
- database_name manaponte.

O database_id versionado no repositório é um placeholder. O workflow de deploy consulta a conta Cloudflare e substitui o valor no workspace do CI antes de migrations/deploy.

## 5. Módulos do Worker

### src/index.js

Responsável por roteamento, healthcheck, tratamento global de erros e delegação de Static Assets.

### src/lib.js

Responsável por:

- respostas JSON;
- cookies;
- tokens aleatórios;
- SHA-256;
- PBKDF2;
- validação de senha;
- leitura de JSON;
- sessão;
- CSRF;
- validações compartilhadas.

### src/auth.js

Responsável por:

- cadastro;
- login;
- logout;
- atualização de perfil;
- rate limiting de autenticação.

### src/catalog.js

Responsável por:

- busca local no D1;
- enriquecimento sob demanda via Scryfall;
- normalização de cartas;
- upsert por scryfall_id;
- listagem de sets.

### src/listings.js

Responsável por:

- filtros de anúncios;
- paginação;
- detalhe público;
- CRUD autenticado;
- ownership.

### src/wants.js

Responsável por:

- desejos;
- matches;
- perfil público.

## 6. D1

A produção usa uma única base D1. Diferentemente do backend Python legado, não existem três arquivos de banco nem ATTACH.

Relações principais:

    users 1 ---- N sessions
    users 1 ---- N listings
    users 1 ---- N wants
    cards 1 ---- N listings
    cards 1 ---- N wants

D1 aplica foreign keys declaradas na migration.

Detalhes: docs/DATA_MODEL.md.

## 7. Catálogo

O D1 nasce com um conjunto pequeno de cartas seed na migration inicial.

GET /api/cards faz busca local primeiro. Quando:

- q tem pelo menos 3 caracteres; e
- a quantidade local encontrada é menor que o limit solicitado,

o Worker consulta o Scryfall.

A busca externa:

- usa name:"consulta" unique:prints;
- aceita filtro de set;
- aceita filtro de idioma;
- define include_extras=false;
- define include_multilingual=true;
- ignora cartas digitais;
- coleta no máximo 100 cartas por requisição do ManaPonte.

Resultados são persistidos no D1 e a página final é lida novamente do banco.

Se o Scryfall falhar, o Worker registra a falha e continua com os dados locais.

## 8. Imagens

Estado atual definitivo da arquitetura:

    cards.image_url
          |
          v
    URL externa do Scryfall
          |
          v
    navegador baixa a imagem diretamente

Não existem:

- R2;
- Cloudflare Images;
- blob/base64 no D1;
- cache persistente próprio de imagens;
- download em massa de imagens em produção.

A coluna image_url é metadado textual.

## 9. Sessão e autenticação

Novo cadastro:

1. normaliza username/e-mail;
2. valida senha e perfil;
3. deriva PBKDF2-SHA256 com 100.000 iterações e salt aleatório;
4. grava user;
5. gera token aleatório de sessão e CSRF;
6. grava somente SHA-256 do token;
7. envia token bruto em cookie HttpOnly/Secure/SameSite=Lax.

O verificador aceita hashes PBKDF2 entre 100.000 e 1.000.000 de iterações para permitir compatibilidade de hashes já persistidos.

Sessões duram 7 dias.

Rate limiting usa a tabela login_attempts e chave SHA-256 de IP + identificador. Cinco falhas dentro de 15 minutos ativam bloqueio de 15 minutos.

## 10. Frontend

public/ é frontend sem framework.

Em produção Cloudflare, MANAPONTE_API_BASE fica vazio e as chamadas /api/* são same-origin.

GitHub Pages continua existindo como modo estático/demonstração. Ele não é a implantação principal.

Detalhes: docs/FRONTEND.md.

## 11. CI/CD

Workflow de produção: .github/workflows/cloudflare.yml.

Em push para main, quando arquivos relevantes mudam:

1. checkout;
2. Node 22;
3. valida secrets;
4. normaliza Account ID;
5. lista D1;
6. cria manaponte se necessário;
7. descobre database_id;
8. atualiza wrangler.jsonc no workspace;
9. aplica migrations remotas;
10. publica Worker e assets.

O workflow não grava o database_id real de volta no GitHub.

## 12. Backend Python legado

app/ e scripts/dev.sh permanecem úteis para desenvolvimento local, fixtures e grande parte da suíte atual.

Esse backend usa SQLite e possui decisões diferentes, como scrypt e bancos divididos. Não deve ser usado como descrição da produção.

Detalhes: docs/LEGACY_PYTHON.md.

## 13. Falhas esperadas

Scryfall indisponível:
- busca local continua.

D1 indisponível/erro SQL:
- API retorna erro interno do banco em JSON quando capturado.

Sessão ausente/expirada:
- rotas autenticadas retornam 401.

CSRF incorreto:
- retorna 403.

Resposta não JSON por falha fora do Worker:
- frontend mostra "Resposta inesperada do servidor".

Erro assíncrono da API:
- o roteador usa await para que a exceção seja capturada e convertida em JSON.

## 14. Observabilidade

Wrangler habilita observability. O Worker usa console.error/console.log para erros relevantes.

Ainda faltam:

- logging de auditoria de domínio;
- métricas próprias;
- alertas;
- tracing de fluxos de negócio;
- política formal de retenção de logs.

## 15. Decisões futuras

Antes de adicionar um novo serviço, verificar se Worker + D1 continua suficiente.

Possíveis evoluções:

- verificação de e-mail;
- recuperação de senha;
- moderação/reputação;
- notificações;
- backup/exportação formal do D1;
- testes E2E do Worker;
- domínio próprio.

Armazenamento próprio de imagens não faz parte da arquitetura planejada atual.
