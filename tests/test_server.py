import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import server


class PublicApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_path = server.DB_PATH
        server.DB_PATH = Path(self.temp_dir.name) / "test.sqlite"
        server.API_CACHE.clear()
        server.ITEMS_CACHE.clear()
        server.INDEX_CACHE.clear()
        server.init_db()
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.client = urllib.request.build_opener()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        server.DB_PATH = self.old_db_path
        server.API_CACHE.clear()
        self.temp_dir.cleanup()

    def request(self, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with self.client.open(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_opportunities_are_public_and_filters_reach_the_api(self):
        captured = {}

        def fake_fetch(params):
            captured.update(params)
            return {"opportunities": [], "total": 0, "page": 1, "pages": 1, "source": "PNCP",
                    "period": params.get("period"), "updated_at": "2026-11-23T12:00:00"}

        query = urllib.parse.urlencode([
            ("state", "SC"), ("state", "PR"), ("region", "Sul"), ("period", "future"),
            ("product", "Cimento"), ("q", "limpeza"), ("city", "Joinville"), ("sort", "value"),
        ])
        with patch.object(server, "fetch_opportunities", side_effect=fake_fetch):
            status, result = self.request(f"/api/opportunities?{query}")
        self.assertEqual(status, 200, result)
        self.assertEqual(captured["states"], ["PR", "RS", "SC"])
        self.assertEqual(captured["period"], "future")
        self.assertEqual(captured["products"], ["Cimento"])
        self.assertEqual(captured["q"], "limpeza")
        self.assertEqual(captured["city"], "Joinville")
        self.assertEqual(captured["sort"], "value")

    def test_each_selected_state_is_queried_separately(self):
        calls = []

        def fake_page(uf, page, refresh):
            calls.append((uf, page, refresh))
            return {"data": [], "totalPaginas": 1}, server.time.time()

        with patch.object(server, "proposta_page", side_effect=fake_page):
            result = server.fetch_opportunities({"states": ["SC", "PR"], "page": 2, "products": [], "sort": "date"})
        self.assertEqual(calls, [("PR", 2, False), ("SC", 2, False)])
        self.assertEqual(result["total"], 0)

    def test_future_period_keeps_only_openings_ahead(self):
        soon = (datetime.now() + timedelta(days=4)).isoformat(timespec="seconds")
        past = (datetime.now() - timedelta(days=4)).isoformat(timespec="seconds")
        deadline = (datetime.now() + timedelta(days=20)).isoformat(timespec="seconds")

        def record(control, opening):
            return {"numeroControlePNCP": control, "objetoCompra": "Objeto", "modalidadeNome": "Pregão Eletrônico",
                    "dataAberturaProposta": opening, "dataEncerramentoProposta": deadline,
                    "valorTotalEstimado": 1000.0, "orgaoEntidade": {"razaoSocial": "Órgão", "cnpj": "111"},
                    "unidadeOrgao": {"ufSigla": "SC", "municipioNome": "Florianópolis"}}

        payload = {"data": [record("111-1-1/2026", soon), record("111-1-2/2026", past)]}
        with patch.object(server, "future_records", return_value=([server.normalize(x) for x in payload["data"]], [server.time.time()])):
            result = server.fetch_opportunities({"period": "future", "products": [], "sort": "date"})
        self.assertEqual([x["id"] for x in result["opportunities"]], ["111-1-1/2026"])
        self.assertEqual(result["period"], "future")

    def test_items_endpoint_is_public(self):
        item_id = "11222333000181-1-123/2026"
        with patch.object(server, "fetch_json", side_effect=[
            [{"descricao": "Papel A4", "materialOuServicoNome": "Material", "quantidade": 10,
              "unidadeMedida": "Resma", "valorUnitarioEstimado": 25.0, "valorTotal": 250.0}],
            [{"titulo": "Edital completo", "url": "https://pncp.gov.br/documento.pdf"}],
        ]):
            status, result = self.request(f"/api/opportunities/{urllib.parse.quote(item_id, safe='')}/items")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["items"][0]["descricao"], "Papel A4")
        self.assertEqual(result["documents"][0]["title"], "Edital completo")

    def test_chat_answers_without_account(self):
        opportunity = {"id": "111-1-1/2026", "titulo": "Compra de material de limpeza", "orgao": "Órgão",
                       "cidade": "Florianópolis", "uf": "SC", "valor": 5000.0, "sessao": "2026-12-01T10:00:00",
                       "pncp": "111-1-1/2026", "url": "https://pncp.gov.br/app/editais/111/2026/1", "match": True}
        with patch.object(server, "fetch_opportunities", return_value={"opportunities": [opportunity], "total": 1,
                                                                     "page": 1, "pages": 1, "source": "PNCP",
                                                                     "updated_at": "2026-11-23T12:00:00"}), \
             patch.object(server, "get_indexed_opportunities", return_value=[opportunity]):
            status, result = self.request("/api/chat", {"message": "material de limpeza", "products": []})
        self.assertEqual(status, 200, result)
        self.assertIn("material de limpeza", result["answer"])
        self.assertEqual(result["opportunities"][0]["id"], "111-1-1/2026")

    def test_product_filter_requires_every_word_of_the_item(self):
        deadline = (datetime.now() + timedelta(days=5)).isoformat(timespec="seconds")

        def record(control, objeto):
            return {"numeroControlePNCP": control, "objetoCompra": objeto, "modalidadeNome": "Pregão Eletrônico",
                    "situacaoCompraNome": "Divulgada", "dataEncerramentoProposta": deadline,
                    "valorTotalEstimado": 1000.0, "orgaoEntidade": {"razaoSocial": "Órgão", "cnpj": "111"},
                    "unidadeOrgao": {"ufSigla": "SC", "municipioNome": "Florianópolis"}}

        page = {"data": [
            record("111-1-1/2026", "Aquisição de cadeiras giratórias para escritório"),
            record("111-1-2/2026", "Contratação de veículos de comunicação para publicidade institucional"),
            record("111-1-3/2026", "Aquisição de bomba hidráulica para saneamento"),
            record("111-1-4/2026", "Contrato de exames de ressonância magnética"),
        ], "totalRegistros": 4, "totalPaginas": 1}
        with patch.object(server, "index_records", return_value=([], [])), \
                patch.object(server, "proposta_page", return_value=(page, server.time.time())):
            result = server.fetch_opportunities({"states": ["SC"], "page": 1, "sort": "date",
                                                 "products": ["Cadeira", "Bomba hidráulica", "Comunicação visual"]})
        self.assertEqual([x["id"] for x in result["opportunities"]], ["111-1-1/2026", "111-1-3/2026"])
        self.assertEqual(result["total"], 2)

    def test_opportunity_chat_answers_about_one_tender(self):
        record = {"id": "111-1-1/2026", "titulo": "Aquisição de cadeiras giratórias", "orgao": "Prefeitura",
                  "cidade": "Florianópolis", "uf": "SC", "numero": "12/2026", "modalidade": "Pregão Eletrônico",
                  "status": "Divulgada", "sessao": "2026-12-10T09:00:00", "abertura": "2026-12-01T09:00:00",
                  "valor": 25000.0, "pncp": "111-1-1/2026", "url": "https://pncp.gov.br/app/editais/111/2026/1",
                  "demo": False}
        items = [{"descricao": "Cadeira giratória com braços", "quantidade": 20, "unidade": "UN"}]
        with patch.object(server, "load_opportunity_items", return_value=(items, [], False)), \
                patch.object(server, "fetch_opportunities") as global_search:
            status, result = self.request("/api/chat", {
                "message": "Quais itens foram publicados?",
                "opportunity": record, "history": [],
            })
        self.assertEqual(status, 200, result)
        self.assertIn("Cadeira giratória com braços", result["answer"])
        self.assertIn("Aquisição de cadeiras giratórias", result["answer"])
        self.assertEqual(result["focus"], "111-1-1/2026")
        global_search.assert_not_called()

    def test_opportunity_chat_explains_why_the_tender_matched_the_filter(self):
        record = {"id": "111-1-7/2026", "titulo": "Aquisição de itens de decoração natalina",
                  "orgao": "Prefeitura", "cidade": "Florianópolis", "uf": "SC", "numero": "12/2026",
                  "modalidade": "Pregão Eletrônico", "status": "Divulgada", "sessao": "2026-12-10T09:00:00",
                  "abertura": "2026-12-01T09:00:00", "valor": 25000.0, "pncp": "111-1-7/2026",
                  "url": "", "demo": False}
        items = [{"descricao": "Manutenção elétrica nas instalações da praça central", "quantidade": 1,
                  "unidade": "SERVIÇO"},
                 {"descricao": "Saco de lixo 100 litros para coleta de resíduos", "quantidade": 50,
                  "unidade": "UN"}]
        with patch.object(server, "load_opportunity_items", return_value=(items, [], False)):
            status, result = self.request("/api/chat", {
                "message": "Filtrei por saco de lixo e material elétrico, o que essa licitação tem a ver?",
                "products": ["saco de lixo", "material elétrico"], "opportunity": record, "history": [],
            })
        self.assertEqual(status, 200, result)
        answer = result["answer"]
        self.assertIn("No edital eles pedem «Saco de lixo 100 litros para coleta de resíduos» (50 UN).", answer)
        self.assertIn("apareceu quando você filtrou por saco de lixo", answer)
        self.assertIn("«material elétrico» não aparece", answer)
        self.assertIn("Dados publicados no PNCP:", answer)

    def test_product_filter_uses_the_pncp_search_index(self):
        deadline = (datetime.now() + timedelta(days=6)).isoformat(timespec="seconds")
        stored = {"id": "111-1-1/2026", "titulo": "Aquisição de mobiliário", "orgao": "Órgão",
                  "cidade": "Florianópolis", "uf": "SC", "sessao": deadline, "valor": 900.0,
                  "pncp": "111-1-1/2026", "url": "", "demo": False, "modalidade": "Pregão Eletrônico",
                  "status": "Divulgada", "numero": "1/2026"}
        hit = {"numero_controle_pncp": "111-1-1/2026", "orgao_cnpj": "111", "ano": 2026,
               "numero_sequencial": 1, "situacao_nome": "Divulgada no PNCP",
               "data_publicacao_pncp": datetime.now().isoformat(timespec="seconds")}
        with patch.object(server, "stored_snapshot", return_value=([stored], "2026-11-23T12:00:00")), \
                patch.object(server, "cached_index", return_value=({"items": [hit]}, server.time.time())), \
                patch.object(server, "proposta_page") as scan:
            result = server.fetch_opportunities({"states": ["SC"], "products": ["Cadeira giratória"],
                                                 "sort": "date"})
        scan.assert_not_called()
        self.assertEqual([x["id"] for x in result["opportunities"]], ["111-1-1/2026"])
        self.assertEqual(result["opportunities"][0]["matched_product"], "Cadeira giratória")

    def test_product_filter_keeps_recent_edital_found_only_in_the_index(self):
        hit = {"numero_controle_pncp": "222-1-9/2026", "orgao_cnpj": "222", "ano": 2026,
               "numero_sequencial": 9, "description": "Aquisição de cadeiras para escritório",
               "orgao_nome": "Prefeitura", "municipio_nome": "Blumenau", "uf": "SC",
               "situacao_nome": "Divulgada no PNCP", "modalidade_licitacao_nome": "Pregão - Eletrônico",
               "valor_total_estimado": 15000.0,
               "data_publicacao_pncp": datetime.now().isoformat(timespec="seconds")}
        with patch.object(server, "stored_snapshot", return_value=([], "")), \
                patch.object(server, "cached_index", return_value=({"items": [hit]}, server.time.time())):
            result = server.fetch_opportunities({"states": ["SC"], "products": ["Cadeira"],
                                                 "sort": "date"})
        self.assertEqual([x["id"] for x in result["opportunities"]], ["222-1-9/2026"])
        self.assertEqual(result["opportunities"][0]["sessao"], "")
        self.assertEqual(result["opportunities"][0]["matched_product"], "Cadeira")

    def test_product_index_query_asks_for_every_word_in_one_phrase(self):
        self.assertEqual(server.index_term("Cadeira giratória"), '"cadeira giratória"')
        self.assertEqual(server.index_term("bomba hidráulica"), '"bomba hidráulica"')
        self.assertEqual(server.index_term("Cadeiras"), "cadeiras")

    def test_download_returns_the_official_file_as_attachment(self):
        item_id = "11222333000181-1-123/2026"

        class FakeFile:
            def __init__(self, body):
                self.body = body
                self.headers = {"Content-Type": "application/pdf", "Content-Length": str(len(body))}

            def read(self, size=-1):
                chunk, self.body = self.body, b""
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        documents = [{"title": "Edital completo", "url": "https://pncp.gov.br/arquivos/edital.pdf",
                      "type": "Edital"}]
        with patch.object(server, "load_opportunity_items", return_value=([], documents, False)), \
                patch.object(server.urllib.request, "urlopen", return_value=FakeFile(b"%PDF-1.4 edital")):
            request = urllib.request.Request(
                f"{self.base_url}/api/opportunities/{urllib.parse.quote(item_id, safe='')}/download")
            with self.client.open(request, timeout=5) as response:
                body = response.read()
                disposition = response.headers.get("Content-Disposition")
        self.assertEqual(body, b"%PDF-1.4 edital")
        self.assertEqual(disposition, 'attachment; filename="edital-completo.pdf"')

    def test_download_explains_when_the_orgao_published_no_file(self):
        item_id = "11222333000181-1-123/2026"
        with patch.object(server, "load_opportunity_items", return_value=([], [], False)):
            status, result = self.request(
                f"/api/opportunities/{urllib.parse.quote(item_id, safe='')}/download")
        self.assertEqual(status, 404, result)
        self.assertIn("edital", result["error"])

    def test_account_endpoints_were_removed(self):
        self.assertEqual(self.request("/api/signup", {"email": "a@b.test"})[0], 404)
        self.assertEqual(self.request("/api/login", {"email": "a@b.test", "password": "x"})[0], 404)
        self.assertEqual(self.request("/api/admin/companies")[0], 404)


if __name__ == "__main__":
    unittest.main()
