#!/usr/bin/env python3
import datetime as dt
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None


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
USER_AGENT = "FrontierSignals/2.0 (+http://127.0.0.1)"
MAX_MATCHED_PAPERS = int(os.getenv("ARXIV_MAX_MATCHED", "24"))
ARXIV_PAGE_SIZE = int(os.getenv("ARXIV_PAGE_SIZE", "100"))
ARXIV_FETCH_CAP = int(os.getenv("ARXIV_FETCH_CAP", "600"))
PDF_TEXT_LIMIT = int(os.getenv("PDF_TEXT_LIMIT", "65000"))

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
).rstrip("/")
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen3-coder-plus").strip() or "qwen3-coder-plus"

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
TRACKED_TOPICS = list(TOPIC_KEYWORDS.keys())

ARXIV_CATEGORIES = [
    "cs.AI",
    "cs.CL",
    "cs.CV",
    "cs.CR",
    "cs.HC",
    "cs.IR",
    "cs.LG",
    "cs.MA",
    "cs.NE",
    "cs.RO",
    "cs.SE",
    "eess.AS",
    "eess.IV",
    "stat.ML",
]
ARXIV_CATEGORY_QUERY = "(" + " OR ".join(f"cat:{category}" for category in ARXIV_CATEGORIES) + ")"

KEYWORD_TOKEN_RE = re.compile(r"^[a-z0-9.+-]{2,6}$")
WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+-]{2,}")
DECLARED_KEYWORDS_RE = re.compile(r"(?:keywords?|index terms?)\s*[:：]\s*([^\n]+)", re.IGNORECASE)
SESSIONS = {}
SESSION_LOCK = threading.Lock()

STOPWORDS = {
    "about",
    "after",
    "against",
    "among",
    "also",
    "approach",
    "based",
    "being",
    "between",
    "both",
    "building",
    "can",
    "context",
    "data",
    "demonstrate",
    "design",
    "does",
    "during",
    "each",
    "enable",
    "from",
    "framework",
    "future",
    "general",
    "into",
    "large",
    "learn",
    "learning",
    "method",
    "methods",
    "model",
    "models",
    "more",
    "neural",
    "new",
    "paper",
    "performance",
    "propose",
    "proposed",
    "results",
    "show",
    "study",
    "such",
    "system",
    "systems",
    "task",
    "tasks",
    "that",
    "their",
    "these",
    "this",
    "through",
    "using",
    "with",
    "without",
}

ACRONYMS = {"llm", "gpt", "cot", "rlhf", "dpo", "lora", "kv", "ml", "ai"}


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def iso_now():
    return utc_now().isoformat()


def clean_text(value):
    return WHITESPACE_RE.sub(" ", (value or "").strip())


def normalize_summary_text(value):
    lines = [line.strip() for line in str(value or "").replace("\r", "").split("\n")]
    compact = "\n".join(line for line in lines if line)
    return compact.strip()


def parse_arxiv_timestamp(value):
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def db_connection():
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    ensure_data_dir()
    with db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                paper_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_summary_cache (
                paper_id TEXT PRIMARY KEY,
                paper_url TEXT NOT NULL,
                pdf_url TEXT NOT NULL,
                model_name TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        migrate_db(conn)


def table_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def migrate_db(conn):
    favorites_columns = table_columns(conn, "favorites")
    if "updated_at" not in favorites_columns:
        conn.execute("ALTER TABLE favorites ADD COLUMN updated_at TEXT")
        conn.execute("UPDATE favorites SET updated_at = created_at WHERE updated_at IS NULL OR updated_at = ''")
    conn.commit()


def load_json_file(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_file(path, payload):
    ensure_data_dir()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_cached_live_papers():
    return load_json_file(CACHE_PATH) or []


def save_cached_live_papers(papers):
    save_json_file(CACHE_PATH, papers)


def build_demo_papers():
    now = utc_now()

    def paper(days_ago, suffix, title, title_zh, summary, summary_zh, topics, keywords, authors, category, ai_summary=""):
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
            "keywords": keywords,
            "aiSummary": ai_summary,
            "aiSummarySource": "abstract",
            "aiSummaryUpdatedAt": "",
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
            ["language model", "agentic", "tool use", "reasoning", "planning"],
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
            ["world model", "multimodal reasoning", "robotics", "manipulation", "sensorimotor"],
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
            ["speculative decoding", "KV cache", "latency", "throughput", "efficient inference"],
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
            ["alignment", "distillation", "trustworthy AI", "generalization", "robustness"],
            ["Demo Author F", "Demo Author G"],
            "cs.CR",
        ),
    ]


