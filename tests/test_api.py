"""Testes de integração da API HTTP do ManaPonte."""

import http.client
import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app.server as server_module
from app.db import get_connection
from app.seed import DEV_PASSWORD, seed_all
from app.server import create_server


class ApiTest(unittest.TestCase):
    """Inicia um servidor real em uma porta temporária para cada suíte."""

    @classmethod
    def setUpClass(cls):
        # Um banco isolado torna os testes repetíveis e não altera data/app.db.
        cls.temp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.temp.name) / "api.db"
        seed_all(cls.db, reset=True)

        # A porta 0 pede ao sistema operacional uma porta livre.
        cls.server = create_server("127.0.0.1", 0, cls.db)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        # O shutdown encerra o loop HTTP antes de liberar a porta.
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def setUp(self):
        # Cada teste começa sem cookie e sem token CSRF.
        self.cookie = None
        self.csrf = None

    def request(self, method, path, payload=None, csrf=None):
        """Faz uma requisição HTTP e devolve ``(status, corpo)``."""

        conn = http.client.HTTPConnection(
            "127.0.0.1",
            self.port,
            timeout=4,
        )

        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body else {}

        # Reutilizamos o cookie recebido em uma requisição anterior.
        if self.cookie:
            headers["Cookie"] = self.cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf

        conn.request(method, path, body, headers)
        response = conn.getresponse()
        raw = response.read()

        # Guardamos somente o par nome=valor; atributos como Path não precisam
        # ser enviados manualmente na próxima requisição de teste.
        cookie = response.getheader("Set-Cookie")
        if cookie:
            self.cookie = cookie.split(";", 1)[0]

        content_type = response.getheader("Content-Type", "")
        data = json.loads(raw) if content_type.startswith("application/json") else raw
        status = response.status
        conn.close()
        return status, data

    def login_demo(self):
        """Entra com o usuário criado pelo seed e guarda o CSRF."""

        status, data = self.request(
            "POST",
            "/api/auth/login",
            {
                "identifier": "danton",
                "password": DEV_PASSWORD,
            },
        )
        self.assertEqual(status, 200)
        self.csrf = data["csrf_token"]
        return data

    def test_register_duplicate_cookie_and_me(self):
        """Cadastro normaliza dados, cria cookie e rejeita duplicatas."""

        payload = {
            "username": "novo.jogador",
            "email": "novo@example.com",
            "password": "Strong!Pass2026",
            "display_name": "Novo Jogador",
            "city": "Natal",
            "state": "rn",
        }

        status, data = self.request("POST", "/api/auth/register", payload)
        self.assertEqual(status, 201)
        self.assertTrue(self.cookie.startswith("mp_session="))
        self.assertEqual(data["user"]["state"], "RN")

        self.csrf = data["csrf_token"]
        status, me = self.request("GET", "/api/auth/me")
        self.assertEqual(status, 200)
        self.assertEqual(me["user"]["username"], "novo.jogador")

        # O mesmo username/e-mail já existe e deve retornar conflito.
        other_status, _ = self.request("POST", "/api/auth/register", payload)
        self.assertEqual(other_status, 409)

    def test_login_logout_and_csrf(self):
        """Logout sem CSRF falha; com o token correto encerra a sessão."""

        self.login_demo()

        status, _ = self.request("POST", "/api/auth/logout")
        self.assertEqual(status, 403)

        status, _ = self.request(
            "POST",
            "/api/auth/logout",
            csrf=self.csrf,
        )
        self.assertEqual(status, 200)

        status, _ = self.request("GET", "/api/auth/me")
        self.assertEqual(status, 401)

    def test_invalid_login_and_rate_limit(self):
        """Tentativas inválidas repetidas ativam o limitador de login."""

        for _ in range(4):
            status, data = self.request(
                "POST",
                "/api/auth/login",
                {
                    "identifier": "missing-rate@example.com",
                    "password": "Wrong!Password1",
                },
            )
            self.assertEqual(status, 401)
            self.assertEqual(data["error"], "Credenciais inválidas")

        status, _ = self.request(
            "POST",
            "/api/auth/login",
            {
                "identifier": "missing-rate@example.com",
                "password": "Wrong!Password1",
            },
        )
        self.assertEqual(status, 429)

    def test_expired_session(self):
        """Uma sessão expirada não autentica mais o usuário."""

        self.login_demo()

        with closing(get_connection(self.db)) as conn:
            conn.execute("UPDATE sessions SET expires_at = 0")
            conn.commit()

        status, _ = self.request("GET", "/api/auth/me")
        self.assertEqual(status, 401)

    def test_listing_requires_session_and_csrf_and_uses_session_user(self):
        """Criar oferta exige sessão, CSRF e ignora user_id enviado pelo cliente."""

        payload = {
            "card_id": 1,
            # Este valor tenta impersonar outro usuário e deve ser ignorado.
            "user_id": 2,
            "title": "Oferta autenticada",
            "condition": "NM",
            "mode": "ambos",
            "price_cents": 100,
        }

        status, _ = self.request("POST", "/api/listings", payload)
        self.assertEqual(status, 401)

        self.login_demo()

        status, _ = self.request("POST", "/api/listings", payload)
        self.assertEqual(status, 403)

        status, data = self.request(
            "POST",
            "/api/listings",
            payload,
            csrf=self.csrf,
        )
        self.assertEqual(status, 201)

        with closing(get_connection(self.db)) as conn:
            owner = conn.execute(
                "SELECT user_id FROM listings WHERE id = ?",
                (data["id"],),
            ).fetchone()[0]
            self.assertEqual(owner, 1)

    def test_public_routes(self):
        """Rotas públicas respondem sem sessão e servem a página inicial."""

        status, health = self.request("GET", "/api/health")
        self.assertEqual((status, health["status"]), (200, "ok"))

        status, home = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"ManaPonte", home)

        # ``So`` é uma busca local curta e não aciona a integração remota.
        status, cards = self.request(
            "GET",
            "/api/cards?q=So&set=cmm&limit=1",
        )
        self.assertEqual(cards["total"], 1)

    def test_cards_fall_back_to_scryfall_and_persist_locally(self):
        """Uma carta remota é retornada e fica disponível na busca local."""

        server_module.REMOTE_CARD_CACHE.clear()
        remote_row = (
            "remote-card-id",
            "remote-oracle-id",
            "Regression Felidar",
            "tst",
            "Regression Set",
            "1",
            "en",
            "rare",
            "https://img.test/felidar.jpg",
        )

        with patch(
            "app.server.search_scryfall",
            return_value=[remote_row],
        ) as remote:
            status, first = self.request(
                "GET",
                "/api/cards?q=Regression%20Felidar&limit=10",
            )
            self.assertEqual(status, 200)
            self.assertEqual(first["source"], "scryfall")
            self.assertEqual(first["total"], 1)
            self.assertEqual(first["cards"][0]["name"], "Regression Felidar")

            # Com a integração remota desligada, a segunda chamada encontra o
            # registro que a primeira chamada persistiu no banco.
            with patch("app.server.remote_search_enabled", return_value=False):
                status, second = self.request(
                    "GET",
                    "/api/cards?q=Regression%20Felidar&limit=10",
                )

            self.assertEqual(status, 200)
            self.assertEqual(second["source"], "local")
            self.assertEqual(second["total"], 1)
            remote.assert_called_once_with("Regression Felidar", "", "")

    def test_cards_enrich_existing_local_results_from_scryfall(self):
        """A busca remota complementa resultados que já existiam localmente."""

        server_module.REMOTE_CARD_CACHE.clear()
        remote_row = (
            "remote-sol-ring-id",
            "remote-sol-ring-oracle",
            "Sol Ring",
            "tst",
            "Regression Set",
            "2",
            "en",
            "uncommon",
            "https://img.test/sol-ring.jpg",
        )

        with patch(
            "app.server.search_scryfall",
            return_value=[remote_row],
        ) as remote:
            status, data = self.request(
                "GET",
                "/api/cards?q=Sol%20Ring&limit=200",
            )

            self.assertEqual(status, 200)
            self.assertEqual(data["source"], "scryfall")
            self.assertEqual(data["total"], 2)
            self.assertEqual(
                {card["set_code"] for card in data["cards"]},
                {"cmm", "tst"},
            )
            remote.assert_called_once_with("Sol Ring", "", "")
