import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch

import server


class PlatformFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_path = server.DB_PATH
        self.old_demo_mode = server.DEMO_MODE
        server.DB_PATH = Path(self.temp_dir.name) / "test.sqlite"
        server.DEMO_MODE = False
        server.API_CACHE.clear()
        server.init_db()
        with server.connect() as db:
            server.seed_user(db, "Admin", "admin@example.test", "", "SecureAdmin#2026", "admin", "approved")
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.client = self.opener()
        self.admin = self.opener()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        server.DB_PATH = self.old_db_path
        server.DEMO_MODE = self.old_demo_mode
        server.API_CACHE.clear()
        self.temp_dir.cleanup()

    def opener(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def request(self, opener, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def signup_company(self):
        return self.request(self.client, "/api/signup", {
            "name": "Ana Costa", "email": "ana@example.test", "phone": "48999990000",
            "password": "CompanyPass#2026", "legal_name": "Costa Ltda.",
            "trade_name": "Costa Suprimentos", "cnpj": "11.222.333/0001-81",
            "state": "SC", "city": "Florianópolis", "activity": "Fornecimento de materiais",
            "products": ["Material de limpeza"],
        })

    def test_cnpj_check_digit_validation(self):
        self.assertTrue(server.valid_cnpj("11.222.333/0001-81"))
        self.assertFalse(server.valid_cnpj("11.222.333/0001-80"))
        self.assertFalse(server.valid_cnpj("00.000.000/0000-00"))

    def test_pending_company_cannot_access_admin_or_opportunities_until_approved(self):
        status, result = self.signup_company()
        self.assertEqual(status, 201, result)
        status, result = self.request(self.client, "/api/login", {
            "email": "ana@example.test", "password": "CompanyPass#2026",
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(result["user"]["status"], "pending")
        self.assertEqual(self.request(self.client, "/api/admin/companies")[0], 403)
        self.assertEqual(self.request(self.client, "/api/opportunities")[0], 403)

        self.request(self.admin, "/api/login", {
            "email": "admin@example.test", "password": "SecureAdmin#2026",
        })
        with server.connect() as db:
            user_id = db.execute("SELECT id FROM users WHERE email='ana@example.test'").fetchone()["id"]
        status, result = self.request(self.admin, "/api/admin/action", {
            "action": "approve", "user_id": user_id,
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(result["status"], "approved")

        with patch.object(server, "fetch_opportunities", return_value={
            "opportunities": [], "total": 0, "page": 1, "pages": 1,
            "source": "PNCP", "updated_at": "2026-11-20T12:00:00",
        }):
            status, result = self.request(self.client, "/api/opportunities")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["source"], "PNCP")
        item_id = "11222333000181-1-123/2026"
        with patch.object(server, "fetch_json", side_effect=[
            [{"descricao": "Papel A4", "materialOuServicoNome": "Material", "quantidade": 10,
              "unidadeMedida": "Resma", "valorUnitarioEstimado": 25.0, "valorTotal": 250.0}],
            [{"titulo": "Edital completo", "url": "https://pncp.gov.br/documento.pdf"}],
        ]):
            status, result = self.request(self.client, f"/api/opportunities/{urllib.parse.quote(item_id, safe='')}/items")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["items"][0]["descricao"], "Papel A4")
        self.assertEqual(result["items"][0]["natureza"], "Material")
        self.assertEqual(result["documents"][0]["title"], "Edital completo")
        self.assertEqual(self.request(self.admin, "/api/admin/history")[0], 200)


if __name__ == "__main__":
    unittest.main()
