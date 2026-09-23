# Segurança

Este documento descreve controles implementados no runtime Cloudflare de produção.

## Fronteiras

Confiança:

    navegador não confiável
          |
          v
       Worker
          |
          +-- D1
          +-- Scryfall

Nunca confiar em user_id, ownership, preço, enumeração ou identificação de carta enviada pelo cliente sem validação.

## Senhas

Novos hashes usam:

- PBKDF2
- SHA-256
- 100.000 iterações
- salt aleatório de 16 bytes
- saída de 256 bits

Formato persistido:

pbkdf2$sha256$iterations$salt$hash

O verificador aceita entre 100.000 e 1.000.000 de iterações para compatibilidade.

Senhas precisam:

- 12–128 caracteres;
- minúscula;
- maiúscula;
- número;
- símbolo.

## Sessões

Token aleatório: 32 bytes antes de codificação URL-safe.

Persistência:
- somente SHA-256 do token.

Cookie:
- mp_session
- HttpOnly
- Secure
- SameSite=Lax
- Path=/
- 7 dias

CSRF é token separado.

## CSRF

Rotas mutáveis autenticadas exigem X-CSRF-Token.

Exemplos:

- logout
- update profile
- create/update/delete listing
- create/delete want

Comparação usa função de igualdade sem saída antecipada quando tamanhos coincidem.

## Autoria

O Worker ignora autoria fornecida pelo cliente.

user_id de listings/wants vem da sessão.

Update/delete usam id + user_id.

## Rate limiting

Login usa chave derivada de:

IP + identificador normalizado

A chave é SHA-256 antes de persistir.

Regra atual:

- janela: 15 minutos;
- bloqueio após 5 falhas;
- bloqueio: 15 minutos;
- login correto remove a entrada.

Estado fica em D1, portanto é compartilhado entre execuções do Worker.

## Validação

São limitados/validados:

- username;
- e-mail;
- senha;
- UF;
- telefone;
- tamanhos de título/descrição;
- card_id;
- preço;
- condition;
- mode;
- paginação.

Queries D1 usam bind parameters.

## Privacidade

Perfil público pode expor:

- username;
- display_name;
- phone quando informado;
- city;
- state;
- anúncios;
- desejos.

Perfil público não expõe:

- e-mail;
- password_hash;
- session token/hash;
- csrf_token.

## Imagens

O sistema não aceita upload de imagem.

Isso remove uma superfície importante de:

- armazenamento arbitrário;
- malware em upload;
- custo de mídia;
- validação de formatos;
- moderação de imagens.

image_url vem do catálogo externo.

## Secrets

CLOUDFLARE_API_TOKEN e CLOUDFLARE_ACCOUNT_ID ficam em GitHub Actions Secrets.

Não registrar valores em README, logs ou código.

O token deve ter somente permissões necessárias para Workers e D1.

## Pendências de segurança

Ainda faltam:

- recuperação segura de senha;
- verificação de e-mail;
- MFA opcional;
- política de senha vazada;
- moderação/denúncia;
- auditoria persistente;
- mecanismos antiabuso além do login;
- política formal de retenção e privacidade;
- testes de segurança específicos do Worker.
