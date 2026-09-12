# ManaPonte - Auditoria e correções

## Etapas

- [x] Etapa 1: auditoria inicial e linha de base
- [x] Etapa 2: importação incremental do catálogo (gzip, JSONL/array, validação, contagens e upsert)
- [x] Etapa 3: busca local previsível, fallback remoto, cache limitado e paginação
- [x] Etapa 4: anúncios, contato HTTP(S), escaping HTML e fluxo de idioma
- [ ] Etapa 5: validação visual e de interação no navegador (inspeção parcial feita; revisão completa e responsiva pendente)
- [ ] Etapa 6: preparar imagens locais (opcional; sem coleta em massa nesta etapa)
- [x] Etapa 7: encerramento técnico (testes com bancos temporários/mocks, documentação e `git diff --check`)

## Estado de validação

Os contratos de API foram exercitados contra servidor HTTP real em portas
temporárias, com bancos separados e legado isolados. A suíte completa não
acessa a rede Scryfall. A interface estática mantém os JSONs demonstrativos e
salva anúncios no `localStorage`; a API é necessária para contas e anúncios
compartilhados.
