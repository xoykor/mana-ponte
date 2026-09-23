# ManaPonte no Cloudflare

Este diretório contém o backend e a configuração da implantação principal.

## Arquitetura

    Cloudflare Worker
       |-- Static Assets -> ../public
       |-- API -> src/
       +-- D1 -> manaponte

Fonte externa:

Scryfall, para metadados e URLs de imagens.

Não existe proxy para Oracle.

## Arquivos

- src/index.js — roteador e Static Assets.
- src/lib.js — sessão, crypto, JSON e validações.
- src/auth.js — autenticação/perfil.
- src/catalog.js — catálogo/Scryfall.
- src/listings.js — anúncios.
- src/wants.js — desejos, matching e perfis.
- migrations/ — schema D1.
- wrangler.jsonc — Worker, assets e binding DB.

## Imagens

Nenhuma imagem é armazenada.

D1 guarda somente image_url.

Não usar R2 ou Cloudflare Images para cartas na arquitetura atual.

## D1

Binding:

DB

Nome:

manaponte

O database_id no wrangler.jsonc do Git é placeholder.

O GitHub Actions consulta o ID real e altera a cópia do arquivo somente durante o job.

## Deploy automático

Workflow:

../.github/workflows/cloudflare.yml

Secrets:

- CLOUDFLARE_API_TOKEN
- CLOUDFLARE_ACCOUNT_ID

O workflow cria o D1 quando necessário, aplica migrations e executa wrangler deploy.

## Deploy manual

Com Wrangler autenticado:

    npx wrangler@latest d1 list
    npx wrangler@latest d1 migrations apply manaponte --remote
    npx wrangler@latest deploy

Antes do deploy manual, o binding precisa apontar para o database_id real.

## URL atual

https://mana-ponte.vsxk.workers.dev

## Health

GET /api/health

Resposta identifica runtime cloudflare-workers-d1 e image_storage none.

## Catálogo

Busca:

1. consulta D1;
2. quando q possui 3+ caracteres e os resultados locais não completam o limit, consulta Scryfall;
3. persiste metadados encontrados;
4. relê o resultado do D1.

Máximo remoto por chamada: 100 cartas.

## Autenticação

Produção usa PBKDF2-SHA256 com 100.000 iterações para novos hashes.

Sessões:

- token aleatório;
- apenas SHA-256 persistido;
- 7 dias;
- cookie HttpOnly/Secure/SameSite=Lax;
- CSRF separado.

## Observação

app/ não é chamado por este Worker. O backend Python existe apenas como runtime local/legado.
