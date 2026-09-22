# ManaPonte

ManaPonte é uma vitrine comunitária brasileira para jogadores de **Magic: The Gathering** encontrarem quem possui — ou procura — uma impressão específica. O projeto combina catálogo, perfis, anúncios, desejos e matching, mantendo a negociação diretamente entre jogadores e sem intermediar pagamentos no MVP.

## Estado do projeto

- frontend estático preparado para GitHub Pages;
- modo de demonstração com JSON e `localStorage` quando não há API;
- backend opcional para cadastro, sessão, perfis, anúncios, desejos e matches;
- catálogo baseado em impressões reais e integração com dados/imagens do Scryfall;
- busca com filtros, autocomplete e páginas próprias para perfil e anúncio;
- arquitetura preparada para separar frontend estático e API hospedada externamente.

> O repositório é **source-available**, não open source. Consulte a seção de licença antes de reutilizar ou implantar o código.

## Frontend e GitHub Pages

URL prevista quando Pages estiver habilitado:

**https://xoykor.github.io/mana-ponte/**

O frontend em `public/` está pronto para GitHub Pages. No estado atual do repositório, o próprio GitHub informou que o site Pages ainda não foi habilitado; por isso o workflow detecta essa situação e encerra sem tratar a ausência de Pages como falha. Para publicar, habilite **Settings → Pages → Build and deployment → Source: GitHub Actions** e execute novamente o workflow `Publicar no GitHub Pages`.

Sem uma API configurada, a página funciona como demonstração com JSON e `localStorage`. Com `window.MANAPONTE_API_BASE` definido em `public/config.js`, cadastro, sessão, perfil, anúncios, desejos e matches passam a usar o backend real.

A interface possui páginas próprias para busca, perfil e anúncio: `anuncios.html`, `perfil.html?user=<id>` e `anuncio.html?id=<id>`. A busca aceita idioma, condição, faixa de preço e ordenação, mantém filtros na URL e oferece autocomplete de nomes. A página individual usa a imagem oficial da impressão no Scryfall, evitando armazenamento de mídia na VPS. O celular é opcional e, quando informado, habilita telefone e WhatsApp no perfil/anúncio. Desejos podem exigir um idioma específico ou aceitar qualquer idioma, e o matching respeita essa escolha. Qualquer imagem de carta marcada pela interface pode ser ampliada.

## Executar

Requer somente Python 3.11 ou superior; não há pacotes para instalar.

```bash
cd /home/x/Documentos/Estudo/Projetinho
./scripts/dev.sh
```

Acesse `http://127.0.0.1:8000`. O script garante de forma idempotente os dados demonstrativos com 12 impressões reais, 4 perfis e 6 anúncios, sem apagar um catálogo já importado. O estado local fica em três arquivos: `data/cards.db`, `data/accounts.db` e `data/listings.db`.

Se a porta estiver ocupada: `env MANAPONTE_PORT=8001 ./scripts/dev.sh`.

Conta local de desenvolvimento: `danton` / `ManaPonte!2026`. Essa credencial é exclusivamente um fixture público; nunca a reutilize em produção.

Testes offline (os testes HTTP usam bancos temporários e, quando executados fora
do sandbox, uma porta local efêmera):

```bash
python3 -m unittest discover -s tests -v
```

## Catálogo Scryfall

O seed é pequeno para o protótipo. Para carregar o catálogo completo de impressões em papel:

```bash
python3 scripts/import_scryfall.py --download
```

Ou, se o arquivo `default_cards` já foi baixado:

```bash
python3 scripts/import_scryfall.py --file /caminho/default-cards.json
```

