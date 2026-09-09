# ManaPonte

Protótipo funcional de uma vitrine comunitária brasileira para jogadores de Magic: The Gathering encontrarem quem possui — ou procura — uma impressão específica. A negociação acontece diretamente entre jogadores; o produto não intermedeia pagamentos no MVP.

## Executar

Requer somente Python 3.11 ou superior; não há pacotes para instalar.

```bash
cd /home/x/Documentos/Estudo/Qwen/mana-ponte
./scripts/dev.sh
```

Acesse `http://127.0.0.1:8000`. O script garante de forma idempotente os dados demonstrativos com 12 impressões reais, 4 perfis e 6 anúncios, sem apagar um catálogo já importado.

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

## API

| Método | Rota | Função |
| --- | --- | --- |
| GET | `/api/health` | Saúde do serviço |
| GET | `/api/cards?q=&set=&lang=&page=&limit=` | Busca paginada no catálogo |
| GET | `/api/sets` | Coleções e contagem de impressões |
| GET | `/api/listings?card=&card_id=&set=&city=&state=&mode=` | Ofertas filtradas |
| POST | `/api/listings` | Cria uma oferta validada |
| GET | `/api/matches?card_id=` | Ofertas compatíveis para uma impressão |

Exemplo de criação:

```json
{
  "card_id": 1,
  "user_id": 1,
  "title": "Vendo ou troco",
  "price_cents": 2500,
  "condition": "NM",
  "language": "en",
  "mode": "ambos"
}
```

No MVP, `user_id` é recebido apenas para permitir a demonstração. Em produção, ele deve obrigatoriamente vir da sessão autenticada.

## Estrutura

```text
app/                 domínio, SQLite, catálogo e servidor HTTP
public/              interface responsiva sem framework
scripts/dev.sh       seed + servidor local
scripts/import_scryfall.py
tests/               API real, banco e importador sem rede
data/app.db          banco local gerado
```

## Limitações conscientes

- sem autenticação, chat, reputação ou moderação;
- sem pagamentos, frete ou custódia da transação;
- o carregamento do grande JSON Scryfall ocorre em memória antes do upsert em lotes;
- SQLite e o servidor da biblioteca padrão são adequados ao esboço, não à operação pública;
- imagens dependem de conexão e da disponibilidade do Scryfall.

Veja [ARCHITECTURE.md](ARCHITECTURE.md) para limites, decisões e evolução.
