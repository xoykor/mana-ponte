# Guia de leitura do código

Este guia assume apenas conhecimentos iniciais de Lógica de Programação.

## 1. Ordem recomendada

Backend:

1. `cloudflare-worker/src/index.js`
2. `cloudflare-worker/src/lib.js`
3. `cloudflare-worker/src/auth.js`
4. `cloudflare-worker/src/catalog.js`
5. `cloudflare-worker/src/listings.js`
6. `cloudflare-worker/src/wants.js`

Frontend:

1. `public/page-common.js`
2. `public/listing-detail.js`
3. `public/profile-page.js`
4. `public/listings-page.js`
5. `public/card-picker.js`
6. `public/app.js`

## 2. Quatro ideias aparecem em todo o projeto

- variável — guarda um valor;
- função — agrupa passos;
- `if` — escolhe um caminho;
- laço — repete uma ação.

## 3. Roteamento

`index.js` funciona como recepção.

```text
se método == GET e caminho == /api/cards
    chamar getCards()
```

## 4. Funções compartilhadas

`lib.js` contém ferramentas reutilizadas por outros módulos:

- `json()`;
- `readJson()`;
- `positiveInt()`;
- `requireSession()`;
- `csrfValid()`.

## 5. Padrão principal

```text
entrada
  -> normalização
  -> validação
  -> banco/serviço externo
  -> resposta
```

## 6. async/await

```js
const user = await env.DB.prepare("...").first();
```

`await` espera uma operação assíncrona terminar antes de continuar a função.

## 7. HTTP

Status comuns:

- 200 — sucesso;
- 201 — criado;
- 400 — entrada inválida;
- 401 — não autenticado;
- 403 — proibido;
- 404 — não encontrado;
- 409 — conflito;
- 429 — tentativas demais;
- 500 — erro interno.

## 8. SQL e bind()

```js
env.DB.prepare("SELECT ... WHERE email=?")
  .bind(email)
```

O `?` é um espaço reservado. `bind()` fornece o valor separadamente do comando SQL.

## 9. JOIN

```text
listings
   +-- card_id -> cards
   +-- user_id -> users
```

JOIN combina dados de tabelas relacionadas.

## 10. CRUD

Em `listings.js`:

- Create -> `createListing()`
- Read -> `getListing()`, `getListings()`
- Update -> `updateListing()`
- Delete -> `deleteListing()`

## 11. Sessão

```text
login
  -> token aleatório
  -> cookie no navegador
  -> SHA-256(token) no D1
```

## 12. Senhas e CSRF

Senhas são derivadas com PBKDF2 e nunca persistidas em texto original.

Operações que alteram dados exigem CSRF.

## 13. Catálogo

```text
buscar no D1
   |
   +-- suficiente -> responder
   |
   +-- insuficiente -> Scryfall
                         -> salvar metadados
                         -> reler D1
                         -> responder
```

## 14. Imagens

O banco guarda somente `image_url`. O navegador acessa a URL externa.

## 15. Frontend

`fetch()` envia requisições HTTP.

Funções `render...` transformam dados em elementos visíveis.

`AbortController` cancela buscas que já ficaram obsoletas.

## 16. Antes de editar

Pergunte:

1. quem chama?
2. o que entra?
3. o que retorna?
4. o que altera?
5. quais erros podem ocorrer?

Depois confira sintaxe e CI.

## 17. Visão completa

```text
navegador
   |
   +-- HTML/CSS/JS -> Static Assets
   |
   +-- /api/* -----> Worker
                        |
                        +-- D1
                        +-- Scryfall
```
