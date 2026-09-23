# Guia de leitura do código

Este documento foi escrito para alguém no começo de Lógica de Programação.

## 1. Quase tudo se resume a quatro ideias

Mesmo em um sistema web, você continua usando:

1. **variável** — guarda um valor;
2. **função** — dá nome a uma sequência de passos;
3. **if** — escolhe um caminho;
4. **laço** — repete uma ação.

HTTP, banco e Cloudflare parecem assuntos diferentes, mas essas quatro ideias
continuam aparecendo o tempo todo.

## 2. Ordem recomendada de leitura

Comece pela produção atual:

1. `cloudflare-worker/src/index.js`
2. `cloudflare-worker/src/lib.js`
3. `cloudflare-worker/src/auth.js`
4. `cloudflare-worker/src/catalog.js`
5. `cloudflare-worker/src/listings.js`
6. `cloudflare-worker/src/wants.js`

Depois vá para o frontend:

1. `public/page-common.js`
2. `public/listing-detail.js`
3. `public/profile-page.js`
4. `public/listings-page.js`
5. `public/card-picker.js`
6. `public/app.js`

O backend Python em `app/` é legado/local e pode ser estudado depois.

## 3. index.js é a recepção

Leia um bloco assim:

```text
se método == GET e caminho == /api/cards
    chamar getCards()
```

Isso se chama **roteamento**.

O arquivo não deveria fazer todo o trabalho sozinho. Ele apenas decide qual
função especializada chamar.

## 4. lib.js é uma caixa de ferramentas

Funções pequenas evitam repetição.

Exemplos:

- `json()` monta respostas JSON;
- `readJson()` lê o corpo enviado pelo navegador;
- `positiveInt()` valida paginação;
- `requireSession()` verifica login;
- `csrfValid()` confere o token CSRF.

Quando a mesma lógica aparece em vários lugares, uma função auxiliar costuma
ser melhor do que copiar e colar.

## 5. Entrada → validação → banco → resposta

Grande parte do backend segue este formato:

```text
receber dados
    ↓
normalizar
    ↓
validar
    ↓
consultar/gravar no banco
    ↓
responder JSON
```

Use `auth.js` como primeiro exemplo.

## 6. O que significa async/await?

Consultar banco ou internet leva tempo.

Uma função marcada com `async` pode usar `await`.

```js
const user = await env.DB.prepare("...").first();
```

Leia como:

> espere a consulta terminar e só depois coloque o resultado em user.

Sem `await`, a operação pode ainda não ter terminado quando o código seguir.

## 7. Request e Response

Uma requisição é uma mensagem enviada ao servidor.

Exemplo:

```text
GET /api/cards?q=lotus
```

Uma resposta possui:

- status HTTP;
- headers;
- corpo.

A API do ManaPonte tenta responder JSON.

## 8. Status HTTP mais comuns no projeto

- 200 — funcionou;
- 201 — algo foi criado;
- 400 — entrada inválida;
- 401 — precisa estar logado;
- 403 — não autorizado/CSRF inválido;
- 404 — recurso não encontrado;
- 409 — conflito, como conta duplicada;
- 429 — tentativas demais;
- 500 — erro interno.

## 9. Banco: por que existem ? e bind()?

Evite montar SQL assim:

```text
"... WHERE email='" + email + "'"
```

O projeto usa:

```js
env.DB.prepare("SELECT ... WHERE email=?")
  .bind(email)
```

O `?` é um espaço reservado.

`bind(email)` envia o valor separadamente do comando SQL.

Além de ficar mais organizado, isso evita tratar texto do usuário como parte
do comando SQL.

## 10. O que é JOIN?

As informações ficam em tabelas diferentes.

Um anúncio tem `card_id` e `user_id`.

Para mostrar nome da carta e vendedor, fazemos JOIN:

```text
listings
   ├── card_id -> cards
   └── user_id -> users
```

Não tente entender a query grande de `wants.js` primeiro. Entenda duas
tabelas por vez.

