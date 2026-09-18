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

# Busca remota é armazenada em memória para não repetir a mesma chamada ao
# Scryfall em cada tecla digitada no seletor de cartas. O conjunto é limitado
# e elimina chamadas duplicadas enquanto uma consulta ainda está em voo.
REMOTE_CARD_CACHE_MAX_ENTRIES = 256
REMOTE_CARD_CACHE: dict[tuple[str, str, str], tuple[float, list[tuple]]] = {}
# Idade (tempo monotônico) de cada entrada, usada para evictar a mais antiga.
REMOTE_CARD_CACHE_AGE: dict[tuple[str, str, str], float] = {}
# Resultados de consultas ainda em voo, compartilhados entre requisições
# idênticas para deduplicar chamadas concorrentes à API remota.
REMOTE_CARD_CACHE_PENDING: dict[tuple[str, str, str], threading.Event] = {}
REMOTE_CARD_CACHE_LOCK = threading.Lock()
REMOTE_CARD_CACHE_TTL = 300


def remote_search_enabled() -> bool:
    """Informa se o fallback/enriquecimento remoto está habilitado."""

    disabled_values = {"0", "false", "no", "off"}
    configured_value = os.environ.get("MANAPONTE_REMOTE_SEARCH", "1")
    return configured_value.lower() not in disabled_values


def _remote_cache_key(
    query: str,
    set_code: str | None,
    language: str | None,
) -> tuple[str, str, str]:
    """Chave de cache normalizada para consultas equivalentes baterem."""

    return (
        query.strip().lower(),
        (set_code or "").lower(),
        (language or "").lower(),
    )


def _remote_remove_expired_locked(now: float) -> None:
    """Remove entradas expiradas; o chamador já deve possuir o lock."""

    expired_keys = [
        key
        for key, (expires_at, _result) in REMOTE_CARD_CACHE.items()
        if expires_at <= now
    ]
    for key in expired_keys:
        REMOTE_CARD_CACHE.pop(key, None)
        REMOTE_CARD_CACHE_AGE.pop(key, None)
        pending_event = REMOTE_CARD_CACHE_PENDING.pop(key, None)
        if pending_event is not None:
            # Uma entrada expirada não pode deixar um evento órfão prendendo
            # aguardantes; uma nova chamada poderá iniciar outra geração.
            pending_event.set()


def _remote_evict_oldest_locked() -> None:
    """Mantém o cache no limite; o chamador já deve possuir o lock."""

    while len(REMOTE_CARD_CACHE) > REMOTE_CARD_CACHE_MAX_ENTRIES:
        oldest_key = min(
            REMOTE_CARD_CACHE,
            key=lambda key: REMOTE_CARD_CACHE_AGE.get(key, 0.0),
        )
        REMOTE_CARD_CACHE.pop(oldest_key, None)
        REMOTE_CARD_CACHE_AGE.pop(oldest_key, None)

        # Em condições normais consultas pendentes ainda não estão no cache,
        # mas liberar o evento aqui evita deixar um aguardante bloqueado se
        # os mapas forem alterados durante uma evicção.
        pending_event = REMOTE_CARD_CACHE_PENDING.pop(oldest_key, None)
        if pending_event is not None:
            pending_event.set()


def _remote_evict_oldest() -> None:
    """Mantém o cache no limite, podendo ser chamada por testes e diagnósticos."""

    with REMOTE_CARD_CACHE_LOCK:
        _remote_evict_oldest_locked()


