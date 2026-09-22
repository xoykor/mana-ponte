# Estado da revisão

O núcleo do marketplace está implementado fora do trabalho de catálogo local:
busca e paginação, autenticação, criação/edição/remoção de anúncios pelo
proprietário, perfil, lista de desejos e matching entre desejos e ofertas.
O matching usa `oracle_id` para aceitar reimpressões e respeita modalidade,
preço máximo e condição mínima.

A vitrine permite filtrar por carta, coleção, cidade, UF e modalidade. Anúncios
`ambos` aparecem tanto em venda quanto em troca. A área autenticada reúne
perfil, anúncios próprios, desejos e matches. O GitHub Pages continua operando
como demonstração quando `public/config.js` não aponta para uma API; quando a
URL é configurada, o frontend usa o backend externo com credenciais.

O backend suporta CORS por allowlist e cookies cross-site seguros para essa
separação de domínios. A CI verifica o diff, sintaxe dos JavaScripts e toda a
suíte `unittest`, incluindo bancos separados, propriedade de anúncios, CSRF,
wants/matching e contrato CORS.

A validação visual registrada anteriormente permanece em
`e5-screenshots/`. As mudanças posteriores mantêm a interface responsiva, mas
o driver CDP legado não faz parte da CI porque depende de um caminho local do
módulo WebSocket. Os arquivos de imagens existentes foram preservados; coleta
em massa de imagens continua opcional e fora deste trabalho.

## Auditoria arquitetural

A arquitetura foi revisada contra o código atual e documentada em profundidade.
`ARCHITECTURE.md` funciona como documento-mestre, com referências separadas para API, persistência, frontend, operação e testes em `docs/`.

A revisão registrou explicitamente precedência de configuração, modo legado, concorrência do servidor, cache remoto com deduplicação em voo, semântica de `source` em `/api/cards`, nomes `name`/`printed_name`, invariantes de ownership/idioma, detecção do modo estático, lifecycle do seed, CI/Pages e limites operacionais.

Também fica documentado que os AVIFs locais ainda não fazem parte do runtime: o código atual continua consumindo `cards.image_url`. A integração de mídia local deve ser feita como camada estática separada, sem blobs no SQLite.
