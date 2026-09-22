# Arquitetura do ManaPonte

## Mapa da documentação técnica

Este arquivo mantém a visão de alto nível. Os contratos detalhados, revisados contra o código atual, estão separados para facilitar manutenção:

- [API e HTTP](docs/API.md)
- [Modelo de dados e persistência](docs/DATA_MODEL.md)
- [Frontend](docs/FRONTEND.md)
- [Operação, configuração e deploy](docs/OPERATIONS.md)
- [Testes e contratos verificados](docs/TESTING.md)

A regra de manutenção é: comportamento estrutural implementado no código deve estar descrito aqui ou em um dos documentos acima.

## Contratos arquiteturais explícitos

1. `GET /api/cards` é local-first: consulta o SQLite, opcionalmente enriquece via Scryfall e sempre monta a resposta final novamente a partir do banco local.
2. `cards.id` é o ID local da impressão; `scryfall_id` identifica a impressão no provedor; `oracle_id` identifica a carta conceitual entre reimpressões.
3. `name` é o nome canônico e `printed_name` guarda o nome realmente impresso/traduzido quando existir.
4. O usuário de um anúncio vem da sessão, nunca do payload.
5. O idioma de uma oferta vem da impressão em `cards`; `listings.language` é mantido por compatibilidade.
6. Tokens brutos de sessão nunca são persistidos.
7. O modo estático do frontend é demonstração local, não persistência compartilhada.
8. Falha do Scryfall não deve inutilizar o catálogo local.
9. Os três bancos separados são o padrão; o arquivo único existe somente por compatibilidade.
10. Imagens não devem ser armazenadas como blobs no SQLite.

## Estado atual das imagens

O runtime ainda usa `cards.image_url` e o navegador requisita essa URL diretamente. `data/images/sample/` contém somente amostras. Os AVIFs locais já preparados fora do runtime ainda não estão conectados à aplicação; copiar esses arquivos para a VPS, isoladamente, não muda a resolução de imagens do ManaPonte.

Quando a camada local for integrada, ela deve ficar desacoplada do domínio: arquivos estáticos no filesystem/object storage, banco com chave/metadado e uma única função/camada responsável por transformar a chave em URL.

## Concorrência e estado em memória

O servidor usa `ThreadingHTTPServer`. Conexões SQLite são abertas por operação, enquanto estruturas compartilhadas em memória usam locks. O cache de busca remota tem no máximo 256 entradas, TTL de 300 segundos e deduplica chamadas idênticas em voo com `threading.Event`. O rate limiter de login também é local ao processo.

Reiniciar o processo apaga cache remoto e histórico do rate limiter; múltiplas instâncias não compartilham esses estados.

## Configuração e precedência

Para cada banco dividido, a precedência é: caminho explícito recebido pela função, variável de ambiente específica e, por último, caminho padrão em `data/`. Se somente `MANAPONTE_DB_PATH` estiver configurado, o modo legado de arquivo único é ativado.

## Migrações atuais

- v1: schemas-base;
- v2/v3: autenticação, sessões e telefone;
- v4: `desired_language` em desejos;
- v5: `printed_name` e índice correspondente no catálogo.

Sessões antigas podem ser recriadas quando incompatíveis porque são efêmeras; dados permanentes são preservados por migrações incrementais.

---
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
Catálogo (app/catalog.py) ← default_cards JSON/JSONL (gzip ou texto) ← Scryfall Bulk Data
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
- `scripts/import_allcards.py`: adaptador de rede para importar um tipo de Bulk Data escolhido, reutilizando o parser incremental.

## Modelo de dados

- `cards` (`data/cards.db`): uma linha por impressão (`scryfall_id`). `oracle_id` permite agrupar reimpressões da mesma carta; coleção, número, idioma e arte distinguem o exemplar anunciado.
- `users` e `sessions` (`data/accounts.db`): identidade, localização, celular público opcional, hash de senha, estado de verificação e sessões cujo token bruto nunca é persistido.
- `listings` e `wants` (`data/listings.db`): ofertas e cartas procuradas. Desejos podem restringir condição, idioma, modalidade e preço. O backend não recebe nem armazena imagens enviadas por usuários.
- `schema_version`: base para migrações incrementais em cada arquivo. Como SQLite não aplica chaves estrangeiras entre arquivos anexados, a API valida a existência da carta e a sessão valida a existência do usuário antes de gravar ofertas.

Índices cobrem busca por nome, coleção/idioma, `oracle_id`, localização e relações de ofertas/desejos.

## Fluxos

### Busca

1. A interface envia nome, coleção, idioma, cidade, UF, modalidade, condição, faixa de preço e ordenação.
2. A API monta somente cláusulas permitidas e usa parâmetros SQL.
3. `cards.db` identifica a impressão; a conexão de `listings.db` anexa `cards.db` e `accounts.db` para unir oferta, usuário e localização.
4. A resposta retorna URLs de imagem do Scryfall e metadados da oferta.

`GET /api/cards` sempre informa `page`, `limit`, `total` e `source`. O limite
aceito é positivo e fica restrito a 100 registros por resposta. Consultas com
três ou mais caracteres podem buscar todas as páginas do Scryfall; o cache
remoto tem no máximo 256 entradas, expira em cinco minutos e compartilha uma
consulta enquanto ela está em voo.

`GET /api/listings` usa os mesmos campos de paginação e conta o total depois
dos filtros. A ordenação por `created_at DESC, id DESC` mantém páginas
repetíveis enquanto os dados não mudam. A API também oferece ordenação por preço/idade e filtros de faixa de preço/condição. Cada anúncio devolve título, descrição, idioma e preço; a arte vem da URL oficial da impressão no catálogo. O idioma é lido da impressão em `cards`, que é a fonte de verdade; a coluna legada em `listings` é mantida apenas por compatibilidade. O campo legado `contact_url` continua no contrato por compatibilidade, mas a interface usa o perfil público do jogador como ponto de contato. `mine=1`
restringe a consulta ao usuário autenticado. Filtros de venda/troca incluem
anúncios marcados como `ambos`.

