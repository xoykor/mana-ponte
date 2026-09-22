# Modelo de dados e persistência

## Topologia atual

O modo padrão usa três arquivos SQLite:

```text
data/cards.db
  └─ cards
  └─ schema_version

data/accounts.db
  └─ users
  └─ sessions
  └─ schema_version

data/listings.db
  └─ listings
  └─ wants
  └─ schema_version
```

O banco de anúncios é aberto como banco principal e os outros dois são anexados:

```text
catalog  -> cards.db
accounts -> accounts.db
main     -> listings.db
```

Isso permite JOINs de leitura entre os três arquivos.

SQLite não aplica foreign keys entre bancos anexados. Por isso, `card_id` e `user_id` em `listings.db` não possuem FKs reais no modo dividido. A consistência é imposta pela aplicação antes das gravações.

## Resolução de caminhos

A prioridade de cada banco é:

1. caminho explícito recebido pela função;
2. variável de ambiente específica;
3. caminho padrão.

Variáveis:

- `MANAPONTE_CARDS_DB_PATH`;
- `MANAPONTE_ACCOUNTS_DB_PATH`;
- `MANAPONTE_LISTINGS_DB_PATH`.

O modo legado usa `MANAPONTE_DB_PATH` e um único arquivo.

Se somente `MANAPONTE_DB_PATH` estiver definido e nenhuma variável específica existir, o servidor e o seed entram em modo legado.

## Configuração de conexão

Toda conexão criada por `get_connection()`:

- cria o diretório pai se necessário;
- usa timeout de 10 segundos;
- define `row_factory = sqlite3.Row`;
- executa `PRAGMA foreign_keys = ON`;
- executa `PRAGMA busy_timeout = 10000`.

Cada requisição abre conexões independentes. Não existe pool.

## Tabela `cards`

Uma linha representa uma impressão física.

Campos:

- `id`: chave local inteira usada por anúncios/desejos;
- `scryfall_id`: identificador estável da impressão no Scryfall, único;
- `oracle_id`: identidade conceitual da carta, usada para agrupar reimpressões;
- `name`: nome canônico/Oracle, normalmente inglês;
- `printed_name`: nome realmente impresso na edição traduzida, opcional;
- `set_code`;
- `set_name`;
- `collector_number`;
- `language`;
- `rarity`;
- `image_url`;
- `updated_at`.

Índices:

- `name COLLATE NOCASE`;
- `printed_name COLLATE NOCASE` criado pela migração v5;
- `(set_code, language)`;
- `oracle_id`.

### Identidade da carta

`cards.id` identifica uma linha local.

`scryfall_id` identifica uma impressão específica.

`oracle_id` identifica a carta conceitual entre reimpressões.

Esses três IDs não são intercambiáveis.

### Nome canônico x nome impresso

Uma impressão traduzida pode ser armazenada como:

```text
name         = Lightning Bolt
printed_name = Raio
language     = pt
```

A busca aceita ambos os nomes. O nome impresso não substitui o nome canônico.

## Tabela `users`

Campos:

- `id`;
- `username`, único e NOCASE;
- `email`, único e NOCASE;
- `display_name`;
- `phone`, opcional;
- `city`;
- `state`, exatamente 2 caracteres;
- `password_hash`;
- `email_verified`, 0 ou 1;
- `created_at`;
- `updated_at`.

Índice de localização:

```text
(state, city)
```

O telefone é público quando preenchido. O e-mail não é exposto pelas rotas públicas.

## Tabela `sessions`

Campos:

- `token_hash`: SHA-256 do token bruto, chave primária;
- `user_id`;
- `csrf_token`;
- `created_at`: epoch em segundos;
- `expires_at`: epoch em segundos.

Índices:

- `user_id`;
- `expires_at`.

O token bruto nunca é persistido.

## Tabela `listings`

Campos:

- `id`;
- `card_id`;
- `user_id`;
- `title`;
- `description`;
- `price_cents`, nulo ou >= 0;
- `condition`: `NM|SP|MP|HP|DMG`;
- `language`;
- `mode`: `venda|troca|ambos`;
- `contact_url`;
- `created_at`.

Índices:

- `card_id`;
- `mode`.

### Coluna `language`

Ela continua no schema por compatibilidade. Nas respostas e filtros atuais, a fonte de verdade é `cards.language`.

Ao criar ou editar um anúncio, o servidor copia novamente o idioma da impressão para a coluna legada, evitando divergência nova.

### `contact_url`

Permanece no banco e no contrato por compatibilidade. A interface atual prioriza perfil público, telefone e WhatsApp.

## Tabela `wants`

Campos:

- `id`;
- `card_id`;
- `user_id`;
- `max_price_cents`;
- `desired_condition`;
- `desired_language`;
- `mode`: `compra|troca|ambos`;
- `created_at`.

Restrição:

```text
UNIQUE(card_id, user_id)
```

Índice:

- `card_id`.

## Migrações

Cada banco possui `schema_version`, mas as migrações são aplicadas por código e de forma idempotente.

### v1

Schemas iniciais.

### v2 e v3 — autenticação

A migração de contas garante:

- `password_hash`;
- `email_verified`;
- `updated_at`;
- `phone`;
- estrutura moderna de `sessions`.

Sessões são consideradas efêmeras. Se uma tabela antiga de sessões tiver estrutura incompatível, ela pode ser descartada e recriada.

Dados permanentes de usuário são migrados com `ALTER TABLE` quando possível.

### v4 — desejos

Adiciona `desired_language` a `wants`.

### v5 — catálogo

Adiciona `printed_name` e cria o índice de nome impresso.

## Modo legado

`app/schema.sql` mantém todas as tabelas no mesmo arquivo.

O modo legado existe para:

- instalações antigas;
- testes que passam um caminho único;
- consumidores que ainda dependem de `data/app.db`.

No banco único, FKs locais podem ser aplicadas normalmente.

O caminho novo deve continuar sendo preferido.

## Seed

`app.seed` é determinístico e sem rede.

No modo dividido:

1. inicializa os três schemas;
2. abre os três bancos;
3. insere/atualiza cartas de demonstração;
4. insere/atualiza usuários;
5. resolve os IDs locais das cartas por `scryfall_id`;
6. insere/atualiza anúncios;
7. cria o desejo de demonstração se ainda não existir.

Sem `reset`, o seed é idempotente e não apaga um catálogo importado.

Com `reset=True`, limpa os dados de demonstração/estado nas tabelas envolvidas antes de recriar fixtures.

A senha `ManaPonte!2026` é exclusivamente fixture de desenvolvimento.

## Transações e consistência

- Importação de catálogo faz batches e um commit final; exceção gera rollback.
- Cadastro faz commit do usuário antes de criar a sessão.
- Operações de anúncio/desejo fazem commit antes da resposta.
- Não existe transação distribuída entre os três arquivos.
- Cross-database invariants são verificadas em código.
- Não há replicação, journaling customizado, backup automático nem migração online implementada.

## Estratégia de imagens no estado atual

A tabela armazena `image_url`.

O runtime atual usa essas URLs diretamente no frontend.

`data/images/sample/` contém apenas amostras e não participa da resolução de imagens da aplicação.

Portanto, os AVIFs locais ainda não estão ligados ao caminho de execução. Uma futura camada de storage local deve preservar o princípio de não gravar blobs no SQLite e resolver um identificador de imagem para uma URL pública.
