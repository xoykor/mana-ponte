# Arquitetura do frontend

O frontend vive em public/ e usa HTML, CSS e JavaScript sem framework.

## Produção

Na implantação principal, public/ é publicado como Cloudflare Static Assets junto do Worker.

Fluxo:

    navegador
       |
       +-- /, HTML, CSS, JS -> ASSETS
       |
       +-- /api/* ----------> Worker

Como frontend e API compartilham a mesma origem, public/config.js mantém MANAPONTE_API_BASE vazio.

## GitHub Pages

O repositório ainda possui workflow de GitHub Pages.

Pages deve ser tratado como demonstração/modo estático, não como produção principal.

Quando hostname termina em github.io sem API configurada, o frontend entra em STATIC_MODE.

## STATIC_MODE

Ativado por:

- parâmetro ?static;
- github.io sem API_BASE;
- protocolo file: sem API_BASE.

Nesse modo:

- cards vêm de public/data/cards.json;
- listings iniciais vêm de public/data/listings.json;
- anúncios criados ficam apenas em localStorage;
- não existe sessão compartilhada;
- autenticação real não existe;
- wants/matches reais não existem.

Chave local:

manaponte-demo-listings

## API mode

No Worker de produção:

- STATIC_MODE é falso;
- chamadas /api/* permanecem same-origin;
- credentials: include é usado;
- cookies HttpOnly são enviados automaticamente.

## Páginas

### index.html

Responsabilidades:

- busca;
- vitrine;
- cadastro/login;
- criação/edição de anúncio;
- área autenticada;
- perfil;
- desejos;
- matches.

Scripts principais:

- config.js
- card-preview.js
- card-autocomplete.js
- card-picker.js
- app.js

### anuncios.html

Página dedicada de busca/filtros.

Usa:

- page-common.js
- listings-page.js
- autocomplete
- preview

Filtros são sincronizados com a query string.

### perfil.html

Recebe user via query string.

Mostra identidade pública, localização, contato opcional, anúncios e desejos.

### anuncio.html

Recebe id via query string.

Mostra impressão, preço, condição, modalidade, descrição e vendedor.

## Comunicação HTTP

app.js e page-common.js usam fetch com credentials: include.

getJson valida Content-Type.

Se a API devolver JSON com status de erro, a mensagem error é exibida.

Se a resposta não for JSON, a interface mostra:

"Resposta inesperada do servidor"

Isso normalmente indica erro fora do contrato da API, por exemplo página de erro da plataforma.

## Busca de cartas

card-picker.js mantém:

- debounce;
- AbortController;
- request id monotônico;
- paginação;
- carta selecionada.

No modo API envia q, lang, page e limit.

catalog.js no Worker pode enriquecer o D1 via Scryfall.

## Imagens

O frontend recebe image_url e atribui diretamente ao elemento img.

Não há endpoint de imagem do ManaPonte.

Fluxo:

    D1 -> image_url -> HTML img -> Scryfall

card-preview.js apenas amplia a imagem remota já carregada.

## Segurança de renderização

Conteúdo interpolado em HTML passa por esc() quando necessário.

Links para WhatsApp usam noopener/noreferrer.

E-mail não é mostrado em perfis públicos.

O cookie de sessão não é acessível pelo JavaScript por ser HttpOnly.

## Responsividade

styles.css cobre layout geral.

auth.css cobre autenticação e área de conta.

