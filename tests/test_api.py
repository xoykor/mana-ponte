import http.client
import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from app.db import get_connection
from app.seed import DEV_PASSWORD, seed_all
from app.server import create_server


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.db=Path(cls.temp.name)/"api.db"; seed_all(cls.db,reset=True)
        cls.server=create_server("127.0.0.1",0,cls.db); cls.port=cls.server.server_address[1]
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2); cls.temp.cleanup()
    def setUp(self): self.cookie=None; self.csrf=None

    def request(self,method,path,payload=None,csrf=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.port,timeout=4); body=json.dumps(payload).encode() if payload is not None else None
        headers={"Content-Type":"application/json"} if body else {}
        if self.cookie: headers["Cookie"]=self.cookie
        if csrf: headers["X-CSRF-Token"]=csrf
        conn.request(method,path,body,headers); response=conn.getresponse(); raw=response.read(); cookie=response.getheader("Set-Cookie")
        if cookie: self.cookie=cookie.split(";",1)[0]
        data=json.loads(raw) if response.getheader("Content-Type","").startswith("application/json") else raw
        status=response.status; conn.close(); return status,data

    def login_demo(self):
        status,data=self.request("POST","/api/auth/login",{"identifier":"danton","password":DEV_PASSWORD})
        self.assertEqual(status,200); self.csrf=data["csrf_token"]; return data

    def test_register_duplicate_cookie_and_me(self):
        payload={"username":"novo.jogador","email":"novo@example.com","password":"Strong!Pass2026","display_name":"Novo Jogador","city":"Natal","state":"rn"}
        status,data=self.request("POST","/api/auth/register",payload)
        self.assertEqual(status,201); self.assertTrue(self.cookie.startswith("mp_session=")); self.assertEqual(data["user"]["state"],"RN")
        self.csrf=data["csrf_token"]; status,me=self.request("GET","/api/auth/me")
        self.assertEqual(status,200); self.assertEqual(me["user"]["username"],"novo.jogador")
        other=ApiTest.request(self,"POST","/api/auth/register",payload)
        self.assertEqual(other[0],409)

    def test_login_logout_and_csrf(self):
        self.login_demo(); status,_=self.request("POST","/api/auth/logout")
        self.assertEqual(status,403); status,_=self.request("POST","/api/auth/logout",csrf=self.csrf)
        self.assertEqual(status,200); status,_=self.request("GET","/api/auth/me"); self.assertEqual(status,401)

    def test_invalid_login_and_rate_limit(self):
        for _ in range(4):
            status,data=self.request("POST","/api/auth/login",{"identifier":"missing-rate@example.com","password":"Wrong!Password1"})
            self.assertEqual(status,401); self.assertEqual(data["error"],"Credenciais inválidas")
        status,_=self.request("POST","/api/auth/login",{"identifier":"missing-rate@example.com","password":"Wrong!Password1"})
        self.assertEqual(status,429)

    def test_expired_session(self):
        self.login_demo()
        with closing(get_connection(self.db)) as conn:
            conn.execute("UPDATE sessions SET expires_at=0"); conn.commit()
        status,_=self.request("GET","/api/auth/me"); self.assertEqual(status,401)

    def test_listing_requires_session_and_csrf_and_uses_session_user(self):
        payload={"card_id":1,"user_id":2,"title":"Oferta autenticada","condition":"NM","mode":"ambos","price_cents":100}
        status,_=self.request("POST","/api/listings",payload); self.assertEqual(status,401)
        self.login_demo(); status,_=self.request("POST","/api/listings",payload); self.assertEqual(status,403)
        status,data=self.request("POST","/api/listings",payload,csrf=self.csrf); self.assertEqual(status,201)
        with closing(get_connection(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT user_id FROM listings WHERE id=?",(data["id"],)).fetchone()[0],1)

    def test_public_routes(self):
        status,health=self.request("GET","/api/health"); self.assertEqual((status,health["status"]),(200,"ok"))
        status,home=self.request("GET","/"); self.assertEqual(status,200); self.assertIn(b"ManaPonte",home)
        status,cards=self.request("GET","/api/cards?q=Sol&set=cmm&limit=1"); self.assertEqual(cards["total"],1)