def normalize_for_match(text):
    return clean_text(text).lower()


def keyword_matches(keyword, normalized_text):
    normalized_keyword = keyword.lower()
    if KEYWORD_TOKEN_RE.fullmatch(normalized_keyword):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
        return bool(re.search(pattern, normalized_text))
    return normalized_keyword in normalized_text


def match_topics(title, summary):
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


def extract_declared_keywords(text):
    match = DECLARED_KEYWORDS_RE.search(text or "")
    if not match:
        return []
    raw = match.group(1)
    pieces = re.split(r"[;,，；]\s*", raw)
    return [clean_text(piece) for piece in pieces if clean_text(piece)]


def prettify_keyword(term):
    words = []
    for part in term.split():
        lower = part.lower()
        if lower in ACRONYMS:
            words.append(lower.upper())
        else:
            words.append(lower)
    return " ".join(words)


def extract_keywords(title, summary, matched_keywords):
    declared = extract_declared_keywords(summary)
    seen = set()
    keywords = []

    def add(term):
        normalized = clean_text(term).strip(".,;:()[]{}")
        if len(normalized) < 3:
            return
        lowered = normalized.lower()
        if lowered in seen:
            return
        if lowered in STOPWORDS:
            return
        seen.add(lowered)
        keywords.append(normalized)

    for keyword in declared:
        add(keyword)
    for keyword in matched_keywords:
        add(keyword)

    counters = Counter()
    for text, boost in ((title, 4), (summary, 1)):
        tokens = [token.lower() for token in TOKEN_RE.findall(text or "")]
        tokens = [token for token in tokens if token not in STOPWORDS]
        for token in tokens:
            counters[token] += boost
        for ngram_size in (2, 3):
            for index in range(len(tokens) - ngram_size + 1):
                phrase_tokens = tokens[index : index + ngram_size]
                if any(token in STOPWORDS for token in phrase_tokens):
                    continue
                counters[" ".join(phrase_tokens)] += boost

    for phrase, _ in counters.most_common(30):
        if len(keywords) >= 8:
            break
        add(prettify_keyword(phrase))

    return keywords[:8]


def extract_paper_id(entry_url):
    if "/abs/" in entry_url:
        return entry_url.split("/abs/", 1)[1]
    candidate = entry_url.rstrip("/").rsplit("/", 1)[-1]
    return candidate or hashlib.sha1(entry_url.encode("utf-8")).hexdigest()[:16]


def parse_arxiv_entry(entry):
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
        "keywords": [],
        "aiSummary": "",
        "aiSummarySource": "",
        "aiSummaryUpdatedAt": "",
        "isFavorite": False,
    }


