# API de produção do ManaPonte

Este documento descreve a API implementada em cloudflare-worker/src/.

Base de produção:

https://mana-ponte.vsxk.workers.dev

## Convenções

Rotas /api/* são executadas pelo Worker.

Respostas JSON geradas pelo helper comum incluem:

- Content-Type: application/json; charset=utf-8
- Cache-Control: no-store
- X-Content-Type-Options: nosniff

Rotas desconhecidas retornam 404 JSON.

Erros de validação normalmente retornam 400 com campo error.

Erros identificados como D1/SQL/database/binding retornam 500 com mensagem genérica de banco.

O corpo JSON é limitado a 64 KiB quando Content-Length é informado.

## Sessão

Cookie:

mp_session

Atributos:

- Path=/
- Max-Age=604800
- HttpOnly
- Secure
- SameSite=Lax

O token bruto só fica no cookie. O D1 armazena SHA-256 do token.

Operações mutáveis autenticadas exigem X-CSRF-Token.

## Health

### GET /api/health

Resposta:

    {
      "status": "ok",
      "service": "ManaPonte",
      "runtime": "cloudflare-workers-d1",
      "image_storage": "none"
    }

O healthcheck não consulta Scryfall.

## Autenticação

### POST /api/auth/register

Campos:

- username: 3–30; a-z, 0-9, _, . e -
- email: até 254 caracteres e formato válido
- password: 12–128, com minúscula, maiúscula, número e símbolo
- display_name: 2–80
- phone: opcional; 10–15 dígitos após normalização
- city: 2–80
- state: UF brasileira válida

Senha: PBKDF2-SHA256 com 100.000 iterações para novos hashes.

Sucesso: 201, sessão iniciada, user + csrf_token.

Duplicidade: 409.

### POST /api/auth/login

Campos:

- identifier: username ou e-mail
- password

Cinco falhas em 15 minutos por IP + identificador ativam bloqueio por 15 minutos.

Sucesso limpa a entrada de rate limit e cria nova sessão.

### GET /api/auth/me

Exige sessão.

Retorna:

- id
- username
- email
- display_name
- phone
- city
- state
- email_verified
- csrf_token

### POST /api/auth/logout

Exige sessão e CSRF.

Revoga a sessão e expira o cookie.

### PATCH /api/profile

Exige sessão e CSRF.

Campos mutáveis:

- display_name
- phone
- city
- state

## Catálogo

### GET /api/cards

Parâmetros:

- q
- set
- lang
- page
- limit

Limites:

- q: até 100 caracteres usados
- set: até 16
- lang: até 8
- limit: máximo 100
- page: máximo lógico 100000

Busca local usa name e printed_name com LIKE NOCASE.

Enriquecimento Scryfall ocorre quando q possui pelo menos 3 caracteres e a quantidade local encontrada é menor que o limit.

A integração externa pode persistir no máximo 100 resultados por chamada.

Resposta:

    {
      "cards": [],
      "page": 1,
      "limit": 24,
      "total": 0,
      "source": "local"
    }

source pode ser local ou scryfall.

image_url é somente uma URL externa. Nenhuma imagem é gravada no D1.

### GET /api/sets

Retorna apenas sets já presentes no D1.

Campos:

- set_code
- set_name
- card_count

## Anúncios

### GET /api/listings

Filtros:

- card_id
- card
- set
- lang
- city
- state
- condition
- mode
- min_price
- max_price
- mine
- sort
- page
- limit

mode:

- venda inclui venda e ambos
- troca inclui troca e ambos
- ambos exige ambos

sort:

- recent
- oldest
- price_asc
- price_desc

mine=1, true ou yes exige sessão.

min_price e max_price chegam em valor decimal e são convertidos para centavos.

### GET /api/listings/{id}

Rota pública.

Retorna listing com dados da carta e vendedor, incluindo phone quando preenchido.

### POST /api/listings

Exige sessão e CSRF.

Campos:

- card_id
- title
- description
- price_cents
- condition
- mode

Regras:

- card_id deve existir;
- title: 3–120;
- description: até 1000;
- condition: NM, SP, MP, HP ou DMG;
- mode: venda, troca ou ambos;
- price_cents: inteiro não negativo ou null.

Autoria vem da sessão.

O idioma é derivado da carta.

### PATCH /api/listings/{id}

Exige sessão, CSRF e ownership.

### DELETE /api/listings/{id}

Exige sessão, CSRF e ownership.

## Desejos

### GET /api/wants

Exige sessão.

Paginação máxima: 100.

### POST /api/wants

Exige sessão e CSRF.

Campos:

- card_id
- max_price_cents
- desired_condition
- desired_language
- mode

mode:

- compra
- troca
- ambos

Existe UNIQUE(card_id, user_id). Repetir a mesma carta atualiza o desejo.

### DELETE /api/wants/{id}

Exige sessão, CSRF e ownership.

## Matching

### GET /api/matches?card_id={id}

Público.

Busca ofertas da impressão e de reimpressões com mesmo oracle_id.

### GET /api/matches

Exige sessão.

Cruza os desejos do usuário com anúncios de outros usuários.

Regras:

- impressão exata ou mesmo oracle_id;
- não retorna anúncio do próprio usuário;
- respeita modalidade;
- respeita desired_language quando definido;
- respeita max_price_cents;
- condição usa ordem NM > SP > MP > HP > DMG.

## Perfis

### GET /api/users/{id}

Público.

Retorna:

- user: id, username, display_name, phone, city, state, created_at
- stats: listing_count e want_count
- até 100 anúncios
- até 100 desejos

Nunca retorna e-mail, password_hash, sessões ou CSRF.

## OPTIONS

OPTIONS em /api/* retorna 204 e anuncia:

- GET, POST, PATCH, DELETE, OPTIONS
- Content-Type, X-CSRF-Token
- max age 600

A implantação principal é same-origin. CORS cross-origin não é um requisito do Worker atual.

## Imagens

A API nunca recebe upload de imagem e nunca devolve bytes de imagem.

Ela devolve somente image_url.
