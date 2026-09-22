# API do ManaPonte

Este documento descreve o contrato HTTP implementado em `app/server.py`. Ele documenta o comportamento atual do código, não uma API futura.

## Transporte e respostas

- O servidor usa `ThreadingHTTPServer` e `BaseHTTPRequestHandler` da biblioteca padrão.
- Rotas `/api/*` respondem JSON UTF-8.
- Respostas JSON incluem `X-Content-Type-Options: nosniff`.
- Rotas de autenticação usam `Cache-Control: no-store`; as demais respostas JSON usam `no-cache`.
- O corpo de rotas mutáveis é limitado a 32 KiB.
- O corpo precisa ser um objeto JSON. Arrays, valores escalares e corpo vazio são rejeitados.
- Erros de parâmetros capturados pelo dispatcher retornam HTTP 400 com `{"error": "..."}`.
- Rotas desconhecidas sob `/api/` retornam 404 em JSON.
- Arquivos estáticos fora de `/api/` são servidos de `public/`.

## CORS

`MANAPONTE_ALLOWED_ORIGIN` contém uma lista separada por vírgulas. A origem recebida precisa coincidir exatamente com uma entrada configurada.

Quando autorizada, a resposta inclui:

- `Access-Control-Allow-Origin` com a origem solicitante;
- `Access-Control-Allow-Credentials: true`;
- `Vary: Origin`.

O preflight `OPTIONS` só é aceito para caminhos `/api/*` e retorna:

- métodos: `GET, POST, PATCH, DELETE, OPTIONS`;
- headers: `Content-Type, X-CSRF-Token`;
- `Access-Control-Max-Age: 600`.

## Sessão e CSRF

O cookie da sessão se chama `mp_session`.

Por padrão:

- `HttpOnly`;
- `SameSite=Lax`;
- `Path=/`;
- `Max-Age=604800` segundos.

Com `MANAPONTE_SECURE_COOKIES=1`, o cookie recebe `Secure`.

Com `MANAPONTE_CROSS_SITE_COOKIES=1`, o servidor força:

- `SameSite=None`;
- `Secure`.

Operações mutáveis autenticadas exigem o header `X-CSRF-Token`, obtido em `/api/auth/me` ou na resposta de login/cadastro.

## Rotas

### `GET /api/health`

Retorna o estado básico do processo:

```json
{"status":"ok","service":"ManaPonte"}
```

Não verifica disponibilidade do Scryfall nem integridade profunda dos bancos.

### `POST /api/auth/register`

Cria usuário e inicia sessão.

Campos:

- `username`: 3–30 caracteres; letras minúsculas após normalização, números, `_`, `.` e `-`;
- `email`: normalizado com `casefold()`, até 254 caracteres;
- `password`: 12–128 caracteres, com minúscula, maiúscula, número e símbolo;
- `display_name`: 2–80 caracteres;
- `phone`: opcional, 10–15 dígitos após normalização;
- `city`: 2–80 caracteres;
- `state`: uma UF brasileira válida.

O cliente não define `email_verified`; novos usuários começam com 0.

Conflito de username/e-mail retorna 409.

Resposta 201 contém usuário público/autenticado, `csrf_token` e `Set-Cookie`.

### `POST /api/auth/login`

Aceita:

- `identifier`: username ou e-mail;
- `password`.

O identificador é normalizado da mesma forma que e-mail/username.

O rate limiter usa a chave:

```text
IP:identificador
```

São permitidas até 5 falhas numa janela de 900 segundos por processo. Um login correto apaga o histórico da chave.

Usuário inexistente ainda passa por uma verificação de hash fictício para reduzir diferença temporal observável.

### `GET /api/auth/me`

Exige sessão válida. Retorna:

- `id`;
- `username`;
- `email`;
- `display_name`;
- `phone`;
- `city`;
- `state`;
- `email_verified`;
- `csrf_token`.

O e-mail aparece aqui porque esta é uma rota autenticada do próprio usuário. Ele não aparece no perfil público.

### `POST /api/auth/logout`

Exige sessão e CSRF.

Revoga a linha da sessão e sobrescreve o cookie com `Max-Age=0`.

### `PATCH /api/profile`

Exige sessão e CSRF.

Permite alterar:

- `display_name`;
- `phone`;
- `city`;
- `state`.

Após o commit, a sessão é relida para a resposta refletir os dados atualizados.

### `GET /api/cards`

Parâmetros:

- `q`: até 100 caracteres;
- `set`: até 16;
- `lang`: até 8;
- `page`: inteiro positivo, máximo lógico de 100000;
- `limit`: inteiro positivo, máximo 100.

A busca local usa:

```sql
name LIKE ? COLLATE NOCASE
OR printed_name LIKE ? COLLATE NOCASE
```

`set` compara `set_code` sem distinção de caixa. `lang` compara `language`.

#### Ordem real da busca

1. Abre o banco local de cartas.
2. Conta resultados locais com os filtros recebidos.
3. Se `q` tiver 3 ou mais caracteres e a busca remota estiver habilitada, consulta o Scryfall.
4. Resultados remotos são normalizados e gravados por upsert no banco local.
5. O total é recalculado.
6. A página final é lida novamente do banco local.

Portanto, o Scryfall é enriquecimento/fallback do catálogo local; a resposta final é sempre construída a partir do SQLite.

