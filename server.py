#!/usr/bin/env python3
import datetime as dt
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
CACHE_PATH = DATA_DIR / "latest_papers.json"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin123")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
COOKIE_NAME = "arxiv_everyday_session"
SESSION_TTL_SECONDS = 12 * 60 * 60

ARXIV_API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "ArxivEveryday/1.0 (+http://127.0.0.1)"
MAX_MATCHED_PAPERS = int(os.getenv("ARXIV_MAX_MATCHED", "18"))
ARXIV_PAGE_SIZE = int(os.getenv("ARXIV_PAGE_SIZE", "100"))
ARXIV_FETCH_CAP = int(os.getenv("ARXIV_FETCH_CAP", "500"))

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

TOPIC_KEYWORDS = {
    "大语言模型": [
        "large language model",
        "LLM",
        "foundation model",
        "transformer",
        "pretrained model",
        "generative model",
        "diffusion",
        "GPT",
        "language model",
    ],
    "智能体": [
        "agent",
        "multi-agent",
        "autonomous agent",
        "tool use",
        "tool calling",
        "planning",
        "task decomposition",
        "agentic",
    ],
    "推理": [
        "reasoning",
        "chain of thought",
        "CoT",
        "self-consistency",
        "test-time compute",
        "inference scaling",
        "deliberate reasoning",
    ],
    "世界模型": [
        "world model",
        "world representation",
        "environment modeling",
        "simulation",
        "predictive model",
    ],
    "具身智能": [
        "embodied AI",
        "embodied",
        "robot learning",
        "robotics",
        "control policy",
        "sensorimotor",
        "manipulation",
    ],
    "多模态": [
        "vision-language",
        "multimodal reasoning",
        "video model",
        "audio-text",
        "cross-modal",
        "image-text",
        "multimodal",
    ],
    "代码生成": [
        "code generation",
        "program synthesis",
        "code LLM",
        "software engineering",
        "AI coding",
    ],
    "训练优化": [
        "fine-tuning",
        "alignment",
        "RLHF",
        "DPO",
        "distillation",
        "quantization",
        "LoRA",
        "instruction tuning",
    ],
    "推理优化": [
        "inference optimization",
        "serving",
        "latency",
        "throughput",
        "efficient inference",
        "speculative decoding",
        "KV cache",
    ],
    "AI安全": [
        "AI safety",
        "trustworthy AI",
        "robustness",
        "interpretability",
        "explainability",
        "hallucination",
        "adversarial",
        "jailbreak",
    ],
    "扩展与泛化": [
        "scaling",
        "generalization",
        "emergent",
        "state-of-the-art",
        "scaling law",
        "in-context learning",
    ],
}

ARXIV_CATEGORIES = [
    "cs.AI",
    "cs.CL",
    "cs.CV",
    "cs.CR",
    "cs.HC",
    "cs.LG",
    "cs.MA",
    "cs.NE",
    "cs.RO",
    "cs.SE",
    "eess.AS",
    "stat.ML",
]
ARXIV_CATEGORY_QUERY = "(" + " OR ".join(f"cat:{category}" for category in ARXIV_CATEGORIES) + ")"

KEYWORD_TOKEN_RE = re.compile(r"^[a-z0-9.+-]{2,6}$")
WHITESPACE_RE = re.compile(r"\s+")
SESSIONS = {}
SESSION_LOCK = threading.Lock()


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", (value or "").strip())


