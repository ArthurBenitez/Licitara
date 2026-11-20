import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "data" / "licitara.db"))
PNCP_BASE = "https://pncp.gov.br/api/consulta"
PNCP_DATA_BASE = "https://pncp.gov.br/api/pncp"
DEMO_MODE = os.environ.get("DEMO_MODE", "1").lower() in ("1", "true", "yes")
SESSION_DAYS = 7
API_CACHE = {}
API_CACHE_TTL = 300
LOGIN_ATTEMPTS = {}
API_REQUEST_LOCK = threading.Lock()
LAST_API_REQUEST = 0.0
API_MIN_INTERVAL = 0.25

CATALOG = {
    "Materiais de construção": ["Cimento", "Areia", "Brita", "Tijolo", "Telha", "Material hidráulico", "Material elétrico", "Tintas", "Ferramentas"],
    "Informática e tecnologia": ["Computador", "Notebook", "Impressora", "Monitor", "Servidor", "Equipamentos de rede", "Licença de software", "Suporte de TI"],
    "Limpeza e higiene": ["Material de limpeza", "Detergente", "Papel higiênico", "Desinfetante", "Saco de lixo", "Serviços de limpeza"],
    "Saúde e hospitalar": ["Material hospitalar", "Medicamentos", "EPIs", "Mobiliário hospitalar", "Equipamento médico", "Serviços médicos"],
    "Alimentação": ["Gêneros alimentícios", "Merenda escolar", "Água mineral", "Cesta básica", "Refeições prontas"],
    "Uniformes e vestuário": ["Uniformes", "Calçados", "Tecidos", "EPIs", "Confecção"],
    "Serviços especializados": ["Manutenção predial", "Ar-condicionado", "Manutenção elétrica", "Manutenção hidráulica", "Engenharia", "Consultoria"],
    "Transporte e logística": ["Locação de veículos", "Transporte escolar", "Combustíveis", "Frete", "Serviços de logística"],
    "Mobiliário e escritório": ["Móveis de escritório", "Cadeiras", "Mesas", "Material de escritório", "Arquivo de aço"],
    "Equipamentos e indústria": ["Máquinas e equipamentos", "Gerador", "Bomba hidráulica", "Equipamento de segurança", "Peças industriais"],
    "Comunicação e eventos": ["Serviços gráficos", "Impressão", "Comunicação visual", "Organização de eventos", "Publicidade"],
}
STATES_FOR_SEARCH = [
    ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapá"), ("AM", "Amazonas"), ("BA", "Bahia"),
    ("CE", "Ceará"), ("DF", "Distrito Federal"), ("ES", "Espírito Santo"), ("GO", "Goiás"),
    ("MA", "Maranhão"), ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"), ("MG", "Minas Gerais"),
    ("PA", "Pará"), ("PB", "Paraíba"), ("PR", "Paraná"), ("PE", "Pernambuco"), ("PI", "Piauí"),
    ("RJ", "Rio de Janeiro"), ("RN", "Rio Grande do Norte"), ("RS", "Rio Grande do Sul"),
    ("RO", "Rondônia"), ("RR", "Roraima"), ("SC", "Santa Catarina"), ("SP", "São Paulo"),
    ("SE", "Sergipe"), ("TO", "Tocantins"),
]
REGIONS_FOR_SEARCH = {
    "Norte": ["AC", "AP", "AM", "PA", "RO", "RR", "TO"],
    "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste": ["DF", "GO", "MT", "MS"],
    "Sudeste": ["ES", "MG", "RJ", "SP"],
    "Sul": ["PR", "RS", "SC"],
}

