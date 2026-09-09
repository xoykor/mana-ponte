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
  ├─ cadastro, sessões e CSRF ─────→ SQLite (users, sessions)
  ├─ catálogo e ofertas ───────────→ SQLite (cards, listings, wants)
  ├─ arquivos estáticos
  └─ rate limiting de login em memória
          ↑
Catálogo (app/catalog.py) ← default_cards JSON ← Scryfall Bulk Data
          ↑
Seed offline (app/seed.py)
```

Este é um monólito modular: uma unidade de implantação, mas fronteiras explícitas. Isso reduz custo operacional e mantém a migração futura possível.

## Limites dos módulos

- `db.py`: resolve caminhos, abre conexões, ativa chaves estrangeiras e aplica o schema versionado. Não contém regras HTTP.
- `auth.py`: normaliza identidades, deriva senhas com `scrypt` e administra sessões opacas. Não conhece HTTP.
- `catalog.py`: converte objetos Scryfall em impressões locais e realiza upsert em lotes. Não conhece anúncios.
- `seed.py`: fixture determinístico para demonstração e testes; não acessa rede.
- `server.py`: traduz HTTP em consultas/comandos, limita entradas e serve a interface. Não baixa catálogo.
- `public/`: apresentação e interação. Não contém dados autoritativos.
- `scripts/import_scryfall.py`: adaptador de rede e CLI para Bulk Data.

## Modelo de dados

- `cards`: uma linha por impressão (`scryfall_id`). `oracle_id` permite agrupar reimpressões da mesma carta; coleção, número, idioma e arte distinguem o exemplar anunciado.
- `users`: identidade, localização, hash de senha e estado de verificação do jogador.
- `sessions`: somente o hash SHA-256 do token, vínculo com usuário, CSRF e expiração.
- `listings`: o que um usuário possui, com condição, idioma, modalidade e preço opcional.
- `wants`: o que um usuário procura e seus limites. No MVP, `/matches` consulta ofertas por impressão; a evolução cruza `wants` e `listings` automaticamente.
- `schema_version`: base para migrações incrementais.

Índices cobrem busca por nome, coleção/idioma, `oracle_id`, localização e relações de ofertas/desejos.

## Fluxos

### Busca

1. A interface envia nome, coleção, UF e modalidade.
2. A API monta somente cláusulas permitidas e usa parâmetros SQL.
3. `cards` identifica a impressão e `listings` une oferta, usuário e localização.
4. A resposta retorna URLs de imagem do Scryfall e metadados da oferta.

### Sincronização do catálogo

1. A CLI consulta `/bulk-data` e seleciona o objeto `default_cards`.
2. O JSON é baixado temporariamente ou fornecido por `--file`.
3. Registros digitais são descartados; cartas dupla-face usam a imagem da primeira face disponível.
4. Lotes de 500 são inseridos/atualizados por `scryfall_id`.
5. Anúncios permanecem ligados ao ID local estável da impressão existente.

### Criação de oferta

O corpo é limitado a 32 KiB; IDs, enumerações, tamanho de texto e preço são validados. A API exige sessão e CSRF, ignora `user_id` enviado pelo cliente e deriva a autoria da sessão. Todas as consultas usam parâmetros.

### Cadastro e sessão

1. Usuário e e-mail são normalizados e validados; a senha precisa de 12–128 caracteres e variedade de classes.
2. A senha é derivada por `scrypt` com salt aleatório individual e parâmetros incorporados no formato versionado.
3. Cadastro ou login gera token opaco e CSRF independentes. O token bruto existe somente no cookie `HttpOnly`; o banco guarda seu SHA-256.
4. `/api/auth/me` recupera identidade e CSRF. Logout e comandos mutáveis exigem o cabeçalho CSRF.
5. Cinco falhas de login por IP e identificador em 15 minutos bloqueiam novas tentativas naquela instância.
6. A migração v2 adiciona campos sem remover contas existentes; uma estrutura de sessão antiga é revogada por ser efêmera.

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