O importador descobre o `jsonl_download_uri` atual no endpoint Bulk Data e usa
`download_uri` como fallback para metadados antigos. Ele identifica o cliente
por User-Agent, aceita JSONL ou array JSON, comprimido com gzip ou em texto
simples, e decodifica os registros incrementalmente. Cartas exclusivamente
digitais e entradas inválidas são ignoradas; o relatório final informa
`importadas`, `ignoradas` e `invalidas`. O upsert acontece em lotes de 500 por
`scryfall_id`, preservando o ID local usado pelos anúncios. O protótipo
armazena URLs das imagens oficiais do catálogo, não cópias delas. O uso público/comercial deve respeitar
as políticas de dados e imagens do Scryfall e da Wizards of the Coast.

Para importar outro tipo de Bulk Data, como `all_cards`, use o adaptador
opcional:

```bash
python3 scripts/import_allcards.py --type all_cards
```

Quando uma busca da API tem três ou mais caracteres, o ManaPonte também consulta o endpoint de busca do Scryfall, percorre todas as páginas retornadas e grava as impressões encontradas em `data/cards.db`. Para operar somente com o catálogo local, use `MANAPONTE_REMOTE_SEARCH=0`.

## API

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/api/health` | Saúde do serviço |
| POST | `/api/auth/register` | Valida dados, cria conta e sessão |
| POST | `/api/auth/login` | Autentica e cria sessão |
| GET | `/api/auth/me` | Retorna usuário e token CSRF da sessão |
| POST | `/api/auth/logout` | Revoga a sessão; exige CSRF |
| GET | `/api/cards?q=&set=&lang=&page=&limit=` | Busca paginada no catálogo; retorna `cards`, `page`, `limit`, `total` e `source` |
| GET | `/api/sets` | Coleções e contagem de impressões |
| GET | `/api/listings?card=&card_id=&set=&lang=&city=&state=&mode=&condition=&min_price=&max_price=&sort=&mine=&page=&limit=` | Ofertas filtradas/paginadas; suporta faixa de preço, condição e ordenação (`recent`, `oldest`, `price_asc`, `price_desc`) |
| GET | `/api/listings/{id}` | Detalhe público do anúncio, impressão e vendedor |
| POST | `/api/listings` | Cria uma oferta validada |
| PATCH | `/api/listings/{id}` | Edita um anúncio do próprio usuário; exige sessão e CSRF |
| DELETE | `/api/listings/{id}` | Remove um anúncio do próprio usuário; exige sessão e CSRF |
| PATCH | `/api/profile` | Atualiza nome de exibição, celular opcional, cidade e UF do usuário autenticado |
| GET | `/api/wants?page=&limit=` | Lista os desejos do usuário autenticado |
| POST | `/api/wants` | Cria ou atualiza um desejo, incluindo `desired_language` opcional; exige sessão e CSRF |
| DELETE | `/api/wants/{id}` | Remove um desejo do próprio usuário; exige sessão e CSRF |
| GET | `/api/matches?card_id=` | Busca ofertas da impressão ou de reimpressões com o mesmo `oracle_id` |
| GET | `/api/matches` | Cruza os desejos do usuário autenticado com ofertas compatíveis e identifica o outro jogador |
| GET | `/api/users/{id}` | Perfil público com data de entrada, contato opcional, contagens, anúncios ativos e cartas procuradas |

Exemplo de criação:

```json
{
  "card_id": 1,
  "title": "Vendo ou troco",
  "price_cents": 2500,
  "condition": "NM",
  "language": "en",
  "mode": "ambos"
}
```

Envie o cookie de sessão e o cabeçalho `X-CSRF-Token` recebido em `/api/auth/me`. O backend ignora qualquer `user_id` do cliente e atribui a oferta ao usuário da sessão.

`contact_url` permanece aceito apenas para compatibilidade com dados/clientes antigos, mas não faz mais parte do fluxo de contato da interface. O contato comunitário começa pelo perfil público do outro jogador. O idioma público da oferta é derivado da impressão selecionada no catálogo; valores de `language` enviados pelo cliente não substituem o idioma real da carta.

Senhas usam `scrypt` com salt individual. A sessão usa token opaco em cookie `HttpOnly` e apenas seu SHA-256 é persistido. O celular aceita de 10 a 15 dígitos, é opcional e só é publicado quando o usuário o informa. Em HTTPS, execute com `MANAPONTE_SECURE_COOKIES=1` para adicionar `Secure` ao cookie.

### Frontend no GitHub Pages + API externa

Defina a URL pública do backend em `public/config.js`:

```js
window.MANAPONTE_API_BASE = "https://api.exemplo.com";
```

No backend, autorize somente a origem do Pages e habilite cookies cross-site seguros:

```bash
env \
  MANAPONTE_ALLOWED_ORIGIN=https://xoykor.github.io \
  MANAPONTE_SECURE_COOKIES=1 \
  MANAPONTE_CROSS_SITE_COOKIES=1 \
  ./scripts/dev.sh