def remote_cards(
    query: str,
    set_code: str | None = None,
    language: str | None = None,
) -> list[tuple]:
    """Busca cartas remotamente com cache limitado e deduplicação em voo."""

    cache_key = _remote_cache_key(query, set_code, language)
    with REMOTE_CARD_CACHE_LOCK:
        now = time.monotonic()
        _remote_remove_expired_locked(now)
        cached = REMOTE_CARD_CACHE.get(cache_key)
        if cached is not None and cached[0] > now:
            # Atualiza a idade para que entradas recentes não sejam evitadas.
            REMOTE_CARD_CACHE_AGE[cache_key] = now
            return cached[1]

        event = REMOTE_CARD_CACHE_PENDING.get(cache_key)
        is_fetcher = event is None
        if is_fetcher:
            # A criação e a consulta do evento acontecem no mesmo trecho
            # protegido. Assim, apenas uma requisição se torna responsável por
            # chamar a API remota mesmo sob concorrência.
            event = threading.Event()
            REMOTE_CARD_CACHE_PENDING[cache_key] = event

    if not is_fetcher:
        # Outra requisição já está buscando esta mesma consulta. Aguarda o
        # resultado compartilhado em vez de repetir a chamada à API remota.
        completed = event.wait(timeout=REMOTE_CARD_CACHE_TTL)
        with REMOTE_CARD_CACHE_LOCK:
            if not completed and REMOTE_CARD_CACHE_PENDING.get(cache_key) is event:
                # Um fetcher que ultrapassou o TTL não deve manter novas
                # requisições presas para sempre. O fetcher original verifica
                # a identidade antes de gravar o resultado, então uma nova
                # geração pode assumir a consulta com segurança.
                REMOTE_CARD_CACHE_PENDING.pop(cache_key, None)
                event.set()
            cached = REMOTE_CARD_CACHE.get(cache_key)
            now = time.monotonic()
            if cached is not None and cached[0] > now:
                REMOTE_CARD_CACHE_AGE[cache_key] = now
                return cached[1]
        # Falhas, expiração ou evicção não devem transformar o sinal em uma
        # resposta antiga. O resultado vazio mantém o contrato da busca.
        return []

    found_cards: list[tuple] = []
    try:
        found_cards = search_scryfall(query, set_code, language)
    except Exception as error:  # A API local deve continuar útil sem Scryfall.
        print(f"Busca remota do catálogo indisponível: {error}")

    finally:
        # O evento sempre é sinalizado, inclusive quando a API remota falha.
        # A identidade impede que uma evicção seguida de uma nova consulta
        # apague o evento da geração mais recente.
        with REMOTE_CARD_CACHE_LOCK:
            pending_event = REMOTE_CARD_CACHE_PENDING.get(cache_key)
            try:
                if pending_event is event:
                    cached_at = time.monotonic()
                    REMOTE_CARD_CACHE[cache_key] = (
                        cached_at + REMOTE_CARD_CACHE_TTL,
                        found_cards,
                    )
                    REMOTE_CARD_CACHE_AGE[cache_key] = cached_at
                    _remote_evict_oldest_locked()
            finally:
                if pending_event is event:
                    REMOTE_CARD_CACHE_PENDING.pop(cache_key, None)
                event.set()

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


def normalize_public_phone(value: object) -> str | None:
    """Normaliza celular opcional para um formato seguro de contato público."""

    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None
    if len(raw) > 32:
        raise ValueError("Celular inválido")

    # Aceita a pontuação usual de telefone, mas persiste somente dígitos e,
    # quando informado, o sinal de código internacional.
    allowed = set("0123456789+()- .")
    if any(character not in allowed for character in raw):
        raise ValueError("Celular inválido")

    digits = "".join(character for character in raw if character.isdigit())
    if not 10 <= len(digits) <= 15:
        raise ValueError("Celular deve ter entre 10 e 15 dígitos")

    return f"+{digits}" if raw.startswith("+") else digits


