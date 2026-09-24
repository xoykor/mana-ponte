# Testes e validação

## CI atual

`.github/workflows/tests.yml` executa:

- `git diff --check`;
- `node --check` no JavaScript do frontend;
- `node --check` no JavaScript do Worker.

A CI atual valida sintaxe.

## Cobertura ainda necessária

Uma suíte de comportamento do Worker deve cobrir:

1. autenticação;
2. roteamento;
3. CRUD de anúncios;
4. desejos e matching;
5. D1 local;
6. fallback Scryfall;
7. migrations;
8. browser E2E.

## Contratos críticos

- nenhuma imagem armazenada;
- `user_id` derivado da sessão;
- token bruto nunca persistido;
- CSRF em mutações;
- `cards.id` como ID local;
- `oracle_id` para reimpressões;
- falha do Scryfall não apaga dados locais;
- erros capturados retornam JSON.

## Validação manual mínima

- health;
- cadastro/login/logout;
- busca;
- criar/editar/excluir anúncio;
- desejo;
- perfil;
- matching.
