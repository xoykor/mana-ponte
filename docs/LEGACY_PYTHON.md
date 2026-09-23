# Backend Python legado/local

O diretório app/ representa a arquitetura original do ManaPonte.

Ele continua versionado por três motivos:

- desenvolvimento local;
- testes históricos;
- ferramentas de importação/fixtures.

Ele NÃO é a implantação de produção atual.

## Runtime

Entrada:

python3 -m app.server

Atalho:

./scripts/dev.sh

Servidor:

ThreadingHTTPServer da biblioteca padrão.

## Persistência

Modo padrão histórico:

- data/cards.db
- data/accounts.db
- data/listings.db

Existe modo legado adicional de arquivo único.

## Diferenças para produção

| Tema | Python local | Produção Cloudflare |
| --- | --- | --- |
| Runtime | Python | Worker JavaScript |
| Banco | SQLite em arquivos | D1 |
| Frontend | servido pelo Python | Static Assets |
| Hash de senha | scrypt | PBKDF2-SHA256 |
| Rate limit | memória do processo | D1 |
| Catálogo | SQLite + Scryfall | D1 + Scryfall |
| Deploy | processo local | GitHub Actions/Wrangler |
| Oracle VPS | historicamente possível | não usada |

## Importadores

scripts/import_scryfall.py e scripts/import_allcards.py pertencem ao ecossistema local/legado.

Eles podem popular SQLite em massa.

A produção D1 não executa esses importadores no deploy.

## Testes

A maior parte de tests/ testa este runtime.

Isso é útil, mas não deve ser confundido com teste do Worker.

## Por que não remover agora

app/ ainda contém lógica consolidada, fixtures e contratos que ajudam desenvolvimento e comparação durante a migração.

Uma remoção futura deve acontecer somente depois de:

- cobertura equivalente do Worker;
- ferramentas D1 maduras;
- migração de toda utilidade ainda necessária.

## Imagens

Mesmo o runtime legado armazena somente URLs de imagem no banco.

Qualquer diretório de amostras não faz parte da produção.
