"""Servidor HTTP e API REST, sem dependências externas."""
from __future__ import annotations

import json
import mimetypes
from contextlib import closing
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .db import DEFAULT_DB_PATH, get_connection, init_db

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
MAX_BODY = 32 * 1024


def positive_int(value, default, maximum):
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


class ManaPonteHandler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB_PATH

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def params(self):
        return {key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()}

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/api/health":
                return self.send_json({"status": "ok", "service": "ManaPonte"})
            if path == "/api/cards":
                return self.get_cards()
            if path == "/api/sets":
                return self.get_sets()
            if path == "/api/listings":
                return self.get_listings()
            if path == "/api/matches":
                return self.get_matches()
            if path.startswith("/api/"):
                return self.send_json({"error": "Rota não encontrada"}, HTTPStatus.NOT_FOUND)
            return self.serve_static(path)
        except (ValueError, TypeError) as error:
            return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def get_cards(self):
        query = self.params()
        page = positive_int(query.get("page"), 1, 100000)
        limit = positive_int(query.get("limit"), 24, 100)
        clauses, values = [], []
        if query.get("q"):
            clauses.append("name LIKE ? COLLATE NOCASE")
            values.append(f"%{query['q'][:100]}%")
        if query.get("set"):
            clauses.append("set_code = ? COLLATE NOCASE")
            values.append(query["set"][:16])
        if query.get("lang"):
            clauses.append("language = ?")
            values.append(query["lang"][:8])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(get_connection(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM cards" + where, values).fetchone()[0]
            found = rows(conn.execute(
                "SELECT id,scryfall_id,oracle_id,name,set_code,set_name,collector_number,language,rarity,image_url "
                + "FROM cards" + where + " ORDER BY name,set_code,collector_number LIMIT ? OFFSET ?",
                values + [limit, (page - 1) * limit]))
        self.send_json({"cards": found, "page": page, "limit": limit, "total": total})

    def get_sets(self):
        with closing(get_connection(self.db_path)) as conn:
            found = rows(conn.execute(
                "SELECT set_code,set_name,COUNT(*) AS card_count FROM cards "
                "GROUP BY set_code,set_name ORDER BY set_name"))
        self.send_json({"sets": found})

    def get_listings(self):
        query = self.params()
        clauses, values = [], []
        mapping = {
            "card_id": ("l.card_id = ?", int), "set": ("c.set_code = ? COLLATE NOCASE", str),
            "city": ("u.city = ? COLLATE NOCASE", str), "state": ("u.state = ? COLLATE NOCASE", str),
            "mode": ("l.mode = ?", str),
        }
        for key, (sql, converter) in mapping.items():
            if query.get(key):
                clauses.append(sql)
                values.append(converter(query[key]))
        if query.get("card"):
            clauses.append("c.name LIKE ? COLLATE NOCASE")
            values.append(f"%{query['card'][:100]}%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = """SELECT l.id,l.card_id,c.name,c.set_code,c.set_name,c.image_url,
                    u.username,u.display_name,u.city,u.state,l.title,l.description,
                    l.price_cents,l.condition,l.language,l.mode,l.contact_url,l.created_at
                 FROM listings l JOIN cards c ON c.id=l.card_id
                 JOIN users u ON u.id=l.user_id""" + where + " ORDER BY l.created_at DESC,l.id DESC"
        with closing(get_connection(self.db_path)) as conn:
            found = rows(conn.execute(sql, values))
        self.send_json({"listings": found, "total": len(found)})

    def get_matches(self):
        value = self.params().get("card_id")
        if not value:
            raise ValueError("card_id é obrigatório")
        card_id = int(value)
        with closing(get_connection(self.db_path)) as conn:
            found = rows(conn.execute(
                """SELECT l.id AS listing_id,l.card_id,c.name,c.image_url,l.title,l.price_cents,
                          l.condition,l.mode,u.display_name,u.city,u.state
                   FROM listings l JOIN cards c ON c.id=l.card_id JOIN users u ON u.id=l.user_id
                   WHERE l.card_id=? ORDER BY u.state,u.city""", (card_id,)))
        self.send_json({"matches": found, "total": len(found)})

    def do_POST(self):
        if urlsplit(self.path).path != "/api/listings":
            return self.send_json({"error": "Rota não encontrada"}, HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                return self.send_json({"error": "Corpo JSON ausente ou maior que 32 KiB"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            data = json.loads(self.rfile.read(length))
            created = self.create_listing(data)
            return self.send_json(created, HTTPStatus.CREATED)
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def create_listing(self, data):
        if not isinstance(data, dict):
            raise ValueError("O corpo deve ser um objeto JSON")
        try:
            card_id, user_id = int(data["card_id"]), int(data["user_id"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("card_id e user_id são obrigatórios e numéricos")
        title = str(data.get("title", "")).strip()
        description = str(data.get("description", "")).strip()
        condition, mode = data.get("condition", "NM"), data.get("mode", "venda")
        if not 3 <= len(title) <= 120 or len(description) > 1000:
            raise ValueError("Título deve ter 3–120 caracteres e descrição no máximo 1000")
        if condition not in {"NM", "SP", "MP", "HP", "DMG"} or mode not in {"venda", "troca", "ambos"}:
            raise ValueError("Condição ou modalidade inválida")
        price = data.get("price_cents")
        price = None if price in (None, "") else int(price)
        if price is not None and price < 0:
            raise ValueError("Preço não pode ser negativo")
        # TODO produção: user_id deve vir da sessão autenticada, nunca do cliente.
        with closing(get_connection(self.db_path)) as conn:
            if not conn.execute("SELECT 1 FROM cards WHERE id=?", (card_id,)).fetchone():
                raise ValueError("Carta não encontrada")
            if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                raise ValueError("Usuário não encontrado")
            cursor = conn.execute(
                """INSERT INTO listings(card_id,user_id,title,description,price_cents,condition,language,mode,contact_url)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (card_id, user_id, title, description, price, condition,
                 str(data.get("language", "en"))[:8], mode, str(data.get("contact_url", ""))[:300]))
            listing_id = cursor.lastrowid
            conn.commit()
        return {"id": listing_id, "message": "Anúncio criado"}

    def serve_static(self, path):
        relative = "index.html" if path == "/" else path.lstrip("/")
        candidate = (PUBLIC_DIR / relative).resolve()
        if PUBLIC_DIR.resolve() not in candidate.parents and candidate != PUBLIC_DIR.resolve():
            return self.send_error(HTTPStatus.FORBIDDEN)
        if not candidate.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def create_server(host="127.0.0.1", port=8000, db_path=None):
    handler = type("ConfiguredManaPonteHandler", (ManaPonteHandler,), {"db_path": db_path or DEFAULT_DB_PATH})
    return ThreadingHTTPServer((host, port), handler)


def main():
    init_db()
    server = create_server()
    print(f"ManaPonte em http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
