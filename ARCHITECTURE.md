# Arquitetura do ManaPonte

Este documento descreve a arquitetura atual do projeto.

## 1. Objetivo

O ManaPonte conecta jogadores que possuem ou procuram cartas de Magic: The Gathering.

O MVP cobre descoberta, anúncios, desejos, matching e contato. Pagamento, frete e custódia estão fora do escopo atual.

## 2. Topologia

```text
Internet
   |
   v
Cloudflare
   |
   +-- Static Assets
   |      +-- public/*.html
   |      +-- public/*.css
   |      +-- public/*.js
   |
   +-- Worker
          +-- /api/auth/*
          +-- /api/cards
          +-- /api/sets
          +-- /api/listings/*
          +-- /api/wants/*
          +-- /api/matches
          +-- /api/users/*
          |
          +-- DB -> Cloudflare D1
          |
          +-- fetch -> Scryfall
```

## 3. Princípios

1. Frontend e API usam a mesma origem em produção.
2. D1 é a fonte persistente da aplicação.
3. Scryfall fornece metadados externos de cartas.
4. Nenhum byte de imagem é armazenado pelo ManaPonte.
5. `cards.id` é o identificador local usado por anúncios e desejos.
6. `scryfall_id` identifica uma impressão.
7. `oracle_id` agrupa reimpressões da mesma carta.
8. autoria de anúncios/desejos vem da sessão, não do cliente.
9. token bruto de sessão nunca é persistido.
10. operações mutáveis autenticadas exigem CSRF.
11. mudanças de schema entram por migrations versionadas.

## 4. Runtime Cloudflare

Entrada: `cloudflare-worker/src/index.js`.

O roteador separa:

- `/api/*` -> código do Worker;
- demais caminhos -> binding `ASSETS`.

`wrangler.jsonc` define o Worker, os Static Assets e o binding D1.

O `database_id` versionado é um placeholder. O workflow descobre o ID real no deploy.

## 5. Módulos

- `index.js` — roteamento, healthcheck, erros e Static Assets.
- `lib.js` — JSON, cookies, tokens, crypto, sessão, CSRF e validações.
- `auth.js` — cadastro, login, logout, perfil e rate limiting.
- `catalog.js` — D1, Scryfall e upsert de cartas.
- `listings.js` — pesquisa, paginação e CRUD de anúncios.
- `wants.js` — desejos, matching e perfis públicos.

## 6. D1

```text
users 1 ---- N sessions
users 1 ---- N listings
users 1 ---- N wants
cards 1 ---- N listings
cards 1 ---- N wants
```

Detalhes em `docs/DATA_MODEL.md`.

## 7. Catálogo

`GET /api/cards` consulta o D1 primeiro.

Quando a pesquisa possui pelo menos 3 caracteres e os resultados locais não completam o limite solicitado, o Worker consulta o Scryfall.

A integração ignora cartas digitais, limita o enriquecimento a 100 cartas por chamada, persiste metadados e relê o D1 antes de responder.

## 8. Imagens

```text
D1: cards.image_url
        |
        v
URL externa
        |
        v
navegador
```

Não existe storage próprio de imagens.

## 9. Autenticação

Cadastro:

1. normaliza dados;
2. valida perfil e senha;
3. deriva PBKDF2-SHA256;
4. grava o usuário;
5. gera token de sessão e CSRF;
6. persiste somente SHA-256 do token;
7. envia o token bruto em cookie seguro.

Novos hashes usam 100.000 iterações.

Sessões duram 7 dias.

Cinco falhas de login numa janela de 15 minutos bloqueiam a chave por 15 minutos.

## 10. Frontend

`public/` é HTML/CSS/JavaScript sem framework.

Em produção, `MANAPONTE_API_BASE` fica vazio e `/api/*` é same-origin.

O repositório também mantém um modo estático/demonstração para GitHub Pages.

## 11. CI/CD

Deploy: `.github/workflows/cloudflare.yml`.

Validação: `.github/workflows/tests.yml`.

O deploy localiza/cria o D1, aplica migrations e publica Worker + assets.

## 12. Falhas esperadas

- Scryfall indisponível -> busca local continua.
- sessão ausente/expirada -> 401.
- CSRF inválido -> 403.
- recurso inexistente -> 404.
- conflito de cadastro -> 409.
- rate limit -> 429.
- erro D1 detectado -> 500 JSON.

## 13. Observabilidade

`observability.enabled=true` no Wrangler.

Ainda faltam métricas próprias, alertas e política formal de retenção de logs.

## 14. Evoluções futuras

- recuperação de senha;
- verificação de e-mail;
- moderação/reputação;
- notificações;
- backup/export automatizado do D1;
- testes de integração do Worker;
- domínio próprio.
