# ManaPonte - Auditoria e correções

## Etapas

- [x] Etapa 1: auditoria inicial e linha de base
- [x] Etapa 2: importação incremental do catálogo (gzip, JSONL/array, validação, contagens e upsert)
- [x] Etapa 3: busca local previsível, fallback remoto, cache limitado e paginação
- [x] Etapa 4: anúncios, contato HTTP(S), escaping HTML e fluxo de idioma
- [x] Etapa 5: validação visual e de interação no navegador — Chromium headless via CDP, 23/23 verificações aprovadas. Cenários: carga inicial/desktop, filtro de modalidade (chips venda/troca/ambos), seletor de cartas (busca "Sol Ring" + seleção → card_id), autenticação (diálogo abre, cadastro→201, badge/Sair, logout com CSRF 200), criação de oferta end-to-end (POST /api/listings 201, modal fecha) e responsividade mobile (375x667) + tablet (768x1024). Evidência: `e5-screenshots/e5_report.json` + screenshots.
- [ ] Etapa 6: preparar imagens locais (opcional; sem coleta em massa nesta etapa)
- [x] Etapa 7: encerramento técnico (testes com bancos temporários/mocks, documentação e `git diff --check`)
- [x] Etapa 8: área autenticada (perfil, meus anúncios, edição/remoção, desejos e matches por `oracle_id`)
- [x] Etapa 9: frontend preparado para API externa (config runtime, CORS, cookies cross-site seguros e CI)
- [x] Etapa 10: auditoria arquitetural completa — backend, bancos, catálogo, cache remoto, frontend, segurança, operação, CI/Pages e contratos de teste documentados em `ARCHITECTURE.md` e `docs/`

## Estado de validação

Os contratos de API foram exercitados contra servidor HTTP real em portas
temporárias, com bancos separados e legado isolados. A suíte completa não
acessa a rede Scryfall. A interface estática mantém os JSONs demonstrativos e
salva anúncios no `localStorage`; a API é necessária para contas e anúncios
compartilhados.