def fetch_url(url, timeout=12, data=None, headers=None):
    final_headers = {"User-Agent": USER_AGENT}
    if headers:
        final_headers.update(headers)
    request = Request(url, data=data, headers=final_headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def split_for_translation(text, max_chars=700):
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


def translation_cache_key(source_lang, target_lang, text):
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return f"{source_lang}:{target_lang}:{digest}"


def load_translation_from_cache(source_lang, target_lang, text):
    cache_key = translation_cache_key(source_lang, target_lang, text)
    with db_connection() as conn:
        row = conn.execute(
            "SELECT translated_text FROM translation_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    return row["translated_text"] if row else None


def save_translation_to_cache(source_lang, target_lang, source_text, translated_text):
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


def translate_with_mymemory(text, source_lang, target_lang):
    query = urlencode({"q": text, "langpair": f"{source_lang}|{target_lang}"})
    payload = fetch_url(f"https://api.mymemory.translated.net/get?{query}")
    data = json.loads(payload.decode("utf-8"))
    translated = html.unescape(data.get("responseData", {}).get("translatedText", "")).strip()
    return translated


def translate_with_google(text, source_lang, target_lang):
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


def translate_text(text, source_lang="en", target_lang="zh-CN"):
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


def summary_cache_map(paper_ids):
    ids = [paper_id for paper_id in paper_ids if paper_id]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with db_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM ai_summary_cache WHERE paper_id IN ({placeholders})",
            ids,
        ).fetchall()
    return {row["paper_id"]: row for row in rows}


def get_cached_summary_record(paper_id):
    if not paper_id:
        return None
    return summary_cache_map([paper_id]).get(paper_id)


def save_summary_cache(paper_id, paper_url, pdf_url, model_name, summary_text, source_kind, source_hash):
    now = iso_now()
    with db_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ai_summary_cache (
                paper_id, paper_url, pdf_url, model_name, summary_text, source_kind,
                source_hash, created_at, updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                COALESCE((SELECT created_at FROM ai_summary_cache WHERE paper_id = ?), ?),
                ?
            )
            """,
            (
                paper_id,
                paper_url,
                pdf_url,
                model_name,
                summary_text,
                source_kind,
                source_hash,
                paper_id,
                now,
                now,
            ),
        )
        conn.commit()


def validate_dashscope_key():
    if not DASHSCOPE_API_KEY:
        raise ValueError("AI Summary 未配置。请在环境变量中设置标准百炼 API Key：DASHSCOPE_API_KEY。")
    if DASHSCOPE_API_KEY.startswith("sk-sp-"):
        raise ValueError(
            "检测到 Coding Plan key（sk-sp-）。阿里云官方说明该 key 仅限 AI 编程工具，"
            "不适合自定义应用后端 API。请改用标准百炼 API Key（sk-...）。"
        )


def extract_pdf_text(pdf_url):
    if not pdf_url:
        raise ValueError("当前论文没有可用的 PDF 链接。")
    if PdfReader is None:
        raise ValueError("当前环境未安装 pypdf，无法抽取论文全文。")
    raw = fetch_url(pdf_url, timeout=30)
    reader = PdfReader(io.BytesIO(raw))
    chunks = []
    current_size = 0
    for page in reader.pages:
        text = clean_text(page.extract_text() or "")
        if not text:
            continue
        chunks.append(text)
        current_size += len(text)
        if current_size >= PDF_TEXT_LIMIT:
            break
    full_text = "\n".join(chunks).strip()
    if len(full_text) < 800:
        raise ValueError("未能从 PDF 中抽取出足够多的正文文本。")
    return full_text[:PDF_TEXT_LIMIT]


def normalize_summary_content(content):
    if isinstance(content, str):
        return normalize_summary_text(content)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        return normalize_summary_text("\n".join(parts))
    return normalize_summary_text(str(content))


def call_dashscope_summary(paper, source_text, source_kind):
    validate_dashscope_key()
    prompt = (
        "请你作为资深 AI 研究分析师，基于下面提供的论文信息，输出一份面向工程团队的中文总结。"
        "要求：\n"
        "1. 用简洁自然的中文。\n"
        "2. 结构固定为四段：核心问题、方法亮点、关键结论、对团队的启发。\n"
        "3. 如果输入源是全文，请充分利用全文信息；如果输入源仅为题目和摘要，请在首句明确提示“当前基于题目与摘要生成”。\n"
        "4. 不要虚构实验数字；不确定就明确写不确定。\n"
        "5. 控制在 220 到 380 个中文字符之间。\n"
    )
    user_message = (
        f"论文标题：{paper['title']}\n"
        f"中文标题：{paper.get('titleZh', '')}\n"
        f"作者：{', '.join(paper.get('authors', []))}\n"
        f"主题：{', '.join(paper.get('matchedTopics', []))}\n"
        f"关键词：{', '.join(paper.get('keywords', []))}\n"
        f"内容来源：{'全文 PDF' if source_kind == 'pdf' else '题目与摘要'}\n"
        f"论文内容：\n{source_text}"
    )
    payload = {
        "model": DASHSCOPE_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ],
    }
    raw = fetch_url(
        f"{DASHSCOPE_BASE_URL}/chat/completions",
        timeout=90,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    data = json.loads(raw.decode("utf-8"))
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("百炼未返回可用的 summary 结果。")
    content = choices[0].get("message", {}).get("content", "")
    summary_text = normalize_summary_content(content)
    if not summary_text:
        raise ValueError("百炼返回了空的 summary。")
    return summary_text


def attach_cached_summary_to_paper(paper, summary_row):
    record = dict(paper)
    if summary_row:
        record["aiSummary"] = summary_row["summary_text"]
        record["aiSummarySource"] = summary_row["source_kind"]
        record["aiSummaryUpdatedAt"] = summary_row["updated_at"]
    return record


def ensure_ai_summary_for_paper(paper, force=False):
    paper = normalize_paper_payload(paper)
    if not force:
        cached = get_cached_summary_record(paper["id"])
        if cached:
            return attach_cached_summary_to_paper(paper, cached), "已使用缓存的 AI Summary。"

    source_kind = "pdf"
    source_text = ""
    extraction_note = ""
    try:
        source_text = extract_pdf_text(paper["pdfUrl"])
    except Exception as exc:
        source_kind = "abstract"
        source_text = (
            f"Title: {paper['title']}\n"
            f"Abstract: {paper['summary']}\n"
            f"Keywords: {', '.join(paper['keywords'])}"
        )
        extraction_note = f"未能抽取全文，已退回题目与摘要：{exc}"

    source_hash = hashlib.sha1(source_text.encode("utf-8")).hexdigest()
    summary_text = call_dashscope_summary(paper, source_text, source_kind)
    save_summary_cache(
        paper["id"],
        paper["paperUrl"],
        paper["pdfUrl"],
        DASHSCOPE_MODEL,
        summary_text,
        source_kind,
        source_hash,
    )
    refreshed = attach_cached_summary_to_paper(paper, get_cached_summary_record(paper["id"]))
    if extraction_note:
        return refreshed, f"AI Summary 已生成。{extraction_note}"
    return refreshed, "AI Summary 已基于论文全文生成。"


def fetch_arxiv_candidates(start_dt, end_dt):
    candidates = []
    seen = set()
    start_index = 0

    while start_index < ARXIV_FETCH_CAP and len(candidates) < MAX_MATCHED_PAPERS * 3:
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

            paper["matchedTopics"] = matched_topics
            paper["matchedKeywords"] = matched_keywords
            paper["keywords"] = extract_keywords(paper["title"], paper["summary"], matched_keywords)
            candidates.append(paper)
            seen.add(paper["id"])
            if len(candidates) >= MAX_MATCHED_PAPERS * 3:
                break

        if reached_older_records or len(candidates) >= MAX_MATCHED_PAPERS * 3:
            break

        start_index += ARXIV_PAGE_SIZE
        time.sleep(0.35)

    candidates.sort(key=lambda item: item["published"], reverse=True)
    return candidates


def enrich_translations(papers):
    enriched = []
    for paper in papers:
        record = dict(paper)
        record["titleZh"] = translate_text(record["title"]) or "翻译暂不可用"
        record["summaryZh"] = translate_text(record["summary"]) or "翻译暂不可用"
        enriched.append(record)
    return enriched


def safe_parse_date(value):
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def parse_selected_topics(params):
    raw_topics = params.get("topic", []) + params.get("topics", [])
    selected_topics = []
    for raw in raw_topics:
        pieces = [clean_text(piece) for piece in str(raw).split(",")]
        for piece in pieces:
            if piece and piece in TRACKED_TOPICS and piece not in selected_topics:
                selected_topics.append(piece)
    return selected_topics or list(TRACKED_TOPICS)


def resolve_filters(params):
    start_value = clean_text((params.get("startDate", [""])[0] or ""))
    end_value = clean_text((params.get("endDate", [""])[0] or ""))
    if not start_value or not end_value:
        raise ValueError("请同时提供开始日期和结束日期。")
    start_date = safe_parse_date(start_value)
    end_date = safe_parse_date(end_value)
    if end_date < start_date:
        raise ValueError("结束日期不能早于开始日期。")
    if (end_date - start_date).days > 180:
        raise ValueError("日期跨度建议控制在 180 天以内。")
    start_dt = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(end_date, dt.time.max, tzinfo=dt.timezone.utc)
    selected_topics = parse_selected_topics(params)
    label = f"{start_date.isoformat()} 至 {end_date.isoformat()}"
    return start_dt, end_dt, selected_topics, label


def paper_in_window(paper, start_dt, end_dt):
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


def paper_matches_topics(paper, selected_topics):
    if not selected_topics:
        return True
    return bool(set(paper.get("matchedTopics", [])) & set(selected_topics))


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

    keywords = payload.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = [str(keywords)]

    record = {
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
        "keywords": [clean_text(str(item)) for item in keywords if clean_text(str(item))][:10],
        "aiSummary": normalize_summary_text(payload.get("aiSummary", "")),
        "aiSummarySource": clean_text(str(payload.get("aiSummarySource", ""))),
        "aiSummaryUpdatedAt": clean_text(str(payload.get("aiSummaryUpdatedAt", ""))),
        "isFavorite": bool(payload.get("isFavorite", False)),
    }
    if not record["keywords"]:
        record["keywords"] = extract_keywords(record["title"], record["summary"], record["matchedKeywords"])
    return record


def get_favorite_ids():
    with db_connection() as conn:
        rows = conn.execute("SELECT paper_id FROM favorites").fetchall()
    return {row["paper_id"] for row in rows}


def apply_runtime_metadata(papers):
    records = [normalize_paper_payload(paper) for paper in papers]
    favorite_ids = get_favorite_ids()
    summary_map = summary_cache_map([paper["id"] for paper in records])
    final = []
    for paper in records:
        summary_row = summary_map.get(paper["id"])
        record = attach_cached_summary_to_paper(paper, summary_row)
        record["isFavorite"] = record["id"] in favorite_ids
        final.append(record)
    return final


def get_favorites():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT paper_id, payload_json, created_at FROM favorites ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
    favorites = []
    summary_map = summary_cache_map([row["paper_id"] for row in rows])
    for row in rows:
        paper = normalize_paper_payload(json.loads(row["payload_json"]))
        paper = attach_cached_summary_to_paper(paper, summary_map.get(row["paper_id"]))
        paper["isFavorite"] = True
        favorites.append(paper)
    return favorites


def save_favorite_record(paper):
    paper = normalize_paper_payload(paper)
    if not paper["id"]:
        raise ValueError("缺少论文 ID。")
    paper["isFavorite"] = True
    now = iso_now()
    with db_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO favorites (paper_id, payload_json, created_at, updated_at)
            VALUES (
                ?, ?, COALESCE((SELECT created_at FROM favorites WHERE paper_id = ?), ?), ?
            )
            """,
            (
                paper["id"],
                json.dumps(paper, ensure_ascii=False),
                paper["id"],
                now,
                now,
            ),
        )
        conn.commit()
    return paper


