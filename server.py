import ipaddress
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "data" / "licitara.db"))
PNCP_BASE = "https://pncp.gov.br/api/consulta"
PNCP_DATA_BASE = "https://pncp.gov.br/api/pncp"
API_CACHE = {}
API_CACHE_TTL = 300
WARM_INTERVAL = 180
API_MAX_ATTEMPTS = 2
API_REQUEST_LOCK = threading.Lock()
LAST_API_REQUEST = 0.0
API_MIN_INTERVAL = 1.0
RATE_LIMIT_UNTIL = 0.0
# Quando a rota de propostas abertas falha, ela fica de castigo por um minuto
# para a página não esperar o tempo limite em cada acesso.
PROPOSTA_DOWN_UNTIL = 0.0
FETCH_STATE = threading.local()
PAGE_SIZE = 50
FUTURE_WINDOW_DAYS = 15
# A rota de propostas abertas cai com frequência. A reserva oficial
# (v1/contratacoes/publicacao) entrega 50 registros por página e o PNCP limita
# o IP, então as contratações recentes são coletadas em segundo plano e
# acumuladas aqui: sem isso a tela mostrava apenas as primeiras ~250.
# Consultar vários dias de uma vez devolve as publicações mais antigas primeiro
# (só 16 em 50 ainda recebiam propostas); por isso a coleta pergunta um dia por
# vez, começando hoje, onde praticamente todas as contratações estão abertas.
FALLBACK_WINDOW_DAYS = 7
# Pregão Eletrônico, Dispensa, Inexigibilidade, Concorrências, Pregão
# Presencial e Leilão. Dispensa e Inexigibilidade são as de maior volume.
FALLBACK_MODALITIES = (6, 8, 9, 4, 5, 7, 1)
FALLBACK_PAGES = 12
FALLBACK_TARGET = 4000
FALLBACK_MIN_READY = 200
# O PNCP responde 429 quando as requisições chegam a cada segundo; ~3 s entre
# elas é o ritmo que a coleta sustenta sem parar o site inteiro.
FALLBACK_PACE = 3.0
# Hoje primeiro, página 1 de todas as modalidades, depois as páginas
# seguintes e só então o dia anterior.
FALLBACK_QUEUE = tuple((back, code, page) for back in range(FALLBACK_WINDOW_DAYS)
                       for page in range(1, FALLBACK_PAGES + 1)
                       for code in FALLBACK_MODALITIES)
FALLBACK_STORE = {}
FALLBACK_LOCK = threading.Lock()
FALLBACK_CURSOR = 0
FALLBACK_STAMP = 0.0
FALLBACK_LAST_NEEDED = 0.0
FALLBACK_PASS_DONE = 0.0
FALLBACK_SEEDED = False
# O PNCP filtra propostas pelo encerramento: sem janela, a consulta com a data
# de hoje devolvia só quem fechava hoje e os filtros ficavam vazios.
OPEN_WINDOW_DAYS = 15
FILTER_SCAN_PAGES = 4
# Modalidades publicadas no PNCP usadas na busca por licitações futuras.
# Códigos conferidos na API de consulta (v1/contratacoes/publicacao).
FUTURE_MODALITIES = ((6, "Pregão Eletrônico"), (4, "Concorrência Eletrônica"),
                     (5, "Concorrência Presencial"), (7, "Pregão Presencial"),
                     (1, "Leilão Eletrônico"))
PERIODS = ("open", "future")

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
VALID_UFS = {code for code, _ in STATES_FOR_SEARCH}
REGIONS_FOR_SEARCH = {
    "Norte": ["AC", "AP", "AM", "PA", "RO", "RR", "TO"],
    "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste": ["DF", "GO", "MT", "MS"],
    "Sudeste": ["ES", "MG", "RJ", "SP"],
    "Sul": ["PR", "RS", "SC"],
}

DEMO_OPPORTUNITIES = [
    {"id": "demo-001", "modalidade": "Pregão Eletrônico", "status": "Aberta", "origem": "Demonstração", "titulo": "Fornecimento de materiais de limpeza para unidades municipais", "orgao": "Prefeitura Municipal (exemplo)", "cidade": "Florianópolis", "uf": "SC", "numero": "DEMO-001", "sessao": "2026-12-15T09:00:00", "abertura": "2026-12-15T09:00:00", "valor": 125000, "pncp": "DADO DEMONSTRATIVO", "documentos": None, "url": "", "demo": True, "items": [{"descricao": "Material de limpeza (exemplo demonstrativo)", "quantidade": None, "unidade": None, "unitario": None, "total": None}]},
    {"id": "demo-002", "modalidade": "Concorrência", "status": "Aberta", "origem": "Demonstração", "titulo": "Aquisição de equipamentos de informática", "orgao": "Órgão público (exemplo)", "cidade": "Curitiba", "uf": "PR", "numero": "DEMO-002", "sessao": "2026-12-18T10:00:00", "abertura": "2026-12-18T10:00:00", "valor": 248900, "pncp": "DADO DEMONSTRATIVO", "documentos": None, "url": "", "demo": True, "items": [{"descricao": "Computadores e periféricos (exemplo demonstrativo)", "quantidade": None, "unidade": None, "unitario": None, "total": None}]},
    {"id": "demo-003", "modalidade": "Pregão Eletrônico", "status": "Aberta", "origem": "Demonstração", "titulo": "Serviços de manutenção preventiva de ar-condicionado", "orgao": "Secretaria municipal (exemplo)", "cidade": "Joinville", "uf": "SC", "numero": "DEMO-003", "sessao": "2026-12-22T14:00:00", "abertura": "2026-12-22T14:00:00", "valor": 86400, "pncp": "DADO DEMONSTRATIVO", "documentos": None, "url": "", "demo": True, "items": [{"descricao": "Manutenção de ar-condicionado (exemplo demonstrativo)", "quantidade": None, "unidade": None, "unitario": None, "total": None}]},
    {"id": "demo-004", "modalidade": "Dispensa Eletrônica", "status": "Aberta", "origem": "Demonstração", "titulo": "Aquisição de mobiliário para escritório", "orgao": "Autarquia pública (exemplo)", "cidade": "Porto Alegre", "uf": "RS", "numero": "DEMO-004", "sessao": "2026-12-27T08:30:00", "abertura": "2026-12-27T08:30:00", "valor": 41900, "pncp": "DADO DEMONSTRATIVO", "documentos": None, "url": "", "demo": True, "items": [{"descricao": "Mobiliário de escritório (exemplo demonstrativo)", "quantidade": None, "unidade": None, "unitario": None, "total": None}]},
]

# Tabelas da versão com contas: o acesso anônimo não guarda dados de usuários.
LEGACY_TABLES = ("chat_history", "notifications", "approval_history", "sessions", "companies", "users")


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
        for table in LEGACY_TABLES:
            db.execute(f"DROP TABLE IF EXISTS {table}")


def now():
    return datetime.now().isoformat(timespec="seconds")


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


# Palavras de ligação não identificam um item: "material de limpeza" precisa de
# "material" e "limpeza", não de "de".
PRODUCT_STOPWORDS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na",
                     "nos", "nas", "para", "com", "por", "ao", "ou", "um", "uma", "que"}
SEARCH_STOPWORDS = PRODUCT_STOPWORDS | {"licitacao", "licitacoes", "edital", "editais", "oportunidade",
                                        "oportunidades", "busca", "buscar", "encontre", "procurando"}
