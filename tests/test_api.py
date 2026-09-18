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
        """Perfil atualiza nome, celular e localização da sessão."""

        self.login_demo()

        payload = {
            "display_name": "Danton Atualizado",
            "phone": "(84) 99999-1234",
            "city": "Parnamirim",
            "state": "RN",
        }

        status, _ = self.request("PATCH", "/api/profile", payload)
        self.assertEqual(status, 403)

        status, data = self.request(
            "PATCH",
            "/api/profile",
            payload,
            csrf=self.csrf,
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["display_name"], "Danton Atualizado")
        self.assertEqual(data["user"]["phone"], "84999991234")
        self.assertEqual(data["user"]["city"], "Parnamirim")

        status, me = self.request("GET", "/api/auth/me")
        self.assertEqual(status, 200)
        self.assertEqual(me["user"]["phone"], "84999991234")
        self.assertEqual(me["user"]["city"], "Parnamirim")

        status, invalid = self.request(
            "PATCH",
            "/api/profile",
            {"phone": "123"},
            csrf=self.csrf,
        )
        self.assertEqual(status, 400)
        self.assertIn("Celular", invalid["error"])

        # Restaura o fixture para os testes seguintes não dependerem da ordem.
        status, _ = self.request(
            "PATCH",
            "/api/profile",
            {
                "display_name": "Danton Homero",
                "phone": "",
                "city": "Natal",
                "state": "RN",
            },
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

    def test_public_user_profile_exposes_only_public_data_and_listings(self):
        """Perfil público não vaza e-mail, hash ou dados de sessão."""

        status, data = self.request("GET", "/api/users/2")
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["display_name"], "Marina Lima")
        self.assertEqual(data["user"]["city"], "Fortaleza")
        self.assertIn("phone", data["user"])
        self.assertNotIn("email", data["user"])
        self.assertNotIn("password_hash", data["user"])
        self.assertNotIn("email_verified", data["user"])
        self.assertTrue(data["listings"])
        self.assertTrue(
            all(item["user_id"] == 2 for item in data["listings"])
        )

        status, data = self.request("GET", "/api/users/999999")
        self.assertEqual(status, 404)
        self.assertEqual(data["error"], "Usuário não encontrado")

    def test_matches_identify_the_other_player_for_profile_navigation(self):
        """Cada match informa o jogador que publicou a oferta."""

        self.login_demo()
        status, data = self.request("GET", "/api/matches")
        self.assertEqual(status, 200)
        self.assertTrue(data["matches"])

        match = data["matches"][0]
        self.assertIn("user_id", match)
        self.assertIn("username", match)
        self.assertNotEqual(match["user_id"], 1)

        status, profile = self.request(
            "GET",
            f"/api/users/{match['user_id']}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            profile["user"]["display_name"],
            match["display_name"],
        )

    def test_listing_language_filter_uses_print_language(self):
        """Idioma do anúncio vem da impressão e pode filtrar a busca pública."""

        self.login_demo()

        with closing(get_connection(self.db)) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cards(
                    scryfall_id,
                    oracle_id,
                    name,
                    set_code,
                    set_name,
                    collector_number,
                    language,
                    rarity,
                    image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "test-pt-print",
                    "test-language-oracle",
                    "Carta de Teste PT",
                    "tst",
                    "Teste",
                    "1",
                    "pt",
                    "common",
                    "https://example.test/card.jpg",
                ),
            )
            card_id = cursor.lastrowid
            conn.commit()

        listing_id = None
        try:
            status, created = self.request(
                "POST",
                "/api/listings",
                {
                    "card_id": card_id,
                    "title": "Impressão em português",
                    "condition": "NM",
                    "mode": "venda",
                    # O cliente tenta mentir; o catálogo deve prevalecer.
                    "language": "en",
                },
                csrf=self.csrf,
            )
            self.assertEqual(status, 201)
            listing_id = created["id"]

            status, portuguese = self.request(
                "GET",
                "/api/listings?lang=pt&limit=100",
            )
            self.assertEqual(status, 200)
            selected = next(
                item
                for item in portuguese["listings"]
                if item["id"] == listing_id
            )
            self.assertEqual(selected["language"], "pt")
            self.assertTrue(
                all(item["language"].lower() == "pt"
                    for item in portuguese["listings"])
            )

            status, english = self.request(
                "GET",
                "/api/listings?lang=en&limit=100",
            )
            self.assertEqual(status, 200)
            self.assertNotIn(
                listing_id,
                {item["id"] for item in english["listings"]},
            )
        finally:
            with closing(get_connection(self.db)) as conn:
                if listing_id is not None:
                    conn.execute(
                        "DELETE FROM listings WHERE id = ?",
                        (listing_id,),
                    )
                conn.execute(
                    "DELETE FROM cards WHERE id = ?",
                    (card_id,),
                )
                conn.commit()

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

    def test_matching_respects_minimum_condition(self):
        """Condição mínima aceita exemplares melhores, mas rejeita piores."""

        self.login_demo()

        # Lightning Bolt do fixture está em SP. Um desejo por NM não deve casar.
        status, created = self.request(
            "POST",
            "/api/wants",
            {
                "card_id": 3,
                "desired_condition": "NM",
                "mode": "compra",
            },
            csrf=self.csrf,
        )
        self.assertEqual(status, 201)

        status, matches = self.request("GET", "/api/matches")
        self.assertEqual(status, 200)
        self.assertFalse(
            any(item["want_id"] == created["id"] for item in matches["matches"])
        )

        status, _ = self.request(
            "POST",
            "/api/wants",
            {
                "card_id": 3,
                "desired_condition": "SP",
                "mode": "compra",
            },
            csrf=self.csrf,
        )
        self.assertEqual(status, 201)

        status, matches = self.request("GET", "/api/matches")
        self.assertTrue(
            any(item["want_id"] == created["id"] for item in matches["matches"])
        )

        self.request(
            "DELETE",
            f"/api/wants/{created['id']}",
            csrf=self.csrf,
        )

    def test_cors_preflight_allows_only_configured_origin(self):
        """Frontend externo recebe CORS apenas para a origem autorizada."""

        allowed = "https://xoykor.github.io"
        with patch.dict(
            "os.environ",
            {"MANAPONTE_ALLOWED_ORIGIN": allowed},
            clear=False,
        ):
            connection = http.client.HTTPConnection(
                "127.0.0.1",
                self.port,
                timeout=4,
            )
            connection.request(
                "OPTIONS",
                "/api/auth/login",
                headers={
                    "Origin": allowed,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type",
                },
            )
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 204)
            self.assertEqual(
                response.getheader("Access-Control-Allow-Origin"),
                allowed,
            )
            self.assertEqual(
                response.getheader("Access-Control-Allow-Credentials"),
                "true",
            )
            self.assertIn(
                "PATCH",
                response.getheader("Access-Control-Allow-Methods"),
            )
            connection.close()

            connection = http.client.HTTPConnection(
                "127.0.0.1",
                self.port,
                timeout=4,
            )
            connection.request(
                "OPTIONS",
                "/api/auth/login",
                headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 204)
            self.assertIsNone(
                response.getheader("Access-Control-Allow-Origin")
            )
            connection.close()

    def test_public_routes(self):
        """Rotas públicas respondem sem sessão e servem a página inicial."""

        status, health = self.request("GET", "/api/health")
        self.assertEqual((status, health["status"]), (200, "ok"))

        status, home = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"ManaPonte", home)

        status, listings_page = self.request("GET", "/anuncios.html")
        self.assertEqual(status, 200)
        self.assertIn(b"Todos os an", listings_page)

        status, profile_page = self.request("GET", "/perfil.html?user=2")
        self.assertEqual(status, 200)
        self.assertIn(b"Perfil", profile_page)

        status, listing_page = self.request("GET", "/anuncio.html?id=2")
        self.assertEqual(status, 200)
        self.assertIn(b"An", listing_page)

        status, autocomplete_script = self.request("GET", "/card-autocomplete.js")
        self.assertEqual(status, 200)
        self.assertIn(b"autocomplete", autocomplete_script.lower())

        status, detail_script = self.request("GET", "/listing-detail.js")
        self.assertEqual(status, 200)
        self.assertIn(b"listingDetail", detail_script)

        status, preview_script = self.request("GET", "/card-preview.js")
        self.assertEqual(status, 200)
        self.assertIn(b"ManaPonteCardPreview", preview_script)

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

    def test_advanced_listing_filters_and_sorting(self):
        """Condição, faixa de preço e ordenação são aplicadas pela API."""

        status, data = self.request(
            "GET",
            "/api/listings?condition=NM&min_price=5&max_price=220"
            "&sort=price_asc&limit=100",
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["listings"])
        prices = [item["price_cents"] for item in data["listings"]]
        self.assertTrue(all(item["condition"] == "NM" for item in data["listings"]))
        self.assertTrue(all(500 <= price <= 22000 for price in prices))
        self.assertEqual(prices, sorted(prices))

        status, invalid = self.request(
            "GET",
            "/api/listings?min_price=100&max_price=10",
        )
        self.assertEqual(status, 400)
        self.assertIn("mínimo", invalid["error"])

    def test_wishlist_language_restricts_oracle_matches(self):
        """Wishlist aceita reimpressões, mas respeita o idioma desejado."""

        self.login_demo()

        with closing(get_connection(self.db)) as conn:
            english = conn.execute(
                "SELECT oracle_id FROM cards WHERE id = 3"
            ).fetchone()
            cursor = conn.execute(
                """
                INSERT INTO cards(
                    scryfall_id, oracle_id, name, set_code, set_name,
                    collector_number, language, rarity, image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "bolt-pt-regression",
                    english["oracle_id"],
                    "Lightning Bolt",
                    "tst",
                    "Teste PT",
                    "99",
                    "pt",
                    "common",
                    "https://example.test/bolt-pt.jpg",
                ),
            )
            portuguese_card_id = cursor.lastrowid
            listing = conn.execute(
                """
                INSERT INTO listings(
                    card_id, user_id, title, description, price_cents,
                    condition, language, mode
                ) VALUES (?, 2, ?, '', 1300, 'NM', 'pt', 'venda')
                """,
                (portuguese_card_id, "Bolt português"),
            )
            portuguese_listing_id = listing.lastrowid
            conn.commit()

        want_id = None
        try:
            status, created = self.request(
                "POST",
                "/api/wants",
                {
                    "card_id": 3,
                    "desired_condition": "SP",
                    "desired_language": "pt",
                    "mode": "compra",
                },
                csrf=self.csrf,
            )
            self.assertEqual(status, 201)
            want_id = created["id"]

            status, matches = self.request("GET", "/api/matches")
            self.assertEqual(status, 200)
            own_matches = [
                item for item in matches["matches"]
                if item["want_id"] == want_id
            ]
            self.assertTrue(own_matches)
            self.assertTrue(
                all(item["language"].lower() == "pt" for item in own_matches)
            )
            self.assertIn(
                portuguese_listing_id,
                {item["listing_id"] for item in own_matches},
            )

            status, _ = self.request(
                "POST",
                "/api/wants",
                {
                    "card_id": 3,
                    "desired_condition": "SP",
                    "desired_language": "en",
                    "mode": "compra",
                },
                csrf=self.csrf,
            )
            self.assertEqual(status, 201)

            status, matches = self.request("GET", "/api/matches")
            own_matches = [
                item for item in matches["matches"]
                if item["want_id"] == want_id
            ]
            self.assertTrue(own_matches)
            self.assertTrue(
                all(item["language"].lower() == "en" for item in own_matches)
            )
        finally:
            if want_id is not None:
                self.request(
                    "DELETE",
                    f"/api/wants/{want_id}",
                    csrf=self.csrf,
                )
            with closing(get_connection(self.db)) as conn:
                conn.execute(
                    "DELETE FROM listings WHERE id = ?",
                    (portuguese_listing_id,),
                )
                conn.execute(
                    "DELETE FROM cards WHERE id = ?",
                    (portuguese_card_id,),
                )
                conn.commit()

    def test_public_profile_contains_stats_join_date_and_wants(self):
        """Perfil público traz data de entrada, contagens e wishlist pública."""

        status, profile = self.request("GET", "/api/users/1")
        self.assertEqual(status, 200)
        self.assertIn("created_at", profile["user"])
        self.assertGreaterEqual(profile["stats"]["listing_count"], 1)
        self.assertGreaterEqual(profile["stats"]["want_count"], 1)
        self.assertEqual(
            profile["stats"]["listing_count"],
            len(profile["listings"]),
        )
        self.assertEqual(
            profile["stats"]["want_count"],
            len(profile["wants"]),
        )
        self.assertTrue(
            any(item["name"] == "Rhystic Study" for item in profile["wants"])
        )
