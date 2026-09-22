# Arquitetura do frontend

O frontend é HTML/CSS/JavaScript sem framework e vive em `public/`.

## Dois modos de execução

### Modo API

É usado quando:

- a página está servida pelo backend Python sem `?static`; ou
- `window.MANAPONTE_API_BASE` aponta para uma API externa.

Nesse modo:

- autenticação é real;
- anúncios são compartilhados;
- desejos e matches funcionam;
- perfis públicos e página individual de anúncio funcionam;
- buscas usam a API.

### Modo estático

É ativado quando:

- existe `?static` na URL; ou
- não há `MANAPONTE_API_BASE` e o host termina em `github.io`; ou
- não há API e o protocolo é `file:`.

Nesse modo:

- catálogo de demonstração vem de `public/data/cards.json`;
- anúncios iniciais vêm de `public/data/listings.json`;
- novos anúncios ficam em `localStorage`;
- não existe conta real;
- não existem desejos/matches compartilhados;
- perfil público e detalhe de anúncio que exigem API não funcionam como experiência completa.

A chave de anúncios locais é:

```text
manaponte-demo-listings
```

JSON inválido no `localStorage` é tratado como lista vazia.

## Configuração da API

`public/config.js` define:

```js
window.MANAPONTE_API_BASE = "";
```

O valor é normalizado removendo barras finais.

Somente caminhos que começam com `/api/` recebem o prefixo da API externa. Arquivos estáticos continuam relativos ao site atual.

Todas as chamadas de API usam:

```js
credentials: "include"
```

para permitir cookie de sessão.

## Páginas e scripts

### `index.html`

Scripts, nesta ordem:

1. `config.js`;
2. `card-preview.js`;
3. `card-autocomplete.js`;
4. `card-picker.js`;
5. `app.js`.

Responsabilidades:

- busca inicial;
- vitrine resumida;
- login/cadastro;
- criação/edição de anúncio;
- área “Minha conta”;
- perfil;
- desejos;
- matches.

Dialogs:

- `modal`: anúncio;
- `authModal`: login/cadastro;
- `accountModal`: área autenticada;
- `wantModal`: novo desejo.

### `anuncios.html`

Scripts:

1. `config.js`;
2. `page-common.js`;
3. `card-preview.js`;
4. `card-autocomplete.js`;
5. `listings-page.js`.

A página sincroniza os filtros com a query string usando `history.replaceState`.

No modo API, pagina em blocos de 24.

No modo estático, filtra e ordena todos os registros no navegador e apresenta uma única página lógica.

### `perfil.html`

Scripts:

1. `config.js`;
2. `page-common.js`;
3. `card-preview.js`;
4. `profile-page.js`.

Exige API.

O id vem de `?user=<id>`.

Mostra:

- display name;
- username;
- localização;
- mês/ano de entrada;
- contagem de anúncios;
- contagem de desejos;
- telefone/WhatsApp quando disponível;
- anúncios;
- desejos.

### `anuncio.html`

Scripts:

1. `config.js`;
2. `page-common.js`;
3. `card-preview.js`;
4. `listing-detail.js`.

Exige API.

O id vem de `?id=<id>`.

Mostra impressão, condição, modalidade, preço, descrição, data e dados públicos do vendedor.

## `page-common.js`

Expõe `window.ManaPontePage` com:

- `API_BASE`;
- `STATIC_MODE`;
- `apiUrl()`;
- `getJson()`;
- `esc()`;
- `money()`;
- `formatPhone()`;
- `phoneHref()`;
- `whatsappHref()`.

`getJson()` rejeita respostas que não tenham Content-Type JSON e transforma erros HTTP em `Error` com `status`.

## Escaping

Strings interpoladas em HTML passam por `esc()`, que substitui:

- `&`;
- `<`;
- `>`;
- aspas duplas;
- aspas simples.

Campos atribuídos via `textContent` não precisam desse escape manual.

## Busca e cancelamento

### Vitrine da home

`loadListings()` mantém:

- contador incremental de requisição;
- `AbortController` da chamada ativa.

Uma nova busca aborta a anterior. Mesmo se uma resposta antiga chegar, ela é descartada quando o id da requisição não coincide.

### Card picker

Cada instância mantém estado privado:

- carta selecionada;
- resultados atuais;
- timer de debounce;
- `AbortController`;
- id monotônico de requisição;
- página seguinte;
- flag `hasMore`.

Regras:

- menos de 2 caracteres não consulta;
- debounce de 220 ms;
- mudança de texto invalida a seleção antiga;
- mudança de idioma também invalida a seleção;
- paginação adiciona resultados;
- respostas obsoletas são ignoradas.

No modo estático, a busca é feita em memória e considera:

- `name`;
- `printed_name`;
- `set_code`;
- `collector_number`;
- idioma selecionado.

No modo API, envia `q`, `lang`, `page` e `limit=20`.

## Autocomplete leve

`card-autocomplete.js` é separado do card picker.

- mínimo de 2 caracteres;
- debounce de 180 ms;
- cancela fetch anterior;
- solicita até 30 cartas;
- reduz a até 12 nomes únicos;
- prefere `printed_name`, depois `printedName`, depois `name`.

Quando está em GitHub Pages sem API configurada, ele simplesmente não é ativado.

## Visualização ampliada

`card-preview.js` implementa um dialog global criado sob demanda.

Qualquer `img[data-card-image]` pode abrir o preview:

- clique;
- Enter;
- Espaço.

O listener de clique usa capture e cancela propagação/navegação para que clicar na arte dentro de um link ou botão não execute a ação externa.

## Busca da home

O formulário da home não filtra apenas a grade atual. Ele monta a query string e navega para `anuncios.html`.

Filtros enviados:

- card;
- set;
- lang;
- city;
- state;
- mode.

`?static` é preservado quando foi explicitamente solicitado.

## Criação de anúncio

Em modo API:

1. usuário precisa estar autenticado;
2. card picker precisa ter uma impressão selecionada;
3. preço digitado em reais é transformado em centavos;
4. POST ou PATCH é escolhido conforme `editingListingId`;
5. CSRF é enviado;
6. vitrine e área da conta são recarregadas.

Em modo estático:

1. não exige autenticação real;
2. cria um id com `Date.now()`;
3. salva o anúncio no navegador;
4. adiciona metadados demonstrativos de usuário/localização.

## Área autenticada

`app.js` mantém em memória:

- `currentUser`;
- `csrfToken`;
- mapa de anúncios próprios por id;
- seletores de carta;
- estado da edição.

`/api/auth/me` é usado na inicialização. HTTP 401 é tratado como “visitante não autenticado”, não como falha fatal.

A área da conta recarrega anúncios próprios, desejos e matches a partir da API.

## Telefone e WhatsApp

O frontend:

- formata números brasileiros comuns;
- cria links `tel:`;
- adiciona DDI 55 ao WhatsApp quando o usuário informou apenas DDD+número;
- usa `encodeURIComponent` na mensagem.

Links externos de WhatsApp usam `target="_blank"` e `rel="noopener noreferrer"`.

## Nome traduzido

O card picker e autocomplete já priorizam `printed_name`.

Outras áreas ainda renderizam majoritariamente `name`. Isso é comportamento atual e não deve ser confundido com ausência de suporte de busca: o backend pesquisa ambos os campos.

## CSS e responsividade

`styles.css` contém layout geral, cards, grids, dialogs e páginas independentes.

`auth.css` contém estilos da autenticação e área de conta.

A validação visual histórica está em `e5-screenshots/`; o driver CDP não faz parte da CI atual.
