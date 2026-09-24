# ManaPonte

ManaPonte é uma vitrine comunitária brasileira para jogadores de Magic: The Gathering encontrarem, anunciarem, venderem e trocarem cartas diretamente entre si.

## Arquitetura

```text
Navegador
   |
   +-- HTML/CSS/JS ------> Cloudflare Static Assets
   |
   +-- /api/* -----------> Cloudflare Worker
                              |
                              +-- Cloudflare D1
                              |
                              +-- Scryfall
```

Produção:

https://mana-ponte.vsxk.workers.dev

## Componentes

- `public/` — frontend HTML, CSS e JavaScript sem framework.
- `cloudflare-worker/src/` — API.
- `cloudflare-worker/migrations/` — migrations do D1.
- `cloudflare-worker/wrangler.jsonc` — configuração do Worker, Static Assets e D1.
- `.github/workflows/cloudflare.yml` — deploy de produção.
- `.github/workflows/tests.yml` — validação de sintaxe do JavaScript.

## Persistência

Todos os dados persistentes da aplicação ficam no Cloudflare D1 `manaponte`.

Tabelas principais:

- `cards` — metadados das impressões;
- `users` — contas;
- `sessions` — sessões;
- `listings` — anúncios;
- `wants` — desejos;
- `login_attempts` — controle de tentativas de login.

O catálogo cresce sob demanda. Quando uma busca local não possui resultados suficientes, o Worker pode consultar o Scryfall e persistir os metadados encontrados.

## Imagens

O ManaPonte não armazena imagens de cartas.

`cards.image_url` guarda somente uma URL externa. Não há R2, Cloudflare Images, blobs de imagem nem coleção local de imagens no runtime.

## Autenticação

- PBKDF2-SHA256;
- 100.000 iterações para novos hashes;
- salt aleatório;
- somente o hash do token de sessão é persistido;
- cookie `mp_session` com `HttpOnly`, `Secure` e `SameSite=Lax`;
- sessão de 7 dias;
- CSRF em operações mutáveis;
- rate limiting de login persistido no D1.

## Deploy

O GitHub Actions publica automaticamente alterações relevantes em `main`.

Secrets necessários:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

Fluxo:

1. localizar ou criar o D1 `manaponte`;
2. descobrir seu `database_id`;
3. aplicar migrations;
4. publicar Worker + Static Assets.

## Documentação

- `ARCHITECTURE.md` — arquitetura completa.
- `docs/CODE_GUIDE.md` — guia didático de leitura do código.
- `docs/API.md` — contrato HTTP.
- `docs/DATA_MODEL.md` — modelo D1.
- `docs/FRONTEND.md` — frontend.
- `docs/OPERATIONS.md` — deploy e operação.
- `docs/SECURITY.md` — segurança.
- `docs/TESTING.md` — validação atual e lacunas.
- `cloudflare-worker/README.md` — detalhes do Worker.

## Limitações atuais

Ainda não existem recuperação de senha, verificação real de e-mail, MFA, pagamentos, frete, reputação ou moderação completa.

## Licença

Consulte `LICENSE` e `THIRD_PARTY_NOTICES.md`.