### Sincronização do catálogo

1. A CLI consulta `/bulk-data` e seleciona o objeto `default_cards` (ou o tipo solicitado pelo adaptador `import_allcards.py`).
2. O JSON é baixado temporariamente ou fornecido por `--file`.
3. O parser aceita JSONL ou array JSON, gzip ou texto simples, e lê um registro por vez. Registros digitais, incompletos, não-objeto e linhas inválidas são descartados com contagem no relatório.
4. A normalização escolhe a primeira variante disponível na ordem `normal`, `large`, `png`, `small`, `art_crop`, `border_crop`, considerando a carta e suas faces.
5. Lotes de 500 são inseridos/atualizados por `scryfall_id`.
6. Anúncios permanecem ligados ao ID local estável da impressão existente; a consistência entre arquivos é garantida pela aplicação.

### Interface pública

No servidor Python, a interface usa `index.html` como entrada,
`anuncios.html` como catálogo dedicado de ofertas e
`perfil.html?user=<id>` como página pública compartilhável do jogador e `anuncio.html?id=<id>` como detalhe compartilhável de uma oferta.
`public/app.js` coordena a tela inicial, enquanto scripts menores atendem as
páginas independentes. O seletor de impressões envia `q`, `page` e `limit`,
cancela consultas anteriores e ignora respostas que chegaram depois de uma
busca mais nova. No GitHub Pages ou com
`?static`, a página usa os JSONs versionados e guarda novas ofertas somente no
`localStorage`; esse modo não tem cadastro, sessão nem persistência
compartilhada. A renderização escapa campos de catálogo e anúncios e só cria
perfis públicos sem expor e-mail ou credenciais. O celular só aparece quando
foi informado pelo próprio usuário. O componente `card-preview.js` permite
ampliar toda arte de carta renderizada pela interface, inclusive anúncios,
desejos, matches, perfis e resultados do seletor. Se `public/config.js` definir
`MANAPONTE_API_BASE`, o mesmo frontend do Pages usa a API externa com
credenciais. O backend só libera CORS para origens configuradas por
`MANAPONTE_ALLOWED_ORIGIN`; sessões entre domínios usam
`MANAPONTE_CROSS_SITE_COOKIES=1` junto de HTTPS.

### Ofertas, desejos e matching

O corpo é limitado a 32 KiB; IDs, enumerações, tamanho de texto e preço são
validados. A API exige sessão e CSRF, ignora `user_id` enviado pelo cliente e
deriva a autoria da sessão. Edição e remoção de anúncios usam o mesmo vínculo
de proprietário. Desejos são criados por usuário e podem limitar modalidade, preço, condição e idioma. O matching cruza `wants` e `listings`, usa `oracle_id` para aceitar reimpressões da mesma carta e aplica `desired_language` quando definido. Todas as consultas usam parâmetros.

### Cadastro, perfil e sessão

1. Usuário e e-mail são normalizados e validados; a senha precisa de 12–128 caracteres e variedade de classes.
2. A senha é derivada por `scrypt` com salt aleatório individual e parâmetros incorporados no formato versionado.
3. Cadastro ou login gera token opaco e CSRF independentes. O token bruto existe somente no cookie `HttpOnly`; o banco guarda seu SHA-256.
4. `/api/auth/me` recupera identidade e CSRF. Logout e comandos mutáveis exigem o cabeçalho CSRF.
5. Cinco falhas de login por IP e identificador em 15 minutos bloqueiam novas tentativas naquela instância.
6. A migração v2 moderniza autenticação e sessões; a v3 adiciona o celular opcional; a v4 adiciona o idioma desejado sem remover dados existentes. Uma estrutura de sessão antiga pode ser revogada por ser efêmera. Bases antigas de arquivo único continuam aceitas quando um caminho explícito é fornecido.

## Segurança e produção

O protótipo implementa hashing de senha, sessão opaca, cookie `HttpOnly/SameSite`, expiração, CSRF, consultas parametrizadas, rate limiting de login e validação de URLs de contato. Antes de exposição pública, ainda são necessários:

1. HTTPS com cookie `Secure`, gestão externa de segredos e proxy reverso robusto;
2. recuperação de senha, verificação de e-mail, MFA opcional e política contra senhas vazadas;
3. logs persistentes, auditoria e trilha de moderação;
4. controles adicionais de privacidade para celular/localização, além da opção atual de deixar o celular vazio;
5. denúncias, reputação e regras contra fraude;
6. PostgreSQL, migrações formais e rate limiting compartilhado (Redis ou equivalente);
7. jobs agendados e observáveis para sincronização incremental do Scryfall;
8. manter o backend sem upload de mídia enquanto a VPS for limitada; se isso mudar, usar armazenamento de objetos externo em vez do disco da aplicação;
9. caso seja necessário, um job separado e autorizado para preparar cópias locais de imagens; o protótipo não faz coleta em massa.

## Caminho de evolução

- Fase 1: verificação de e-mail, recuperação de senha e inventário estruturado.
- Fase 2: distância geográfica opcional, mensagens e alertas.
- Fase 3: moderação, reputação, métricas e aplicativo instalável.
- Fase 4, somente se validado: pagamento/frete intermediado, com análise jurídica, fiscal e antifraude.

Manter o monólito até haver evidência de gargalo. O primeiro candidato a separação é o job de catálogo, não a API transacional.
