# Testes e contratos

A suíte atual possui duas realidades: código de produção Cloudflare e backend Python legado.

## CI atual

Workflow:

.github/workflows/tests.yml

Executa:

- git diff --check;
- node --check em JavaScript do frontend;
- unittest Python.

## Limitação importante

A suíte Python foi criada antes da migração para Workers/D1.

Ela continua útil para regras históricas e regressões do backend local, mas não valida diretamente:

- cloudflare-worker/src/*.js;
- comportamento real de D1;
- PBKDF2 Web Crypto do Worker;
- binding ASSETS;
- wrangler;
- migrations remotas;
- limites/runtime Cloudflare.

Portanto, CI verde não significa cobertura completa da produção.

## Testes Python existentes

Cobrem, no runtime legado:

- autenticação;
- sessões;
- CSRF;
- rate limiting;
- catálogo;
- Scryfall;
- listings;
- wants;
- matches;
- perfis;
- migrações SQLite;
- importadores;
- cache remoto;
- bancos divididos.

Eles devem permanecer enquanto app/ continuar no repositório.

## JavaScript frontend

A CI executa node --check para scripts de public/.

Isso detecta erro de sintaxe, não comportamento.

## Worker

No estado atual, o Worker ainda precisa de uma suíte dedicada.

Cobertura recomendada futura:

1. testes unitários de lib.js;
2. autenticação com mock D1;
3. roteamento;
4. CRUD de listings;
5. wants/matches;
6. catalog fallback;
7. migration em D1 local;
8. integração Wrangler/Miniflare;
9. browser E2E contra ambiente de preview.

## Produção

Não manter smoke tests que criem contas a cada deploy sem necessidade.

Testes contra produção devem ser explícitos, de baixa frequência e com limpeza controlada.

## Contratos críticos a preservar

- nenhuma imagem armazenada;
- user_id sempre derivado da sessão;
- token bruto nunca persistido;
- CSRF em mutações autenticadas;
- cards.id local estável;
- oracle_id usado para equivalência;
- falha do Scryfall não destrói catálogo local;
- rotas API retornam JSON para erros capturados.

## Validação manual mínima após mudanças críticas

- GET /api/health;
- cadastro;
- login;
- logout;
- busca de carta;
- criar anúncio;
- editar/excluir anúncio;
- criar desejo;
- visualizar perfil;
- matching.

## O que ainda não é garantido

- comportamento sob carga;
- restauração de D1;
- disponibilidade do Scryfall;
- compatibilidade visual ampla;
- limites reais do plano Cloudflare ao longo do tempo;
- observabilidade/alertas;
- segurança ofensiva.