Se o Scryfall falhar, a exceção é absorvida pela camada de cache remoto e a busca local continua.

`source` vale:

- `local`: nenhuma linha nova foi importada naquela chamada;
- `scryfall`: a chamada remota devolveu linhas e elas foram persistidas.

`source` não significa que cada item da página veio originalmente do Scryfall naquela requisição.

A ordenação é:

```text
name, set_code, collector_number
```

### `GET /api/sets`

Retorna `set_code`, `set_name` e contagem de cartas agrupada por combinação código/nome, ordenada por nome do set.

### `GET /api/listings`

Filtros:

- `card_id`;
- `card`;
- `set`;
- `lang`;
- `city`;
- `state`;
- `mode`;
- `condition`;
- `min_price`;
- `max_price`;
- `mine`;
- `sort`;
- `page`;
- `limit`.

`card` pesquisa `cards.name` e `cards.printed_name`.

`mode=venda` inclui `venda` e `ambos`.

`mode=troca` inclui `troca` e `ambos`.

`mode=ambos` exige exatamente `ambos`.

`mine=1`, `true` ou `yes` exige autenticação e limita a consulta ao usuário da sessão.

Preços de filtro chegam em reais decimais e são convertidos com `Decimal` e arredondamento `ROUND_HALF_UP` para centavos. Preço mínimo maior que máximo é rejeitado.

Ordenações:

- `recent`: `created_at DESC, id DESC`;
- `oldest`: `created_at ASC, id ASC`;
- `price_asc`: nulos depois dos preços definidos;
- `price_desc`: nulos depois dos preços definidos.

O idioma público vem de `cards.language`, não da coluna legada `listings.language`.

### `GET /api/listings/{id}`

Retorna um anúncio, metadados da impressão e dados públicos do vendedor.

Inclui telefone somente porque esta é a página pública de contato do anúncio. Não inclui e-mail, hash de senha, token ou CSRF.

### `POST /api/listings`

Exige sessão e CSRF.

Valida:

- `card_id` existente;
- título de 3–120 caracteres;
- descrição de até 1000;
- condição: `NM|SP|MP|HP|DMG`;
- modalidade: `venda|troca|ambos`;
- preço em centavos não negativo ou nulo;
- `contact_url` vazia ou HTTP(S) válida, até 300 caracteres.

O `user_id` sempre vem da sessão.

O idioma é lido da impressão selecionada. Um valor de `language` enviado pelo cliente não é fonte de verdade.

### `PATCH /api/listings/{id}`

Exige sessão e CSRF.

Só encontra o anúncio quando `id` e `user_id` da sessão coincidem. Isso faz com que tentativa de editar anúncio alheio se comporte como “não encontrado”.

Revalida todos os campos mutáveis e recalcula o idioma a partir da impressão escolhida.

### `DELETE /api/listings/{id}`

Exige sessão e CSRF.

Remove somente quando o anúncio pertence ao usuário atual.

### `GET /api/users/{id}`

Rota pública.

Retorna:

- identidade pública: id, username, display_name, phone, city, state, created_at;
- contagem de anúncios;
- contagem de desejos;
- até 100 anúncios do usuário;
- até 100 desejos do usuário.

Não retorna e-mail, hash de senha, sessões nem CSRF.

### `GET /api/wants`

Exige sessão.

Parâmetros `page` e `limit`, com máximo 100 por página.

Retorna apenas desejos do usuário atual.

### `POST /api/wants`

Exige sessão e CSRF.

Campos:

- `card_id`;
- `max_price_cents`: opcional, não negativo;
- `desired_condition`: opcional, `NM|SP|MP|HP|DMG`;
- `desired_language`: opcional, 2–8 caracteres alfanuméricos;
- `mode`: `compra|troca|ambos`.

Existe uma restrição única em `(card_id, user_id)`. Repetir a mesma carta para o mesmo usuário atualiza o desejo em vez de criar outro.

### `DELETE /api/wants/{id}`

Exige sessão e CSRF.

Só remove desejo pertencente ao usuário atual.

### `GET /api/matches?card_id=<id>`

Não exige sessão.

Encontra ofertas da impressão exata e de outras impressões com o mesmo `oracle_id`, quando esse identificador existe.

O resultado é ordenado por UF, cidade e id do anúncio decrescente.

### `GET /api/matches`

Sem `card_id`, exige sessão.

Cruza todos os desejos do usuário com anúncios de outros usuários.

Compatibilidade:

- impressão exata ou mesmo `oracle_id`;
- nunca casa anúncio do próprio usuário;
- `compra` aceita oferta `venda` ou `ambos`;
- `troca` aceita `troca` ou `ambos`;
- `ambos` aceita qualquer modalidade compatível;
- `desired_language`, quando definido, precisa coincidir;
- preço máximo aceita anúncio sem preço ou com preço menor/igual;
- condição mínima usa a ordem `NM > SP > MP > HP > DMG`.

## Arquivos estáticos

O servidor trata `/` como `public/index.html`.

O caminho é resolvido com `Path.resolve()` e precisa permanecer dentro de `public/`; tentativas de traversal são rejeitadas.

O servidor estático do protótipo:

- lê o arquivo inteiro em memória;
- usa `mimetypes.guess_type`;
- não implementa range requests, compressão, ETag ou cache avançado.

Em produção, esses arquivos devem ser servidos por um servidor/proxy dedicado.