ITEMS_CACHE = {}
ITEMS_CACHE_TTL = 600
# O índice de busca do PNCP é a única fonte que pesquisa texto em todo o acervo
# (objeto e itens). É ele que evita que um produto do perfil fique de fora só
# porque o objeto do edital é genérico.
INDEX_BASE = "https://pncp.gov.br/api/search/"
INDEX_PAGE_SIZE = 50
INDEX_PAGES = 3
INDEX_PAGES_PER_STATE = 2
INDEX_RECENT_DAYS = 45
INDEX_CACHE = {}
INDEX_CACHE_TTL = 600
INDEX_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://pncp.gov.br/app/editais",
}
DOWNLOAD_LIMIT = 30 * 1024 * 1024
DOWNLOAD_TIMEOUT = 60


def word_set(value):
    """Palavras normalizadas (sem acento e no singular) para comparar textos."""
    return {singular_word(word) for word in re.findall(r"[\w]+", fold_text(value))
            if len(word) > 1 and word not in PRODUCT_STOPWORDS}


def stem_word(word):
    """Radical simples: cadeira/cadeiras e hidráulica/hidráulico passam a coincidir."""
    word = singular_word(word)
    return word[:-1] if len(word) > 5 and word[-1] in ("a", "o") else word


def product_matches(text, product):
    """Um item do perfil só conta quando todas as suas palavras aparecem no texto.

    Antes bastava uma palavra em comum, então "comunicação visual" trazia
    qualquer edital que falasse em "comunicação" e o resultado parecia aleatório.
    """
    words = {stem_word(word) for word in re.findall(r"[\w]+", fold_text(text))
             if len(word) > 1 and word not in PRODUCT_STOPWORDS}
    terms = [stem_word(term) for term in re.findall(r"[\w]+", fold_text(product))
             if len(term) > 1 and term not in PRODUCT_STOPWORDS]
    if not terms:
        return False
    return all(term in words for term in terms)


def record_text(record):
    return " ".join(str(record.get(key) or "") for key in
                    ("titulo", "orgao", "cidade", "numero", "modalidade", "status"))


def pncp_parts(item_id):
    parts = str(item_id or "").split("-")
    if len(parts) != 3 or "/" not in parts[2]:
        return None
    cnpj, _separator, sequence_year = parts
    seq, year = sequence_year.split("/", 1)
    if not (cnpj and seq.isdigit() and year.isdigit()):
        return None
    return cnpj, year, seq


def _retry_delay(exc, attempt):
    raw = (exc.headers.get("Retry-After") if exc.headers else "") or ""
    try:
        return max(5, min(15, int(raw)))
    except (TypeError, ValueError):
        return min(15, 5 * (attempt + 1))


def fetch_json(url):
    global LAST_API_REQUEST, RATE_LIMIT_UNTIL
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Licitara/1.0 (public PNCP data)"})
    for attempt in range(API_MAX_ATTEMPTS):
        with API_REQUEST_LOCK:
            wait = API_MIN_INTERVAL - (time.time() - LAST_API_REQUEST)
            if wait > 0:
                time.sleep(wait)
            LAST_API_REQUEST = time.time()
        if RATE_LIMIT_UNTIL > time.time():
            raise urllib.error.URLError("PNCP em limite de requisições")
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read().decode("utf-8", errors="replace").strip()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {}
            if exc.code == 429:
                # PNCP limita por IP: pausa curta e usa o cache, sem travar a página.
                RATE_LIMIT_UNTIL = time.time() + _retry_delay(exc, attempt)
                raise
            if exc.code < 500 or attempt == API_MAX_ATTEMPTS - 1:
                raise
            time.sleep(2 * (attempt + 1))
        except urllib.error.URLError:
            # Fonte lenta ou fora do ar: não segura a resposta, o cache cobre a lacuna.
            raise
        except json.JSONDecodeError:
            if attempt == API_MAX_ATTEMPTS - 1:
                return {}
            time.sleep(1)
    return {}

def cached_json(url, refresh=False):
    """Devolve o JSON e o instante em que ele foi realmente buscado no PNCP."""
    cached = API_CACHE.get(url)
    if cached and not refresh and time.time() - cached[0] < API_CACHE_TTL:
        return cached[1], cached[0]
    try:
        payload = fetch_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        # PNCP limitou ou caiu: devolve o último dado real em vez de exemplos falsos.
        if cached:
            FETCH_STATE.stale = True
            return cached[1], cached[0]
        raise
    stamp = time.time()
    API_CACHE[url] = (stamp, payload)
    expired = [key for key, value in API_CACHE.items() if time.time() - value[0] > API_CACHE_TTL]
    for key in expired:
        API_CACHE.pop(key, None)
    while len(API_CACHE) > 400:
        API_CACHE.pop(next(iter(API_CACHE)))
    return payload, stamp


def fetch_index_json(url):
    request = urllib.request.Request(url, headers=INDEX_HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8", errors="replace").strip()
    return json.loads(raw) if raw else {}


def cached_index(url, refresh=False):
    cached = INDEX_CACHE.get(url)
    if cached and not refresh and time.time() - cached[0] < INDEX_CACHE_TTL:
        return cached[1], cached[0]
    try:
        payload = fetch_index_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        if cached:
            return cached[1], cached[0]
        raise
    stamp = time.time()
    INDEX_CACHE[url] = (stamp, payload)
    while len(INDEX_CACHE) > 200:
        INDEX_CACHE.pop(next(iter(INDEX_CACHE)))
    return payload, stamp


def index_term(product):
    """Frase com todas as palavras do item, como a busca do site do PNCP."""
    words = [word for word in re.findall(r"[\w]+", str(product).casefold())
             if len(word) > 1 and fold_text(word) not in PRODUCT_STOPWORDS]
    if not words:
        return clean(product)
    return words[0] if len(words) == 1 else '"' + " ".join(words) + '"'


def index_query_url(term, page, uf=None):
    query = {"q": term, "tipos_documento": "edital", "ordenacao": "-data",
             "pagina": page, "tamanhoPagina": INDEX_PAGE_SIZE}
    if uf:
        query["ufs"] = uf
    return INDEX_BASE + "?" + urllib.parse.urlencode(query)


def index_record(hit):
    """Converte um resultado do índice no mesmo formato da consulta de propostas."""
    control = clean(hit.get("numero_controle_pncp"))
    if not control:
        return None
    cnpj = clean(hit.get("orgao_cnpj"))
    year = hit.get("ano")
    sequence = hit.get("numero_sequencial")
    url = f"https://pncp.gov.br/app/editais/{cnpj}/{year}/{sequence}" if cnpj and year and sequence else ""
    title = clean(hit.get("description")) or clean(hit.get("title")) or "Objeto não informado"
    value = hit.get("valor_total_estimado")
    return {
        "id": control,
        "modalidade": clean(hit.get("modalidade_licitacao_nome")) or "Modalidade não informada",
        "status": clean(hit.get("situacao_nome")) or "Status não informado",
        "origem": clean(hit.get("usuario_nome")) or "PNCP",
        "titulo": title[:800],
        "orgao": clean(hit.get("orgao_nome")) or "Órgão não informado",
        "cidade": clean(hit.get("municipio_nome")) or "Município não informado",
        "uf": clean(hit.get("uf")),
        "numero": clean(hit.get("numero")) or "Não informado",
        "sessao": "", "abertura": "",
        "publicacao": hit.get("data_publicacao_pncp"),
        "valor": float(value) if isinstance(value, (int, float)) else None,
        "pncp": control, "documentos": None, "url": url, "demo": False,
        "orgao_cnpj": cnpj, "ano": year, "sequencial": sequence, "indexed": True,
    }


def recent_index_hit(hit):
    """O índice não publica prazos: só vale como oportunidade o que é recente e segue divulgado."""
    if hit.get("cancelado"):
        return False
    status = fold_text(hit.get("situacao_nome"))
    if status and not any(word in status for word in ("divulgada", "publicada", "aberta", "andamento")):
        return False
    published = _parse_moment(hit.get("data_publicacao_pncp"))
    return bool(published) and published >= datetime.now() - timedelta(days=INDEX_RECENT_DAYS)


def index_records(products, states, refresh):
    """Candidatos pelo índice de busca do PNCP, com os dados oficiais já conhecidos."""
    known = {}
    for record in stored_snapshot()[0]:
        if record.get("id"):
            known.setdefault(record["id"], record)
    hits = {}
    stamps = []
    pages = INDEX_PAGES_PER_STATE if len(states) > 1 else INDEX_PAGES
    for product in products[:8]:
        term = index_term(product)
        for uf in (states or [None]):
            for page in range(1, pages + 1):
                stamp = None
                try:
                    payload, stamp = cached_index(index_query_url(term, page, uf), refresh)
                except (urllib.error.URLError, TimeoutError, ValueError, OSError):
                    payload = {}
                if stamp:
                    stamps.append(stamp)
                entries = payload.get("items") or []
                for hit in entries:
                    control = clean(hit.get("numero_controle_pncp"))
                    if control:
                        hits.setdefault(control, (hit, product))
                if len(entries) < INDEX_PAGE_SIZE:
                    break
    if not hits:
        if not stamps:
            raise urllib.error.URLError("Índice de busca do PNCP indisponível")
        return [], stamps
    records = []
    for control, (hit, product) in hits.items():
        record = known.get(control)
        if record is not None:
            record = dict(record)
            if states and record.get("uf") and record["uf"] not in states:
                continue
        else:
            if not recent_index_hit(hit):
                continue
            record = index_record(hit)
            if not record:
                continue
        record["match"] = True
        record["matched_product"] = product
        records.append(record)
    return records, stamps


def pncp_link(record):
    org = record.get("orgaoEntidade") or {}
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
        "abertura": record.get("dataAberturaProposta"),
        "publicacao": record.get("dataPublicacaoPncp"),
        "valor": record.get("valorTotalEstimado"), "pncp": control or "Não informado",
        "documentos": None, "url": pncp_link(record), "demo": False,
        "orgao_cnpj": org.get("cnpj"), "ano": record.get("anoCompra"),
        "sequencial": record.get("sequencialCompra")
    }


