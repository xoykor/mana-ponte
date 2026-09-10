"""Testes unitários das regras de autenticação e sessão."""

import hashlib
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.auth import (
    create_session,
    csrf_matches,
    delete_expired_sessions,
    get_session,
    hash_password,
    normalize_email,
    normalize_username,
    revoke_session,
    valid_email,
    valid_username,
    validate_password,
    verify_password,
)
from app.db import get_connection
from app.seed import seed_all


class AuthUnitTest(unittest.TestCase):
    """Verifica funções de baixo nível sem iniciar um servidor HTTP."""

    def setUp(self):
        # Cada teste recebe um banco temporário para não compartilhar estado.
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "auth.db"
        seed_all(self.db, reset=True)

    def tearDown(self):
        # TemporaryDirectory remove o banco e a pasta ao final do teste.
        self.temp.cleanup()

    def test_normalization_and_validation(self):
        """Normalização transforma entradas válidas em uma forma canônica."""

        self.assertEqual(normalize_email(" User@Example.COM "), "user@example.com")
        self.assertEqual(normalize_username(" Player.One "), "player.one")

        self.assertTrue(valid_email("user@example.com"))
        self.assertFalse(valid_email("bad@"))
        self.assertTrue(valid_username("player.one"))
        self.assertFalse(valid_username("a space"))
        self.assertTrue(validate_password("Strong!Pass2026"))

        # Cada senha abaixo falha por pelo menos uma regra de complexidade.
        weak_passwords = (
            "short",
            "alllowercase!123",
            "ALLUPPERCASE!123",
            "NoNumber!Password",
            "NoSymbolPassword12",
        )
        for password in weak_passwords:
            self.assertFalse(validate_password(password))

    def test_hash_is_salted_and_verified(self):
        """A senha usa salt aleatório e só a senha original valida."""

        first = hash_password("Strong!Pass2026")
        second = hash_password("Strong!Pass2026")

        # Dois hashes da mesma senha não devem ser iguais porque cada um tem
        # um salt diferente.
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("scrypt$"))
        self.assertTrue(verify_password("Strong!Pass2026", first))
        self.assertFalse(verify_password("Wrong!Pass2026", first))
        self.assertFalse(verify_password("x", "corrupt"))

    def test_session_stores_only_hash_and_csrf(self):
        """A sessão guarda hash do token, nunca o token em texto puro."""

        created = create_session(1, self.db)

        with closing(get_connection(self.db)) as conn:
            row = conn.execute(
                "SELECT token_hash, csrf_token FROM sessions"
            ).fetchone()

            expected_hash = hashlib.sha256(
                created["token"].encode()
            ).hexdigest()
            self.assertNotEqual(row["token_hash"], created["token"])
            self.assertEqual(row["token_hash"], expected_hash)

        session = get_session(created["token"], self.db)
        self.assertEqual(session["user_id"], 1)
        self.assertTrue(csrf_matches(session, created["csrf_token"]))
        self.assertFalse(csrf_matches(session, "wrong"))

    def test_expiry_cleanup_and_revocation(self):
        """Sessões expiradas somem e sessões ativas podem ser revogadas."""

        expired = create_session(1, self.db)
        active = create_session(1, self.db)

        # Forçamos a primeira sessão a expirar para testar a limpeza.
        expired_hash = hashlib.sha256(expired["token"].encode()).hexdigest()
        with closing(get_connection(self.db)) as conn:
            conn.execute(
                "UPDATE sessions SET expires_at = 0 WHERE token_hash = ?",
                (expired_hash,),
            )
            conn.commit()

        self.assertIsNone(get_session(expired["token"], self.db))
        self.assertEqual(delete_expired_sessions(self.db), 1)

        self.assertTrue(revoke_session(active["token"], self.db))
        self.assertIsNone(get_session(active["token"], self.db))
