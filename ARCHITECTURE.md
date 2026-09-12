# Arquitetura do ManaPonte

## Objetivo e recorte

O ManaPonte resolve descoberta e contato: “quem perto de mim tem esta impressão e aceita vender ou trocar?”. O catálogo de Magic é referência compartilhada; usuários não digitam nomes livres para representar uma carta. Pagamento, logística e garantia da transação ficam fora do MVP.

## Visão de componentes

```text
Navegador
  ├─ busca, filtros e formulário (public/)
  └─ HTTP/JSON
          ↓
Servidor/API (app/server.py)
  ├─ cadastro, sessões e CSRF ─────→ data/accounts.db
  ├─ catálogo ─────────────────────→ data/cards.db
  ├─ ofertas e desejos ─────────────→ data/listings.db
  │                                  (cards.db e accounts.db anexados nas consultas)
  ├─ arquivos estáticos
  └─ rate limiting de login em memória
          ↑
Catálogo (app/catalog.py) ← default_cards JSON ← Scryfall Bulk Data
          ↑
Seed offline (app/seed.py)
```

Este é um monólito modular: uma unidade de implantação, mas fronteiras explícitas. Isso reduz custo operacional e mantém a migração futura possível.

## Limites dos módulos

- `db.py`: resolve caminhos, abre conexões, ativa chaves estrangeiras, anexa os bancos necessários e aplica os schemas versionados. Não contém regras HTTP.
- `auth.py`: normaliza identidades, deriva senhas com `scrypt` e administra sessões opacas. Não conhece HTTP.
- `catalog.py`: converte objetos Scryfall em impressões locais e realiza upsert em lotes. Não conhece anúncios.
- `seed.py`: fixture determinístico para demonstração e testes; não acessa rede.
- `server.py`: traduz HTTP em consultas/comandos, limita entradas, serve a interface e pode enriquecer buscas do catálogo sob demanda via Scryfall.
- `public/`: apresentação e interação. Não contém dados autoritativos.
- `scripts/import_scryfall.py`: adaptador de rede e CLI para Bulk Data.

## Modelo de dados

- `cards` (`data/cards.db`): uma linha por impressão (`scryfall_id`). `oracle_id` permite agrupar reimpressões da mesma carta; coleção, número, idioma e arte distinguem o exemplar anunciado.
- `users` e `sessions` (`data/accounts.db`): identidade, localização, hash de senha, estado de verificação e sessões cujo token bruto nunca é persistido.
- `listings` e `wants` (`data/listings.db`): o que um usuário possui ou procura, com condição, idioma, modalidade e preço opcional.
- `schema_version`: base para migrações incrementais em cada arquivo. Como SQLite não aplica chaves estrangeiras entre arquivos anexados, a API valida a existência da carta e a sessão valida a existência do usuário antes de gravar ofertas.

Índices cobrem busca por nome, coleção/idioma, `oracle_id`, localização e relações de ofertas/desejos.

## Fluxos

### Busca

1. A interface envia nome, coleção, UF e modalidade.
2. A API monta somente cláusulas permitidas e usa parâmetros SQL.
3. `cards.db` identifica a impressão; a conexão de `listings.db` anexa `cards.db` e `accounts.db` para unir oferta, usuário e localização.
4. A resposta retorna URLs de imagem do Scryfall e metadados da oferta.

### Sincronização do catálogo

1. A CLI consulta `/bulk-data` e seleciona o objeto `default_cards`.
2. O JSON é baixado temporariamente ou fornecido por `--file`.
3. Registros digitais são descartados; cartas dupla-face usam a imagem da primeira face disponível.
4. Lotes de 500 são inseridos/atualizados por `scryfall_id`.
5. Anúncios permanecem ligados ao ID local estável da impressão existente; a consistência entre arquivos é garantida pela aplicação.

### Criação de oferta

O corpo é limitado a 32 KiB; IDs, enumerações, tamanho de texto e preço são validados. A API exige sessão e CSRF, ignora `user_id` enviado pelo cliente e deriva a autoria da sessão. Todas as consultas usam parâmetros.

### Cadastro e sessão

1. Usuário e e-mail são normalizados e validados; a senha precisa de 12–128 caracteres e variedade de classes.
2. A senha é derivada por `scrypt` com salt aleatório individual e parâmetros incorporados no formato versionado.
3. Cadastro ou login gera token opaco e CSRF independentes. O token bruto existe somente no cookie `HttpOnly`; o banco guarda seu SHA-256.
4. `/api/auth/me` recupera identidade e CSRF. Logout e comandos mutáveis exigem o cabeçalho CSRF.
5. Cinco falhas de login por IP e identificador em 15 minutos bloqueiam novas tentativas naquela instância.
6. A migração v2 adiciona campos sem remover contas existentes; uma estrutura de sessão antiga é revogada por ser efêmera. Bases antigas de arquivo único continuam aceitas quando um caminho explícito é fornecido.

## Segurança e produção

O protótipo implementa hashing de senha, sessão opaca, cookie `HttpOnly/SameSite`, expiração, CSRF, consultas parametrizadas e rate limiting de login. Antes de exposição pública, ainda são necessários:

1. HTTPS com cookie `Secure`, gestão externa de segredos e proxy reverso robusto;
2. recuperação de senha, verificação de e-mail, MFA opcional e política contra senhas vazadas;
3. autorização de edição/remoção por proprietário, logs e trilha de moderação;
4. privacidade de contatos e localização menos granular por padrão;
5. denúncias, reputação e regras contra fraude;
6. PostgreSQL, migrações formais e rate limiting compartilhado (Redis ou equivalente);
7. jobs agendados e observáveis para sincronização incremental do Scryfall;
8. armazenamento de fotos do exemplar do usuário separado da imagem oficial da carta.

## Caminho de evolução

- Fase 1: verificação de e-mail, recuperação de senha, perfis, inventário e lista de desejos reais.
- Fase 2: matching por `oracle_id`, distância geográfica opcional, mensagens e alertas.
- Fase 3: moderação, reputação, métricas e aplicativo instalável.
- Fase 4, somente se validado: pagamento/frete intermediado, com análise jurídica, fiscal e antifraude.

Manter o monólito até haver evidência de gargalo. O primeiro candidato a separação é o job de catálogo, não a API transacional.
