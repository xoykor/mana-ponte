"""Servidor HTTP, API REST e autenticação por sessão."""
from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import closing
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .auth import (create_session, csrf_matches, get_session, hash_password,
                   normalize_email, normalize_username, revoke_session,
                   valid_email, valid_username, validate_password, verify_password)
from .catalog import search_scryfall, upsert_rows
from .db import DEFAULT_DB_PATH, get_connection, init_db

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
MAX_BODY = 32 * 1024
SESSION_TTL = 7 * 24 * 60 * 60
BRAZIL_STATES = {"AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"}
DUMMY_PASSWORD_HASH = hash_password("InvalidAccount!2026")
REMOTE_CARD_CACHE = {}
REMOTE_CARD_CACHE_LOCK = threading.Lock()
REMOTE_CARD_CACHE_TTL = 300


def remote_search_enabled():
    return os.environ.get("MANAPONTE_REMOTE_SEARCH", "1").lower() not in {"0", "false", "no", "off"}


def remote_cards(query, set_code=None, language=None):
    key = (query.strip().lower(), (set_code or "").lower(), (language or "").lower())
    now = time.monotonic()
    with REMOTE_CARD_CACHE_LOCK:
        cached = REMOTE_CARD_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        found = search_scryfall(query, set_code, language)
    except Exception as error:
        print(f"Busca remota do catálogo indisponível: {error}")
        found = []
    with REMOTE_CARD_CACHE_LOCK:
        REMOTE_CARD_CACHE[key] = (now + REMOTE_CARD_CACHE_TTL, found)
    return found


class LoginRateLimiter:
    def __init__(self, limit=5, window=900):
        self.limit, self.window = limit, window
        self.failures, self.lock = defaultdict(deque), threading.Lock()

    def _prune(self, key, now):
        while self.failures[key] and self.failures[key][0] <= now - self.window:
            self.failures[key].popleft()

    def blocked(self, key):
        with self.lock:
            self._prune(key, time.time())
            return len(self.failures[key]) >= self.limit

    def fail(self, key):
        with self.lock:
            now = time.time(); self._prune(key, now); self.failures[key].append(now)
            return len(self.failures[key])

    def success(self, key):
        with self.lock:
            self.failures.pop(key, None)


def positive_int(value, default, maximum):
    try: return max(1, min(int(value), maximum))
    except (TypeError, ValueError): return default


def rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


