# ManaPonte

Protótipo funcional de uma vitrine comunitária brasileira para jogadores de Magic: The Gathering encontrarem quem possui — ou procura — uma impressão específica. A negociação acontece diretamente entre jogadores; o produto não intermedeia pagamentos no MVP.

## Site publicado

**https://xoykor.github.io/mana-ponte/**

O GitHub Pages executa a versão estática em `public/`, com catálogo e ofertas demonstrativas em JSON. Busca, filtros e criação demonstrativa de ofertas funcionam no navegador; ofertas criadas ali ficam somente no `localStorage`. Cadastro real fica indisponível nessa versão porque exige a API e o banco. O deploy é automático pelo workflow `.github/workflows/pages.yml` a cada push na branch `main`.

## Executar

Requer somente Python 3.11 ou superior; não há pacotes para instalar.

```bash
cd /home/x/Documentos/Estudo/Qwen/mana-ponte
./scripts/dev.sh
```

Acesse `http://127.0.0.1:8000`. O script garante de forma idempotente os dados demonstrativos com 12 impressões reais, 4 perfis e 6 anúncios, sem apagar um catálogo já importado.

Se a porta estiver ocupada: `MANAPONTE_PORT=8001 ./scripts/dev.sh`.

Conta local de desenvolvimento: `danton` / `ManaPonte!2026`. Essa credencial é exclusivamente um fixture público; nunca a reutilize em produção.

Testes offline:

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

O importador descobre o `download_uri` atual no endpoint Bulk Data, identifica o cliente por User-Agent, ignora cartas exclusivamente digitais, reconhece imagens de cartas dupla-face e faz upsert a cada 500 registros. O protótipo armazena URLs, não cópias das imagens. O uso público/comercial deve respeitar as políticas de dados e imagens do Scryfall e da Wizards of the Coast.

Quando uma busca da API tem três ou mais caracteres, o ManaPonte também consulta o endpoint de busca do Scryfall, percorre todas as páginas retornadas e grava as impressões encontradas no SQLite. Para operar somente com o catálogo local, use `MANAPONTE_REMOTE_SEARCH=0`.

## API

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/api/health` | Saúde do serviço |
| POST | `/api/auth/register` | Valida dados, cria conta e sessão |
| POST | `/api/auth/login` | Autentica e cria sessão |
| GET | `/api/auth/me` | Retorna usuário e token CSRF da sessão |
| POST | `/api/auth/logout` | Revoga a sessão; exige CSRF |
| GET | `/api/cards?q=&set=&lang=&page=&limit=` | Busca paginada no catálogo |
| GET | `/api/sets` | Coleções e contagem de impressões |
| GET | `/api/listings?card=&card_id=&set=&city=&state=&mode=` | Ofertas filtradas |
| POST | `/api/listings` | Cria uma oferta validada |
| GET | `/api/matches?card_id=` | Ofertas compatíveis para uma impressão |

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

Senhas usam `scrypt` com salt individual. A sessão usa token opaco em cookie `HttpOnly` e apenas seu SHA-256 é persistido. Em HTTPS, execute com `MANAPONTE_SECURE_COOKIES=1` para adicionar `Secure` ao cookie.

## Estrutura

```text
app/                 domínio, autenticação, SQLite, catálogo e servidor HTTP
public/              interface responsiva sem framework
scripts/dev.sh       seed + servidor local
scripts/import_scryfall.py
tests/               API real, banco e importador sem rede
data/app.db          banco local gerado
```

## Limitações conscientes

- sem recuperação de senha, verificação de e-mail, MFA, chat, reputação ou moderação;
- sem pagamentos, frete ou custódia da transação;
- o carregamento do grande JSON Scryfall ocorre em memória antes do upsert em lotes;
- SQLite e o servidor da biblioteca padrão são adequados ao esboço, não à operação pública;
- imagens dependem de conexão e da disponibilidade do Scryfall.
- no GitHub Pages não há persistência compartilhada: para contas e anúncios reais, o frontend deverá apontar para uma API hospedada separadamente.

Veja [ARCHITECTURE.md](ARCHITECTURE.md) para limites, decisões e evolução.
