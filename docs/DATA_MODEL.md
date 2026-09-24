# Modelo de dados de produção

Produção usa Cloudflare D1, com schema definido em cloudflare-worker/migrations/0001_initial.sql.

## Topologia

Uma única base D1:

    manaponte
      |-- cards
      |-- users
      |-- sessions
      |-- listings
      |-- wants
      +-- login_attempts

PRAGMA foreign_keys = ON é aplicado pela migration.

## cards

Uma linha representa uma impressão.

Campos:

- id: INTEGER PRIMARY KEY AUTOINCREMENT
- scryfall_id: identificador único da impressão
- oracle_id: identificador conceitual entre reimpressões
- name: nome canônico
- printed_name: nome impresso/localizado opcional
- set_code
- set_name
- collector_number
- language
- rarity
- image_url
- updated_at

Índices:

- name NOCASE
- printed_name NOCASE
- set_code + language
- oracle_id

### Identidades

cards.id:
ID local do ManaPonte. Listings e wants referenciam este valor.

scryfall_id:
Identifica uma impressão no Scryfall.

oracle_id:
Permite considerar reimpressões da mesma carta no matching.

## Imagens

image_url é TEXT.

Ela guarda uma referência externa; nunca bytes, base64 ou blob.

O schema não possui tabela de imagens.

## users

Campos:

- id
- username, UNIQUE NOCASE
- email, UNIQUE NOCASE
- display_name
- phone, opcional
- city
- state
- password_hash
- email_verified
- created_at
- updated_at

Índice:

- state + city

E-mail é privado nas rotas públicas. Phone é público quando informado.

## sessions

Campos:

- token_hash: SHA-256 do token bruto
- user_id: FK users(id), ON DELETE CASCADE
- csrf_token
- created_at: epoch
- expires_at: epoch

Índices:

- user_id
- expires_at

O token bruto nunca é persistido.

## listings

Campos:

- id
- card_id: FK cards(id)
- user_id: FK users(id), ON DELETE CASCADE
- title
- description
- price_cents
- condition
- language
- mode
- contact_url
- created_at

Condições:

- NM
- SP
- MP
- HP
- DMG

Modalidades:

- venda
- troca
- ambos

Índices:

- card_id
- user_id
- mode
- created_at

Ao criar ou atualizar um anúncio, o runtime deriva o idioma da impressão em `cards`.

`contact_url` é opcional e o fluxo atual de criação não depende dele.

## wants

Campos:

- id
- card_id: FK cards(id)
- user_id: FK users(id), ON DELETE CASCADE
- max_price_cents
- desired_condition
- desired_language
- mode
- created_at

Modalidades:

- compra
- troca
- ambos

Restrição:

UNIQUE(card_id, user_id)

Índices:

- card_id
- user_id

## login_attempts

Rate limiting persistente.

Campos:

- key: SHA-256 de IP + identificador
- failures
- window_started
- blocked_until

## Seed inicial

A migration 0001 contém um pequeno conjunto de cartas para que o sistema não nasça totalmente vazio.

Essas linhas armazenam metadados e URLs externas do Scryfall.

O seed não representa catálogo completo.

## Crescimento do catálogo

O catálogo cresce sob demanda.

Fluxo:

1. usuário busca carta;
2. D1 é consultado;
3. quando há poucos resultados e q possui 3+ caracteres, Scryfall é consultado;
4. resultados são normalizados;
5. INSERT ... ON CONFLICT(scryfall_id) atualiza os metadados;
6. a resposta é relida do D1.

O Worker limita a 100 cartas remotas por chamada.

## Migrations

Diretório:

cloudflare-worker/migrations/

Deploy aplica:

    wrangler d1 migrations apply manaponte --remote

Novas alterações estruturais devem usar migrations adicionais, por exemplo:

    0002_nome_da_mudanca.sql

Não editar silenciosamente a migration já aplicada para mudanças futuras de produção.

## Integridade

D1 possui foreign keys no schema de produção.

A aplicação também valida recursos antes de gravar:

- card_id precisa existir;
- ownership é validado por user_id da sessão;
- enumerações são validadas em JavaScript;
- preços precisam ser inteiros não negativos quando armazenados em centavos.

## Backup

O repositório ainda não implementa rotina automática de export/backup do D1.

Dados de contas, anúncios e desejos devem ser considerados permanentes. O catálogo de cartas é reconstruível a partir do Scryfall, mas os dados comunitários não são.
