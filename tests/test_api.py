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

    def test_profile_update_requires_csrf_and_refreshes_session(self):
        """Perfil autenticado atualiza nome e localização da sessão."""

        self.login_demo()

        status, _ = self.request(
            "PATCH",
            "/api/profile",
            {"display_name": "Danton Atualizado", "city": "Parnamirim", "state": "RN"},
        )
        self.assertEqual(status, 403)

        status, data = self.request(
            "PATCH",
            "/api/profile",
            {"display_name": "Danton Atualizado", "city": "Parnamirim", "state": "RN"},
            csrf=self.csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["display_name"], "Danton Atualizado")
        self.assertEqual(data["user"]["city"], "Parnamirim")

        status, me = self.request("GET", "/api/auth/me")
        self.assertEqual(status, 200)
        self.assertEqual(me["user"]["city"], "Parnamirim")

        # Restaura o fixture para os testes seguintes não dependerem da ordem.
        status, _ = self.request(
            "PATCH",
            "/api/profile",
            {"display_name": "Danton Homero", "city": "Natal", "state": "RN"},
            csrf=self.csrf,
        )
        self.assertEqual(status, 200)

    def test_owner_can_list_edit_and_delete_own_listing(self):
        """mine=1, PATCH e DELETE respeitam o proprietário do anúncio."""

        self.login_demo()
        status, created = self.request(
            "POST",
            "/api/listings",
            {
                "card_id": 3,
                "title": "Bolt editável",
                "description": "Antes",
                "condition": "SP",
                "mode": "venda",
                "price_cents": 1200,
            },
            csrf=self.csrf,
        )
        self.assertEqual(status, 201)
        listing_id = created["id"]

        status, mine = self.request("GET", "/api/listings?mine=1&limit=100")
        self.assertEqual(status, 200)
        self.assertIn(listing_id, {item["id"] for item in mine["listings"]})
        self.assertTrue(
            all(item["user_id"] == 1 for item in mine["listings"])
        )

        status, _ = self.request(
            "PATCH",
            f"/api/listings/{listing_id}",
            {
                "title": "Bolt atualizado",
                "description": "Depois",
                "price_cents": 1000,
                "mode": "ambos",
            },
        )
        self.assertEqual(status, 403)

        status, updated = self.request(
            "PATCH",
            f"/api/listings/{listing_id}",
            {
                "title": "Bolt atualizado",
                "description": "Depois",
                "price_cents": 1000,
                "mode": "ambos",
            },
            csrf=self.csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["id"], listing_id)

        status, listing_payload = self.request(
            "GET",
            f"/api/listings?card_id=3&limit=100",
        )
        edited = next(
            item for item in listing_payload["listings"]
            if item["id"] == listing_id
        )
        self.assertEqual(edited["title"], "Bolt atualizado")
        self.assertEqual(edited["description"], "Depois")
        self.assertEqual(edited["price_cents"], 1000)
        self.assertEqual(edited["mode"], "ambos")

        status, _ = self.request(
            "DELETE",
            f"/api/listings/{listing_id}",
            csrf=self.csrf,
        )
        self.assertEqual(status, 200)

        status, mine = self.request("GET", "/api/listings?mine=1&limit=100")
        self.assertNotIn(listing_id, {item["id"] for item in mine["listings"]})

    def test_user_cannot_edit_or_delete_another_users_listing(self):
        """Rotas mutáveis não revelam nem alteram anúncio de outro usuário."""

        self.login_demo()

        # O fixture 2 pertence a Marina, não ao usuário danton.
        status, payload = self.request(
            "PATCH",
            "/api/listings/2",
            {"title": "Tentativa indevida"},
            csrf=self.csrf,
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "Anúncio não encontrado")

        status, payload = self.request(
            "DELETE",
            "/api/listings/2",
            csrf=self.csrf,
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "Anúncio não encontrado")

    def test_listing_mode_filter_includes_both_mode(self):
        """Venda/troca incluem anúncios marcados como ambos."""

        status, sales = self.request("GET", "/api/listings?mode=venda&limit=100")
        self.assertEqual(status, 200)
        self.assertTrue(sales["listings"])
        self.assertTrue(
            all(item["mode"] in {"venda", "ambos"} for item in sales["listings"])
        )
        self.assertIn("ambos", {item["mode"] for item in sales["listings"]})

        status, trades = self.request("GET", "/api/listings?mode=troca&limit=100")
        self.assertEqual(status, 200)
        self.assertTrue(trades["listings"])
        self.assertTrue(
            all(item["mode"] in {"troca", "ambos"} for item in trades["listings"])
        )
        self.assertIn("ambos", {item["mode"] for item in trades["listings"]})

    def test_wants_crud_and_matching(self):
        """Desejos autenticados são salvos, casados e removidos."""

        self.login_demo()

        # O seed já contém um desejo por Rhystic Study e uma oferta compatível
        # de outro usuário; o matching sem card_id cruza wants x listings.
        status, seeded_matches = self.request("GET", "/api/matches")
        self.assertEqual(status, 200)
        self.assertEqual(seeded_matches["basis"], "wants")
        self.assertTrue(
            any(item["wanted_name"] == "Rhystic Study" for item in seeded_matches["matches"])
        )

        payload = {
            "card_id": 4,
            "max_price_cents": 1000,
            "desired_condition": "NM",
            "mode": "compra",
        }

        status, _ = self.request("POST", "/api/wants", payload)
        self.assertEqual(status, 403)

        status, created = self.request(
            "POST",
            "/api/wants",
            payload,
            csrf=self.csrf,
        )
        self.assertEqual(status, 201)

        status, wants = self.request("GET", "/api/wants")
        self.assertEqual(status, 200)
        saved = next(item for item in wants["wants"] if item["id"] == created["id"])
        self.assertEqual(saved["name"], "Counterspell")
        self.assertEqual(saved["max_price_cents"], 1000)
        self.assertEqual(saved["mode"], "compra")

        status, matches = self.request("GET", "/api/matches")
        self.assertEqual(status, 200)
        self.assertTrue(
            any(
                item["want_id"] == created["id"]
                and item["name"] == "Counterspell"
                and item["mode"] in {"venda", "ambos"}
                for item in matches["matches"]
            )
        )

        status, _ = self.request(
            "DELETE",
            f"/api/wants/{created['id']}",
            csrf=self.csrf,
        )
        self.assertEqual(status, 200)

        status, wants = self.request("GET", "/api/wants")
        self.assertFalse(any(item["id"] == created["id"] for item in wants["wants"]))

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