## 11. CRUD

`listings.js` é um bom arquivo para estudar CRUD:

- Create — `createListing()`;
- Read — `getListing()` e `getListings()`;
- Update — `updateListing()`;
- Delete — `deleteListing()`.

CRUD é apenas um nome comum para essas quatro operações.

## 12. Sessão

Depois de login correto:

```text
gera token aleatório
    ↓
navegador recebe token no cookie
    ↓
D1 guarda SHA-256(token)
```

Nas próximas requisições:

```text
cookie
  ↓
SHA-256
  ↓
procura sessão no D1
```

A senha e o token bruto não ficam gravados no banco.

## 13. Hash de senha

Senha não é criptografada para ser "descriptografada depois".

O projeto deriva um hash com PBKDF2.

No cadastro:

```text
senha + salt
    ↓
PBKDF2
    ↓
hash
```

No login, o cálculo é repetido e o resultado é comparado.

## 14. CSRF

Cookies são enviados automaticamente pelo navegador.

Para ações que alteram dados, como excluir anúncio, o projeto exige também um
token CSRF.

Assim, conhecer somente o cookie não é o fluxo normal esperado pelo frontend.

## 15. Catálogo e Scryfall

`catalog.js` segue esta estratégia:

```text
procurar no D1
    ↓
tem resultados suficientes?
   sim -> responder
   não -> consultar Scryfall
            ↓
          salvar metadados no D1
            ↓
          reler D1
            ↓
          responder
```

Se o Scryfall falhar, os dados já presentes no D1 continuam utilizáveis.

## 16. Imagens

O ManaPonte não guarda imagens.

O banco guarda somente:

```text
image_url = "https://..."
```

O navegador acessa essa URL externa.

## 17. Frontend: o que é renderizar?

Renderizar significa pegar dados e transformá-los em elementos visíveis.

Exemplo mental:

```text
[
  { nome: "Carta A" },
  { nome: "Carta B" }
]
```

vira algo equivalente a:

```html
<div>Carta A</div>
<div>Carta B</div>
```

Funções que começam com `render` fazem esse tipo de trabalho.

## 18. fetch()

No navegador, `fetch()` envia uma requisição HTTP.

```js
const response = await fetch("/api/cards?q=lotus");
```

Depois o código lê a resposta e usa os dados para atualizar a página.

## 19. Estado

"Estado" é simplesmente informação que o programa precisa lembrar por algum
tempo.

Exemplos no frontend:

- usuário atual;
- token CSRF;
- carta selecionada;
- página atual;
- filtros;
- requisição em andamento.

## 20. Por que AbortController?

Se a pessoa digita muito rápido:

```text
l
li
lig
ligh
light
```

várias buscas poderiam estar acontecendo ao mesmo tempo.

`AbortController` permite cancelar a busca antiga quando uma nova já a tornou
inútil.

## 21. Backend Python legado

Quando estiver confortável com o Worker, leia:

1. `app/auth.py`
2. `app/db.py`
3. `app/catalog.py`
4. `app/seed.py`
5. `app/server.py`

`server.py` é o maior e deve ficar por último.

## 22. Testes

Um teste normalmente tem três partes:

```text
preparar
    ↓
executar
    ↓
verificar
```

Exemplo:

```text
criar usuário
    ↓
fazer login
    ↓
verificar se status == 200
```

## 23. Regra prática antes de editar uma função

Responda:

1. Quem chama esta função?
2. O que entra?
3. O que ela devolve?
4. O que ela altera?
5. Que erros podem acontecer?

Depois de editar:

1. confira sintaxe;
2. rode testes;
3. confira o diff;
4. só então publique.

## 24. Arquitetura inteira em uma figura

```text
navegador
   |
   +---- HTML/CSS/JS ----> Cloudflare Static Assets
   |
   +---- /api/* ---------> Cloudflare Worker
                                |
                                +---- D1
                                |
                                +---- Scryfall
```

Esse desenho é suficiente para se localizar antes de entrar nos detalhes.
