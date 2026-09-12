# Estado da revisão

As correções de catálogo, busca, cache, anúncios e interface estão aplicadas
no checkout atual. A importação aceita JSONL ou array JSON, gzip ou texto
simples, processa o arquivo incrementalmente e faz upsert por `scryfall_id`.
Busca remota usa cache limitado, TTL e deduplicação de chamadas simultâneas.
Ofertas têm paginação, título, descrição, idioma e contato HTTP(S) validado.

A integração foi coberta com bancos SQLite temporários e mocks sem chamadas à
API Scryfall. O teste de contrato em três bancos confirma login, criação de
oferta, roundtrip de `contact_url` e `language`, paginação e rejeição de uma
URL longa que seria truncada. A suíte completa passou com 35 testes e
`git diff --check` não encontrou erros.

Foi feita uma inspeção visual parcial com o CUA em servidor temporário:
carregamento da página, grade de ofertas, filtro de modalidade, diálogo de
autenticação e seleção de impressão no formulário demonstrativo. Isso não
constitui uma validação visual completa ou responsiva; a Etapa 5 permanece
pendente. O CUA em subagente não oferece uma janela visível, então a análise
usou estado de acessibilidade e capturas da página.

Os arquivos existentes em `data/images/` foram preservados. Coleta em massa de
imagens do Scryfall não faz parte desta etapa; pode ser avaliada como job
opcional separado, respeitando as políticas dos provedores.
