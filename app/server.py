"""Servidor HTTP, API REST e autenticação por sessão.

O projeto usa apenas a biblioteca padrão do Python para manter o protótipo
fácil de executar localmente. Cada método do handler representa uma pequena
parte do contrato HTTP da aplicação.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import threading
import time
from collections.abc import Mapping
from collections import defaultdict, deque
from contextlib import closing
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .auth import (
    create_session,
    csrf_matches,
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
from .catalog import search_scryfall, upsert_rows
from .db import (
    DEFAULT_DB_PATH,
    get_accounts_connection,
    get_cards_connection,
    get_connection,
    get_listings_app_connection,
    init_db,
    legacy_env_db_path,
    resolve_db_path,
    resolve_db_paths,
)


# Arquivos estáticos são servidos pelo mesmo processo da API durante o
# desenvolvimento local. O GitHub Pages publica essa pasta separadamente.
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

# O corpo de uma requisição JSON não pode ultrapassar 32 KiB no protótipo.
MAX_BODY = 32 * 1024

# Sessões novas duram uma semana, salvo configuração diferente no chamador.
SESSION_TTL = 7 * 24 * 60 * 60

# Estados aceitos pelo formulário de cadastro.
BRAZIL_STATES = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}

# O login usa este hash quando o usuário não existe, evitando que essa
# diferença seja facilmente percebida pelo tempo de resposta.
DUMMY_PASSWORD_HASH = hash_password("InvalidAccount!2026")

# Busca remota é armazenada por alguns minutos para não repetir a mesma
# chamada ao Scryfall em cada tecla digitada no seletor de cartas.
REMOTE_CARD_CACHE: dict[tuple[str, str, str], tuple[float, list[tuple]]] = {}
REMOTE_CARD_CACHE_LOCK = threading.Lock()
REMOTE_CARD_CACHE_TTL = 300


def remote_search_enabled() -> bool:
    """Informa se o fallback/enriquecimento remoto está habilitado."""

    disabled_values = {"0", "false", "no", "off"}
    configured_value = os.environ.get("MANAPONTE_REMOTE_SEARCH", "1")
    return configured_value.lower() not in disabled_values


def remote_cards(
    query: str,
    set_code: str | None = None,
    language: str | None = None,
) -> list[tuple]:
    """Busca cartas remotamente, reutilizando respostas recentes em memória."""

    cache_key = (
        query.strip().lower(),
        (set_code or "").lower(),
        (language or "").lower(),
    )
    now = time.monotonic()

    # O lock protege apenas a leitura curta do dicionário; nunca seguramos o
    # lock durante uma chamada de rede lenta.
    with REMOTE_CARD_CACHE_LOCK:
        cached = REMOTE_CARD_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

    try:
        found_cards = search_scryfall(query, set_code, language)
    except Exception as error:  # A API local deve continuar útil sem Scryfall.
        print(f"Busca remota do catálogo indisponível: {error}")
        found_cards = []

    # Mesmo uma resposta vazia é armazenada por alguns minutos para evitar
    # repetir uma consulta que acabou de falhar ou não encontrou cartas.
    with REMOTE_CARD_CACHE_LOCK:
        REMOTE_CARD_CACHE[cache_key] = (
            now + REMOTE_CARD_CACHE_TTL,
            found_cards,
        )

    return found_cards


class LoginRateLimiter:
    """Rate limiter simples em memória para tentativas de login."""

    def __init__(self, limit: int = 5, window: int = 900):
        # ``limit`` é o número máximo de falhas dentro de ``window`` segundos.
        self.limit = limit
        self.window = window

        # Cada chave guarda os horários das tentativas que ainda podem contar.
        self.failures: defaultdict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        """Remove falhas antigas da fila da chave informada."""

        cutoff = now - self.window
        while self.failures[key] and self.failures[key][0] <= cutoff:
            self.failures[key].popleft()

    def blocked(self, key: str) -> bool:
        """Informa se a chave já atingiu o limite de falhas."""

        with self.lock:
            now = time.time()
            self._prune(key, now)
            return len(self.failures[key]) >= self.limit

    def fail(self, key: str) -> int:
        """Registra uma falha e retorna o total atual de falhas."""

        with self.lock:
            now = time.time()
            self._prune(key, now)
            self.failures[key].append(now)
            return len(self.failures[key])

    def success(self, key: str) -> None:
        """Apaga o histórico de falhas depois de um login correto."""

        with self.lock:
            self.failures.pop(key, None)


def positive_int(value, default: int, maximum: int) -> int:
    """Converte um parâmetro em inteiro positivo dentro de um limite."""

    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def rows(cursor) -> list[dict]:
    """Converte todas as linhas SQLite do cursor em dicionários simples."""

    return [dict(row) for row in cursor.fetchall()]


class ManaPonteHandler(BaseHTTPRequestHandler):
    """Handler HTTP com rotas da API e arquivos estáticos."""

    # A fábrica ``create_server`` substitui este caminho por banco de teste
    # quando necessário. Ele também identifica o modo legado de arquivo único.
    db_path = DEFAULT_DB_PATH
    split_databases = False
    cards_db_path = None
    accounts_db_path = None
    listings_db_path = None

    # Cada servidor recebe seu próprio limiter para os testes e para processos
    # diferentes não compartilharem estado acidentalmente.
    rate_limiter = LoginRateLimiter()

    def log_message(self, fmt, *args):
        """Mantém os logs curtos e legíveis no terminal local."""

        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(
        self,
        payload,
        status: int | HTTPStatus = HTTPStatus.OK,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """Serializa e envia uma resposta JSON com headers básicos."""

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")

        # Respostas de autenticação nunca devem ser reutilizadas pelo cache.
        cache_control = (
            "no-store"
            if self.path.startswith("/api/auth/")
            else "no-cache"
        )
        self.send_header("Cache-Control", cache_control)

        for name, value in headers:
            self.send_header(name, value)

        self.end_headers()
        self.wfile.write(body)

    def params(self) -> dict[str, str]:
        """Retorna o primeiro valor de cada parâmetro da query string."""

        query_string = urlsplit(self.path).query
        parsed = parse_qs(query_string)
        return {key: values[0] for key, values in parsed.items()}

    def read_json(self) -> dict:
        """Lê e valida o corpo JSON de uma requisição.

        O servidor aceita somente objetos JSON, não arrays ou valores simples,
        porque todas as rotas mutáveis esperam campos nomeados.
        """

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Content-Length inválido") from error

        if content_length <= 0:
            raise ValueError("Corpo JSON ausente")
        if content_length > MAX_BODY:
            raise OverflowError("Corpo JSON maior que 32 KiB")

        data = json.loads(self.rfile.read(content_length))
        if not isinstance(data, dict):
            raise ValueError("O corpo deve ser um objeto JSON")

        return data

    def session_token(self) -> str | None:
        """Extrai o token da sessão do cookie HttpOnly."""

        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            # Cookies malformados são tratados como ausência de sessão.
            return None

        if "mp_session" not in cookie:
            return None
        return cookie["mp_session"].value

    def accounts_path(self):
        """Retorna o banco que contém usuários e sessões."""

        return self.accounts_db_path if self.split_databases else self.db_path

    def cards_path(self):
        """Retorna o banco que contém o catálogo de cartas."""

        return self.cards_db_path if self.split_databases else self.db_path

    def cards_table(self) -> str:
        """Nome qualificado da tabela de cartas para o modo atual."""

        return "catalog.cards" if self.split_databases else "cards"

    def users_table(self) -> str:
        """Nome qualificado da tabela de usuários para o modo atual."""

        return "accounts.users" if self.split_databases else "users"

    def account_connection(self):
        """Abre a conexão do banco de contas."""

        return (
            get_accounts_connection(self.accounts_path())
            if self.split_databases
            else get_connection(self.accounts_path())
        )

    def cards_connection(self):
        """Abre a conexão do banco de cartas."""

        return (
            get_cards_connection(self.cards_path())
            if self.split_databases
            else get_connection(self.cards_path())
        )

    def listings_connection(self):
        """Abre anúncios e, quando necessário, anexa cartas e contas."""

        if not self.split_databases:
            return get_connection(self.db_path)
        return get_listings_app_connection(
            self.listings_db_path,
            self.cards_db_path,
            self.accounts_db_path,
        )

    def current_session(self) -> dict | None:
        """Busca no banco a sessão correspondente ao cookie atual."""

        return get_session(self.session_token(), self.accounts_path())

    def session_cookie(self, token: str, max_age: int = SESSION_TTL) -> str:
        """Monta o cookie de sessão com atributos de segurança."""

        secure_values = {"1", "true", "yes"}
        secure = os.environ.get("MANAPONTE_SECURE_COOKIES", "").lower() in secure_values
        cookie = (
            f"mp_session={token}; Path=/; Max-Age={max_age}; "
            "HttpOnly; SameSite=Lax"
        )
        return cookie + ("; Secure" if secure else "")

    def do_GET(self) -> None:
        """Despacha rotas GET da API ou serve um arquivo estático."""

        path = urlsplit(self.path).path

        try:
            if path == "/api/health":
                return self.send_json({"status": "ok", "service": "ManaPonte"})
            if path == "/api/auth/me":
                return self.get_me()
            if path == "/api/cards":
                return self.get_cards()
            if path == "/api/sets":
                return self.get_sets()
            if path == "/api/listings":
                return self.get_listings()
            if path == "/api/matches":
                return self.get_matches()
            if path.startswith("/api/"):
                return self.send_json({"error": "Rota não encontrada"}, 404)

            return self.serve_static(path)
        except (ValueError, TypeError) as error:
            # Erros de parâmetros chegam ao cliente como HTTP 400.
            return self.send_json({"error": str(error)}, 400)

    def do_POST(self) -> None:
        """Despacha rotas POST de autenticação e criação de ofertas."""

        path = urlsplit(self.path).path

        try:
            content_length = int(self.headers.get("Content-Length", "0"))

            # Logout não precisa de corpo; as demais rotas POST precisam.
            if path == "/api/auth/logout" and content_length == 0:
                data = {}
            else:
                data = self.read_json()

            if path == "/api/auth/register":
                return self.register(data)
            if path == "/api/auth/login":
                return self.login(data)
            if path == "/api/auth/logout":
                return self.logout()
            if path == "/api/listings":
                return self.create_listing(data)

            return self.send_json({"error": "Rota não encontrada"}, 404)
        except OverflowError as error:
            return self.send_json(
                {"error": str(error)},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def auth_payload(self, session: dict) -> dict:
        """Seleciona os dados que podem voltar para o navegador."""

        return {
            "user": {
                "id": session["user_id"],
                "username": session["username"],
                "email": session["email"],
                "display_name": session["display_name"],
                "city": session["city"],
                "state": session["state"],
                "email_verified": bool(session["email_verified"]),
            },
            "csrf_token": session["csrf_token"],
        }

    def get_me(self) -> None:
        """Retorna a identidade autenticada ou HTTP 401."""

        session = self.current_session()
        if not session:
            return self.send_json({"error": "Não autenticado"}, 401)

        return self.send_json(self.auth_payload(session))

    def register(self, data: dict) -> None:
        """Valida e cria uma conta, iniciando sua sessão."""

        username = normalize_username(data.get("username", ""))
        email = normalize_email(data.get("email", ""))
        password = data.get("password", "")
        display_name = str(data.get("display_name", "")).strip()
        city = str(data.get("city", "")).strip()
        state = str(data.get("state", "")).strip().upper()

        if not valid_username(username):
            raise ValueError(
                "Usuário deve ter 3–30 caracteres: letras, números, _, . ou -"
            )
        if not valid_email(email):
            raise ValueError("E-mail inválido")
        if not validate_password(password):
            raise ValueError(
                "Senha deve ter 12–128 caracteres, maiúscula, minúscula, "
                "número e símbolo"
            )
        if (
            not 2 <= len(display_name) <= 80
            or not 2 <= len(city) <= 80
            or state not in BRAZIL_STATES
        ):
            raise ValueError("Nome, cidade ou UF inválidos")

        connection = self.account_connection()
        try:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO users(
                        username,
                        email,
                        display_name,
                        city,
                        state,
                        password_hash,
                        email_verified,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                    """,
                    (
                        username,
                        email,
                        display_name,
                        city,
                        state,
                        hash_password(password),
                    ),
                )
                connection.commit()
                user_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                return self.send_json(
                    {"error": "Já existe uma conta com esses dados"},
                    409,
                )
        finally:
            connection.close()

        # Criar a sessão depois do commit garante que o usuário já exista.
        session_data = create_session(user_id, self.accounts_path(), SESSION_TTL)
        session = get_session(session_data["token"], self.accounts_path())

        return self.send_json(
            self.auth_payload(session),
            201,
            (("Set-Cookie", self.session_cookie(session_data["token"])),),
        )

    def login(self, data: dict) -> None:
        """Autentica usuário por nome ou e-mail e cria uma sessão."""

        identifier = normalize_email(data.get("identifier", ""))
        password = data.get("password", "")
        key = f"{self.client_address[0]}:{identifier[:254]}"

        if self.rate_limiter.blocked(key):
            return self.send_json(
                {"error": "Muitas tentativas. Aguarde 15 minutos."},
                429,
            )

        connection = self.account_connection()
        try:
            user = connection.execute(
                """
                SELECT id, password_hash
                FROM users
                WHERE username = ? OR email = ?
                """,
                (identifier, identifier),
            ).fetchone()
        finally:
            connection.close()

        # Verificar o hash fictício mantém custo semelhante mesmo quando o
        # identificador não existe.
        password_hash = user["password_hash"] if user else DUMMY_PASSWORD_HASH
        password_is_valid = verify_password(password, password_hash)

        if not user or not password_is_valid:
            failures = self.rate_limiter.fail(key)
            if failures >= self.rate_limiter.limit:
                return self.send_json(
                    {"error": "Muitas tentativas. Aguarde 15 minutos."},
                    429,
                )
            return self.send_json({"error": "Credenciais inválidas"}, 401)

        self.rate_limiter.success(key)
        session_data = create_session(user["id"], self.accounts_path(), SESSION_TTL)
        session = get_session(session_data["token"], self.accounts_path())

        return self.send_json(
            self.auth_payload(session),
            200,
            (("Set-Cookie", self.session_cookie(session_data["token"])),),
        )

    def logout(self) -> None:
        """Revoga a sessão atual depois de validar o token CSRF."""

        token = self.session_token()
        session = self.current_session()

        if not session:
            return self.send_json({"error": "Não autenticado"}, 401)
        if not csrf_matches(session, self.headers.get("X-CSRF-Token")):
            return self.send_json({"error": "Token CSRF inválido"}, 403)

        revoke_session(token, self.accounts_path())
        return self.send_json(
            {"message": "Sessão encerrada"},
            200,
            (("Set-Cookie", self.session_cookie("", 0)),),
        )

    def get_cards(self) -> None:
        """Busca impressões locais e enriquece a busca pelo Scryfall.

        O enriquecimento acontece para consultas com três ou mais caracteres.
        Assim, um catálogo inicial pequeno não esconde outras impressões que
        ainda não foram gravadas localmente.
        """

        query_params = self.params()
        page = positive_int(query_params.get("page"), 1, 100000)
        limit = positive_int(query_params.get("limit"), 24, 100)

        clauses = []
        values = []

        search = query_params.get("q", "").strip()[:100]
        set_code = query_params.get("set", "").strip()[:16]
        language = query_params.get("lang", "").strip()[:8]

        if search:
            clauses.append("name LIKE ? COLLATE NOCASE")
            values.append(f"%{search}%")
        if set_code:
            clauses.append("set_code = ? COLLATE NOCASE")
            values.append(set_code)
        if language:
            clauses.append("language = ?")
            values.append(language)

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        source = "local"

        connection = self.cards_connection()
        try:
            total = connection.execute(
                "SELECT COUNT(*) FROM cards" + where,
                values,
            ).fetchone()[0]

            if search and len(search) >= 3 and remote_search_enabled():
                imported = remote_cards(search, set_code, language)
                if imported:
                    upsert_rows(connection, imported)
                    connection.commit()
                    source = "scryfall"
                    total = connection.execute(
                        "SELECT COUNT(*) FROM cards" + where,
                        values,
                    ).fetchone()[0]

            found = rows(
                connection.execute(
                    """
                    SELECT
                        id,
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        language,
                        rarity,
                        image_url
                    FROM cards
                    """
                    + where
                    + " ORDER BY name, set_code, collector_number LIMIT ? OFFSET ?",
                    values + [limit, (page - 1) * limit],
                )
            )
        finally:
            connection.close()

        return self.send_json(
            {
                "cards": found,
                "page": page,
                "limit": limit,
                "total": total,
                "source": source,
            }
        )

    def get_sets(self) -> None:
        """Retorna todas as coleções presentes no catálogo local."""

        connection = self.cards_connection()
        try:
            found = rows(
                connection.execute(
                    """
                    SELECT
                        set_code,
                        set_name,
                        COUNT(*) AS card_count
                    FROM cards
                    GROUP BY set_code, set_name
                    ORDER BY set_name
                    """
                )
            )
        finally:
            connection.close()

        return self.send_json({"sets": found})

    def get_listings(self) -> None:
        """Retorna ofertas filtradas por carta, localidade e modalidade."""

        query_params = self.params()
        clauses = []
        values = []

        # Cada entrada liga um parâmetro público à coluna e ao conversor
        # esperados. Os valores continuam parametrizados pelo SQLite.
        filters = {
            "card_id": ("l.card_id = ?", int),
            "set": ("c.set_code = ? COLLATE NOCASE", str),
            "city": ("u.city = ? COLLATE NOCASE", str),
            "state": ("u.state = ? COLLATE NOCASE", str),
            "mode": ("l.mode = ?", str),
        }

        for key, (sql, converter) in filters.items():
            if query_params.get(key):
                clauses.append(sql)
                values.append(converter(query_params[key]))

        if query_params.get("card"):
            clauses.append("c.name LIKE ? COLLATE NOCASE")
            values.append(f"%{query_params['card'][:100]}%")

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        cards_table = self.cards_table()
        users_table = self.users_table()
        sql = (
            f"""
            SELECT
                l.id,
                l.card_id,
                c.name,
                c.set_code,
                c.set_name,
                c.image_url,
                u.username,
                u.display_name,
                u.city,
                u.state,
                l.title,
                l.description,
                l.price_cents,
                l.condition,
                l.language,
                l.mode,
                l.contact_url,
                l.created_at
            FROM listings AS l
            JOIN {cards_table} AS c ON c.id = l.card_id
            JOIN {users_table} AS u ON u.id = l.user_id
            """
            + where
            + " ORDER BY l.created_at DESC, l.id DESC"
        )

        connection = self.listings_connection()
        try:
            found = rows(connection.execute(sql, values))
        finally:
            connection.close()

        return self.send_json({"listings": found, "total": len(found)})

    def get_matches(self) -> None:
        """Retorna ofertas ligadas a uma impressão específica."""

        card_id = self.params().get("card_id")
        if not card_id:
            raise ValueError("card_id é obrigatório")

        connection = self.listings_connection()
        try:
            cards_table = self.cards_table()
            users_table = self.users_table()
            found = rows(
                connection.execute(
                    f"""
                    SELECT
                        l.id AS listing_id,
                        l.card_id,
                        c.name,
                        c.image_url,
                        l.title,
                        l.price_cents,
                        l.condition,
                        l.mode,
                        u.display_name,
                        u.city,
                        u.state
                    FROM listings AS l
                    JOIN {cards_table} AS c ON c.id = l.card_id
                    JOIN {users_table} AS u ON u.id = l.user_id
                    WHERE l.card_id = ?
                    ORDER BY u.state, u.city
                    """,
                    (int(card_id),),
                )
            )
        finally:
            connection.close()

        return self.send_json({"matches": found, "total": len(found)})

    def create_listing(self, data: dict) -> None:
        """Valida e cria uma oferta para o usuário da sessão atual."""

        session = self.current_session()
        if not session:
            return self.send_json({"error": "Faça login para anunciar"}, 401)
        if not csrf_matches(session, self.headers.get("X-CSRF-Token")):
            return self.send_json({"error": "Token CSRF inválido"}, 403)

        try:
            card_id = int(data["card_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("card_id é obrigatório e numérico") from error

        title = str(data.get("title", "")).strip()
        description = str(data.get("description", "")).strip()
        condition = data.get("condition", "NM")
        mode = data.get("mode", "venda")

        if not 3 <= len(title) <= 120 or len(description) > 1000:
            raise ValueError(
                "Título deve ter 3–120 caracteres e descrição no máximo 1000"
            )
        if condition not in {"NM", "SP", "MP", "HP", "DMG"}:
            raise ValueError("Condição ou modalidade inválida")
        if mode not in {"venda", "troca", "ambos"}:
            raise ValueError("Condição ou modalidade inválida")

        raw_price = data.get("price_cents")
        price_cents = None if raw_price in (None, "") else int(raw_price)
        if price_cents is not None and price_cents < 0:
            raise ValueError("Preço não pode ser negativo")

        connection = self.listings_connection()
        try:
            cards_table = self.cards_table()
            card_exists = connection.execute(
                f"SELECT 1 FROM {cards_table} WHERE id = ?",
                (card_id,),
            ).fetchone()
            if not card_exists:
                raise ValueError("Carta não encontrada")

            cursor = connection.execute(
                """
                INSERT INTO listings(
                    card_id,
                    user_id,
                    title,
                    description,
                    price_cents,
                    condition,
                    language,
                    mode,
                    contact_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    session["user_id"],
                    title,
                    description,
                    price_cents,
                    condition,
                    str(data.get("language", "en"))[:8],
                    mode,
                    str(data.get("contact_url", ""))[:300],
                ),
            )
            connection.commit()
            listing_id = cursor.lastrowid
        finally:
            connection.close()

        return self.send_json(
            {"id": listing_id, "message": "Anúncio criado"},
            201,
        )

    def serve_static(self, path: str) -> None:
        """Serve um arquivo de ``public/`` sem permitir sair do diretório."""

        # A raiz do site aponta para index.html; outros caminhos são relativos
        # à pasta public.
        relative_path = "index.html" if path == "/" else path.lstrip("/")
        candidate = (PUBLIC_DIR / relative_path).resolve()
        public_root = PUBLIC_DIR.resolve()

        # O teste de parents bloqueia tentativas de acessar ../etc/passwd.
        is_inside_public = public_root in candidate.parents or candidate == public_root
        if not is_inside_public:
            return self.send_error(403)
        if not candidate.is_file():
            return self.send_error(404)

        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0]

        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    db_path: str | Path | Mapping[str, str | Path | None] | None = None,
    db_paths: Mapping[str, str | Path | None] | None = None,
) -> ThreadingHTTPServer:
    """Cria um servidor usando bancos separados ou o modo legado.

    O modo novo é o padrão e aceita ``db_paths`` com as chaves ``cards``,
    ``accounts`` e ``listings``. Um caminho único em ``db_path`` mantém a
    compatibilidade com a API anterior e usa um único SQLite.
    """

    # Aceitar o mapping também no argumento antigo torna a transição menos
    # surpreendente para scripts que já passavam uma configuração posicional.
    if isinstance(db_path, Mapping):
        if db_paths is not None:
            raise ValueError("Informe db_path ou db_paths, não ambos")
        db_paths = db_path
        db_path = None

    if db_path is not None and db_paths is not None:
        raise ValueError("Informe db_path ou db_paths, não ambos")

    if db_path is None and db_paths is None:
        db_path = legacy_env_db_path()

    if db_path is None:
        paths = resolve_db_paths(db_paths)
        init_db(paths)
        handler_options = {
            "db_path": DEFAULT_DB_PATH,
            "split_databases": True,
            "cards_db_path": paths["cards"],
            "accounts_db_path": paths["accounts"],
            "listings_db_path": paths["listings"],
        }
    else:
        legacy_path = resolve_db_path(db_path)
        init_db(legacy_path)
        handler_options = {
            "db_path": legacy_path,
            "split_databases": False,
            "cards_db_path": None,
            "accounts_db_path": None,
            "listings_db_path": None,
        }

    handler_options["rate_limiter"] = LoginRateLimiter()

    configured_handler = type(
        "ConfiguredManaPonteHandler",
        (ManaPonteHandler,),
        handler_options,
    )
    return ThreadingHTTPServer((host, port), configured_handler)


def main() -> None:
    """Inicializa o banco e mantém o servidor rodando até Ctrl+C."""

    init_db()

    host = os.environ.get("MANAPONTE_HOST", "127.0.0.1")
    port = int(os.environ.get("MANAPONTE_PORT", "8000"))
    server = create_server(host, port)

    print(f"ManaPonte em http://{server.server_address[0]}:{server.server_address[1]}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # Ctrl+C é a forma normal de desligar o servidor no desenvolvimento.
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