class ManaPonteHandler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB_PATH
    rate_limiter = LoginRateLimiter()

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, payload, status=HTTPStatus.OK, headers=()):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/auth/") else "no-cache")
        for name, value in headers: self.send_header(name, value)
        self.end_headers(); self.wfile.write(body)

    def params(self):
        return {key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()}

    def read_json(self):
        try: length = int(self.headers.get("Content-Length", "0"))
        except ValueError: raise ValueError("Content-Length inválido")
        if length <= 0: raise ValueError("Corpo JSON ausente")
        if length > MAX_BODY: raise OverflowError("Corpo JSON maior que 32 KiB")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict): raise ValueError("O corpo deve ser um objeto JSON")
        return data

    def session_token(self):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get("Cookie", ""))
        except Exception: return None
        return cookie["mp_session"].value if "mp_session" in cookie else None

    def current_session(self):
        return get_session(self.session_token(), self.db_path)

    def session_cookie(self, token, max_age=SESSION_TTL):
        secure = os.environ.get("MANAPONTE_SECURE_COOKIES", "").lower() in {"1","true","yes"}
        value = f"mp_session={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
        return value + ("; Secure" if secure else "")

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/api/health": return self.send_json({"status":"ok","service":"ManaPonte"})
            if path == "/api/auth/me": return self.get_me()
            if path == "/api/cards": return self.get_cards()
            if path == "/api/sets": return self.get_sets()
            if path == "/api/listings": return self.get_listings()
            if path == "/api/matches": return self.get_matches()
            if path.startswith("/api/"): return self.send_json({"error":"Rota não encontrada"}, 404)
            return self.serve_static(path)
        except (ValueError, TypeError) as error:
            return self.send_json({"error":str(error)}, 400)

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            data = self.read_json() if path != "/api/auth/logout" or int(self.headers.get("Content-Length", "0")) else {}
            if path == "/api/auth/register": return self.register(data)
            if path == "/api/auth/login": return self.login(data)
            if path == "/api/auth/logout": return self.logout()
            if path == "/api/listings": return self.create_listing(data)
            return self.send_json({"error":"Rota não encontrada"}, 404)
        except OverflowError as error:
            return self.send_json({"error":str(error)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            return self.send_json({"error":str(error)}, 400)

    def auth_payload(self, session):
        return {"user":{"id":session["user_id"],"username":session["username"],"email":session["email"],
                        "display_name":session["display_name"],"city":session["city"],"state":session["state"],
                        "email_verified":bool(session["email_verified"])},
                "csrf_token":session["csrf_token"]}

    def get_me(self):
        session = self.current_session()
        if not session: return self.send_json({"error":"Não autenticado"}, 401)
        return self.send_json(self.auth_payload(session))

    def register(self, data):
        username, email = normalize_username(data.get("username", "")), normalize_email(data.get("email", ""))
        password, display = data.get("password", ""), str(data.get("display_name", "")).strip()
        city, state = str(data.get("city", "")).strip(), str(data.get("state", "")).strip().upper()
        if not valid_username(username): raise ValueError("Usuário deve ter 3–30 caracteres: letras, números, _, . ou -")
        if not valid_email(email): raise ValueError("E-mail inválido")
        if not validate_password(password): raise ValueError("Senha deve ter 12–128 caracteres, maiúscula, minúscula, número e símbolo")
        if not 2 <= len(display) <= 80 or not 2 <= len(city) <= 80 or state not in BRAZIL_STATES:
            raise ValueError("Nome, cidade ou UF inválidos")
        with closing(get_connection(self.db_path)) as conn:
            try:
                cursor = conn.execute("""INSERT INTO users(username,email,display_name,city,state,password_hash,email_verified,updated_at)
                    VALUES(?,?,?,?,?,?,0,CURRENT_TIMESTAMP)""", (username,email,display,city,state,hash_password(password)))
                conn.commit(); user_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                return self.send_json({"error":"Já existe uma conta com esses dados"}, 409)
        session_data = create_session(user_id, self.db_path, SESSION_TTL)
        session = get_session(session_data["token"], self.db_path)
        return self.send_json(self.auth_payload(session), 201,
                              (("Set-Cookie", self.session_cookie(session_data["token"])),))

    def login(self, data):
        identifier = normalize_email(data.get("identifier", ""))
        password = data.get("password", "")
        key = f"{self.client_address[0]}:{identifier[:254]}"
        if self.rate_limiter.blocked(key): return self.send_json({"error":"Muitas tentativas. Aguarde 15 minutos."}, 429)
        with closing(get_connection(self.db_path)) as conn:
            user = conn.execute("SELECT id,password_hash FROM users WHERE username=? OR email=?", (identifier,identifier)).fetchone()
        valid = verify_password(password, user["password_hash"] if user else DUMMY_PASSWORD_HASH)
        if not user or not valid:
            if self.rate_limiter.fail(key) >= self.rate_limiter.limit:
                return self.send_json({"error":"Muitas tentativas. Aguarde 15 minutos."}, 429)
            return self.send_json({"error":"Credenciais inválidas"}, 401)
        self.rate_limiter.success(key)
        session_data = create_session(user["id"], self.db_path, SESSION_TTL)
        session = get_session(session_data["token"], self.db_path)
        return self.send_json(self.auth_payload(session), 200,
                              (("Set-Cookie", self.session_cookie(session_data["token"])),))

    def logout(self):
        token, session = self.session_token(), self.current_session()
        if not session: return self.send_json({"error":"Não autenticado"}, 401)
        if not csrf_matches(session, self.headers.get("X-CSRF-Token")):
            return self.send_json({"error":"Token CSRF inválido"}, 403)
        revoke_session(token, self.db_path)
        return self.send_json({"message":"Sessão encerrada"}, 200,
                              (("Set-Cookie", self.session_cookie("", 0)),))

    def get_cards(self):
        query = self.params()
        page = positive_int(query.get("page"), 1, 100000)
        limit = positive_int(query.get("limit"), 24, 100)
        clauses, values = [], []
        search = query.get("q", "").strip()[:100]
        set_code = query.get("set", "").strip()[:16]
        language = query.get("lang", "").strip()[:8]
        if search:
            clauses.append("name LIKE ? COLLATE NOCASE")
            values.append(f"%{search}%")
        if set_code:
            clauses.append("set_code=? COLLATE NOCASE")
            values.append(set_code)
        if language:
            clauses.append("language=?")
            values.append(language)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        source = "local"
        with closing(get_connection(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM cards" + where, values).fetchone()[0]
            if total == 0 and len(search) >= 3 and remote_search_enabled():
                imported = remote_cards(search, set_code, language)
                if imported:
                    upsert_rows(conn, imported)
                    conn.commit()
                    source = "scryfall"
                    total = conn.execute("SELECT COUNT(*) FROM cards" + where, values).fetchone()[0]
            found = rows(conn.execute(
                "SELECT id,scryfall_id,oracle_id,name,set_code,set_name,collector_number,language,rarity,image_url "
                "FROM cards" + where + " ORDER BY name,set_code,collector_number LIMIT ? OFFSET ?",
                values + [limit, (page - 1) * limit],
            ))
        self.send_json({"cards": found, "page": page, "limit": limit, "total": total, "source": source})

    def get_sets(self):
        with closing(get_connection(self.db_path)) as conn:
            found=rows(conn.execute("SELECT set_code,set_name,COUNT(*) AS card_count FROM cards GROUP BY set_code,set_name ORDER BY set_name"))
        self.send_json({"sets":found})

    def get_listings(self):
        query=self.params(); clauses=[]; values=[]
        mapping={"card_id":("l.card_id=?",int),"set":("c.set_code=? COLLATE NOCASE",str),"city":("u.city=? COLLATE NOCASE",str),"state":("u.state=? COLLATE NOCASE",str),"mode":("l.mode=?",str)}
        for key,(sql,convert) in mapping.items():
            if query.get(key): clauses.append(sql); values.append(convert(query[key]))
        if query.get("card"): clauses.append("c.name LIKE ? COLLATE NOCASE"); values.append(f"%{query['card'][:100]}%")
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        sql="""SELECT l.id,l.card_id,c.name,c.set_code,c.set_name,c.image_url,u.username,u.display_name,u.city,u.state,l.title,l.description,l.price_cents,l.condition,l.language,l.mode,l.contact_url,l.created_at FROM listings l JOIN cards c ON c.id=l.card_id JOIN users u ON u.id=l.user_id"""+where+" ORDER BY l.created_at DESC,l.id DESC"
        with closing(get_connection(self.db_path)) as conn: found=rows(conn.execute(sql,values))
        self.send_json({"listings":found,"total":len(found)})

    def get_matches(self):
        value=self.params().get("card_id")
        if not value: raise ValueError("card_id é obrigatório")
        with closing(get_connection(self.db_path)) as conn:
            found=rows(conn.execute("""SELECT l.id AS listing_id,l.card_id,c.name,c.image_url,l.title,l.price_cents,l.condition,l.mode,u.display_name,u.city,u.state FROM listings l JOIN cards c ON c.id=l.card_id JOIN users u ON u.id=l.user_id WHERE l.card_id=? ORDER BY u.state,u.city""",(int(value),)))
        self.send_json({"matches":found,"total":len(found)})

    def create_listing(self, data):
        session=self.current_session()
        if not session: return self.send_json({"error":"Faça login para anunciar"},401)
        if not csrf_matches(session,self.headers.get("X-CSRF-Token")): return self.send_json({"error":"Token CSRF inválido"},403)
        try: card_id=int(data["card_id"])
        except (KeyError,TypeError,ValueError): raise ValueError("card_id é obrigatório e numérico")
        title=str(data.get("title","")).strip(); description=str(data.get("description","")).strip()
        condition,mode=data.get("condition","NM"),data.get("mode","venda")
        if not 3<=len(title)<=120 or len(description)>1000: raise ValueError("Título deve ter 3–120 caracteres e descrição no máximo 1000")
        if condition not in {"NM","SP","MP","HP","DMG"} or mode not in {"venda","troca","ambos"}: raise ValueError("Condição ou modalidade inválida")
        price=data.get("price_cents"); price=None if price in (None,"") else int(price)
        if price is not None and price<0: raise ValueError("Preço não pode ser negativo")
        with closing(get_connection(self.db_path)) as conn:
            if not conn.execute("SELECT 1 FROM cards WHERE id=?",(card_id,)).fetchone(): raise ValueError("Carta não encontrada")
            cursor=conn.execute("""INSERT INTO listings(card_id,user_id,title,description,price_cents,condition,language,mode,contact_url) VALUES(?,?,?,?,?,?,?,?,?)""",(card_id,session["user_id"],title,description,price,condition,str(data.get("language","en"))[:8],mode,str(data.get("contact_url",""))[:300]))
            conn.commit(); listing_id=cursor.lastrowid
        return self.send_json({"id":listing_id,"message":"Anúncio criado"},201)

    def serve_static(self,path):
        relative="index.html" if path=="/" else path.lstrip("/"); candidate=(PUBLIC_DIR/relative).resolve()
        if PUBLIC_DIR.resolve() not in candidate.parents and candidate!=PUBLIC_DIR.resolve(): return self.send_error(403)
        if not candidate.is_file(): return self.send_error(404)
        body=candidate.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(body))); self.send_header("X-Content-Type-Options","nosniff"); self.end_headers(); self.wfile.write(body)


def create_server(host="127.0.0.1",port=8000,db_path=None):
    handler=type("ConfiguredManaPonteHandler",(ManaPonteHandler,),{"db_path":db_path or DEFAULT_DB_PATH,"rate_limiter":LoginRateLimiter()})
    return ThreadingHTTPServer((host,port),handler)


def main():
    init_db()
    host = os.environ.get("MANAPONTE_HOST", "127.0.0.1")
    port = int(os.environ.get("MANAPONTE_PORT", "8000"))
    server=create_server(host, port); print(f"ManaPonte em http://{server.server_address[0]}:{server.server_address[1]}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=="__main__": main()
