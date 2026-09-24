# Operação e deploy

## Endereço

https://mana-ponte.vsxk.workers.dev

## Serviços

- Cloudflare Workers;
- Cloudflare Static Assets;
- Cloudflare D1;
- GitHub Actions;
- Scryfall.

## Wrangler

`cloudflare-worker/wrangler.jsonc` configura Worker, assets e D1.

O `database_id` versionado é um placeholder. O CI o substitui somente no workspace do job.

## Secrets

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

## Deploy automático

`.github/workflows/cloudflare.yml`:

1. valida secrets;
2. lista/cria D1;
3. descobre `database_id`;
4. ajusta a configuração temporariamente;
5. aplica migrations;
6. publica Worker + assets.

## D1

Migration inicial:

`cloudflare-worker/migrations/0001_initial.sql`

Mudanças futuras de schema devem usar novas migrations numeradas.

## Desenvolvimento local

```bash
cd cloudflare-worker
npx wrangler@latest d1 migrations apply manaponte --local
npx wrangler@latest dev
```

## Healthcheck

`GET /api/health`

## Catálogo

O deploy não importa catálogo em massa.

O Scryfall é consultado sob demanda.

## Imagens

Não existe storage próprio de imagens.

`image_url` é referência externa.

## Observabilidade

`observability.enabled=true`.

## Rollback

Código: reverter commit e redeployar.

Schema: rollback de código não desfaz migrations nem dados automaticamente.

## Backup

Ainda não existe backup automático do D1.