def delete_favorite(paper_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM favorites WHERE paper_id = ?", (paper_id,))
        conn.commit()


def filter_papers(papers, start_dt, end_dt, selected_topics):
    return [
        paper
        for paper in papers
        if paper_in_window(paper, start_dt, end_dt) and paper_matches_topics(paper, selected_topics)
    ]


def load_fallback_papers(start_dt, end_dt, selected_topics):
    cached = filter_papers(get_cached_live_papers(), start_dt, end_dt, selected_topics)
    if cached:
        return apply_runtime_metadata(cached[:MAX_MATCHED_PAPERS]), "cache", "已回退到最近一次成功抓取的缓存数据。"

    demo = filter_papers(build_demo_papers(), start_dt, end_dt, selected_topics)
    if not demo:
        demo = filter_papers(build_demo_papers(), start_dt, end_dt, list(TRACKED_TOPICS))
    return (
        apply_runtime_metadata(demo[:MAX_MATCHED_PAPERS]),
        "demo",
        "当前环境外网受限，已展示内置演示数据，方便你继续联调筛选、收藏与 AI summary 交互。",
    )


def get_live_papers(start_dt, end_dt, selected_topics):
    candidates = fetch_arxiv_candidates(start_dt, end_dt)
    filtered = [paper for paper in candidates if paper_matches_topics(paper, selected_topics)]
    translated = enrich_translations(filtered[:MAX_MATCHED_PAPERS])
    save_cached_live_papers(translated)
    return apply_runtime_metadata(translated)


def create_session(username):
    token = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        SESSIONS[token] = {
            "username": username,
            "expires_at": time.time() + SESSION_TTL_SECONDS,
        }
    return token


def delete_session(token):
    if not token:
        return
    with SESSION_LOCK:
        SESSIONS.pop(token, None)


def cleanup_sessions():
    now = time.time()
    with SESSION_LOCK:
        expired = [token for token, session in SESSIONS.items() if session["expires_at"] <= now]
        for token in expired:
            SESSIONS.pop(token, None)


def get_session(cookie_header):
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


def safe_filename(name):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name or "paper").strip("-")
    return cleaned or "paper"