def parse_arxiv_timestamp(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def db_connection() -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_data_dir()
    with db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                paper_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS translation_cache (
                cache_key TEXT PRIMARY KEY,
                source_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def load_json_file(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_file(path: Path, payload) -> None:
    ensure_data_dir()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_cached_live_papers():
    return load_json_file(CACHE_PATH) or []


def save_cached_live_papers(papers) -> None:
    save_json_file(CACHE_PATH, papers)


def build_demo_papers():
    now = utc_now()

    def paper(days_ago: int, suffix: str, title: str, title_zh: str, summary: str, summary_zh: str, topics, keywords, authors, category):
        published = (now - dt.timedelta(days=days_ago)).replace(microsecond=0)
        updated = published + dt.timedelta(hours=6)
        return {
            "id": f"demo-{suffix}",
            "title": title,
            "titleZh": title_zh,
            "summary": summary,
            "summaryZh": summary_zh,
            "authors": authors,
            "published": published.isoformat(),
            "updated": updated.isoformat(),
            "paperUrl": f"https://arxiv.org/abs/demo-{suffix}",
            "pdfUrl": f"https://arxiv.org/pdf/demo-{suffix}.pdf",
            "primaryCategory": category,
            "matchedTopics": topics,
            "matchedKeywords": keywords,
            "isFavorite": False,
        }

    return [
        paper(
            1,
            "agentic-reasoning",
            "Demo Paper: Agentic Reasoning with Tool-Using Language Models",
            "演示论文：具备工具调用能力的语言模型智能体推理",
            "We present a demonstration-only paper record used when live arXiv access is unavailable. The abstract imitates an agentic reasoning workflow with planning, tool use, and deliberate reasoning for local interface testing.",
            "这是一条仅用于演示的论文记录，在当前环境无法直接访问 arXiv 时用于本地界面联调。摘要模拟了带有规划、工具调用与审慎推理流程的智能体研究场景。",
            ["大语言模型", "智能体", "推理"],
            ["language model", "agentic", "tool use", "reasoning"],
            ["Demo Author A", "Demo Author B"],
            "cs.AI",
        ),
        paper(
            2,
            "multimodal-world-model",
            "Demo Paper: Multimodal World Models for Embodied Manipulation",
            "演示论文：面向具身操作任务的多模态世界模型",
            "This demo abstract combines world models, multimodal reasoning, and robot manipulation to provide a realistic card layout for bilingual rendering and favorites testing.",
            "这段演示摘要融合了世界模型、多模态推理与机器人操作等方向，用来帮助测试双语渲染、标签展示与收藏交互。",
            ["世界模型", "具身智能", "多模态"],
            ["world model", "multimodal reasoning", "robotics", "manipulation"],
            ["Demo Author C", "Demo Author D"],
            "cs.RO",
        ),
        paper(
            4,
            "efficient-inference",
            "Demo Paper: Efficient Inference with Speculative Decoding and KV Cache Reuse",
            "演示论文：结合投机解码与 KV Cache 复用的高效推理",
            "This demo paper focuses on inference optimization, latency, throughput, and efficient serving patterns so the dashboard can showcase topic chips and translated summaries.",
            "这条演示论文聚焦推理优化、时延、吞吐与高效服务模式，用于让看板展示主题标签以及中英文摘要切换效果。",
            ["推理优化", "大语言模型"],
            ["speculative decoding", "KV cache", "latency", "throughput"],
            ["Demo Author E"],
            "cs.LG",
        ),
        paper(
            6,
            "alignment-safety",
            "Demo Paper: Alignment, Distillation, and Robustness for Trustworthy AI Systems",
            "演示论文：可信 AI 系统中的对齐、蒸馏与鲁棒性研究",
            "A final demo record covers alignment, distillation, AI safety, and generalization so offline testing still spans several of the requested paper themes.",
            "最后这条演示记录覆盖对齐、蒸馏、AI 安全与泛化等方向，确保在离线测试时也能覆盖你要求的多个主题。",
            ["训练优化", "AI安全", "扩展与泛化"],
            ["alignment", "distillation", "trustworthy AI", "generalization"],
            ["Demo Author F", "Demo Author G"],
            "cs.CR",
        ),
    ]


def normalize_for_match(text: str) -> str:
    return clean_text(text).lower()


def keyword_matches(keyword: str, normalized_text: str) -> bool:
    normalized_keyword = keyword.lower()
    if KEYWORD_TOKEN_RE.fullmatch(normalized_keyword):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
        return bool(re.search(pattern, normalized_text))
    return normalized_keyword in normalized_text


def match_topics(title: str, summary: str):
    haystack = normalize_for_match(f"{title} {summary}")
    matched_topics = []
    matched_keywords = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        topic_hit = False
        for keyword in keywords:
            if keyword_matches(keyword, haystack):
                topic_hit = True
                if keyword not in matched_keywords:
                    matched_keywords.append(keyword)
        if topic_hit:
            matched_topics.append(topic)
    return matched_topics, matched_keywords


def extract_paper_id(entry_url: str) -> str:
    if "/abs/" in entry_url:
        return entry_url.split("/abs/", 1)[1]
    candidate = entry_url.rstrip("/").rsplit("/", 1)[-1]
    return candidate or hashlib.sha1(entry_url.encode("utf-8")).hexdigest()[:16]


def parse_arxiv_entry(entry: ET.Element):
    entry_id = clean_text(entry.findtext("atom:id", default="", namespaces=ATOM_NS))
    title = clean_text(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
    summary = clean_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
    published = clean_text(entry.findtext("atom:published", default="", namespaces=ATOM_NS))
    updated = clean_text(entry.findtext("atom:updated", default="", namespaces=ATOM_NS))
    authors = [
        clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
        for author in entry.findall("atom:author", ATOM_NS)
    ]
    authors = [author for author in authors if author]

    primary_category = ""
    category = entry.find("arxiv:primary_category", ATOM_NS)
    if category is not None:
        primary_category = clean_text(category.attrib.get("term", ""))
    if not primary_category:
        fallback_category = entry.find("atom:category", ATOM_NS)
        if fallback_category is not None:
            primary_category = clean_text(fallback_category.attrib.get("term", ""))

    pdf_url = ""
    for link in entry.findall("atom:link", ATOM_NS):
        title_attr = link.attrib.get("title", "")
        href = clean_text(link.attrib.get("href", ""))
        if title_attr == "pdf" and href:
            pdf_url = href
            break
    if not pdf_url and entry_id:
        pdf_url = entry_id.replace("/abs/", "/pdf/") + ".pdf"

    return {
        "id": extract_paper_id(entry_id),
        "title": title,
        "titleZh": "",
        "summary": summary,
        "summaryZh": "",
        "authors": authors,
        "published": published,
        "updated": updated,
        "paperUrl": entry_id,
        "pdfUrl": pdf_url,
        "primaryCategory": primary_category,
        "matchedTopics": [],
        "matchedKeywords": [],
        "isFavorite": False,
    }


def fetch_url(url: str, timeout: int = 12) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def split_for_translation(text: str, max_chars: int = 700):
    parts = []
    for paragraph in text.splitlines():
        paragraph = clean_text(paragraph)
        if not paragraph:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        buffer = []
        buffer_size = 0
        for sentence in sentences:
            if len(sentence) > max_chars:
                if buffer:
                    parts.append(" ".join(buffer))
                    buffer = []
                    buffer_size = 0
                for index in range(0, len(sentence), max_chars):
                    parts.append(sentence[index : index + max_chars])
                continue
            projected = buffer_size + len(sentence) + (1 if buffer else 0)
            if projected > max_chars and buffer:
                parts.append(" ".join(buffer))
                buffer = [sentence]
                buffer_size = len(sentence)
            else:
                buffer.append(sentence)
                buffer_size = projected
        if buffer:
            parts.append(" ".join(buffer))
    return parts or [text]


def translation_cache_key(source_lang: str, target_lang: str, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return f"{source_lang}:{target_lang}:{digest}"


def load_translation_from_cache(source_lang: str, target_lang: str, text: str):
    cache_key = translation_cache_key(source_lang, target_lang, text)
    with db_connection() as conn:
        row = conn.execute(
            "SELECT translated_text FROM translation_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    return row["translated_text"] if row else None


def save_translation_to_cache(source_lang: str, target_lang: str, source_text: str, translated_text: str) -> None:
    cache_key = translation_cache_key(source_lang, target_lang, source_text)
    with db_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO translation_cache (
                cache_key, source_text, translated_text, source_lang, target_lang, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cache_key, source_text, translated_text, source_lang, target_lang, iso_now()),
        )
        conn.commit()


def translate_with_mymemory(text: str, source_lang: str, target_lang: str) -> str:
    query = urlencode({"q": text, "langpair": f"{source_lang}|{target_lang}"})
    payload = fetch_url(f"https://api.mymemory.translated.net/get?{query}")
    data = json.loads(payload.decode("utf-8"))
    translated = html.unescape(data.get("responseData", {}).get("translatedText", "")).strip()
    return translated


def translate_with_google(text: str, source_lang: str, target_lang: str) -> str:
    query = urlencode(
        {
            "client": "gtx",
            "sl": source_lang,
            "tl": target_lang,
            "dt": "t",
            "q": text,
        }
    )
    payload = fetch_url(f"https://translate.googleapis.com/translate_a/single?{query}")
    data = json.loads(payload.decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def translate_text(text: str, source_lang: str = "en", target_lang: str = "zh-CN") -> str:
    text = clean_text(text)
    if not text:
        return ""

    parts = split_for_translation(text)
    translated_parts = []
    for part in parts:
        cached = load_translation_from_cache(source_lang, target_lang, part)
        if cached is not None:
            translated_parts.append(cached)
            continue

        translated = ""
        for provider in (translate_with_mymemory, translate_with_google):
            try:
                translated = provider(part, source_lang, target_lang)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError):
                translated = ""
            if translated:
                break

        if not translated:
            return ""

        save_translation_to_cache(source_lang, target_lang, part, translated)
        translated_parts.append(translated)

    return clean_text(" ".join(translated_parts))


def fetch_arxiv_candidates(start_dt: dt.datetime, end_dt: dt.datetime):
    candidates = []
    seen = set()
    start_index = 0

    while start_index < ARXIV_FETCH_CAP and len(candidates) < MAX_MATCHED_PAPERS * 2:
        query = urlencode(
            {
                "search_query": ARXIV_CATEGORY_QUERY,
                "start": start_index,
                "max_results": ARXIV_PAGE_SIZE,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        payload = fetch_url(f"{ARXIV_API_URL}?{query}")
        root = ET.fromstring(payload)
        entries = root.findall("atom:entry", ATOM_NS)
        if not entries:
            break

        reached_older_records = False
        for entry in entries:
            paper = parse_arxiv_entry(entry)
            if not paper["published"]:
                continue

            published_dt = parse_arxiv_timestamp(paper["published"])
            if published_dt < start_dt:
                reached_older_records = True
                break
            if published_dt > end_dt:
                continue
            if paper["id"] in seen:
                continue

            matched_topics, matched_keywords = match_topics(paper["title"], paper["summary"])
            if not matched_topics:
                continue

            candidates.append(
                {
                    **paper,
                    "matchedTopics": matched_topics,
                    "matchedKeywords": matched_keywords,
                }
            )
            seen.add(paper["id"])
            if len(candidates) >= MAX_MATCHED_PAPERS * 2:
                break

        if reached_older_records or len(candidates) >= MAX_MATCHED_PAPERS * 2:
            break

        start_index += ARXIV_PAGE_SIZE
        time.sleep(0.35)

    candidates.sort(key=lambda item: item["published"], reverse=True)
    return candidates[:MAX_MATCHED_PAPERS]


def enrich_translations(papers):
    enriched = []
    for paper in papers:
        record = dict(paper)
        record["titleZh"] = translate_text(record["title"]) or "翻译暂不可用"
        record["summaryZh"] = translate_text(record["summary"]) or "翻译暂不可用"
        enriched.append(record)
    return enriched


def safe_parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def resolve_window(params):
    window = (params.get("window", ["7d"])[0] or "7d").strip()
    now = utc_now()

    if window == "custom":
        start_value = (params.get("startDate", [""])[0] or "").strip()
        end_value = (params.get("endDate", [""])[0] or "").strip()
        if not start_value or not end_value:
            raise ValueError("自定义时间窗口需要同时提供开始和结束日期。")
        start_date = safe_parse_date(start_value)
        end_date = safe_parse_date(end_value)
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期。")
        start_dt = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.timezone.utc)
        end_dt = dt.datetime.combine(end_date, dt.time.max, tzinfo=dt.timezone.utc)
        label = f"{start_date.isoformat()} 至 {end_date.isoformat()}"
        return start_dt, end_dt, label

    if not window.endswith("d") or not window[:-1].isdigit():
        raise ValueError("时间窗口格式不正确。")

    days = int(window[:-1])
    if days <= 0 or days > 90:
        raise ValueError("时间窗口仅支持 1 到 90 天。")

    start_dt = now - dt.timedelta(days=days)
    label = f"最近 {days} 天"
    return start_dt, now, label


def paper_in_window(paper, start_dt: dt.datetime, end_dt: dt.datetime) -> bool:
    published = paper.get("published")
    if not published:
        return False
    try:
        published_dt = dt.datetime.fromisoformat(published)
    except ValueError:
        try:
            published_dt = parse_arxiv_timestamp(published)
        except ValueError:
            return False
    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=dt.timezone.utc)
    return start_dt <= published_dt <= end_dt


def normalize_paper_payload(payload):
    authors = payload.get("authors", [])
    if not isinstance(authors, list):
        authors = [str(authors)]

    matched_topics = payload.get("matchedTopics", [])
    if not isinstance(matched_topics, list):
        matched_topics = [str(matched_topics)]

    matched_keywords = payload.get("matchedKeywords", [])
    if not isinstance(matched_keywords, list):
        matched_keywords = [str(matched_keywords)]

    return {
        "id": clean_text(str(payload.get("id", ""))),
        "title": clean_text(str(payload.get("title", ""))),
        "titleZh": clean_text(str(payload.get("titleZh", ""))),
        "summary": clean_text(str(payload.get("summary", ""))),
        "summaryZh": clean_text(str(payload.get("summaryZh", ""))),
        "authors": [clean_text(str(item)) for item in authors if clean_text(str(item))][:20],
        "published": clean_text(str(payload.get("published", ""))),
        "updated": clean_text(str(payload.get("updated", ""))),
        "paperUrl": clean_text(str(payload.get("paperUrl", ""))),
        "pdfUrl": clean_text(str(payload.get("pdfUrl", ""))),
        "primaryCategory": clean_text(str(payload.get("primaryCategory", ""))),
        "matchedTopics": [clean_text(str(item)) for item in matched_topics if clean_text(str(item))][:10],
        "matchedKeywords": [clean_text(str(item)) for item in matched_keywords if clean_text(str(item))][:12],
        "isFavorite": bool(payload.get("isFavorite", False)),
    }


def get_favorite_ids():
    with db_connection() as conn:
        rows = conn.execute("SELECT paper_id FROM favorites").fetchall()
    return {row["paper_id"] for row in rows}


def get_favorites():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT paper_id, payload_json, created_at FROM favorites ORDER BY created_at DESC"
        ).fetchall()
    favorites = []
    for row in rows:
        paper = normalize_paper_payload(json.loads(row["payload_json"]))
        paper["isFavorite"] = True
        favorites.append(paper)
    return favorites


def save_favorite(paper):
    paper = normalize_paper_payload(paper)
    if not paper["id"]:
        raise ValueError("缺少论文 ID。")
    paper["isFavorite"] = True
    with db_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO favorites (paper_id, payload_json, created_at) VALUES (?, ?, ?)",
            (paper["id"], json.dumps(paper, ensure_ascii=False), iso_now()),
        )
        conn.commit()
    return paper


def delete_favorite(paper_id: str) -> None:
    with db_connection() as conn:
        conn.execute("DELETE FROM favorites WHERE paper_id = ?", (paper_id,))
        conn.commit()


def apply_favorite_flags(papers):
    favorite_ids = get_favorite_ids()
    results = []
    for paper in papers:
        record = normalize_paper_payload(paper)
        record["isFavorite"] = record["id"] in favorite_ids
        results.append(record)
    return results


def load_fallback_papers(start_dt: dt.datetime, end_dt: dt.datetime):
    cached = [paper for paper in get_cached_live_papers() if paper_in_window(paper, start_dt, end_dt)]
    if cached:
        return apply_favorite_flags(cached[:MAX_MATCHED_PAPERS]), "cache", "已回退到最近一次成功抓取的缓存数据。"

    demo = [paper for paper in build_demo_papers() if paper_in_window(paper, start_dt, end_dt)]
    if not demo:
        demo = build_demo_papers()
    return apply_favorite_flags(demo[:MAX_MATCHED_PAPERS]), "demo", "当前环境外网受限，已展示内置演示数据，页面交互可正常测试。"


def get_live_papers(start_dt: dt.datetime, end_dt: dt.datetime):
    candidates = fetch_arxiv_candidates(start_dt, end_dt)
    enriched = enrich_translations(candidates)
    save_cached_live_papers(enriched)
    return apply_favorite_flags(enriched)


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        SESSIONS[token] = {
            "username": username,
            "expires_at": time.time() + SESSION_TTL_SECONDS,
        }
    return token


def delete_session(token: str) -> None:
    if not token:
        return
    with SESSION_LOCK:
        SESSIONS.pop(token, None)


def cleanup_sessions() -> None:
    now = time.time()
    with SESSION_LOCK:
        expired = [token for token, session in SESSIONS.items() if session["expires_at"] <= now]
        for token in expired:
            SESSIONS.pop(token, None)


def get_session(cookie_header: str):
    cleanup_sessions()
    if not cookie_header:
        return None, None
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    cookie_value = cookie.get(COOKIE_NAME)
    if cookie_value is None:
        return None, None
    token = cookie_value.value
    with SESSION_LOCK:
        session = SESSIONS.get(token)
    if not session:
        return token, None
    return token, session


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ArxivEveryday/1.0"

    def log_message(self, format_, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {format_ % args}")

    def do_GET(self):
        self.route_request("GET")

    def do_POST(self):
        self.route_request("POST")

    def do_DELETE(self):
        self.route_request("DELETE")

    def route_request(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path == "/health":
                return self.send_json({"ok": True, "time": iso_now()})

            if path.startswith("/assets/"):
                return self.serve_asset(path.removeprefix("/assets/"))

            if path == "/":
                return self.handle_root()
            if path == "/login":
                return self.handle_login_page()

            if path == "/api/session" and method == "GET":
                return self.handle_session()
            if path == "/api/login" and method == "POST":
                return self.handle_login()
            if path == "/api/logout" and method == "POST":
                return self.handle_logout()
            if path == "/api/papers" and method == "GET":
                return self.handle_papers(params)
            if path == "/api/favorites" and method == "GET":
                return self.handle_favorites()
            if path == "/api/favorites" and method == "POST":
                return self.handle_save_favorite()
            if path.startswith("/api/favorites/") and method == "DELETE":
                paper_id = unquote(path.removeprefix("/api/favorites/"))
                return self.handle_delete_favorite(paper_id)

            self.send_error_response(HTTPStatus.NOT_FOUND, "未找到请求资源。")
        except ValueError as exc:
            self.send_error_response(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self.send_error_response(HTTPStatus.INTERNAL_SERVER_ERROR, f"服务器处理失败：{exc}")

    def handle_root(self):
        if not self.require_page_auth():
            return
        self.serve_file(STATIC_DIR / "index.html")

    def handle_login_page(self):
        _, session = get_session(self.headers.get("Cookie", ""))
        if session:
            return self.redirect("/")
        self.serve_file(STATIC_DIR / "login.html")

    def handle_session(self):
        _, session = get_session(self.headers.get("Cookie", ""))
        self.send_json(
            {
                "authenticated": bool(session),
                "username": session["username"] if session else "",
            }
        )

    def handle_login(self):
        payload = self.read_json_body()
        username = clean_text(str(payload.get("username", "")))
        password = str(payload.get("password", ""))

        if username != ADMIN_USERNAME or password != ADMIN_PASSWORD:
            return self.send_error_response(HTTPStatus.UNAUTHORIZED, "账号或密码不正确。")

        token = create_session(username)
        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = token
        cookie[COOKIE_NAME]["path"] = "/"
        cookie[COOKIE_NAME]["httponly"] = True
        cookie[COOKIE_NAME]["samesite"] = "Lax"
        cookie[COOKIE_NAME]["max-age"] = str(SESSION_TTL_SECONDS)

        self.send_json(
            {
                "success": True,
                "username": username,
                "message": "登录成功。",
            },
            extra_headers=[("Set-Cookie", cookie.output(header="").strip())],
        )

    def handle_logout(self):
        token, _ = get_session(self.headers.get("Cookie", ""))
        delete_session(token)

        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = ""
        cookie[COOKIE_NAME]["path"] = "/"
        cookie[COOKIE_NAME]["httponly"] = True
        cookie[COOKIE_NAME]["samesite"] = "Lax"
        cookie[COOKIE_NAME]["max-age"] = "0"

        self.send_json(
            {"success": True, "message": "已退出登录。"},
            extra_headers=[("Set-Cookie", cookie.output(header="").strip())],
        )

    def handle_papers(self, params):
        if not self.require_api_auth():
            return

        start_dt, end_dt, label = resolve_window(params)
        try:
            papers = get_live_papers(start_dt, end_dt)
            source = "live"
            message = f"已从 arXiv 拉取并翻译 {len(papers)} 篇论文。首次翻译可能稍慢，后续会使用本地缓存。"
        except Exception:
            papers, source, message = load_fallback_papers(start_dt, end_dt)

        self.send_json(
            {
                "papers": papers,
                "count": len(papers),
                "source": source,
                "message": message,
                "window": {
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "label": label,
                },
            }
        )

    def handle_favorites(self):
        if not self.require_api_auth():
            return
        favorites = get_favorites()
        self.send_json({"favorites": favorites, "count": len(favorites)})

    def handle_save_favorite(self):
        if not self.require_api_auth():
            return
        payload = self.read_json_body()
        paper = save_favorite(payload)
        self.send_json({"success": True, "paper": paper, "message": "已加入收藏。"})

    def handle_delete_favorite(self, paper_id: str):
        if not self.require_api_auth():
            return
        if not paper_id:
            raise ValueError("缺少论文 ID。")
        delete_favorite(paper_id)
        self.send_json({"success": True, "paperId": paper_id, "message": "已取消收藏。"})

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def require_api_auth(self) -> bool:
        _, session = get_session(self.headers.get("Cookie", ""))
        if session:
            return True
        self.send_error_response(HTTPStatus.UNAUTHORIZED, "请先登录。")
        return False

    def require_page_auth(self) -> bool:
        _, session = get_session(self.headers.get("Cookie", ""))
        if session:
            return True
        self.redirect("/login")
        return False

    def serve_asset(self, asset_path: str):
        asset_path = asset_path.lstrip("/")
        target = (STATIC_DIR / asset_path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists():
            return self.send_error_response(HTTPStatus.NOT_FOUND, "静态资源不存在。")
        self.serve_file(target)

    def serve_file(self, path: Path):
        content = path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, location: str):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers:
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_error_response(self, status: HTTPStatus, message: str):
        self.send_json({"error": message, "status": int(status)}, status=status)


def run():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Arxiv Everyday is running at http://127.0.0.1:{PORT}")
    print(f"Login with username={ADMIN_USERNAME} password={ADMIN_PASSWORD}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
