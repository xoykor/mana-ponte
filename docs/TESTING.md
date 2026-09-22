# Testes e contratos verificados

A suíte usa `unittest` e não depende de rede externa.

Comando:

```bash
python3 -m unittest discover -s tests -v
```

## CI

Workflow: `.github/workflows/tests.yml`.

Dispara em:

- push para `main`;
- pull request para `main`;
- `workflow_dispatch`.

Etapas:

1. checkout com histórico completo;
2. Python 3.11;
3. `git diff --check origin/main...HEAD`;
4. `node --check` dos JavaScripts;
5. suíte offline Python.

A CI não executa browser E2E atualmente.

## `tests/test_api.py`

Cobre servidor HTTP real em porta temporária, incluindo:

- pesquisa por `printed_name`;
- cadastro e duplicidade;
- login/logout;
- CSRF;
- rate limiting;
- sessão expirada;
- criação de anúncio;
- ownership em edição/remoção;
- perfil público sem vazamento de dados privados;
- navegação de matches para usuário;
- idioma derivado da impressão;
- semântica de `ambos`;
- CRUD de desejos;
- condição mínima no matching;
- preflight CORS;
- rotas públicas;
- fallback/enriquecimento remoto persistido localmente;
- filtros e ordenação;
- matching por idioma;
- estatísticas do perfil público.

## `tests/test_auth.py`

Cobre:

- normalização;
- validação de username/e-mail/senha;
- salt aleatório do scrypt;
- verificação de senha;
- persistência apenas do hash do token;
- CSRF;
- expiração;
- revogação.

## `tests/test_catalog.py`

Cobre:

- normalização de carta física;
- carta dupla-face;
- descarte de digital;
- `printed_name`;
- upsert idempotente;
- preservação do id local;
- paginação remota do Scryfall;
- `include_multilingual=true`.

## `tests/test_import_fixtures.py`

Cobre:

- array JSON;
- JSONL;
- gzip;
- parser incremental;
- proibição implícita de leitura integral do JSONL;
- linhas inválidas;
- relatório de ignoradas/inválidas;
- preferência de variantes de imagem.

## `tests/test_db.py`

Cobre:

- schema e seed;
- idempotência;
- migração de usuários;
- migração de `printed_name`;
- migração de `desired_language`;
- preservação de dados.

## `tests/test_integration_contracts.py`

Cobre contratos que atravessam bancos:

- contato e idioma de anúncio;
- paginação em modo dividido;
- wants/matches entre arquivos;
- perfil público cruzando contas, catálogo e anúncios;
- limite de `contact_url`.

## `tests/test_listings_pagination.py`

Cobre total e limites de paginação.

## `tests/test_remote_cache.py`

Cobre:

- limite de capacidade;
- evicção;
- cache hit;
- deduplicação concorrente;
- liberação de waiters após falha;
- expiração;
- timeout de waiter;
- validação de `contact_url`.

## `tests/test_split_db.py`

Cobre seed e JOIN cross-database.

## Validação visual histórica

`e5-screenshots/` contém evidências de uma rodada anterior de validação responsiva e de interação.

`scripts/e5_cdp_driver.js` é um driver CDP auxiliar, mas não está na CI atual porque depende de ambiente/browser específico.

## O que não está coberto automaticamente

A suíte atual não garante:

- disponibilidade real do Scryfall;
- comportamento de produção sob carga;
- integridade após queda abrupta de energia;
- Nginx/Caddy/reverse proxy;
- HTTPS real;
- compatibilidade visual em todos os navegadores;
- storage local de AVIF, pois ainda não está integrado;
- backup/restauração;
- performance com o catálogo completo em escala de produção.

Esses itens devem ser tratados como riscos operacionais separados, não como propriedades já verificadas.