DEMO_OPPORTUNITIES = [
    {"id": "demo-001", "modalidade": "Pregão Eletrônico", "status": "Aberta", "origem": "Demonstração", "titulo": "Fornecimento de materiais de limpeza para unidades municipais", "orgao": "Prefeitura Municipal (exemplo)", "cidade": "Florianópolis", "uf": "SC", "numero": "DEMO-001", "sessao": "2026-12-15T09:00:00", "valor": 125000, "pncp": "DADO DEMONSTRATIVO", "documentos": None, "url": "", "demo": True, "items": [{"descricao": "Material de limpeza (exemplo demonstrativo)", "quantidade": None, "unidade": None, "unitario": None, "total": None}]},
    {"id": "demo-002", "modalidade": "Concorrência", "status": "Aberta", "origem": "Demonstração", "titulo": "Aquisição de equipamentos de informática", "orgao": "Órgão público (exemplo)", "cidade": "Curitiba", "uf": "PR", "numero": "DEMO-002", "sessao": "2026-12-18T10:00:00", "valor": 248900, "pncp": "DADO DEMONSTRATIVO", "documentos": None, "url": "", "demo": True, "items": [{"descricao": "Computadores e periféricos (exemplo demonstrativo)", "quantidade": None, "unidade": None, "unitario": None, "total": None}]},
    {"id": "demo-003", "modalidade": "Pregão Eletrônico", "status": "Aberta", "origem": "Demonstração", "titulo": "Serviços de manutenção preventiva de ar-condicionado", "orgao": "Secretaria municipal (exemplo)", "cidade": "Joinville", "uf": "SC", "numero": "DEMO-003", "sessao": "2026-12-22T14:00:00", "valor": 86400, "pncp": "DADO DEMONSTRATIVO", "documentos": None, "url": "", "demo": True, "items": [{"descricao": "Manutenção de ar-condicionado (exemplo demonstrativo)", "quantidade": None, "unidade": None, "unitario": None, "total": None}]},
    {"id": "demo-004", "modalidade": "Dispensa Eletrônica", "status": "Aberta", "origem": "Demonstração", "titulo": "Aquisição de mobiliário para escritório", "orgao": "Autarquia pública (exemplo)", "cidade": "Porto Alegre", "uf": "RS", "numero": "DEMO-004", "sessao": "2026-12-27T08:30:00", "valor": 41900, "pncp": "DADO DEMONSTRATIVO", "documentos": None, "url": "", "demo": True, "items": [{"descricao": "Mobiliário de escritório (exemplo demonstrativo)", "quantidade": None, "unidade": None, "unitario": None, "total": None}]},
]


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, phone TEXT NOT NULL,
                password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'client',
                status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS companies (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                legal_name TEXT NOT NULL, trade_name TEXT NOT NULL, cnpj TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL, city TEXT NOT NULL, activity TEXT NOT NULL,
                products TEXT NOT NULL DEFAULT '[]', regions TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approval_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company_user_id INTEGER NOT NULL,
                admin_user_id INTEGER NOT NULL, action TEXT NOT NULL, note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT NOT NULL,
                subject TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                question TEXT NOT NULL, answer TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, record_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tender_items (
                opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
                item_index INTEGER NOT NULL, item_json TEXT NOT NULL,
                PRIMARY KEY(opportunity_id,item_index)
            );
            CREATE TABLE IF NOT EXISTS tender_documents (
                opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
                document_id TEXT NOT NULL, document_json TEXT NOT NULL,
                PRIMARY KEY(opportunity_id,document_id)
            );
        """)
        if DEMO_MODE:
            seed_user(db, "Administrador Demonstração", "admin@licitara.demo", "+55 48 99157-9450", "AdminDemo#2026", "admin", "approved")
            seed_user(db, "Mariana Costa", "empresa@licitara.demo", "+55 48 99999-0000", "EmpresaDemo#2026", "client", "approved")
            user = db.execute("SELECT id FROM users WHERE email=?", ("empresa@licitara.demo",)).fetchone()
            if user:
                db.execute("""INSERT OR IGNORE INTO companies
                    (user_id,legal_name,trade_name,cnpj,state,city,activity,products,regions,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (user["id"], "Costa Suprimentos Ltda.", "Costa Suprimentos", "11222333000181", "SC", "Florianópolis",
                     "Fornecimento de materiais de limpeza e escritório.",
                     json.dumps(["Material de limpeza", "Material de escritório"], ensure_ascii=False),
                     json.dumps([], ensure_ascii=False), now()))
        elif os.environ.get("ADMIN_EMAIL") and os.environ.get("ADMIN_PASSWORD"):
            if len(os.environ["ADMIN_PASSWORD"]) < 12:
                raise RuntimeError("ADMIN_PASSWORD deve ter pelo menos 12 caracteres.")
            seed_user(db, os.environ.get("ADMIN_NAME", "Administrador"), os.environ["ADMIN_EMAIL"].lower(),
                      "", os.environ["ADMIN_PASSWORD"], "admin", "approved")


def now():
    return datetime.now().isoformat(timespec="seconds")


def seed_user(db, name, email, phone, password, role, status):
    if not db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        db.execute("INSERT INTO users(name,email,phone,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?,?)",
                   (name, email, phone, hash_password(password), role, status, now()))


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return salt.hex() + "$" + digest.hex()


def check_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        computed = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 310000).hex()
        return hmac.compare_digest(computed, digest_hex)
    except (ValueError, TypeError):
        return False