def _parse_moment(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        # O PNCP manda frações de segundo com nove dígitos, que o fromisoformat
        # do Python 3.10 recusa.
        text = re.sub(r"(\.\d{6})\d+", r"\1", str(value or ""))
        try:
            return datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None


def _is_expired(value, current_time):
    closing = _parse_moment(value)
    if not closing:
        return False
    return closing.date() < current_time.date() if closing.tzinfo is None else closing < current_time.astimezone(closing.tzinfo)


def _is_after(value, current_time):
    moment = _parse_moment(value)
    if not moment:
        return False
    return moment > current_time if moment.tzinfo is None else moment > current_time.astimezone(moment.tzinfo)


def proposta_page(uf, page, refresh):
    """Propostas abertas que encerram até OPEN_WINDOW_DAYS à frente.

    dataFinal é a data limite de encerramento no PNCP; com a data de hoje a
    consulta devolvia apenas 221 editais no Brasil inteiro (8 em SC), o que
    esvaziava busca, produtos e filtros por estado.
    """
    if PROPOSTA_DOWN_UNTIL > time.time():
        # Falhou há pouco: nem tenta de novo agora, quem chama usa a rota de
        # publicações recentes.
        raise urllib.error.URLError("Rota de propostas abertas em falha recente")
    final = (date.today() + timedelta(days=OPEN_WINDOW_DAYS)).strftime("%Y%m%d")
    query = {"dataFinal": final, "pagina": page, "tamanhoPagina": PAGE_SIZE}
    if uf:
        query["uf"] = uf
    return cached_json(PNCP_BASE + "/v1/contratacoes/proposta?" + urllib.parse.urlencode(query), refresh)


def collect_proposta_pages(states, first_page, page_count, refresh):
    """Consulta páginas do PNCP em paralelo, preservando ordem e totais por UF."""
    tasks = [(uf, number) for uf in (states or [None]) for number in range(first_page, first_page + page_count)]

    def run(task):
        global PROPOSTA_DOWN_UNTIL
        uf, number = task
        try:
            payload, stamp = proposta_page(uf, number, refresh)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            PROPOSTA_DOWN_UNTIL = time.time() + 60
            return task, [], 0, 1, None, False
        return (task, payload.get("data") or [], int(payload.get("totalRegistros") or 0),
                int(payload.get("totalPaginas") or 1), stamp, True)

    with ThreadPoolExecutor(max_workers=max(1, min(6, len(tasks)))) as pool:
        results = list(pool.map(run, tasks))
    results.sort(key=lambda item: (item[0][0] or "", item[0][1]))
    return results

def publicacao_page(code, page, back=0):
    """Uma página das contratações publicadas no dia `back` (0 = hoje)."""
    day = (date.today() - timedelta(days=back)).strftime("%Y%m%d")
    query = {"dataInicial": day, "dataFinal": day, "codigoModalidadeContratacao": code,
             "pagina": page, "tamanhoPagina": PAGE_SIZE}
    payload, stamp = cached_json(PNCP_BASE + "/v1/contratacoes/publicacao?"
                                 + urllib.parse.urlencode(query))
    return [normalize(record) for record in payload.get("data") or []], stamp


def remember_fallback(records):
    """Acumula os editais recentes já baixados; o coletor só acrescenta novidades."""
    fresh = []
    with FALLBACK_LOCK:
        for record in records:
            if record["id"] not in FALLBACK_STORE:
                FALLBACK_STORE[record["id"]] = record
                fresh.append(record)
        if len(FALLBACK_STORE) > FALLBACK_TARGET:
            # Mantém as publicações mais novas: as antigas já encerraram.
            ordered = sorted(FALLBACK_STORE.values(),
                             key=lambda r: r.get("publicacao") or "", reverse=True)
            FALLBACK_STORE.clear()
            FALLBACK_STORE.update({r["id"]: r for r in ordered[:FALLBACK_TARGET]})
    if fresh:
        persist_opportunities(fresh)
    return len(fresh)


def collect_fallback_pages(seconds=80.0, max_requests=18):
    """Aprofunda a reserva dentro do orçamento do ciclo.

    Cada página traz 50 contratações e o PNCP corta quem pede a cada segundo:
    respeitar FALLBACK_PACE é o que permite acumular milhares em segundo plano
    em vez de tomar 429 e ficar com as ~250 da primeira passada.
    """
    global FALLBACK_CURSOR, FALLBACK_STAMP
    started = time.time()
    index = FALLBACK_CURSOR
    requests_made = 0
    failures = 0
    while index < len(FALLBACK_QUEUE):
        if requests_made >= max_requests or time.time() - started > seconds:
            break
        if RATE_LIMIT_UNTIL > time.time():
            # O PNCP pediu pausa: o ciclo termina e o coletor espera.
            break
        back, code, page = FALLBACK_QUEUE[index]
        attempt_started = time.time()
        try:
            records, stamp = publicacao_page(code, page, back)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            if RATE_LIMIT_UNTIL > time.time():
                # 429 do PNCP: pausa e tenta a MESMA página, senão a coleta
                # pula justamente as oportunidades que ainda faltavam.
                wait = max(8.0, RATE_LIMIT_UNTIL - time.time())
                if time.time() - started + wait > seconds:
                    break
                time.sleep(wait)
                continue
            failures += 1
            index += 1
            if failures >= 3:
                break
            continue
        requests_made += 1
        failures = 0
        remember_fallback(records)
        if stamp:
            FALLBACK_STAMP = stamp
        index += 1
        wait = FALLBACK_PACE - (time.time() - attempt_started)
        if wait > 0:
            time.sleep(wait)
    FALLBACK_CURSOR = index
    return requests_made


def seed_fallback_from_db():
    """Recomeça de onde parou: a reserva coletada antes fica gravada no SQLite."""
    global FALLBACK_SEEDED
    if FALLBACK_SEEDED:
        return
    FALLBACK_SEEDED = True
    try:
        stored, _latest = stored_snapshot()
    except (sqlite3.Error, OSError):
        return
    with FALLBACK_LOCK:
        for record in stored:
            if record.get("id"):
                FALLBACK_STORE.setdefault(record["id"], record)


def fallback_records(states, _refresh):
    """Reserva: contratações recentes já coletadas, ampliadas em segundo plano."""
    global FALLBACK_LAST_NEEDED
    FALLBACK_LAST_NEEDED = time.time()
    seed_fallback_from_db()
    with FALLBACK_LOCK:
        ready = len(FALLBACK_STORE)
    if ready < FALLBACK_MIN_READY:
        # Clone novo, banco vazio: semeia agora para a tela não abrir quase vazia.
        collect_fallback_pages(seconds=14.0, max_requests=4)
    with FALLBACK_LOCK:
        records = list(FALLBACK_STORE.values())
    if not records:
        raise urllib.error.URLError("PNCP não respondeu à consulta de publicações recentes")
    return records, [FALLBACK_STAMP or time.time()]


def fallback_collector():
    """Mantém milhares de contratações recentes enquanto a rota principal está fora."""
    global FALLBACK_CURSOR, FALLBACK_PASS_DONE
    time.sleep(15)
    while True:
        with FALLBACK_LOCK:
            size = len(FALLBACK_STORE)
        in_use = time.time() - FALLBACK_LAST_NEEDED < 1800
        if not in_use or size >= FALLBACK_TARGET:
            time.sleep(30)
            continue
        if FALLBACK_CURSOR >= len(FALLBACK_QUEUE):
            # Passou por todas as páginas: recomeça depois de meia hora para
            # pegar o que foi publicado nesse meio-tempo.
            if time.time() - FALLBACK_PASS_DONE < 1800:
                time.sleep(30)
                continue
            FALLBACK_CURSOR = 0
        collect_fallback_pages(seconds=90.0, max_requests=18)
        if FALLBACK_CURSOR >= len(FALLBACK_QUEUE):
            FALLBACK_PASS_DONE = time.time()
        if RATE_LIMIT_UNTIL > time.time():
            # O limite é do IP inteiro: o coletor cede a vez para a página,
            # os itens e o download do edital enquanto o PNCP pede pausa.
            time.sleep(max(20.0, RATE_LIMIT_UNTIL - time.time()))
        time.sleep(5)


def future_records(states, refresh, days=FUTURE_WINDOW_DAYS):
    """Contratações publicadas nos últimos dias, por modalidade (licitações futuras).

    A reserva da tela de propostas abertas é outra: usa fallback_records, que
    acumula os editais dia a dia em segundo plano.
    """
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")

    def fetch(code):
        query = {"dataInicial": start, "dataFinal": end, "codigoModalidadeContratacao": code,
                 "pagina": 1, "tamanhoPagina": PAGE_SIZE}
        if len(states) == 1:
            query["uf"] = states[0]
        url = PNCP_BASE + "/v1/contratacoes/publicacao?" + urllib.parse.urlencode(query)
        try:
            payload, stamp = cached_json(url, refresh)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return [], []
        return [normalize(x) for x in payload.get("data") or []], [stamp]

    with ThreadPoolExecutor(max_workers=len(FUTURE_MODALITIES)) as pool:
        batches = list(pool.map(fetch, [code for code, _name in FUTURE_MODALITIES]))
    records = [record for batch, _stamps in batches for record in batch]
    stamps = [stamp for _batch, batch_stamps in batches for stamp in batch_stamps]
    if not stamps:
        # Nenhuma modalidade respondeu: quem chama precisa saber da falha para
        # mostrar os editais já salvos em vez de uma lista vazia.
        raise urllib.error.URLError("PNCP não respondeu à consulta de licitações futuras")
    return records, stamps


def fetch_opportunities(params):
    FETCH_STATE.stale = False
    FETCH_STATE.fallback = False
    period = params.get("period") if params.get("period") in PERIODS else "open"
    page = max(1, min(50, int(params.get("page") or 1)))
    states = sorted({clean(s).upper() for s in params.get("states") or [] if clean(s).upper() in VALID_UFS})
    refresh = bool(params.get("refresh"))

    query_text = fold_text(clean(params.get("q")))
    query_terms = [singular_word(w) for w in re.findall(r"[\w]+", query_text)
                   if len(w) > 1 and w not in SEARCH_STOPWORDS]
    city = fold_text(clean(params.get("city")))
    state_filter = {clean(s).upper() for s in params.get("states") or [] if clean(s).upper() in VALID_UFS}
    products = [clean(p).casefold() for p in params.get("products", []) if clean(p)]
    minimum = None
    try:
        if params.get("min_value") not in (None, ""):
            minimum = float(params.get("min_value"))
    except (TypeError, ValueError):
        minimum = None
    # O PNCP não aceita busca por texto: para esses filtros varremos mais páginas
    # e paginamos o resultado já filtrado aqui.
    local_filters = bool(query_terms or city or products or minimum is not None)

    stamps = []
    available = 0
    pages = 1
    indexed = []
    if products and period == "open":
        # A varredura por página só enxerga o começo de cada UF e o objeto do
        # edital, que costuma ser genérico. O índice do PNCP pesquisa objeto e
        # itens de todo o acervo, então é ele que evita produto de fora.
        try:
            indexed, stamps = index_records(products, states, refresh)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            indexed = []
    if period == "future":
        raw, stamps = future_records(states, refresh)
    elif indexed:
        raw = indexed
        available = len(indexed)
    else:
        if local_filters:
            # Varrer o Brasil inteiro custa uma requisição por página: com muitos
            # estados, duas páginas por UF já cobrem o volume recente.
            scan_states = states or [code for code, _name in STATES_FOR_SEARCH]
            first_page, page_count = 1, (FILTER_SCAN_PAGES if len(scan_states) <= 8 else 2)
        else:
            first_page, page_count = page, 1
        totals = {}
        raw = []
        answered = 0
        try:
            for (_uf, _number), data, total_records, total_pages, stamp, ok in collect_proposta_pages(
                    states, first_page, page_count, refresh):
                if ok:
                    answered += 1
                if stamp:
                    stamps.append(stamp)
                totals.setdefault(_uf, total_records)
                pages = max(pages, total_pages)
                raw.extend(normalize(record) for record in data)
            if not answered:
                # Todas as páginas falharam (429, 403, rede bloqueada ou PNCP
                # fora do ar). Antes a falha era engolida página a página e o
                # site mostrava "nenhuma oportunidade" mesmo havendo milhares.
                raise urllib.error.URLError("PNCP não respondeu à consulta de propostas")
        except (urllib.error.URLError, TimeoutError, OSError):
            # Reserva oficial: contratações publicadas nos últimos dias, que o
            # PNCP serve por outra operação e costuma manter no ar.
            raw, stamps = fallback_records(states, refresh)
            available = len(raw)
            FETCH_STATE.fallback = True
        else:
            available = sum(totals.values())

    seen = set()
    unique = []
    for record in raw:
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        unique.append(record)
    if unique and not getattr(FETCH_STATE, "fallback", False):
        # A reserva já grava cada edital quando ele chega, no coletor.
        persist_opportunities(unique)

    current_time = datetime.now()
    if period == "future":
        records = [r for r in unique if _is_after(r["abertura"], current_time) and (not r["sessao"] or not _is_expired(r["sessao"], current_time))]
    else:
        records = [r for r in unique if not r["sessao"] or not _is_expired(r["sessao"], current_time)]

    if query_terms:
        # Todos os termos precisam aparecer: com um termo só, a lista enchia de
        # editais que compartilhavam apenas uma palavra genérica com a busca.
        records = [r for r in records if all(term in word_set(record_text(r)) for term in query_terms)]
    if state_filter:
        records = [r for r in records if r["uf"] in state_filter]
    if city:
        records = [r for r in records if city in fold_text(r["cidade"])]
    if minimum is not None:
        records = [r for r in records if isinstance(r["valor"], (int, float)) and r["valor"] >= minimum]
    if products and not indexed:
        # Reserva para quando o índice não responde: o edital fica quando o
        # objeto cita todas as palavras de pelo menos um dos itens escolhidos.
        selected = []
        for record in records:
            text = record_text(record)
            matched = next((product for product in products if product_matches(text, product)), None)
            if matched:
                record["match"] = True
                record["matched_product"] = matched
                selected.append(record)
        records = selected
    for record in records:
        record.setdefault("match", False)
    labels = {clean(item).casefold(): clean(item) for item in params.get("products", []) if clean(item)}
    for record in records:
        if record.get("matched_product"):
            record["matched_product"] = labels.get(record["matched_product"].casefold(), record["matched_product"])

    sort = params.get("sort", "date")
    if sort == "value":
        records.sort(key=lambda r: (r["valor"] is not None, r["valor"] or 0), reverse=True)
    elif period == "future":
        records.sort(key=lambda r: r["abertura"] or "")
    else:
        records.sort(key=lambda r: r["sessao"] or "", reverse=True)

    filtered_total = len(records)
    if local_filters or getattr(FETCH_STATE, "fallback", False):
        # Na reserva a lista vem inteira daqui: paginar é o que permite mostrar
        # milhares de contratações sem devolver tudo numa resposta só.
        pages = max(1, -(-filtered_total // PAGE_SIZE))
        start = (page - 1) * PAGE_SIZE
        page_records = records[start:start + PAGE_SIZE]
        total = filtered_total
    else:
        page_records = records
        total = available or len(records)

    data_stamp = max(stamps) if stamps else time.time()
    fallback = bool(getattr(FETCH_STATE, "fallback", False))
    payload = {"opportunities": page_records, "total": total, "page": page, "pages": pages,
               "period": period, "source": "PNCP (publicações recentes)" if fallback else "PNCP",
               "stale": bool(getattr(FETCH_STATE, "stale", False)), "fallback": fallback,
               "updated_at": datetime.fromtimestamp(data_stamp).isoformat(timespec="seconds")}
    if fallback:
        payload["warning"] = ("A consulta de propostas abertas do PNCP não respondeu agora. "
                              f"Exibindo as {filtered_total} contratações publicadas nos últimos "
                              f"{FALLBACK_WINDOW_DAYS} dias que ainda recebem propostas, "
                              "com as datas oficiais de cada uma. "
                              "A lista cresce sozinha em segundo plano enquanto o PNCP não voltar.")
    return payload

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


def stored_snapshot():
    """Últimos editais reais já consultados, guardados no SQLite."""
    with connect() as db:
        rows = db.execute("SELECT record_json, fetched_at FROM opportunities WHERE source='PNCP' "
                          "ORDER BY fetched_at DESC LIMIT 4000").fetchall()
    records = []
    latest = ""
    for row in rows:
        latest = max(latest, row["fetched_at"] or "")
        try:
            records.append(json.loads(row["record_json"]))
        except (ValueError, TypeError):
            continue
    return records, latest


def stored_result(params):
    """Responde com dados reais já salvos quando o PNCP não responde."""
    records, latest = stored_snapshot()
    current_time = datetime.now()
    period = params.get("period") or "open"
    if period == "future":
        records = [r for r in records if _is_after(r.get("abertura"), current_time)]
    records = [r for r in records if not r.get("sessao") or not _is_expired(r["sessao"], current_time)]
    states = set(params.get("states") or [])
    if states:
        records = [r for r in records if r.get("uf") in states]
    city = fold_text(params.get("city"))
    if city:
        records = [r for r in records if city in fold_text(r.get("cidade"))]
    terms = [singular_word(w) for w in re.findall(r"[\w]+", fold_text(params.get("q")))
             if len(w) > 1 and w not in SEARCH_STOPWORDS]
    if terms:
        records = [r for r in records if all(term in word_set(record_text(r)) for term in terms)]
    products = [clean(p) for p in params.get("products", []) if clean(p)]
    if products:
        kept = []
        for r in records:
            text = record_text(r)
            matched = next((p for p in products if product_matches(text, p)), None)
            if matched:
                r["match"] = True
                r["matched_product"] = matched
                kept.append(r)
        records = kept
    if params.get("sort") == "value":
        records.sort(key=lambda r: (r.get("valor") is not None, r.get("valor") or 0), reverse=True)
    else:
        records.sort(key=lambda r: r.get("sessao") or "", reverse=True)
    total = len(records)
    page = max(1, min(50, int(params.get("page") or 1)))
    start = (page - 1) * PAGE_SIZE
    return {"opportunities": records[start:start + PAGE_SIZE], "total": total, "page": page,
            "pages": max(1, -(-total // PAGE_SIZE)), "period": period, "source": "PNCP (cache)",
            "stale": True, "updated_at": latest or now()}


def region_states(region):
    return REGIONS_FOR_SEARCH.get(clean(region), [])


def demo_result(params):
    current_time = datetime.now()
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
    if params.get("period") == "future":
        records = [r for r in records if _is_after(r["abertura"], current_time)]
    return {"opportunities": records, "total": len(records), "page": 1, "pages": 1,
            "period": params.get("period") or "open", "source": "Demonstração", "demo": True, "updated_at": now()}


def normalize_item(entry):
    return {
        "descricao": entry.get("descricao") or entry.get("descricaoItem") or "Não informado",
        "natureza": entry.get("materialOuServicoNome") or "Não informado",
        "quantidade": entry.get("quantidade"),
        "unidade": entry.get("unidadeMedida") or entry.get("unidadeFornecimento"),
        "unitario": entry.get("valorUnitarioEstimado"),
        "total": entry.get("valorTotal") if entry.get("valorTotal") is not None else entry.get("valorTotalEstimado"),
    }


def stored_items(item_id):
    with connect() as db:
        rows = db.execute("SELECT item_json FROM tender_items WHERE opportunity_id=? ORDER BY item_index",
                          (item_id,)).fetchall()
    items = []
    for row in rows:
        try:
            items.append(json.loads(row["item_json"]))
        except (ValueError, TypeError):
            continue
    return items


def load_opportunity_items(item_id, with_documents=False):
    """Itens oficiais de uma contratação, com cache curto e reserva no SQLite."""
    parts = pncp_parts(item_id)
    if not parts:
        return [], [], False
    cnpj, year, seq = parts
    cached = ITEMS_CACHE.get(item_id)
    if cached and time.time() - cached[0] < ITEMS_CACHE_TTL:
        items = cached[1]
    else:
        url = f"{PNCP_DATA_BASE}/v1/orgaos/{urllib.parse.quote(cnpj)}/compras/{year}/{seq}/itens?pagina=1&tamanhoPagina=100"
        try:
            payload = fetch_json(url)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            stored = stored_items(item_id)
            return stored, [], not stored
        entries = payload if isinstance(payload, list) else payload.get("data", [])
        items = [normalize_item(entry) for entry in entries]
        ITEMS_CACHE[item_id] = (time.time(), items)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO opportunities(id,source,record_json,fetched_at) VALUES(?,?,?,?)",
                       (item_id, "PNCP", json.dumps({"id": item_id, "orgao_cnpj": cnpj, "ano": int(year),
                                                     "sequencial": int(seq)}), now()))
            for index, item in enumerate(items):
                db.execute("""INSERT INTO tender_items(opportunity_id,item_index,item_json) VALUES(?,?,?)
                    ON CONFLICT(opportunity_id,item_index) DO UPDATE SET item_json=excluded.item_json""",
                    (item_id, index, json.dumps(item, ensure_ascii=False)))
    if not with_documents:
        return items, [], False
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
    return items, documents, False


def opportunity_context(data):
    """Sanitiza o edital que o navegador envia para o chat focado."""
    if not isinstance(data, dict):
        return None
    limits = {"id": 120, "titulo": 600, "orgao": 300, "cidade": 120, "uf": 4, "numero": 80,
              "modalidade": 120, "status": 120, "sessao": 40, "abertura": 40, "pncp": 80, "url": 600}
    record = {key: clean(data.get(key))[:limit] for key, limit in limits.items()}
    value = data.get("valor")
    record["valor"] = float(value) if isinstance(value, (int, float)) else None
    record["demo"] = bool(data.get("demo"))
    if not record["titulo"] and not record["id"]:
        return None
    if not record["url"].startswith(("http://", "https://")):
        record["url"] = ""
    return record


def chat_history(data):
    raw = data.get("history")
    if not isinstance(raw, list):
        return []
    history = []
    for item in raw[-8:]:
        if not isinstance(item, dict):
            continue
        content = clean(item.get("content"))[:800]
        if content:
            history.append({"role": "assistant" if item.get("role") == "assistant" else "user",
                            "content": content})
    return history


def brl(value):
    if isinstance(value, (int, float)) and value:
        return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "não informado"


def format_moment(value):
    moment = _parse_moment(value)
    return moment.strftime("%d/%m/%Y às %H:%M") if moment else (value or "não informado")


FILTER_MARKERS = ("tem a ver", "tem haver", "a ver com", "filtro", "filtrei", "filtrad", "apareceu",
                  "nexo", "relacao", "relacionad", "nao entendi")


def asks_about_filter(question, products):
    """A pessoa quer saber o que o edital tem a ver com o que ela filtrou?"""
    folded = fold_text(question)
    terms = filter_terms(question, products)
    if not terms:
        return []
    named = [term for term in terms
             if any(word in folded for word in re.findall(r"[\w]+", fold_text(term)) if len(word) > 3)]
    if named or any(marker in folded for marker in FILTER_MARKERS):
        return terms
    return []


def profile_products(data):
    """Produtos do perfil que o navegador envia junto da pergunta."""
    products = data.get("products", [])
    if not isinstance(products, list) or len(products) > 100:
        return []
    return [clean(product)[:120] for product in products if clean(product)]


def filter_terms(question, products):
    """Termos do filtro que vale comparar com o edital (perfil + trechos entre aspas)."""
    candidates = [clean(product) for product in (products or []) if clean(product)]
    candidates += [clean(term) for term in re.findall(r'["“]([^"”]{2,60})["”]', question)]
    terms = []
    for candidate in candidates:
        folded = fold_text(candidate)
        if len(folded) > 2 and folded not in {fold_text(term) for term in terms}:
            terms.append(candidate)
    return terms[:4]


def snippet_around(text, term, window=8):
    """Trecho do texto oficial em volta do termo, sempre cortado em palavras inteiras."""
    tokens = re.findall(r"\S+", text)
    target = fold_text(term).split()[0] if fold_text(term).split() else ""
    for index, token in enumerate(tokens):
        if target and target in fold_text(token):
            start = max(0, index - window)
            end = min(len(tokens), index + window + 1)
            piece = " ".join(tokens[start:end])
            return ("…" if start else "") + piece + ("…" if end < len(tokens) else "")
    return ""


def item_amount(item):
    quantity, unit = item.get("quantidade"), clean(item.get("unidade"))
    if quantity in (None, ""):
        return ""
    if isinstance(quantity, float) and quantity.is_integer():
        quantity = int(quantity)
    return f" ({quantity} {unit})" if unit else f" ({quantity})"


def filter_explanation(record, items, question, products):
    """Explica em linguagem simples o que o edital tem a ver com o filtro da pessoa."""
    terms = filter_terms(question, products)
    if not terms:
        return []
    terms_text = " e ".join(f"«{term}»" for term in terms[:2])
    if not items:
        lines = [f"Não consegui carregar a lista de itens deste processo agora, então não dá para "
                 f"mostrar o trecho do edital que liga o processo a {terms_text}."]
        title = clean(record.get("titulo"))
        if title:
            lines.append(f"O objeto publicado é: «{title[:220]}».")
        return lines
    found, missing = [], []
    for term in terms:
        hits = [item for item in items if product_matches(clean(item.get("descricao")), term)]
        if hits:
            found.append((term, hits[0]))
        elif product_matches(record.get("titulo") or "", term):
            found.append((term, None))
        else:
            missing.append(term)
    lines = []
    for term, hit in found[:3]:
        if hit is not None:
            lines.append(f"No edital eles pedem «{clean(hit.get('descricao'))}»{item_amount(hit)}.")
        else:
            snippet = snippet_around(record.get("titulo") or "", term) or clean(record.get("titulo"))
            lines.append(f"O próprio objeto do edital cita {term}: «{snippet}».")
    if found:
        names = " e ".join(dict.fromkeys(term for term, _hit in found[:3]))
        lines.append(f"É por isso que este processo apareceu quando você filtrou por {names}.")
    for term in missing[:2]:
        lines.append(f"Já «{term}» não aparece nos itens publicados nem no objeto — a busca do "
                     f"PNCP costuma trazer editais por termos parecidos. O que este processo pede de fato "
                     f"está abaixo.")
    return lines


def describe_opportunity(record, items, question, products=None):
    """Resposta sobre um edital específico, em linguagem simples, quando não há chave de IA."""
    folded = fold_text(question)
    asked = word_set(question)
    title = record["titulo"] or "Objeto não informado"
    location = " / ".join(x for x in (record["cidade"], record["uf"]) if x) or "local não informado"

    def mentions(roots):
        """Compara radicais ("iten" cobre item/itens, "praz" cobre prazo/prazos)."""
        return any(word.startswith(root) for word in asked for root in roots) or \
            any(" " in root and root in folded for root in roots)

    lines = []
    relation = asks_about_filter(question, products)
    if relation:
        lines.extend(filter_explanation(record, items, question, relation))
    elif mentions(("praz", "data", "quand", "sessa", "encerr", "abertur", "deadline")):
        lines.append(f"As propostas ficam abertas até {format_moment(record['sessao'])} — vale se organizar antes disso.")
        if record["abertura"]:
            lines.append(f"A abertura está marcada para {format_moment(record['abertura'])}.")
    elif mentions(("valor", "prec", "cust", "orcament", "quant")):
        lines.append(f"O valor estimado publicado é {brl(record['valor'])}.")
        lines.append("Os valores por item, quando existem, aparecem em “Ver itens”.")
    elif mentions(("iten", "item", "produt", "escop", "objet", "fornec")):
        if items:
            lines.append(f"A fonte oficial publicou {len(items)} item(ns) neste processo; os principais estão logo abaixo.")
        else:
            lines.append("A lista de itens não veio da fonte oficial agora, então o objeto publicado é o que está abaixo.")
    elif mentions(("particip", "habilit", "document", "requisit", "cadastr")):
        lines.append("Para participar, o caminho é ler o edital e os anexos: é lá que estão os documentos de "
                     "habilitação, as especificações e a forma de enviar a proposta. Confira também o cadastro "
                     "exigido pela plataforma de compras indicada no aviso.")
    elif mentions(("resum", "sobre", "explic", "vale a pena", "o que e")):
        lines.append(f"Em poucas palavras: {title}")
    else:
        lines.append(f"Este processo é sobre: {title}")
    lines.append("")
    summary = title if len(title) <= 260 else title[:257].rstrip() + "…"
    lines.append("Dados publicados no PNCP:")
    lines.append(f"• Objeto: {summary}")
    lines.append(f"• Órgão: {record['orgao'] or 'não informado'}")
    lines.append(f"• Local: {location}")
    lines.append(f"• Modalidade: {record['modalidade'] or 'não informada'} · Situação: {record['status'] or 'não informada'}")
    lines.append(f"• Edital: {record['numero'] or 'não informado'} · ID PNCP: {record['pncp'] or record['id'] or 'não informado'}")
    lines.append(f"• Abertura das propostas: {format_moment(record['abertura'])}")
    lines.append(f"• Encerramento das propostas: {format_moment(record['sessao'])}")
    lines.append(f"• Valor estimado: {brl(record['valor'])}")
    if items:
        lines.append("")
        lines.append(f"Itens publicados ({len(items)}):")
        for item in items[:8]:
            quantity = item.get("quantidade")
            unit = item.get("unidade") or ""
            suffix = f" — {quantity} {unit}".rstrip() if quantity not in (None, "") else ""
            lines.append(f"• {item.get('descricao') or 'Item sem descrição'}{suffix}")
        if len(items) > 8:
            lines.append(f"• … e mais {len(items) - 8} item(ns), veja em “Ver itens”.")
    if record["url"]:
        lines.append("")
        lines.append(f"Edital oficial: {record['url']}")
    lines.append("")
    lines.append("Tudo isso vem dos dados públicos deste processo; o edital oficial continua sendo a palavra final.")
    return "\n".join(lines)


def ask_ai(question, opportunities, products, items=None, history=None, focus=False):
    context = [{
        "title": r["titulo"], "agency": r["orgao"], "city": r["cidade"], "state": r["uf"],
        "estimated_value": r["valor"], "proposal_deadline": r["sessao"], "opening": r.get("abertura"),
        "modality": r.get("modalidade"), "status": r.get("status"), "process_number": r.get("numero"),
        "pncp_id": r["pncp"], "official_url": r["url"], "matched_company_products": products
    } for r in opportunities]
    if items is not None and context:
        context[0]["published_items"] = items[:60]
    instruction = (
        "Você é a assistente Licitara, especializada exclusivamente em licitações públicas brasileiras. "
        "Responda em português, de forma clara para pequenas empresas. Use somente os registros PNCP "
        "incluídos no contexto. Nunca invente editais, preços, prazos, itens ou requisitos. Se um dado "
        "não estiver no contexto, diga que não foi informado e recomende conferir o edital oficial. "
        "Não afirme que os itens foram extraídos se não houver essa informação. Inclua o link oficial "
        "quando disponível. Esta resposta não substitui a leitura do edital. Fale como uma pessoa "
        "explicando para outra: frases curtas, tom direto e sem jargão. Quando alguém perguntar por que um "
        "edital apareceu no filtro, explique o que o edital realmente pede e cite o texto dos itens "
        "publicados (por exemplo: 'no edital eles pedem manutenção elétrica no centro de convivência'); "
        "se o termo do filtro não aparecer nos itens nem no objeto, diga isso com franqueza em vez de "
        "inventar uma ligação. Depois da explicação, liste os dados oficiais do processo."
    )
    if focus:
        instruction += (" Este chat é dedicado a uma única contratação: responda apenas sobre ela, use os itens "
                        "publicados quando existirem e, se a pergunta tratar de outro processo, diga que aqui o "
                        "assunto é este edital e recomende consultar o processo mencionado na central. Se a "
                        "pessoa quiser entender por que este edital apareceu no filtro dela, ligue cada produto "
                        "do perfil (matched_company_products) ao trecho do item ou do objeto que o justifica.")
    messages = [{"role": "system", "content": instruction}]
    for turn in (history or [])[-8:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": f"Pergunta: {question}\n\nRegistros oficiais PNCP recuperados:\n{json.dumps(context, ensure_ascii=False)}"})
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": 0.2,
        "messages": messages
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


def public_document_url(url):
    """Aceita apenas endereços http(s) públicos, para não virar proxy interno."""
    parsed = urllib.parse.urlparse(clean(url))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    if host == "localhost" or host.endswith((".local", ".internal")):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved)


def edital_document(item_id):
    """Arquivo do edital publicado pelo órgão, com preferência por edital e aviso."""
    _items, documents, _unavailable = load_opportunity_items(item_id, with_documents=True)
    usable = [document for document in documents
              if document.get("url") and public_document_url(document["url"])]
    if not usable:
        return None

    def rank(document):
        text = fold_text(f"{document.get('type') or ''} {document.get('title') or ''}")
        return (0 if "edital" in text else 1 if "aviso" in text else 2,
                len(document.get("title") or ""))

    return sorted(usable, key=rank)[0]


def document_filename(document, content_type):
    title = clean(document.get("title")) or "edital"
    stem = re.sub(r"[^a-z0-9._-]+", "-", fold_text(title)).strip("-._")[:90] or "edital"
    extension = os.path.splitext(urllib.parse.urlparse(document.get("url") or "").path)[1].casefold()
    if extension not in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rtf", ".odt", ".ods"):
        extension = ".zip" if "zip" in clean(content_type).casefold() else ".pdf"
    if stem.casefold().endswith(extension):
        stem = stem[: -len(extension)].rstrip("-._") or "edital"
    return stem + extension


class Handler(BaseHTTPRequestHandler):
    server_version = "Licitara/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("APP_DEBUG") == "1":
            super().log_message(fmt, *args)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 100_000:
            raise ValueError("Corpo da solicitação muito grande.")
        raw = self.rfile.read(size)
        return json.loads(raw.decode("utf-8")) if raw else {}

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
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def query_params(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        states = query.get("state", [])
        for region in query.get("region", []):
            states.extend(region_states(region))
        return {
            "q": query.get("q", [""])[0],
            "city": query.get("city", [""])[0],
            "states": sorted({s.upper() for s in states if s.strip().upper() in VALID_UFS}),
            "sort": query.get("sort", ["date"])[0],
            "page": query.get("page", ["1"])[0],
            "period": query.get("period", ["open"])[0],
            "refresh": query.get("refresh", [""])[0] == "1",
            "min_value": query.get("min_value", [None])[0],
            "products": [p.strip()[:120] for p in query.get("product", []) if p.strip()][:100],
        }

    def api_get(self, path):
        if path == "/api/catalog":
            return self.send_json(200, {"categories": CATALOG})
        if path == "/api/opportunities":
            params = self.query_params()
            try:
                return self.send_json(200, fetch_opportunities(params))
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError):
                stored = stored_result(params)
                if stored["total"]:
                    stored["warning"] = ("O PNCP está lento, limitando as consultas ou fora do ar agora. "
                                         "Exibindo os editais reais já consultados e salvos neste computador; "
                                         "use Atualizar em alguns instantes.")
                    return self.send_json(200, stored)
                result = demo_result(params)
                result["warning"] = ("Não foi possível consultar o PNCP agora (limite de requisições, rede ou fonte fora do ar). "
                                     "Os cards abaixo são exemplos fictícios de demonstração; use Atualizar em alguns instantes "
                                     "para tentar os dados oficiais de novo.")
                return self.send_json(200, result)
        if path.startswith("/api/opportunities/") and path.endswith("/download"):
            item_id = urllib.parse.unquote(path[len("/api/opportunities/"):-len("/download")].strip("/"))
            return self.download(item_id)
        if path.startswith("/api/opportunities/") and path.endswith("/items"):
            item_id = urllib.parse.unquote(path[len("/api/opportunities/"):-len("/items")].strip("/"))
            return self.get_items(item_id)
        return self.send_json(404, {"error": "Rota não encontrada."})

    def get_items(self, item_id):
        if item_id.startswith("demo-"):
            demo = next((x for x in DEMO_OPPORTUNITIES if x["id"] == item_id), None)
            return self.send_json(200, {"items": demo["items"] if demo else [], "documents": [],
                                        "source": "Demonstração", "unavailable": False, "opportunity": demo})
        if not pncp_parts(item_id):
            return self.send_json(400, {"error": "Identificador PNCP inválido."})
        items, documents, unavailable = load_opportunity_items(item_id, with_documents=True)
        if unavailable:
            return self.send_json(200, {"items": [], "source": "PNCP", "unavailable": True,
                                        "message": "A fonte oficial não disponibilizou os itens desta contratação."})
        return self.send_json(200, {"items": items, "documents": documents, "source": "PNCP",
                                    "unavailable": False})

    def download(self, item_id):
        """Baixa o arquivo do edital e entrega como anexo, sem sair do site."""
        if not pncp_parts(item_id):
            return self.send_json(404, {"error": "Só é possível baixar editais publicados no PNCP."})
        try:
            document = edital_document(item_id)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, AttributeError):
            document = None
        if not document:
            return self.send_json(404, {"error": "O órgão não publicou um arquivo de edital para este processo. Use “Site oficial” para ver os documentos na página do PNCP."})
        try:
            request = urllib.request.Request(document["url"], headers={
                "Accept": "*/*", "User-Agent": INDEX_HEADERS["User-Agent"]})
            upstream = urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return self.send_json(502, {"error": "O servidor do órgão não respondeu ao pedido do arquivo. Tente novamente ou abra o site oficial."})
        with upstream:
            content_type = upstream.headers.get("Content-Type") or "application/octet-stream"
            filename = document_filename(document, content_type)
            length = upstream.headers.get("Content-Length") or ""
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            if length.isdigit() and int(length) <= DOWNLOAD_LIMIT:
                self.send_header("Content-Length", length)
            self.end_headers()
            sent = 0
            while True:
                chunk = upstream.read(65536)
                if not chunk:
                    break
                sent += len(chunk)
                if sent > DOWNLOAD_LIMIT:
                    break
                self.wfile.write(chunk)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self.body()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return self.send_json(400, {"error": "Solicitação inválida."})
        if path == "/api/chat":
            return self.chat(data)
        return self.send_json(404, {"error": "Rota não encontrada."})

    def chat(self, data):
        question = clean(data.get("message"))
        if not question or len(question) > 1200:
            return self.send_json(400, {"error": "Escreva uma pergunta de até 1.200 caracteres."})
        focus = opportunity_context(data.get("opportunity"))
        if data.get("opportunity") is not None and not focus:
            return self.send_json(400, {"error": "Oportunidade inválida para o chat."})
        if focus:
            return self.opportunity_chat(question, focus, data)
        product_names = profile_products(data)
        records = []
        try:
            folded_question = fold_text(question)
            stop_words = {
                "encontre", "existem", "quais", "qual", "para", "mais", "acima", "abaixo", "abertas",
                "abertos", "licitacao", "licitacoes", "edital", "editais", "empresa", "minha", "sobre",
                "estado", "municipio", "prefeituras", "valor", "estimado", "estimadas", "recentes",
                "fornecimento", "procurando", "oportunidades", "aberta", "aberto", "produto", "produtos",
                "servico", "servicos", "existe", "estao", "tem", "de", "do", "da",
                "em", "no", "na", "um", "uma", "com", "que", "meus", "minhas", "publicas", "futuras", "futura"
            }
            words = [w for w in re.findall(r"[\w]+", folded_question) if len(w) > 3 and w not in stop_words]
            period = "future" if "futur" in folded_question else "open"
            result = fetch_opportunities({"q": "", "states": [], "products": [], "sort": "date", "period": period})
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
            records = [record for _, record in ranked][:5]

            if os.environ.get("OPENAI_API_KEY") and records:
                return self.send_json(200, {"answer": ask_ai(question, records, product_names),
                                            "source": "PNCP", "grounded": True, "opportunities": records})
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
                elif period == "future":
                    answer = ("Não encontrei licitações com abertura de propostas futura entre os registros publicados nos últimos "
                              f"{FUTURE_WINDOW_DAYS} dias no PNCP. Tente ajustar o período ou os filtros da central.")
                else:
                    answer = ("Não encontrei uma oportunidade correspondente entre os registros carregados do PNCP. Tente palavras-chave "
                              "mais curtas ou ajuste os filtros da central. Não vou inventar editais, valores ou datas.")
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError):
            answer = "O PNCP não respondeu neste momento. Posso orientar sobre a consulta: use termos objetivos, confira a data de encerramento das propostas e confirme sempre condições e requisitos no edital oficial."
        return self.send_json(200, {"answer": answer, "source": "PNCP", "grounded": True, "opportunities": records})

    def opportunity_chat(self, question, record, data):
        """Responde sobre um único edital, com os itens oficiais quando existirem."""
        items = []
        if not record["demo"] and pncp_parts(record["id"]):
            try:
                items, _documents, _unavailable = load_opportunity_items(record["id"])
            except (urllib.error.URLError, TimeoutError, ValueError, OSError, AttributeError):
                items = []
        products = profile_products(data)
        answer = describe_opportunity(record, items, question, products)
        if os.environ.get("OPENAI_API_KEY"):
            try:
                answer = ask_ai(question, [record], products, items=items,
                                history=chat_history(data), focus=True)
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, OSError):
                pass
        return self.send_json(200, {"answer": answer, "source": "PNCP", "grounded": True,
                                    "focus": record["id"], "opportunities": [record]})


def warm_pncp_cache():
    """Mantém o cache quente para o site responder na hora, inclusive em tempo real."""
    # Espera a primeira página carregar: aquecer junto com o primeiro acesso só
    # dividia o limite de requisições do PNCP e deixava a tela lenta.
    time.sleep(10)
    while True:
        for period in ("open", "future"):
            try:
                fetch_opportunities({"q": "", "city": "", "states": [], "sort": "date", "page": 1,
                                     "products": [], "period": period, "refresh": True})
            except Exception:
                pass
        time.sleep(WARM_INTERVAL)

if __name__ == "__main__":
    init_db()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Licitara disponível em http://{host}:{port}")
    threading.Thread(target=warm_pncp_cache, daemon=True, name="pncp-cache-refresh").start()
    threading.Thread(target=fallback_collector, daemon=True, name="pncp-fallback-collector").start()
    ThreadingHTTPServer((host, port), Handler).serve_forever()