```

`MANAPONTE_ALLOWED_ORIGIN` aceita uma lista separada por vírgulas. O backend só devolve CORS para origens explicitamente configuradas. O modo cross-site força `SameSite=None; Secure`, necessário para a sessão funcionar quando frontend e API estão em domínios diferentes. Em produção, a API precisa ficar atrás de HTTPS e de um servidor/proxy apropriado; o servidor da biblioteca padrão continua sendo apenas a implementação de protótipo.

Os caminhos dos três bancos podem ser substituídos por `MANAPONTE_CARDS_DB_PATH`, `MANAPONTE_ACCOUNTS_DB_PATH` e `MANAPONTE_LISTINGS_DB_PATH`. Um caminho único explícito continua disponível para compatibilidade com instalações antigas.

## Estrutura

```text
app/                 domínio, autenticação, SQLite, catálogo e servidor HTTP
public/              interface responsiva sem framework (início, anúncios e perfis)
scripts/dev.sh       seed + servidor local
scripts/import_scryfall.py
scripts/import_allcards.py
tests/               API real, banco e importador sem rede
data/cards.db        catálogo local gerado
data/accounts.db     usuários e sessões locais
data/listings.db     ofertas e desejos locais
```

`data/app.db` e `MANAPONTE_DB_PATH` são mantidos apenas para abrir ou migrar
instalações legadas de arquivo único; o modo legado é ativado ao fornecer esse
caminho explicitamente ou definir essa variável sem as variáveis específicas.

## Limitações conscientes

- sem recuperação de senha, verificação de e-mail, MFA, chat, reputação ou moderação;
- sem pagamentos, frete ou custódia da transação;
- a importação do Bulk Data é incremental, mas mantém um lote de até 500 tuplas normalizadas em memória;
- a busca remota usa cache em memória limitado a 256 consultas, com TTL de cinco minutos e deduplicação de chamadas simultâneas;
- SQLite e o servidor da biblioteca padrão são adequados ao esboço, não à operação pública;
- as imagens oficiais dependem de conexão e da disponibilidade do Scryfall; o backend não armazena mídia enviada por usuários para manter baixo o uso de disco e banda;
- o GitHub Pages não hospeda o backend: persistência compartilhada exige uma API HTTPS separada, embora o frontend já suporte essa configuração via `public/config.js`.

Veja [ARCHITECTURE.md](ARCHITECTURE.md) para a visão completa.

Documentação técnica detalhada:

- [API e HTTP](docs/API.md)
- [Modelo de dados e persistência](docs/DATA_MODEL.md)
- [Frontend](docs/FRONTEND.md)
- [Operação, configuração e deploy](docs/OPERATIONS.md)
- [Testes e contratos verificados](docs/TESTING.md)


## Licença

O código original do ManaPonte é disponibilizado sob a **ManaPonte Proprietary Source-Available License**. A publicação do código permite inspeção, discussão e contribuição ao projeto oficial, mas não concede permissão geral para copiar, redistribuir, hospedar, operar, modificar ou criar produtos derivados.

Materiais de terceiros — incluindo imagens, nomes, símbolos, textos e propriedades relacionadas a Magic: The Gathering e Scryfall — permanecem sujeitos aos direitos e termos de seus respectivos titulares. Consulte [LICENSE](LICENSE) e [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
