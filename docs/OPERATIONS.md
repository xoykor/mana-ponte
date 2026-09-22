# Operação, configuração e deploy

## Requisitos

- Python 3.11+;
- nenhuma dependência Python externa;
- Node é usado na CI apenas para `node --check` dos JavaScripts.

## Desenvolvimento local

`scripts/dev.sh`:

1. usa `set -euo pipefail`;
2. descobre a raiz a partir da própria localização;
3. muda para a raiz;
4. executa `python3 -m app.seed`;
5. usa `exec python3 -m app.server`.

O seed é executado em toda inicialização de desenvolvimento, mas é idempotente quando `reset` não é solicitado.

Padrão:

```text
host = 127.0.0.1
port = 8000
```

Variáveis:

- `MANAPONTE_HOST`;
- `MANAPONTE_PORT`.

## Variáveis de ambiente

### Banco

- `MANAPONTE_CARDS_DB_PATH`;
- `MANAPONTE_ACCOUNTS_DB_PATH`;
- `MANAPONTE_LISTINGS_DB_PATH`;
- `MANAPONTE_DB_PATH` para modo legado.

### Catálogo

- `MANAPONTE_REMOTE_SEARCH`.

A busca remota fica habilitada por padrão.

Valores que desligam:

- `0`;
- `false`;
- `no`;
- `off`.

A comparação é case-insensitive.

### Cookies/CORS

- `MANAPONTE_ALLOWED_ORIGIN`;
- `MANAPONTE_SECURE_COOKIES`;
- `MANAPONTE_CROSS_SITE_COOKIES`.

## Inicialização do servidor

`app.server.main()` chama `init_db()` e depois `create_server()`.

`create_server()` também inicializa os bancos. Essa duplicação é intencionalmente idempotente.

Para cada servidor é criada uma subclasse dinâmica de `ManaPonteHandler` com:

- caminhos de banco resolvidos;
- flag de modo dividido;
- um `LoginRateLimiter` próprio.

Isso impede que servidores de testes compartilhem acidentalmente o limiter global.

## Catálogo local

### Importação default_cards

```bash
python3 scripts/import_scryfall.py --download
```

ou:

```bash
python3 scripts/import_scryfall.py --file /caminho/arquivo
```

Esse script procura especificamente o bulk `default_cards`.

### Importação multilíngue

```bash
python3 scripts/import_allcards.py --type all_cards
```

O segundo script aceita qualquer tipo de bulk publicado pelo Scryfall.

Para o ManaPonte com pesquisa por nomes impressos/traduzidos, `all_cards` é o fluxo apropriado para preencher todas as impressões disponíveis em outros idiomas.

## Parser de Bulk Data

Formatos aceitos:

- JSONL;
- array JSON;
- gzip;
- texto sem compressão;
- UTF-8 com ou sem BOM.

Gzip é detectado pelos bytes mágicos `1f 8b`, não pela extensão.

JSONL é processado linha a linha.

Array JSON usa buffer incremental de 64 KiB e `JSONDecoder.raw_decode`.

O importador não precisa carregar o arquivo completo em memória.

Batch padrão:

```text
500 cartas
```

Entrada inválida, digital ou sem campos mínimos é ignorada e contabilizada.

## Busca remota sob demanda

A busca remota é uma camada de enriquecimento, não a base primária de leitura.

Cache do processo:

- máximo: 256 chaves;
- TTL: 300 segundos;
- chave: `(query, set_code, language)` normalizados em minúsculas;
- política de capacidade: remove a entrada de menor idade registrada;
- consultas idênticas concorrentes compartilham um `threading.Event`;
- o fetcher é único por chave enquanto a chamada está em voo.

Se o fetcher falhar:

- a API registra uma mensagem no stdout;
- os waiters são liberados;
- resultado vazio pode ser cacheado durante o TTL;
- a API continua com o catálogo local.

O endpoint remoto limita paginação a 50 URLs distintas e também detecta repetição de `next_page`.

## Scryfall search

A query remota usa:

```text
name:"consulta" unique:prints
```

e adiciona, quando aplicável:

- `set:<código>`;
- `lang:<idioma>`.

A URL inclui:

- `include_extras=false`;
- `include_multilingual=true`.

Aspas digitadas pelo usuário são removidas antes de construir o operador `name:"..."`.

## Imagens

### Estado implementado

O runtime usa `cards.image_url`, normalmente apontando para o Scryfall.

O backend não baixa nem serve automaticamente a coleção completa de imagens.

`data/images/sample/` não é storage de produção.

### AVIF local

Os AVIFs convertidos ainda não possuem integração no código atual. Quando a camada local for implementada, deve ser tratada como um subsistema separado de arquivos estáticos, mantendo o banco apenas com chave/metadata e não blobs.

Até essa integração existir, copiar AVIFs para a VPS não altera o comportamento da aplicação por si só.

## GitHub Pages

Workflow: `.github/workflows/pages.yml`.

Dispara em:

- push em `main`;
- execução manual.

Permissões:

- `contents: read`;
- `pages: write`;
- `id-token: write`.

Concorrência:

```text
group: pages
cancel-in-progress: true
```

O workflow consulta a API do GitHub para saber se Pages está habilitado.

- HTTP 200: continua;
- HTTP 404: gera notice e encerra os passos de deploy sem tornar a CI vermelha;
- outro status: falha.

Somente `public/` é empacotado.

Nenhum banco SQLite, arquivo Python, teste ou documento é publicado pelo Pages.

## Frontend no Pages + API externa

Defina em `public/config.js`:

```js
window.MANAPONTE_API_BASE = "https://api.exemplo.com";
```

O backend precisa autorizar a origem exata e, para cookie cross-site, operar sobre HTTPS com:

```text
MANAPONTE_SECURE_COOKIES=1
MANAPONTE_CROSS_SITE_COOKIES=1
```

## Logging

O backend escreve logs de request e erros remotos em stdout.

Não há atualmente:

- logging estruturado;
- rotação;
- persistência de auditoria;
- tracing;
- métricas;
- healthcheck profundo.

## Backup e recuperação

Não existe rotina automática de backup implementada no repositório.

Uma operação real precisa tratar separadamente:

- `cards.db` — reconstruível a partir do catálogo externo, embora custoso;
- `accounts.db` — dados permanentes de usuário;
- `listings.db` — anúncios e desejos.

Contas e anúncios não devem ser tratados como dados descartáveis.

## Produção

O servidor Python atual é adequado a desenvolvimento/protótipo.

Antes de exposição pública, a arquitetura deve colocar a aplicação atrás de HTTPS e de um servidor/proxy apropriado, além de resolver:

- persistência de logs;
- backup;
- rate limiting compartilhado;
- recuperação de senha;
- verificação de e-mail;
- moderação;
- observabilidade;
- estratégia de migrações formais;
- banco apropriado para concorrência maior.

## Falhas e degradação

- Scryfall indisponível: busca local continua.
- JSON local corrompido no `localStorage`: frontend ignora e começa vazio.
- resposta não JSON da API: frontend mostra “Resposta inesperada do servidor”.
- sessão expirada: `/api/auth/me` retorna 401 e a home volta ao estado anônimo.
- banco bloqueado: SQLite aguarda até 10 segundos antes de falhar.
- Pages não habilitado: workflow de Pages não falha por esse motivo.
