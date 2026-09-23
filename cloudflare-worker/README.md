# Proxy Cloudflare Worker do ManaPonte

Este Worker publica o ManaPonte em um endereço HTTPS `*.workers.dev` e encaminha as requisições para a aplicação já existente na Oracle VPS.

## Origem atual

A VPS pública está em `168.138.250.53`. Cloudflare Workers não permite `fetch()` diretamente para um endereço IP, então o Worker usa o hostname DNS automático:

```text
http://168-138-250-53.sslip.io
```

Esse hostname resolve para `168.138.250.53`; a aplicação continua hospedada somente na Oracle VPS.

## Fluxo

```text
navegador
   ↓ HTTPS
mana-ponte-proxy.<subdominio-da-conta>.workers.dev
   ↓
Cloudflare Worker
   ↓ HTTP
168-138-250-53.sslip.io
   ↓
168.138.250.53 (Oracle VPS)
   ↓
ManaPonte
```

O Worker preserva caminho, query string, método, corpo, cookies e cabeçalhos. Redirecionamentos absolutos que apontem de volta para a origem são reescritos para o hostname público do Worker.

## Deploy

Dentro deste diretório:

```bash
npx wrangler@latest login
npx wrangler@latest deploy
```

O primeiro comando autoriza a conta Cloudflare. O segundo publica o Worker e imprime a URL `workers.dev`.

Para testar depois do deploy:

```bash
curl -i https://URL-DO-WORKER/api/health
```

A API deve responder com o healthcheck do ManaPonte e o cabeçalho:

```text
X-ManaPonte-Proxy: cloudflare-worker
```

## Cookies HTTPS

Como o navegador acessa a aplicação por HTTPS no Worker, execute o backend da VPS com:

```text
MANAPONTE_SECURE_COOKIES=1
```

Não é necessário habilitar `MANAPONTE_CROSS_SITE_COOKIES` nem CORS quando frontend e API são acessados pelo mesmo Worker.

## Trocar a origem

A origem fica em `wrangler.jsonc`, na variável `MANAPONTE_ORIGIN`. Se a VPS mudar de IP, ajuste o hostname sslip.io correspondente e faça novo deploy.
