"""Identidade, senhas e sessões opacas do ManaPonte.

O módulo não conhece HTTP. Ele recebe valores simples, valida credenciais e
persiste apenas o que é necessário para autenticar uma sessão depois.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from pathlib import Path

from .db import get_accounts_connection


# Os padrões mantêm os nomes simples para o protótipo e são aplicados depois
# de normalizar os valores recebidos do formulário.
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")
EMAIL_RE = re.compile(r"^[^\s@]{1,64}@[a-z0-9.-]{1,190}\.[a-z]{2,63}$")

# Parâmetros do scrypt. Eles ficam junto do hash para que uma futura versão
# possa reconhecer e verificar hashes antigos com parâmetros diferentes.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32

# Uma sessão normal dura uma semana.
DEFAULT_SESSION_TTL = 7 * 24 * 60 * 60


def normalize_email(value: str) -> str:
    """Remove espaços e normaliza e-mail para comparação sem distinção de caixa."""

    return str(value).strip().casefold()


def normalize_username(value: str) -> str:
    """Remove espaços e normaliza nome de usuário para comparação."""

    return str(value).strip().casefold()


def valid_email(value: str) -> bool:
    """Informa se o e-mail tem o formato mínimo aceito pelo cadastro."""

    return len(value) <= 254 and EMAIL_RE.fullmatch(value) is not None


def valid_username(value: str) -> bool:
    """Informa se o nome de usuário usa apenas caracteres permitidos."""

    return USERNAME_RE.fullmatch(value) is not None


def validate_password(password: str) -> bool:
    """Exige tamanho mínimo/máximo e quatro classes de caracteres.

    A senha precisa ter letras minúsculas, letras maiúsculas, números e pelo
    menos um símbolo. A função retorna apenas um booleano para ser reutilizada
    tanto pelo servidor quanto pelos testes.
    """

    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        return False

    has_lowercase = any(character.islower() for character in password)
    has_uppercase = any(character.isupper() for character in password)
    has_number = any(character.isdigit() for character in password)
    has_symbol = any(not character.isalnum() for character in password)

    return all((has_lowercase, has_uppercase, has_number, has_symbol))


def _b64(value: bytes) -> str:
    """Codifica bytes em Base64 seguro para colocar no texto do hash."""

    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    """Decodifica o Base64 sem padding usado pelo formato do hash."""

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    """Gera um hash scrypt com salt aleatório por senha."""

    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=DKLEN,
    )

    # O formato inclui algoritmo, parâmetros, salt e chave derivada.
    return (
        f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}"
        f"${_b64(salt)}${_b64(derived_key)}"
    )


def verify_password(password: str, encoded: str | None) -> bool:
    """Compara uma senha em texto com um hash persistido.

    Hashes corrompidos ou formatos desconhecidos são tratados como inválidos,
    em vez de derrubar a requisição de login.
    """

    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        n, r, p = int(n), int(r), int(p)

        # Os limites evitam aceitar parâmetros absurdos vindos do banco.
        valid_parameters = (
            algorithm == "scrypt"
            and 2**14 <= n <= 2**18
            and r in range(1, 17)
            and p in range(1, 9)
        )
        if not valid_parameters:
            return False

        expected_bytes = _unb64(expected)
        derived_key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=n,
            r=r,
            p=p,
            dklen=len(expected_bytes),
        )

        # A comparação em tempo constante evita vazamento por timing.
        return hmac.compare_digest(derived_key, expected_bytes)
    except (AttributeError, TypeError, ValueError):
        return False


def _token_hash(token: str) -> str:
    """Transforma o token secreto da sessão no valor armazenado no banco."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    user_id: int,
    db_path: str | Path | None = None,
    ttl: int = DEFAULT_SESSION_TTL,
) -> dict:
    """Cria uma sessão e retorna o token bruto apenas para o cookie.

    O token nunca é gravado diretamente no banco. Somente seu SHA-256 é
    persistido, então um vazamento da tabela não entrega sessões utilizáveis.
    """

    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    now = int(time.time())
    expires_at = now + max(60, ttl)

    connection = get_accounts_connection(db_path)
    try:
        # Limpa sessões antigas sempre que uma nova sessão é criada.
        connection.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
        connection.execute(
            """
            INSERT INTO sessions(
                token_hash,
                user_id,
                csrf_token,
                created_at,
                expires_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (_token_hash(token), user_id, csrf_token, now, expires_at),
        )
        connection.commit()
    finally:
        connection.close()

    return {
        "token": token,
        "csrf_token": csrf_token,
        "expires_at": expires_at,
    }


def get_session(
    token: str | None,
    db_path: str | Path | None = None,
) -> dict | None:
    """Busca uma sessão válida pelo token recebido no cookie."""

    if not token:
        return None

    connection = get_accounts_connection(db_path)
    try:
        row = connection.execute(
            """
            SELECT
                s.user_id,
                s.csrf_token,
                s.expires_at,
                u.username,
                u.email,
                u.display_name,
                u.city,
                u.state,
                u.email_verified
            FROM sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.token_hash = ?
              AND s.expires_at > ?
            """,
            (_token_hash(token), int(time.time())),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def csrf_matches(session: dict | None, supplied: str | None) -> bool:
    """Confere o token CSRF da sessão usando comparação em tempo constante."""

    return bool(
        session
        and supplied
        and hmac.compare_digest(session["csrf_token"], supplied)
    )


def revoke_session(token: str | None, db_path: str | Path | None = None) -> bool:
    """Remove uma sessão e informa se uma linha foi realmente removida."""

    if not token:
        return False

    connection = get_accounts_connection(db_path)
    try:
        cursor = connection.execute(
            "DELETE FROM sessions WHERE token_hash = ?",
            (_token_hash(token),),
        )
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def delete_expired_sessions(
    db_path: str | Path | None = None,
    now: int | None = None,
) -> int:
    """Exclui sessões expiradas e retorna quantas foram removidas."""

    reference_time = now or int(time.time())
    connection = get_accounts_connection(db_path)
    try:
        cursor = connection.execute(
            "DELETE FROM sessions WHERE expires_at <= ?",
            (reference_time,),
        )
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()
