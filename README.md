# ManaPonte

ManaPonte é uma vitrine comunitária brasileira para jogadores de Magic: The Gathering encontrarem, anunciarem, venderem e trocarem cartas diretamente entre si. O projeto não intermedeia pagamento, frete ou custódia no MVP.

## Produção atual

A implantação principal não usa Oracle VPS nem servidor Python.

Fluxo de produção:

    Navegador
       |
       v
    Cloudflare Workers
       |-- Static Assets -> public/
       |-- /api/* -> Worker JavaScript
       |
       +-- D1 -> contas, sessões, cartas, anúncios e desejos
       |
       +-- Scryfall -> metadados e URLs externas de imagens

URL atual:

https://mana-ponte.vsxk.workers.dev

As imagens das cartas NÃO são armazenadas pelo ManaPonte. O banco guarda somente image_url apontando para o Scryfall. Não existe R2, Cloudflare Images ou blob de imagem no D1.

## Componentes

- public/: frontend HTML, CSS e JavaScript sem framework.
- cloudflare-worker/src/: API de produção.
- cloudflare-worker/migrations/: schema D1.
- cloudflare-worker/wrangler.jsonc: Static Assets, Worker e binding DB.
- .github/workflows/cloudflare.yml: provisionamento D1, migrations e deploy.
- app/: backend Python/SQLite legado, mantido para desenvolvimento local e compatibilidade.
- tests/: suíte histórica do backend Python e contratos locais.

## Persistência

Produção usa um banco Cloudflare D1 chamado manaponte.

Principais tabelas:

- cards: metadados de impressões de cartas.
- users: contas e dados públicos de perfil.
- sessions: sessões opacas.
- listings: anúncios.
- wants: desejos.
- login_attempts: rate limiting persistido de login.

O catálogo não é importado em massa no deploy. Uma busca com pelo menos três caracteres pode consultar o Scryfall e persistir até 100 impressões encontradas no D1. Isso mantém o banco pequeno e evita uma carga inicial de centenas de milhares de linhas.

## Imagens

Regra arquitetural: zero armazenamento de imagens.

O ManaPonte armazena somente a URL externa da imagem. O navegador busca a mídia diretamente no provedor indicado por image_url. O repositório não deve introduzir R2, Cloudflare Images, blobs no D1 ou coleção local de imagens sem uma decisão arquitetural explícita futura.

## Autenticação

A produção usa:

- PBKDF2-SHA256;
- 100.000 iterações para novos hashes;
- salt aleatório por senha;
- token de sessão aleatório;
- somente SHA-256 do token persistido;
- cookie mp_session com HttpOnly, Secure e SameSite=Lax;
- sessão de 7 dias;
- CSRF separado para operações mutáveis;
- bloqueio após 5 falhas de login em uma janela de 15 minutos por IP + identificador.

## API

Rotas principais:

| Método | Rota | Função |
| --- | --- | --- |
| GET | /api/health | saúde e runtime |
| POST | /api/auth/register | criar conta |
| POST | /api/auth/login | autenticar |
| GET | /api/auth/me | sessão atual |
| POST | /api/auth/logout | encerrar sessão |
| PATCH | /api/profile | atualizar perfil |
| GET | /api/cards | catálogo |
| GET | /api/sets | coleções já conhecidas pelo D1 |
| GET | /api/listings | buscar anúncios |
| GET | /api/listings/{id} | detalhe do anúncio |
| POST | /api/listings | criar anúncio |
| PATCH | /api/listings/{id} | editar anúncio |
| DELETE | /api/listings/{id} | excluir anúncio |
| GET | /api/wants | desejos do usuário |
| POST | /api/wants | criar/atualizar desejo |
| DELETE | /api/wants/{id} | remover desejo |
| GET | /api/matches | matches dos desejos |
| GET | /api/matches?card_id={id} | ofertas equivalentes |
| GET | /api/users/{id} | perfil público |

Contrato completo: docs/API.md.

## Deploy

O deploy é automático em push para main quando public/, cloudflare-worker/ ou o workflow de Cloudflare mudam.

Secrets obrigatórios no GitHub:

- CLOUDFLARE_API_TOKEN
- CLOUDFLARE_ACCOUNT_ID

O workflow:

1. valida as credenciais;
2. procura o D1 manaponte;
3. cria o banco se ainda não existir;
4. injeta o database_id no wrangler.jsonc apenas no workspace do CI;
5. aplica migrations remotas;
6. publica Worker + Static Assets.

Não há dependência da Oracle.

## Desenvolvimento local

O backend Python antigo continua disponível para desenvolvimento e testes históricos:

    ./scripts/dev.sh

Ele usa SQLite local e não representa a arquitetura de produção atual. Consulte docs/LEGACY_PYTHON.md.

## Documentação

- ARCHITECTURE.md — visão canônica da arquitetura.
- docs/CODE_GUIDE.md — guia de leitura para quem está começando a programar.
- docs/API.md — contrato HTTP do Worker.
- docs/DATA_MODEL.md — D1 e modelo de dados.
- docs/FRONTEND.md — frontend e Static Assets.
- docs/OPERATIONS.md — CI/CD, deploy e operação.
- docs/SECURITY.md — autenticação e fronteiras de segurança.
- docs/TESTING.md — cobertura atual e lacunas.
- docs/LEGACY_PYTHON.md — backend Python/SQLite legado.
- cloudflare-worker/README.md — detalhes do runtime Cloudflare.

## Limitações atuais

Não existem ainda recuperação de senha, verificação real de e-mail, MFA, chat, reputação, moderação completa, pagamentos ou frete. A suíte automatizada ainda cobre principalmente o backend Python legado; testes específicos de Worker/D1 devem ser ampliados.

## Licença

O código original do ManaPonte usa a ManaPonte Proprietary Source-Available License. Consulte LICENSE e THIRD_PARTY_NOTICES.md.