def valid_contact_url(value: object) -> bool:
    """Informa se o contato é vazio ou uma URL HTTP(S) com host válido."""

    if value is None:
        return True
    if not isinstance(value, str):
        return False

    candidate = value.strip()
    if not candidate:
        return True

    # Espaços, controles e barras invertidas podem ser reinterpretados pelo
    # navegador e alterar a autoridade efetiva da URL.
    if any(
        character.isspace()
        or ord(character) < 0x20
        or ord(character) == 0x7F
        for character in candidate
    ) or "\\" in candidate:
        return False

    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        # Ler ``port`` também valida portas malformadas ou fora do intervalo.
        parsed.port
    except ValueError:
        return False

    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return False

    # ``urlsplit`` aceita alguns valores que não representam um host útil,
    # como apenas pontuação ou caracteres percent-encoded no host.
    if hostname.strip(".") == "" or any(
        character.isspace() or character in "/?#\\%" for character in hostname
    ):
        return False

    return True


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

    def allowed_cors_origin(self) -> str | None:
        """Retorna a origem permitida para uma chamada cross-origin."""

        origin = self.headers.get("Origin", "").strip()
        configured = {
            item.strip()
            for item in os.environ.get("MANAPONTE_ALLOWED_ORIGIN", "").split(",")
            if item.strip()
        }
        return origin if origin and origin in configured else None

    def send_cors_headers(self) -> None:
        """Emite CORS somente para origens explicitamente configuradas."""

        origin = self.allowed_cors_origin()
        if not origin:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")

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

        self.send_cors_headers()
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
        cross_site = (
            os.environ.get("MANAPONTE_CROSS_SITE_COOKIES", "").lower()
            in secure_values
        )
        if cross_site:
            secure = True
        same_site = "None" if cross_site else "Lax"
        cookie = (
            f"mp_session={token}; Path=/; Max-Age={max_age}; "
            f"HttpOnly; SameSite={same_site}"
        )
        return cookie + ("; Secure" if secure else "")

    def do_OPTIONS(self) -> None:
        """Responde ao preflight usado pelo frontend hospedado em outro domínio."""

        if not urlsplit(self.path).path.startswith("/api/"):
            return self.send_error(404)

        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_cors_headers()
        self.end_headers()

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
            if path == "/api/wants":
                return self.get_wants()
            if path == "/api/matches":
                return self.get_matches()
            if path.startswith("/api/users/"):
                user_id = path.removeprefix("/api/users/")
                if not user_id or "/" in user_id:
                    raise ValueError("ID de usuário inválido")
                return self.get_public_user(int(user_id))
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
            if path == "/api/wants":
                return self.create_want(data)

            return self.send_json({"error": "Rota não encontrada"}, 404)
        except OverflowError as error:
            return self.send_json(
                {"error": str(error)},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def do_PATCH(self) -> None:
        """Atualiza perfil ou anúncio pertencente ao usuário autenticado."""

        path = urlsplit(self.path).path
        try:
            data = self.read_json()
            if path == "/api/profile":
                return self.update_profile(data)
            if path.startswith("/api/listings/"):
                listing_id = path.removeprefix("/api/listings/")
                if not listing_id or "/" in listing_id:
                    raise ValueError("ID de anúncio inválido")
                return self.update_listing(int(listing_id), data)

            return self.send_json({"error": "Rota não encontrada"}, 404)
        except OverflowError as error:
            return self.send_json(
                {"error": str(error)},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def do_DELETE(self) -> None:
        """Remove recursos mutáveis pertencentes ao usuário autenticado."""

        path = urlsplit(self.path).path
        try:
            if path.startswith("/api/wants/"):
                want_id = path.removeprefix("/api/wants/")
                if not want_id or "/" in want_id:
                    raise ValueError("ID de desejo inválido")
                return self.delete_want(int(want_id))
            if path.startswith("/api/listings/"):
                listing_id = path.removeprefix("/api/listings/")
                if not listing_id or "/" in listing_id:
                    raise ValueError("ID de anúncio inválido")
                return self.delete_listing(int(listing_id))

            return self.send_json({"error": "Rota não encontrada"}, 404)
        except (ValueError, TypeError) as error:
            return self.send_json({"error": str(error)}, 400)

    def auth_payload(self, session: dict) -> dict:
        """Seleciona os dados que podem voltar para o navegador."""

        return {
            "user": {
                "id": session["user_id"],
                "username": session["username"],
                "email": session["email"],
                "display_name": session["display_name"],
                "phone": session.get("phone"),
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
        phone = normalize_public_phone(data.get("phone"))
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
                        phone,
                        city,
                        state,
                        password_hash,
                        email_verified,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                    """,
                    (
                        username,
                        email,
                        display_name,
                        phone,
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

    def update_profile(self, data: dict) -> None:
        """Atualiza os dados públicos básicos do usuário autenticado."""

        session = self.current_session()
        if not session:
            return self.send_json({"error": "Não autenticado"}, 401)
        if not csrf_matches(session, self.headers.get("X-CSRF-Token")):
            return self.send_json({"error": "Token CSRF inválido"}, 403)

        display_name = str(
            data.get("display_name", session["display_name"])
        ).strip()
        phone = normalize_public_phone(data.get("phone", session.get("phone")))
        city = str(data.get("city", session["city"])).strip()
        state = str(data.get("state", session["state"])).strip().upper()

        if (
            not 2 <= len(display_name) <= 80
            or not 2 <= len(city) <= 80
            or state not in BRAZIL_STATES
        ):
            raise ValueError("Nome, cidade ou UF inválidos")

        connection = self.account_connection()
        try:
            connection.execute(
                """
                UPDATE users
                SET display_name = ?, phone = ?, city = ?, state = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (display_name, phone, city, state, session["user_id"]),
            )
            connection.commit()
        finally:
            connection.close()

        refreshed = get_session(self.session_token(), self.accounts_path())
        return self.send_json(self.auth_payload(refreshed))

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
            "lang": ("c.language = ? COLLATE NOCASE", str),
            "city": ("u.city = ? COLLATE NOCASE", str),
            "state": ("u.state = ? COLLATE NOCASE", str),
        }

        for key, (sql, converter) in filters.items():
            if query_params.get(key):
                clauses.append(sql)
                values.append(converter(query_params[key]))

        mine = query_params.get("mine", "").strip().lower()
        if mine in {"1", "true", "yes"}:
            session = self.current_session()
            if not session:
                return self.send_json(
                    {"error": "Faça login para ver seus anúncios"},
                    401,
                )
            clauses.append("l.user_id = ?")
            values.append(session["user_id"])

        requested_mode = query_params.get("mode", "").strip()
        if requested_mode:
            if requested_mode == "venda":
                clauses.append("l.mode IN (?, ?)")
                values.extend(("venda", "ambos"))
            elif requested_mode == "troca":
                clauses.append("l.mode IN (?, ?)")
                values.extend(("troca", "ambos"))
            elif requested_mode == "ambos":
                clauses.append("l.mode = ?")
                values.append("ambos")
            else:
                raise ValueError("Modalidade inválida")

        page = positive_int(query_params.get("page"), 1, 100000)
        limit = positive_int(query_params.get("limit"), 24, 100)

        if query_params.get("card"):
            clauses.append("c.name LIKE ? COLLATE NOCASE")
            values.append(f"%{query_params['card'][:100]}%")

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        cards_table = self.cards_table()
        users_table = self.users_table()

        connection = self.listings_connection()
        try:
            # Contagem total respeita os filtros, para paginação sem perdas.
            total = connection.execute(
                f"SELECT COUNT(*) FROM listings AS l "
                f"JOIN {cards_table} AS c ON c.id = l.card_id "
                f"JOIN {users_table} AS u ON u.id = l.user_id {where}",
                values,
            ).fetchone()[0]

            sql = (
                f"""
                SELECT
                    l.id,
                    l.card_id,
                    l.user_id,
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
                    c.language AS language,
                    l.mode,
                    l.contact_url,
                    l.created_at
                FROM listings AS l
                JOIN {cards_table} AS c ON c.id = l.card_id
                JOIN {users_table} AS u ON u.id = l.user_id
                """
                + where
                + " ORDER BY l.created_at DESC, l.id DESC LIMIT ? OFFSET ?"
            )
            values = values + [limit, (page - 1) * limit]
            found = rows(connection.execute(sql, values))
        finally:
            connection.close()

        return self.send_json(
            {"listings": found, "total": total, "page": page, "limit": limit}
        )

    def get_public_user(self, user_id: int) -> None:
        """Retorna somente dados públicos do jogador e seus anúncios."""

        cards_table = self.cards_table()
        users_table = self.users_table()
        connection = self.listings_connection()
        try:
            user = connection.execute(
                f"""
                SELECT id, username, display_name, phone, city, state
                FROM {users_table}
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
            if not user:
                return self.send_json({"error": "Usuário não encontrado"}, 404)

            listings = rows(
                connection.execute(
                    f"""
                    SELECT
                        l.id,
                        l.card_id,
                        l.user_id,
                        c.name,
                        c.set_code,
                        c.set_name,
                        c.image_url,
                        l.title,
                        l.description,
                        l.price_cents,
                        l.condition,
                        c.language AS language,
                        l.mode,
                        l.created_at
                    FROM listings AS l
                    JOIN {cards_table} AS c ON c.id = l.card_id
                    WHERE l.user_id = ?
                    ORDER BY l.created_at DESC, l.id DESC
                    LIMIT 100
                    """,
                    (user_id,),
                )
            )
        finally:
            connection.close()

        return self.send_json(
            {
                "user": dict(user),
                "listings": listings,
            }
        )

    def get_wants(self) -> None:
        """Lista os desejos do usuário autenticado."""

        session = self.current_session()
        if not session:
            return self.send_json({"error": "Faça login para ver seus desejos"}, 401)

        query_params = self.params()
        page = positive_int(query_params.get("page"), 1, 100000)
        limit = positive_int(query_params.get("limit"), 24, 100)
        cards_table = self.cards_table()

        connection = self.listings_connection()
        try:
            total = connection.execute(
                "SELECT COUNT(*) FROM wants WHERE user_id = ?",
                (session["user_id"],),
            ).fetchone()[0]
            found = rows(
                connection.execute(
                    f"""
                    SELECT
                        w.id,
                        w.card_id,
                        c.oracle_id,
                        c.name,
                        c.set_code,
                        c.set_name,
                        c.collector_number,
                        c.language,
                        c.image_url,
                        w.max_price_cents,
                        w.desired_condition,
                        w.mode,
                        w.created_at
                    FROM wants AS w
                    JOIN {cards_table} AS c ON c.id = w.card_id
                    WHERE w.user_id = ?
                    ORDER BY w.created_at DESC, w.id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (session["user_id"], limit, (page - 1) * limit),
                )
            )
        finally:
            connection.close()

        return self.send_json(
            {"wants": found, "total": total, "page": page, "limit": limit}
        )

    def create_want(self, data: dict) -> None:
        """Cria ou atualiza um desejo do usuário autenticado."""

        session = self.current_session()
        if not session:
            return self.send_json({"error": "Faça login para salvar desejos"}, 401)
        if not csrf_matches(session, self.headers.get("X-CSRF-Token")):
            return self.send_json({"error": "Token CSRF inválido"}, 403)

        try:
            card_id = int(data["card_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("card_id é obrigatório e numérico") from error

        raw_max_price = data.get("max_price_cents")
        max_price_cents = (
            None if raw_max_price in (None, "") else int(raw_max_price)
        )
        if max_price_cents is not None and max_price_cents < 0:
            raise ValueError("Preço máximo não pode ser negativo")

        desired_condition = data.get("desired_condition")
        if desired_condition in ("", None):
            desired_condition = None
        elif desired_condition not in {"NM", "SP", "MP", "HP", "DMG"}:
            raise ValueError("Condição desejada inválida")

        mode = str(data.get("mode", "ambos")).strip().lower()
        if mode not in {"compra", "troca", "ambos"}:
            raise ValueError("Modalidade de desejo inválida")

        connection = self.listings_connection()
        try:
            cards_table = self.cards_table()
            card_exists = connection.execute(
                f"SELECT 1 FROM {cards_table} WHERE id = ?",
                (card_id,),
            ).fetchone()
            if not card_exists:
                raise ValueError("Carta não encontrada")

            connection.execute(
                """
                INSERT INTO wants(
                    card_id,
                    user_id,
                    max_price_cents,
                    desired_condition,
                    mode
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(card_id, user_id) DO UPDATE SET
                    max_price_cents = excluded.max_price_cents,
                    desired_condition = excluded.desired_condition,
                    mode = excluded.mode
                """,
                (
                    card_id,
                    session["user_id"],
                    max_price_cents,
                    desired_condition,
                    mode,
                ),
            )
            connection.commit()
            want_id = connection.execute(
                "SELECT id FROM wants WHERE card_id = ? AND user_id = ?",
                (card_id, session["user_id"]),
            ).fetchone()[0]
        finally:
            connection.close()

        return self.send_json(
            {"id": want_id, "message": "Desejo salvo"},
            201,
        )

    def delete_want(self, want_id: int) -> None:
        """Remove um desejo, sem permitir apagar o desejo de outro usuário."""

        session = self.current_session()
        if not session:
            return self.send_json({"error": "Faça login para remover desejos"}, 401)
        if not csrf_matches(session, self.headers.get("X-CSRF-Token")):
            return self.send_json({"error": "Token CSRF inválido"}, 403)

        connection = self.listings_connection()
        try:
            cursor = connection.execute(
                "DELETE FROM wants WHERE id = ? AND user_id = ?",
                (want_id, session["user_id"]),
            )
            connection.commit()
        finally:
            connection.close()

        if cursor.rowcount == 0:
            return self.send_json({"error": "Desejo não encontrado"}, 404)
        return self.send_json({"message": "Desejo removido"})

    def get_matches(self) -> None:
        """Cruza desejos com ofertas ou busca equivalentes de uma carta."""

        card_id = self.params().get("card_id")
        connection = self.listings_connection()
        try:
            cards_table = self.cards_table()
            users_table = self.users_table()

            if card_id:
                found = rows(
                    connection.execute(
                        f"""
                        SELECT
                            l.id AS listing_id,
                            l.card_id,
                            c.oracle_id,
                            c.name,
                            c.set_code,
                            c.set_name,
                            c.image_url,
                            l.title,
                            l.price_cents,
                            l.condition,
                            l.mode,
                            l.contact_url,
                            u.id AS user_id,
                            u.username,
                            u.display_name,
                            u.city,
                            u.state
                        FROM {cards_table} AS target
                        JOIN {cards_table} AS c
                          ON c.id = target.id
                          OR (
                              target.oracle_id IS NOT NULL
                              AND c.oracle_id = target.oracle_id
                          )
                        JOIN listings AS l ON l.card_id = c.id
                        JOIN {users_table} AS u ON u.id = l.user_id
                        WHERE target.id = ?
                        ORDER BY u.state, u.city, l.id DESC
                        """,
                        (int(card_id),),
                    )
                )
                return self.send_json(
                    {
                        "matches": found,
                        "total": len(found),
                        "basis": "oracle_id",
                    }
                )

            session = self.current_session()
            if not session:
                return self.send_json(
                    {"error": "Faça login para ver matches dos seus desejos"},
                    401,
                )

            found = rows(
                connection.execute(
                    f"""
                    SELECT
                        w.id AS want_id,
                        w.card_id AS wanted_card_id,
                        wanted.name AS wanted_name,
                        w.mode AS want_mode,
                        w.max_price_cents,
                        w.desired_condition,
                        l.id AS listing_id,
                        l.card_id,
                        offered.name,
                        offered.set_code,
                        offered.set_name,
                        offered.image_url,
                        l.title,
                        l.price_cents,
                        l.condition,
                        l.mode,
                        l.contact_url,
                        u.id AS user_id,
                        u.username,
                        u.display_name,
                        u.city,
                        u.state
                    FROM wants AS w
                    JOIN {cards_table} AS wanted ON wanted.id = w.card_id
                    JOIN {cards_table} AS offered
                      ON offered.id = wanted.id
                      OR (
                          wanted.oracle_id IS NOT NULL
                          AND offered.oracle_id = wanted.oracle_id
                      )
                    JOIN listings AS l ON l.card_id = offered.id
                    JOIN {users_table} AS u ON u.id = l.user_id
                    WHERE w.user_id = ?
                      AND l.user_id <> w.user_id
                      AND (
                          w.mode = 'ambos'
                          OR (w.mode = 'compra' AND l.mode IN ('venda', 'ambos'))
                          OR (w.mode = 'troca' AND l.mode IN ('troca', 'ambos'))
                      )
                      AND (
                          w.max_price_cents IS NULL
                          OR l.price_cents IS NULL
                          OR l.price_cents <= w.max_price_cents
                      )
                      AND (
                          w.desired_condition IS NULL
                          OR (
                              CASE l.condition
                                  WHEN 'NM' THEN 5
                                  WHEN 'SP' THEN 4
                                  WHEN 'MP' THEN 3
                                  WHEN 'HP' THEN 2
                                  WHEN 'DMG' THEN 1
                              END
                              >=
                              CASE w.desired_condition
                                  WHEN 'NM' THEN 5
                                  WHEN 'SP' THEN 4
                                  WHEN 'MP' THEN 3
                                  WHEN 'HP' THEN 2
                                  WHEN 'DMG' THEN 1
                              END
                          )
                      )
                    ORDER BY w.id DESC, u.state, u.city, l.id DESC
                    """,
                    (session["user_id"],),
                )
            )
        finally:
            connection.close()

        return self.send_json(
            {"matches": found, "total": len(found), "basis": "wants"}
        )

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

        raw_contact_url = data.get("contact_url", "")
        contact_url = "" if raw_contact_url is None else raw_contact_url
        if not valid_contact_url(contact_url):
            raise ValueError(
                "URL de contato deve ser vazia ou usar http(s) com host válido"
            )
        contact_url = contact_url.strip()
        if len(contact_url) > 300:
            raise ValueError("URL de contato deve ter no máximo 300 caracteres")

        connection = self.listings_connection()
        try:
            cards_table = self.cards_table()
            card = connection.execute(
                f"SELECT language FROM {cards_table} WHERE id = ?",
                (card_id,),
            ).fetchone()
            if not card:
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
                    str(card["language"] or "en")[:8],
                    mode,
                    contact_url,
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

    def update_listing(self, listing_id: int, data: dict) -> None:
        """Edita somente um anúncio pertencente ao usuário autenticado."""

        session = self.current_session()
        if not session:
            return self.send_json({"error": "Faça login para editar anúncios"}, 401)
        if not csrf_matches(session, self.headers.get("X-CSRF-Token")):
            return self.send_json({"error": "Token CSRF inválido"}, 403)

        connection = self.listings_connection()
        try:
            current = connection.execute(
                "SELECT * FROM listings WHERE id = ? AND user_id = ?",
                (listing_id, session["user_id"]),
            ).fetchone()
            if not current:
                return self.send_json({"error": "Anúncio não encontrado"}, 404)

            card_id = int(data.get("card_id", current["card_id"]))
            title = str(data.get("title", current["title"])).strip()
            description = str(
                data.get("description", current["description"])
            ).strip()
            condition = data.get("condition", current["condition"])
            mode = data.get("mode", current["mode"])

            if not 3 <= len(title) <= 120 or len(description) > 1000:
                raise ValueError(
                    "Título deve ter 3–120 caracteres e descrição no máximo 1000"
                )
            if condition not in {"NM", "SP", "MP", "HP", "DMG"}:
                raise ValueError("Condição ou modalidade inválida")
            if mode not in {"venda", "troca", "ambos"}:
                raise ValueError("Condição ou modalidade inválida")

            raw_price = data.get("price_cents", current["price_cents"])
            price_cents = None if raw_price in (None, "") else int(raw_price)
            if price_cents is not None and price_cents < 0:
                raise ValueError("Preço não pode ser negativo")

            raw_contact = data.get("contact_url", current["contact_url"] or "")
            contact_url = "" if raw_contact is None else raw_contact
            if not valid_contact_url(contact_url):
                raise ValueError(
                    "URL de contato deve ser vazia ou usar http(s) com host válido"
                )
            contact_url = contact_url.strip()
            if len(contact_url) > 300:
                raise ValueError("URL de contato deve ter no máximo 300 caracteres")

            cards_table = self.cards_table()
            card = connection.execute(
                f"SELECT language FROM {cards_table} WHERE id = ?",
                (card_id,),
            ).fetchone()
            if not card:
                raise ValueError("Carta não encontrada")

            # O idioma pertence à impressão escolhida, não a um campo livre do
            # anúncio. Isso mantém filtros e matching coerentes com o catálogo.
            language = str(card["language"] or "en")[:8]
            connection.execute(
                """
                UPDATE listings
                SET card_id = ?, title = ?, description = ?, price_cents = ?,
                    condition = ?, language = ?, mode = ?, contact_url = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    card_id,
                    title,
                    description,
                    price_cents,
                    condition,
                    language,
                    mode,
                    contact_url,
                    listing_id,
                    session["user_id"],
                ),
            )
            connection.commit()
        finally:
            connection.close()

        return self.send_json({"id": listing_id, "message": "Anúncio atualizado"})

    def delete_listing(self, listing_id: int) -> None:
        """Remove somente um anúncio pertencente ao usuário autenticado."""

        session = self.current_session()
        if not session:
            return self.send_json({"error": "Faça login para remover anúncios"}, 401)
        if not csrf_matches(session, self.headers.get("X-CSRF-Token")):
            return self.send_json({"error": "Token CSRF inválido"}, 403)

        connection = self.listings_connection()
        try:
            cursor = connection.execute(
                "DELETE FROM listings WHERE id = ? AND user_id = ?",
                (listing_id, session["user_id"]),
            )
            connection.commit()
        finally:
            connection.close()

        if cursor.rowcount == 0:
            return self.send_json({"error": "Anúncio não encontrado"}, 404)
        return self.send_json({"message": "Anúncio removido"})

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