def validate_pdf_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("PDF 地址协议不正确。")
    if not parsed.netloc.endswith("arxiv.org"):
        raise ValueError("当前仅允许下载 arXiv PDF。")
    if "/pdf/" not in parsed.path:
        raise ValueError("不是有效的 arXiv PDF 地址。")
    return url


class AppHandler(BaseHTTPRequestHandler):
    server_version = "FrontierSignals/2.0"

    def log_message(self, format_, *args):
        print(f"[{self.log_date_time_string()}] {self.address_string()} {format_ % args}")

    def do_GET(self):
        self.route_request("GET")

    def do_HEAD(self):
        self.route_request("HEAD")

    def do_POST(self):
        self.route_request("POST")

    def do_DELETE(self):
        self.route_request("DELETE")

    def route_request(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path == "/health" and method in {"GET", "HEAD"}:
                return self.send_json({"ok": True, "time": iso_now()})

            if path.startswith("/assets/") and method in {"GET", "HEAD"}:
                return self.serve_asset(path.removeprefix("/assets/"))

            if path == "/" and method in {"GET", "HEAD"}:
                return self.handle_root()
            if path == "/login" and method in {"GET", "HEAD"}:
                return self.handle_login_page()

            if path == "/api/session" and method in {"GET", "HEAD"}:
                return self.handle_session()
            if path == "/api/login" and method == "POST":
                return self.handle_login()
            if path == "/api/logout" and method == "POST":
                return self.handle_logout()
            if path == "/api/papers" and method in {"GET", "HEAD"}:
                return self.handle_papers(params)
            if path == "/api/favorites" and method in {"GET", "HEAD"}:
                return self.handle_favorites()
            if path == "/api/favorites" and method == "POST":
                return self.handle_save_favorite()
            if path.startswith("/api/favorites/") and method == "DELETE":
                paper_id = unquote(path.removeprefix("/api/favorites/"))
                return self.handle_delete_favorite(paper_id)
            if path == "/api/summary" and method == "POST":
                return self.handle_generate_summary()
            if path == "/api/download" and method in {"GET", "HEAD"}:
                return self.handle_download(params)

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
                "aiSummaryEnabled": bool(DASHSCOPE_API_KEY) and not DASHSCOPE_API_KEY.startswith("sk-sp-"),
                "trackedTopics": TRACKED_TOPICS,
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
            {"success": True, "username": username, "message": "登录成功。"},
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

        start_dt, end_dt, selected_topics, label = resolve_filters(params)
        try:
            papers = get_live_papers(start_dt, end_dt, selected_topics)
            source = "live"
            message = f"已拉取 {len(papers)} 篇论文。你当前关注的是 {len(selected_topics)} 个主题，首次翻译可能稍慢。"
        except Exception:
            papers, source, message = load_fallback_papers(start_dt, end_dt, selected_topics)

        self.send_json(
            {
                "papers": papers,
                "count": len(papers),
                "source": source,
                "message": message,
                "filters": {
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                    "label": label,
                    "selectedTopics": selected_topics,
                    "availableTopics": TRACKED_TOPICS,
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
        paper = normalize_paper_payload(payload)
        summary_note = ""
        if not paper.get("aiSummary"):
            try:
                paper, summary_note = ensure_ai_summary_for_paper(paper, force=False)
            except Exception as exc:
                summary_note = f"AI Summary 未自动生成：{exc}"

        paper = save_favorite_record(paper)
        message = "已加入收藏。"
        if summary_note:
            message = f"{message} {summary_note}"
        self.send_json({"success": True, "paper": paper, "message": message})

    def handle_delete_favorite(self, paper_id):
        if not self.require_api_auth():
            return
        if not paper_id:
            raise ValueError("缺少论文 ID。")
        delete_favorite(paper_id)
        self.send_json({"success": True, "paperId": paper_id, "message": "已取消收藏。"})

    def handle_generate_summary(self):
        if not self.require_api_auth():
            return
        payload = self.read_json_body()
        paper_payload = payload.get("paper", payload)
        force = bool(payload.get("force", False))
        favorite = bool(payload.get("favorite", False))
        paper, message = ensure_ai_summary_for_paper(paper_payload, force=force)
        if favorite or paper.get("isFavorite"):
            paper = save_favorite_record({**paper, "isFavorite": True})
        self.send_json({"success": True, "paper": paper, "message": message})

    def handle_download(self, params):
        if not self.require_api_auth():
            return
        pdf_url = clean_text((params.get("pdfUrl", [""])[0] or ""))
        paper_id = clean_text((params.get("paperId", ["paper"])[0] or "paper"))
        validate_pdf_url(pdf_url)
        payload = fetch_url(pdf_url, timeout=30)
        filename = f"{safe_filename(paper_id)}.pdf"
        self.send_binary(
            payload,
            content_type="application/pdf",
            extra_headers=[("Content-Disposition", f'attachment; filename="{filename}"')],
        )

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def require_api_auth(self):
        _, session = get_session(self.headers.get("Cookie", ""))
        if session:
            return True
        self.send_error_response(HTTPStatus.UNAUTHORIZED, "请先登录。")
        return False

    def require_page_auth(self):
        _, session = get_session(self.headers.get("Cookie", ""))
        if session:
            return True
        self.redirect("/login")
        return False

    def serve_asset(self, asset_path):
        asset_path = asset_path.lstrip("/")
        target = (STATIC_DIR / asset_path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists():
            return self.send_error_response(HTTPStatus.NOT_FOUND, "静态资源不存在。")
        self.serve_file(target)

    def serve_file(self, path):
        content = path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def send_binary(self, body, status=HTTPStatus.OK, content_type="application/octet-stream", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers:
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, payload, status=HTTPStatus.OK, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers:
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error_response(self, status, message):
        self.send_json({"error": message, "status": int(status)}, status=status)


def run():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Frontier Signals is running at http://127.0.0.1:{PORT}")
    print(f"Login with username={ADMIN_USERNAME} password={ADMIN_PASSWORD}")
    if not DASHSCOPE_API_KEY:
        print("AI Summary is not configured. Set DASHSCOPE_API_KEY to enable it.")
    elif DASHSCOPE_API_KEY.startswith("sk-sp-"):
        print("Detected a Coding Plan key (sk-sp-). For backend summary generation, use a standard DashScope API key (sk-...).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