def valid_cnpj(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 14 or len(set(digits)) == 1:
        return False
    for length, weights in ((12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
                            (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))):
        total = sum(int(digits[i]) * weights[i] for i in range(length))
        remainder = total % 11
        check = 0 if remainder < 2 else 11 - remainder
        if int(digits[length]) != check:
            return False
    return True


def clean(s):
    return str(s or "").strip()


def fold_text(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def singular_word(word):
    if word.endswith("ais") and len(word) > 4:
        return word[:-3] + "al"
    if word.endswith("oes") and len(word) > 4:
        return word[:-3] + "ao"
    if word.endswith("s") and len(word) > 4:
        return word[:-1]
    return word


def send_email(to, subject, body):
    sent = False
    host = os.environ.get("SMTP_HOST")
    if host and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"):
        message = EmailMessage()
        message["From"] = os.environ.get("SMTP_FROM", os.environ["SMTP_USER"])
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
                smtp.send_message(message)
            sent = True
        except (OSError, smtplib.SMTPException, ValueError):
            sent = False
    with connect() as db:
        db.execute("INSERT INTO notifications(recipient,subject,body,created_at,sent) VALUES(?,?,?,?,?)",
                   (to, subject, body, now(), int(sent)))
    return sent


def fetch_json(url):
    global LAST_API_REQUEST
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Licitara/1.0 (public PNCP data)"})
    for attempt in range(3):
        try:
            with API_REQUEST_LOCK:
                wait = API_MIN_INTERVAL - (time.time() - LAST_API_REQUEST)
                if wait > 0:
                    time.sleep(wait)
                LAST_API_REQUEST = time.time()
            with urllib.request.urlopen(request, timeout=18) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500 or attempt == 2:
                raise
            retry_after = min(3, int(exc.headers.get("Retry-After", "1") or 1))
            time.sleep(max(1, retry_after))
        except urllib.error.URLError:
            if attempt == 2:
                raise
            time.sleep(1)


def pncp_link(record):
    org = record.get("orgaoEntidade") or {}
    unit = record.get("unidadeOrgao") or {}
    cnpj = org.get("cnpj") or record.get("cnpj")
    year = record.get("anoCompra")
    seq = record.get("sequencialCompra")
    if cnpj and year and seq:
        return f"https://pncp.gov.br/app/editais/{cnpj}/{year}/{seq}"
    return record.get("linkSistemaOrigem") or ""


def normalize(record):
    unit = record.get("unidadeOrgao") or {}
    org = record.get("orgaoEntidade") or {}
    control = record.get("numeroControlePNCP") or ""
    return {
        "id": control or secrets.token_hex(8), "modalidade": record.get("modalidadeNome") or "Modalidade não informada",
        "status": record.get("situacaoCompraNome") or "Status não informado",
        "origem": record.get("usuarioNome") or "PNCP", "titulo": record.get("objetoCompra") or "Objeto não informado",
        "orgao": org.get("razaoSocial") or unit.get("nomeUnidade") or "Órgão não informado",
        "cidade": unit.get("municipioNome") or "Município não informado", "uf": unit.get("ufSigla") or "",
        "numero": record.get("numeroCompra") or "Não informado",
        "sessao": record.get("dataEncerramentoProposta") or record.get("dataAberturaProposta"),
        "valor": record.get("valorTotalEstimado"), "pncp": control or "Não informado",
        "documentos": None, "url": pncp_link(record), "demo": False,
        "orgao_cnpj": org.get("cnpj"), "ano": record.get("anoCompra"),
        "sequencial": record.get("sequencialCompra")
    }


def fetch_opportunities(params):
    cache_params = dict(params)
    cache_params.pop("refresh", None)
    cache_key = json.dumps(cache_params, sort_keys=True, ensure_ascii=False)
    cached = API_CACHE.get(cache_key)
    if cached and not params.get("refresh") and time.time() - cached[0] < API_CACHE_TTL:
        return cached[1]
    today = date.today().strftime("%Y%m%d")
    query = {"dataFinal": today, "pagina": max(1, int(params.get("page", 1))), "tamanhoPagina": 50}
    states = params.get("states") or []
    if len(states) == 1:
        query["uf"] = states[0]
    if params.get("city_ibge"):
        query["codigoMunicipioIbge"] = params["city_ibge"]
    url = PNCP_BASE + "/v1/contratacoes/proposta?" + urllib.parse.urlencode(query)
    payload = fetch_json(url)
    records = [normalize(x) for x in payload.get("data", [])]
    persist_opportunities(records)
    current_time = datetime.now()
    records = [r for r in records if not r["sessao"] or not _is_expired(r["sessao"], current_time)]
    query_text = fold_text(clean(params.get("q")))
    query_terms = [w for w in re.findall(r"[\w]+", query_text) if len(w) > 1]
    city = clean(params.get("city")).casefold()
    states = set(params.get("states") or [])
    products = [clean(p).casefold() for p in params.get("products", []) if clean(p)]
    min_value = params.get("min_value")
    if query_terms:
        records = [r for r in records if any(
            term in fold_text(f"{r['titulo']} {r['orgao']} {r['cidade']} {r['numero']} {r['modalidade']}")
            or singular_word(term) in fold_text(f"{r['titulo']} {r['orgao']} {r['cidade']} {r['numero']} {r['modalidade']}")
            for term in query_terms)]
    if states:
        records = [r for r in records if r["uf"] in states]
    if city:
        records = [r for r in records if city in r["cidade"].casefold()]
    if min_value is not None:
        records = [r for r in records if isinstance(r["valor"], (int, float)) and r["valor"] >= float(min_value)]
    for record in records:
        title = fold_text(record["titulo"])
        title_words = set(re.findall(r"[\w]+", title))
        product_terms = {singular_word(w) for p in products for w in re.findall(r"[\w]+", fold_text(p)) if len(w) > 4}
        record["match"] = any(fold_text(p) in title for p in products) or bool(product_terms.intersection({singular_word(w) for w in title_words})) if products else False
    sort = params.get("sort", "date")
    records.sort(key=lambda r: (r["valor"] is not None, r["valor"] or 0) if sort == "value" else (r["sessao"] or ""), reverse=True)
    result = {"opportunities": records, "total": payload.get("totalRegistros", len(records)),
              "page": payload.get("numeroPagina", 1), "pages": payload.get("totalPaginas", 1),
              "source": "PNCP", "updated_at": now()}
    API_CACHE[cache_key] = (time.time(), result)
    expired = [key for key, value in API_CACHE.items() if time.time() - value[0] > API_CACHE_TTL]
    for key in expired:
        API_CACHE.pop(key, None)
    while len(API_CACHE) > 500:
        API_CACHE.pop(next(iter(API_CACHE)))
    return result


def _is_expired(value, current_time):
    try:
        closing = datetime.fromisoformat(value)
        return closing.date() < current_time.date() if closing.tzinfo is None else closing < current_time.astimezone(closing.tzinfo)
    except (TypeError, ValueError):
        return False


def persist_opportunities(records):
    with connect() as db:
        for record in records:
            db.execute("""INSERT INTO opportunities(id,source,record_json,fetched_at) VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET record_json=excluded.record_json,fetched_at=excluded.fetched_at""",
                (record["id"], "PNCP", json.dumps(record, ensure_ascii=False), now()))


def get_indexed_opportunities():
    with connect() as db:
        rows = db.execute("SELECT record_json FROM opportunities WHERE source='PNCP' ORDER BY fetched_at DESC LIMIT 1000").fetchall()
    records = []
    for row in rows:
        try:
            records.append(json.loads(row["record_json"]))
        except (ValueError, TypeError):
            continue
    return records


def public_user(user, company):
    result = {k: user[k] for k in ("id", "name", "email", "phone", "role", "status", "created_at")}
    result["company"] = None
    if company:
        result["company"] = {k: company[k] for k in ("legal_name", "trade_name", "cnpj", "state", "city", "activity")}
        result["company"]["products"] = json.loads(company["products"] or "[]")
        result["company"]["regions"] = json.loads(company["regions"] or "[]")
    return result


def region_states(region):
    mapping = {
        "Norte": ["AC", "AP", "AM", "PA", "RO", "RR", "TO"],
        "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
        "Centro-Oeste": ["DF", "GO", "MT", "MS"],
        "Sudeste": ["ES", "MG", "RJ", "SP"],
        "Sul": ["PR", "RS", "SC"],
    }
    return mapping.get(region, [])


class Handler(BaseHTTPRequestHandler):
    server_version = "Licitara/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("APP_DEBUG") == "1":
            super().log_message(fmt, *args)

    def send_json(self, status, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'")
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 100_000:
            raise ValueError("Corpo da solicitação muito grande.")
        raw = self.rfile.read(size)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def session_user(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["lic_session"].value
        except (KeyError, AttributeError):
            return None, None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connect() as db:
            row = db.execute("""SELECT u.*, c.legal_name,c.trade_name,c.cnpj,c.state,c.city,c.activity,c.products,c.regions
                FROM sessions s JOIN users u ON u.id=s.user_id LEFT JOIN companies c ON c.user_id=u.id
                WHERE s.token_hash=? AND s.expires_at>?""", (digest, now())).fetchone()
        if not row:
            return None, None
        company = {k: row[k] for k in ("legal_name", "trade_name", "cnpj", "state", "city", "activity", "products", "regions")} if row["legal_name"] else None
        return row, company

    def require_user(self, approved=False, admin=False):
        user, company = self.session_user()
        if not user:
            self.send_json(401, {"error": "Entre na sua conta para continuar."})
            return None, None
        if admin and user["role"] != "admin":
            self.send_json(403, {"error": "Acesso restrito à administração."})
            return None, None
        if approved and user["status"] != "approved":
            self.send_json(403, {"error": "O acesso à central depende da aprovação do cadastro.", "status": user["status"]})
            return None, None
        return user, company

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self.api_get(path)
        file = ROOT / ("index.html" if path == "/" else path.lstrip("/"))
        try:
            resolved = file.resolve()
            if ROOT not in resolved.parents and resolved != ROOT / "index.html":
                raise FileNotFoundError()
            data = resolved.read_bytes()
        except (OSError, ValueError):
            self.send_error(404)
            return
        content_type = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}.get(resolved.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def api_get(self, path):
        if path == "/api/catalog":
            return self.send_json(200, {"categories": CATALOG})
        if path == "/api/me":
            user, company = self.session_user()
            if not user:
                return self.send_json(200, {"user": None, "demo_mode": DEMO_MODE})
            return self.send_json(200, {"user": public_user(user, company), "demo_mode": DEMO_MODE})
        if path == "/api/opportunities":
            user, company = self.require_user(approved=True)
            if not user:
                return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            requested_states = query.get("state", [])
            regions = query.get("region", [])
            for region in regions:
                requested_states.extend(region_states(region))
            prefs = json.loads(company["regions"] or "[]") if company else []
            if not requested_states and not query.get("all"):
                requested_states.extend(prefs)
            params = {"q": query.get("q", [""])[0], "city": query.get("city", [""])[0],
                      "states": sorted(set(requested_states)), "sort": query.get("sort", ["date"])[0],
                      "page": query.get("page", ["1"])[0],
                      "refresh": query.get("refresh", [""])[0] == "1",
                      "min_value": query.get("min_value", [None])[0],
                      "products": json.loads(company["products"] or "[]") if company else []}
            try:
                result = fetch_opportunities(params)
                return self.send_json(200, result)
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError) as exc:
                result = demo_result(params)
                result["warning"] = "Não foi possível consultar o PNCP agora. Exibindo exemplos identificados como demonstração."
                result["error_detail"] = "PNCP indisponível temporariamente"
                return self.send_json(200, result)
        if path.startswith("/api/opportunities/") and path.endswith("/items"):
            user, _ = self.require_user(approved=True)
            if not user:
                return
            item_id = urllib.parse.unquote(path[len("/api/opportunities/"):-len("/items")].strip("/"))
            return self.get_items(item_id)
        if path == "/api/admin/companies":
            user, _ = self.require_user(admin=True)
            if not user:
                return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            search = clean(query.get("q", [""])[0]).casefold()
            with connect() as db:
                rows = db.execute("""SELECT u.*,c.legal_name,c.trade_name,c.cnpj,c.state,c.city,c.activity,c.products,c.regions
                    FROM users u JOIN companies c ON c.user_id=u.id ORDER BY u.created_at DESC""").fetchall()
            companies = []
            for row in rows:
                item = public_user(row, row)
                if search and search not in f"{item['name']} {item['email']} {item['company']['trade_name']} {item['company']['cnpj']}".casefold():
                    continue
                companies.append(item)
            counts = {s: sum(1 for c in companies if c["status"] == s) for s in ("pending", "approved", "rejected", "suspended")}
            return self.send_json(200, {"companies": companies, "counts": counts, "total": len(companies)})
        if path == "/api/admin/history":
            user, _ = self.require_user(admin=True)
            if not user:
                return
            with connect() as db:
                rows = db.execute("""SELECT h.*,u.name AS company_name,c.trade_name,a.name AS admin_name
                    FROM approval_history h JOIN users u ON u.id=h.company_user_id
                    LEFT JOIN companies c ON c.user_id=u.id JOIN users a ON a.id=h.admin_user_id
                    ORDER BY h.created_at DESC LIMIT 100""").fetchall()
            return self.send_json(200, {"history": [dict(r) for r in rows]})
        if path == "/api/admin/notifications":
            user, _ = self.require_user(admin=True)
            if not user:
                return
            with connect() as db:
                rows = db.execute("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 50").fetchall()
            return self.send_json(200, {"notifications": [dict(r) for r in rows]})
        return self.send_json(404, {"error": "Rota não encontrada."})

    def get_items(self, item_id):
        if item_id.startswith("demo-"):
            demo = next((x for x in DEMO_OPPORTUNITIES if x["id"] == item_id), None)
            return self.send_json(200, {"items": demo["items"] if demo else [], "documents": [],
                                         "source": "Demonstração", "unavailable": False, "opportunity": demo})
        control = item_id.split("-")
        if len(control) != 3:
            return self.send_json(400, {"error": "Identificador PNCP inválido."})
        cnpj, _, sequence_year = control
        seq, year = sequence_year.split("/", 1) if "/" in sequence_year else (None, None)
        if not seq or not year:
            return self.send_json(400, {"error": "Identificador PNCP inválido."})
        url = f"{PNCP_DATA_BASE}/v1/orgaos/{urllib.parse.quote(cnpj)}/compras/{year}/{seq}/itens?pagina=1&tamanhoPagina=100"
        try:
            payload = fetch_json(url)
            entries = payload if isinstance(payload, list) else payload.get("data", [])
            items = [{
                "descricao": i.get("descricao") or i.get("descricaoItem") or "Não informado",
                "natureza": i.get("materialOuServicoNome") or "Não informado",
                "quantidade": i.get("quantidade"), "unidade": i.get("unidadeMedida") or i.get("unidadeFornecimento"),
                "unitario": i.get("valorUnitarioEstimado"),
                "total": i.get("valorTotal") if i.get("valorTotal") is not None else i.get("valorTotalEstimado")
            } for i in entries]
            with connect() as db:
                db.execute("""INSERT OR IGNORE INTO opportunities(id,source,record_json,fetched_at)
                    VALUES(?,?,?,?)""", (item_id, "PNCP", json.dumps({
                        "id": item_id, "orgao_cnpj": cnpj, "ano": int(year), "sequencial": int(seq)
                    }), now()))
                for index, item in enumerate(items):
                    db.execute("""INSERT INTO tender_items(opportunity_id,item_index,item_json) VALUES(?,?,?)
                        ON CONFLICT(opportunity_id,item_index) DO UPDATE SET item_json=excluded.item_json""",
                        (item_id, index, json.dumps(item, ensure_ascii=False)))
            documents = []
            documents_url = f"{PNCP_DATA_BASE}/v1/orgaos/{urllib.parse.quote(cnpj)}/compras/{year}/{seq}/arquivos?pagina=1&tamanhoPagina=100"
            try:
                docs_payload = fetch_json(documents_url)
                docs_payload = docs_payload if isinstance(docs_payload, list) else docs_payload.get("data", [])
                for doc in docs_payload:
                    url = doc.get("url") or doc.get("uri") or ""
                    parsed_url = urllib.parse.urlparse(url)
                    if parsed_url.scheme not in ("http", "https"):
                        url = ""
                    documents.append({
                        "title": doc.get("titulo") or doc.get("tipoDocumentoNome") or doc.get("tipoDocumentoDescricao") or "Documento oficial",
                        "url": url, "type": doc.get("tipoDocumentoNome") or doc.get("tipoDocumentoDescricao")
                    })
                with connect() as db:
                    for index, document in enumerate(documents):
                        db.execute("""INSERT INTO tender_documents(opportunity_id,document_id,document_json) VALUES(?,?,?)
                            ON CONFLICT(opportunity_id,document_id) DO UPDATE SET document_json=excluded.document_json""",
                            (item_id, str(index), json.dumps(document, ensure_ascii=False)))
            except (urllib.error.URLError, TimeoutError, ValueError, OSError, AttributeError):
                documents = []
            return self.send_json(200, {"items": items, "documents": documents, "source": "PNCP", "unavailable": False})
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return self.send_json(200, {"items": [], "source": "PNCP", "unavailable": True,
                                       "message": "A fonte oficial não disponibilizou os itens desta contratação."})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self.body()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return self.send_json(400, {"error": "Solicitação inválida."})
        if path == "/api/signup":
            return self.signup(data)
        if path == "/api/login":
            return self.login(data)
        if path == "/api/logout":
            user, _ = self.session_user()
            cookie = SimpleCookie()
            cookie["lic_session"] = ""
            cookie["lic_session"]["path"] = "/"
            cookie["lic_session"]["httponly"] = True
            cookie["lic_session"]["samesite"] = "Strict"
            cookie["lic_session"]["max-age"] = 0
            if user:
                with connect() as db:
                    db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            return self.send_json(200, {"ok": True}, {"Set-Cookie": cookie["lic_session"].OutputString()})
        if path == "/api/preferences":
            user, company = self.require_user()
            if not user:
                return
            if user["role"] != "client" or not company:
                return self.send_json(403, {"error": "Preferências não disponíveis."})
            products = data.get("products", [])
            states = data.get("states", [])
            if not isinstance(products, list) or len(products) > 100 or not isinstance(states, list) or len(states) > 27:
                return self.send_json(400, {"error": "Preferências inválidas."})
            with connect() as db:
                db.execute("UPDATE companies SET products=?,regions=?,updated_at=? WHERE user_id=?",
                           (json.dumps([clean(x)[:120] for x in products if clean(x)], ensure_ascii=False),
                            json.dumps([clean(x).upper() for x in states if clean(x)], ensure_ascii=False), now(), user["id"]))
            return self.send_json(200, {"ok": True})
        if path == "/api/admin/action":
            return self.admin_action(data)
        if path == "/api/chat":
            return self.chat(data)
        return self.send_json(404, {"error": "Rota não encontrada."})

    def signup(self, data):
        name, email, phone = clean(data.get("name")), clean(data.get("email")).lower(), clean(data.get("phone"))
        legal, trade = clean(data.get("legal_name")), clean(data.get("trade_name"))
        cnpj = re.sub(r"\D", "", clean(data.get("cnpj")))
        state, city, activity = clean(data.get("state")).upper(), clean(data.get("city")), clean(data.get("activity"))
        password, products = data.get("password", ""), data.get("products", [])
        if not all((name, email, phone, legal, trade, cnpj, state, city, activity)) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return self.send_json(400, {"error": "Preencha todos os campos obrigatórios com informações válidas."})
        if not valid_cnpj(cnpj):
            return self.send_json(400, {"error": "O CNPJ informado não passou pela validação dos dígitos verificadores."})
        if len(password) < 8 or len(name) > 140 or len(activity) > 1200 or not isinstance(products, list) or len(products) > 100:
            return self.send_json(400, {"error": "Use uma senha com pelo menos 8 caracteres e confira os demais campos."})
        if state not in ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]:
            return self.send_json(400, {"error": "Selecione um estado brasileiro válido."})
        try:
            with connect() as db:
                cursor = db.execute("INSERT INTO users(name,email,phone,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?,?)",
                    (name[:140], email, phone[:32], hash_password(password), "client", "pending", now()))
                uid = cursor.lastrowid
                db.execute("""INSERT INTO companies(user_id,legal_name,trade_name,cnpj,state,city,activity,products,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (uid, legal[:180], trade[:180], cnpj, state, city[:120], activity[:1200],
                    json.dumps([clean(p)[:120] for p in products if clean(p)], ensure_ascii=False), now()))
                admin = db.execute("SELECT email FROM users WHERE role='admin' LIMIT 1").fetchone()
        except sqlite3.IntegrityError:
            return self.send_json(409, {"error": "Já existe uma conta ou empresa com este e-mail ou CNPJ."})
        if admin:
            send_email(admin["email"], "Novo cadastro aguardando análise", f"A empresa {trade} ({cnpj}) solicitou acesso à Licitara.")
        return self.send_json(201, {"ok": True, "status": "pending", "message": "Cadastro recebido e aguardando aprovação."})

    def login(self, data):
        email, password = clean(data.get("email")).lower(), data.get("password", "")
        attempt_key = (self.client_address[0], email)
        attempts, first_attempt = LOGIN_ATTEMPTS.get(attempt_key, (0, time.time()))
        if time.time() - first_attempt > 900:
            attempts, first_attempt = 0, time.time()
        if attempts >= 8:
            return self.send_json(429, {"error": "Muitas tentativas. Aguarde 15 minutos e tente novamente."})
        with connect() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not user or not check_password(password, user["password_hash"]):
                LOGIN_ATTEMPTS[attempt_key] = (attempts + 1, first_attempt)
                return self.send_json(401, {"error": "E-mail ou senha incorretos."})
            LOGIN_ATTEMPTS.pop(attempt_key, None)
            token = secrets.token_urlsafe(36)
            expiry = (datetime.now() + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
            db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), user["id"], expiry))
            company = db.execute("SELECT * FROM companies WHERE user_id=?", (user["id"],)).fetchone()
        cookie = SimpleCookie()
        cookie["lic_session"] = token
        cookie["lic_session"]["path"] = "/"
        cookie["lic_session"]["httponly"] = True
        cookie["lic_session"]["samesite"] = "Strict"
        cookie["lic_session"]["max-age"] = SESSION_DAYS * 86400
        if os.environ.get("COOKIE_SECURE", "0") == "1":
            cookie["lic_session"]["secure"] = True
        return self.send_json(200, {"user": public_user(user, company), "demo_mode": DEMO_MODE},
                              {"Set-Cookie": cookie["lic_session"].OutputString()})

    def admin_action(self, data):
        admin, _ = self.require_user(admin=True)
        if not admin:
            return
        try:
            user_id = int(data.get("user_id"))
        except (TypeError, ValueError):
            return self.send_json(400, {"error": "Empresa inválida."})
        action = clean(data.get("action"))
        status_map = {"approve": "approved", "reject": "rejected", "suspend": "suspended", "reinstate": "approved"}
        if action not in status_map:
            return self.send_json(400, {"error": "Ação inválida."})
        with connect() as db:
            target = db.execute("""SELECT u.*,c.trade_name FROM users u JOIN companies c ON c.user_id=u.id WHERE u.id=?""", (user_id,)).fetchone()
            if not target or target["role"] != "client":
                return self.send_json(404, {"error": "Empresa não encontrada."})
            status = status_map[action]
            db.execute("UPDATE users SET status=? WHERE id=?", (status, user_id))
            db.execute("INSERT INTO approval_history(company_user_id,admin_user_id,action,created_at) VALUES(?,?,?,?)",
                       (user_id, admin["id"], status, now()))
        if action in ("approve", "reject", "suspend", "reinstate"):
            if status == "approved":
                subject, body = "Seu acesso à Licitara foi liberado", f"Olá, {target['name']}! O cadastro da empresa {target['trade_name']} foi aprovado. Você já pode acessar a central de oportunidades."
            elif status == "rejected":
                subject, body = "Atualização sobre seu cadastro na Licitara", f"Olá, {target['name']}. O cadastro da empresa {target['trade_name']} não foi aprovado. Entre em contato com nossa equipe para mais informações."
            else:
                subject, body = "Atualização do acesso à Licitara", f"Olá, {target['name']}. O acesso da empresa {target['trade_name']} foi atualizado para: {status}."
            send_email(target["email"], subject, body)
        return self.send_json(200, {"ok": True, "status": status})

    def chat(self, data):
        user, company = self.require_user(approved=True)
        if not user:
            return
        question = clean(data.get("message"))
        if not question or len(question) > 1200:
            return self.send_json(400, {"error": "Escreva uma pergunta de até 1.200 caracteres."})
        try:
            folded_question = fold_text(question)
            stop_words = {
                "encontre", "existem", "quais", "qual", "para", "mais", "acima", "abaixo", "abertas",
                "abertos", "licitacao", "licitacoes", "edital", "editais", "empresa", "minha", "sobre",
                "estado", "municipio", "prefeituras", "valor", "estimado", "estimadas", "recentes",
                "fornecimento", "procurando", "oportunidades", "aberta", "aberto", "produto", "produtos",
                "servico", "servicos", "existe", "estao", "estao", "tem", "acima", "de", "do", "da",
                "em", "no", "na", "um", "uma", "com", "que", "meus", "minhas", "empresa", "publicas"
            }
            words = [w for w in re.findall(r"[\w]+", folded_question) if len(w) > 3 and w not in stop_words]
            product_names = json.loads(company["products"] or "[]") if company else []
            query = {"q": "", "states": [], "products": product_names, "sort": "date"}
            result = fetch_opportunities(query)
            records = get_indexed_opportunities() or result["opportunities"]

            requested_states = {
                code for code, name in STATES_FOR_SEARCH
                if fold_text(name) in folded_question or re.search(rf"\b{code.casefold()}\b", folded_question)
            }
            for region, codes in REGIONS_FOR_SEARCH.items():
                if fold_text(region) in folded_question:
                    requested_states.update(codes)
            if requested_states:
                records = [r for r in records if r.get("uf") in requested_states]

            city_names = {r.get("cidade") for r in records if r.get("cidade")}
            city_names.discard("Município não informado")
            requested_cities = [city for city in city_names if len(fold_text(city)) > 3 and fold_text(city) in folded_question]
            if requested_cities:
                records = [r for r in records if any(fold_text(city) == fold_text(r.get("cidade")) for city in requested_cities)]

            min_match = re.search(r"(?:acima|maior|superior)\s+(?:a|de|que)?\s*(?:r\$\s*)?([\d.,]+)\s*(mil|k|milh(?:ao|oes))?", folded_question)
            minimum = None
            if min_match:
                amount = float(min_match.group(1).replace(".", "").replace(",", "."))
                minimum = amount * (1_000_000 if min_match.group(2) and min_match.group(2).startswith("milh") else 1_000 if min_match.group(2) else 1)
                records = [r for r in records if isinstance(r.get("valor"), (int, float)) and r["valor"] >= minimum]

            for state_name in (name for _, name in STATES_FOR_SEARCH):
                state_words = set(re.findall(r"[\w]+", fold_text(state_name)))
                words = [w for w in words if w not in state_words]
            for city in requested_cities:
                city_words = set(re.findall(r"[\w]+", fold_text(city)))
                words = [w for w in words if w not in city_words]
            query_terms = [w for w in words if w not in stop_words and not w.isdigit()]
            if min_match:
                query_terms = [w for w in query_terms if not re.fullmatch(r"\d+k?", w)]

            def relevance(record):
                title = fold_text(record.get("titulo"))
                title_words = {singular_word(w) for w in re.findall(r"[\w]+", title)}
                query_score = sum(1 for term in query_terms if term in title or singular_word(term) in title_words)
                product_terms = {singular_word(w) for p in product_names for w in re.findall(r"[\w]+", fold_text(p)) if len(w) > 4}
                product_score = len(product_terms.intersection(title_words))
                return query_score, product_score

            ranked = [(relevance(record), record) for record in records]
            if query_terms:
                ranked = [(score, record) for score, record in ranked if score[0] > 0]
            elif not minimum and not requested_states and not requested_cities:
                ranked = [(score, record) for score, record in ranked if score[1] > 0]
            ranked.sort(key=lambda item: (item[0][0], item[0][1], item[1].get("sessao") or ""), reverse=True)
            records = [record for _, record in ranked]
            records = records[:5]
            if os.environ.get("OPENAI_API_KEY") and records:
                answer = ask_ai(question, records, product_names)
                with connect() as db:
                    db.execute("INSERT INTO chat_history(user_id,question,answer,created_at) VALUES(?,?,?,?)", (user["id"], question, answer, now()))
                return self.send_json(200, {"answer": answer, "source": "PNCP", "grounded": True, "opportunities": records})
            if records:
                parts = ["Encontrei oportunidades na consulta ao PNCP. Confira os dados e os documentos na fonte oficial:"]
                for item in records:
                    value = f"R$ {item['valor']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if isinstance(item["valor"], (int, float)) and item["valor"] else "valor não informado"
                    parts.append(f"• {item['titulo']} — {item['cidade']}/{item['uf']}; {value}; sessão: {item['sessao'] or 'não informada'}. Itens: consulte o edital. Link: {item['url']}")
                answer = "\n\n".join(parts)
            else:
                lower = question.casefold()
                if any(term in lower for term in ("como participar", "requisitos", "como funciona", "como entrar", "habilitação", "documentos", "pregão")):
                    answer = ("Em geral, comece lendo o edital e seus anexos: eles definem quem pode participar, documentos de habilitação, "
                              "especificações, prazos e forma de envio da proposta. Verifique também o cadastro exigido pela plataforma "
                              "de compras indicada no aviso e confirme as datas no processo oficial. Cada contratação pode ter condições "
                              "diferentes; o edital publicado pelo órgão é sempre a referência. Posso procurar oportunidades para algum produto ou município?")
                else:
                    answer = "Não encontrei uma oportunidade correspondente entre os registros carregados do PNCP. Tente palavras-chave mais curtas ou ajuste os filtros da central. Não vou inventar editais, valores ou datas."
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError):
            answer = "O PNCP não respondeu neste momento. Posso orientar sobre a consulta: use termos objetivos, confira a data de encerramento das propostas e confirme sempre condições e requisitos no edital oficial."
        with connect() as db:
            db.execute("INSERT INTO chat_history(user_id,question,answer,created_at) VALUES(?,?,?,?)", (user["id"], question, answer, now()))
        return self.send_json(200, {"answer": answer, "source": "PNCP", "grounded": True, "opportunities": records if "records" in locals() else []})


def demo_result(params):
    records = [dict(x) for x in DEMO_OPPORTUNITIES]
    query_text = clean(params.get("q")).casefold()
    states = set(params.get("states") or [])
    city = clean(params.get("city")).casefold()
    for record in records:
        record["match"] = any(clean(p).casefold() in record["titulo"].casefold() for p in params.get("products", []))
    if query_text:
        records = [r for r in records if query_text in f"{r['titulo']} {r['orgao']} {r['cidade']} {r['modalidade']}".casefold()]
    if states:
        records = [r for r in records if r["uf"] in states]
    if city:
        records = [r for r in records if city in r["cidade"].casefold()]
    return {"opportunities": records, "total": len(records), "page": 1, "pages": 1,
            "source": "Demonstração", "demo": True, "updated_at": now()}


def ask_ai(question, opportunities, products):
    context = [{
        "title": r["titulo"], "agency": r["orgao"], "city": r["cidade"], "state": r["uf"],
        "estimated_value": r["valor"], "proposal_deadline": r["sessao"], "pncp_id": r["pncp"],
        "official_url": r["url"], "matched_company_products": products
    } for r in opportunities]
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": (
                "Você é a assistente Licitara, especializada exclusivamente em licitações públicas brasileiras. "
                "Responda em português, de forma clara para pequenas empresas. Use somente os registros PNCP "
                "incluídos no contexto. Nunca invente editais, preços, prazos, itens ou requisitos. Se um dado "
                "não estiver no contexto, diga que não foi informado e recomende conferir o edital oficial. "
                "Não afirme que os itens foram extraídos se não houver essa informação. Inclua o link oficial "
                "quando disponível. Esta resposta não substitui a leitura do edital."
            )},
            {"role": "user", "content": f"Pergunta: {question}\n\nRegistros oficiais PNCP recuperados:\n{json.dumps(context, ensure_ascii=False)}"}
        ]
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        result = json.loads(response.read().decode("utf-8"))
    answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    return answer.strip() or "Não foi possível gerar uma resposta agora. Consulte os registros na fonte oficial."


def warm_pncp_cache():
    while True:
        try:
            fetch_opportunities({"q": "", "city": "", "states": [], "sort": "date", "page": 1, "products": []})
        except Exception:
            pass
        time.sleep(API_CACHE_TTL)


if __name__ == "__main__":
    init_db()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Licitara disponível em http://{host}:{port}")
    if DEMO_MODE:
        print("Modo demonstração ativo. Desative DEMO_MODE em qualquer instalação pública.")
    threading.Thread(target=warm_pncp_cache, daemon=True, name="pncp-cache-refresh").start()
    ThreadingHTTPServer((host, port), Handler).serve_forever()
