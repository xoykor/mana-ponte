# Operação e deploy

Este documento descreve produção em Cloudflare.

Para o backend Python local, consulte LEGACY_PYTHON.md.

## Endereço atual

https://mana-ponte.vsxk.workers.dev

## Serviços usados

- Cloudflare Workers
- Cloudflare Static Assets
- Cloudflare D1
- GitHub Actions
- Scryfall como fonte externa de catálogo/imagens

Não há Oracle VPS na rota de produção.

Não há R2 nem Cloudflare Images.

## Configuração Wrangler

Arquivo:

cloudflare-worker/wrangler.jsonc

Configura:

- Worker mana-ponte;
- entrypoint src/index.js;
- Static Assets em ../public;
- binding ASSETS;
- /api/* executado primeiro pelo Worker;
- binding D1 DB;
- database_name manaponte.

O database_id no Git é placeholder. O CI o substitui temporariamente pelo ID real.

## Secrets do GitHub

Obrigatórios:

- CLOUDFLARE_API_TOKEN
- CLOUDFLARE_ACCOUNT_ID

O token Cloudflare precisa conseguir:

- publicar Workers;
- listar/criar/alterar D1.

Nunca versionar esses valores.

## Workflow de produção

Arquivo:

.github/workflows/cloudflare.yml

Dispara por:

- push em main quando public/** muda;
- push quando cloudflare-worker/** muda;
- alteração do próprio workflow;
- workflow_dispatch.

Passos:

1. checkout;
2. Node 22;
3. validação dos secrets;
4. remoção de whitespace acidental do Account ID;
5. wrangler d1 list;
6. criação de manaponte quando ausente;
7. descoberta do database_id;
8. patch local do wrangler.jsonc;
9. aplicação de migrations;
10. deploy do Worker e assets.

O database_id real não é commitado.

## D1

Banco:

manaponte

Migration atual:

cloudflare-worker/migrations/0001_initial.sql

Para novas mudanças, adicionar migration numerada. Não depender de ALTER manual no painel sem registrar a mudança no repositório.

## Deploy manual

Em uma máquina autenticada com Wrangler, o fluxo equivalente é:

    cd cloudflare-worker
    npx wrangler@latest d1 list
    npx wrangler@latest d1 migrations apply manaponte --remote
    npx wrangler@latest deploy

O wrangler.jsonc precisa conter o database_id real no ambiente local ou ser ajustado antes do deploy.

## Healthcheck

    GET /api/health

Deve indicar:

- service ManaPonte;
- runtime cloudflare-workers-d1;
- image_storage none.

## Catálogo externo

Scryfall é consultado somente para busca de metadados quando necessário.

O Worker não executa bulk import completo durante deploy.

Uma indisponibilidade do Scryfall não apaga o D1 e não impede resultados já persistidos.

## Imagens

Regra operacional: não armazenar imagens.

Não provisionar:

- R2 para cartas;
- Cloudflare Images;
- banco de blobs;
- volume de filesystem;
- downloader de imagens em produção.

image_url é referência externa.

## Observabilidade

wrangler.jsonc mantém observability.enabled=true.

O código usa:

- console.log para falhas remotas recuperáveis;
- console.error para exceções da API.

Ainda não existem dashboards de negócio ou alertas versionados no repositório.

## Erros

Erro de validação:
- JSON 400.

Não autenticado:
- JSON 401.

CSRF inválido:
- JSON 403.

Conflito de cadastro:
- JSON 409.

Rate limit:
- JSON 429.

Erro de D1 detectado pelo dispatcher:
- JSON 500.

Erro de plataforma fora do contrato:
- pode chegar como texto/HTML; frontend exibe "Resposta inesperada do servidor".

## Rollback

Código:
- reverter o commit e deixar GitHub Actions publicar a versão anterior.

Schema:
- migrations D1 devem ser tratadas como mudanças persistentes; rollback de código não desfaz automaticamente schema/dados.

Mudanças destrutivas precisam de plano de migração próprio.

## Backup

Ainda não existe workflow automático de backup/export do D1.

Prioridade de backup:

1. users;
2. listings;
3. wants;
4. sessions, que são efêmeras;
5. cards, reconstruível em grande parte via Scryfall.

## GitHub Pages

.github/workflows/pages.yml continua publicando public/ quando Pages está habilitado.

Isso é secundário. A aplicação completa usa o Worker.

## Desenvolvimento local

O caminho histórico continua:

    ./scripts/dev.sh

Ele sobe Python + SQLite e não replica perfeitamente o ambiente Worker/D1.

Use-o para desenvolvimento legado e testes existentes, não como prova de comportamento de produção.
