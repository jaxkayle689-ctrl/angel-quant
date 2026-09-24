from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode


SOURCE_ID = "youtube-Z6LpMlXuDHA"
SOURCE_URL = "https://www.youtube.com/watch?v=Z6LpMlXuDHA"
SOURCE_TITLE = "缠论终极教程：2小时讲透缠论所有核心"
RESOURCE_NAME = "chanlun_Z6LpMlXuDHA.json"
SCHEMA_VERSION = 1
VECTOR_DIMENSIONS = 384
DOMAIN_TERMS = ("K线合并", "包含关系", "顶分型", "底分型", "分型", "线段", "中枢", "走势类型", "背驰", "第一类买点", "第二类买点", "第三类买点", "买卖点", "笔")
CHAPTERS = {
    "K线合并": (0, 15 * 60), "包含关系": (0, 15 * 60),
    "顶分型": (15 * 60, 41 * 60), "底分型": (15 * 60, 41 * 60), "分型": (15 * 60, 41 * 60),
    "笔": (40 * 60, 75 * 60), "线段": (72 * 60, 110 * 60), "中枢": (90 * 60, 111 * 60),
    "走势类型": (110 * 60, 130 * 60), "背驰": (128 * 60, 145 * 60),
    "第一类买点": (168 * 60, 179 * 60), "第二类买点": (168 * 60, 179 * 60),
    "第三类买点": (168 * 60, 179 * 60), "买卖点": (168 * 60, 179 * 60),
}


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _terms(text: str) -> list[str]:
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text.lower())
    latin = re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower())
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    grams = [chinese[index:index + size] for size in (1, 2, 3) for index in range(max(0, len(chinese) - size + 1))]
    return latin + grams


def _vector(text: str) -> dict[int, float]:
    counts: Counter[int] = Counter()
    for term in _terms(text):
        digest = hashlib.blake2b(term.encode("utf-8"), digest_size=4).digest()
        counts[int.from_bytes(digest, "big") % VECTOR_DIMENSIONS] += 1
    length = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {key: value / length for key, value in counts.items()}


def _cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def _timestamp(seconds: float) -> str:
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _watch_url(seconds: float) -> str:
    return SOURCE_URL + "&" + urlencode({"t": f"{max(0, int(seconds))}s"})


def load_segments(path: Path | None = None) -> list[Segment]:
    if path is None:
        path = Path(resources.files("binance_quant.resources").joinpath(RESOURCE_NAME))
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments: list[Segment] = []
    for item in payload.get("segments", []):
        text = _clean(str(item.get("text", "")))
        if text:
            start = max(0.0, float(item.get("start", 0)))
            end = max(start, float(item.get("end", start)))
            segments.append(Segment(start, end, text))
    return segments


def build_chunks(segments: Iterable[Segment], target_chars: int = 520, overlap: int = 2) -> list[dict[str, Any]]:
    source = list(segments)
    chunks: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(source):
        chosen: list[Segment] = []
        length = 0
        index = cursor
        while index < len(source) and (length < target_chars or len(chosen) < 3):
            chosen.append(source[index])
            length += len(source[index].text)
            index += 1
        text = _clean(" ".join(item.text for item in chosen))
        chunks.append({
            "ordinal": len(chunks),
            "start": chosen[0].start,
            "end": chosen[-1].end,
            "text": text,
            "vector": _vector(text),
        })
        next_cursor = index - min(overlap, max(0, len(chosen) - 1))
        cursor = max(cursor + 1, next_cursor)
    return chunks


class KnowledgeBase:
    """Local, versioned and auditable evidence store for the desktop application."""

    def __init__(self, root: Path, transcript_path: Path | None = None) -> None:
        self.root = Path(root) / "knowledge_base"
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "knowledge.db"
        self.transcript_path = transcript_path
        self._lock = threading.RLock()
        self._setup()
        self.ensure_index()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _setup(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                    checksum TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
                    language TEXT NOT NULL, duration_seconds REAL NOT NULL,
                    segment_count INTEGER NOT NULL, chunk_count INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, start_seconds REAL NOT NULL, end_seconds REAL NOT NULL,
                    text TEXT NOT NULL, terms TEXT NOT NULL, vector TEXT NOT NULL,
                    UNIQUE(source_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
                    query_hash TEXT, result_count INTEGER, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_source_ordinal ON chunks(source_id, ordinal);
                """
            )

    def ensure_index(self, force: bool = False) -> dict[str, Any]:
        try:
            segments = load_segments(self.transcript_path)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return self.status()
        canonical = json.dumps([segment.__dict__ for segment in segments], ensure_ascii=False, separators=(",", ":"))
        checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._lock, self._connect() as db:
            current = db.execute("SELECT checksum FROM sources WHERE id=?", (SOURCE_ID,)).fetchone()
            if current and current["checksum"] == checksum and not force:
                return self.status()
            chunks = build_chunks(segments)
            db.execute("DELETE FROM sources WHERE id=?", (SOURCE_ID,))
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (SOURCE_ID, SOURCE_TITLE, SOURCE_URL, checksum, SCHEMA_VERSION, "ready", "zh-CN",
                 segments[-1].end if segments else 0, len(segments), len(chunks), _now()),
            )
            for chunk in chunks:
                chunk_id = f"{SOURCE_ID}-{chunk['ordinal']:04d}"
                db.execute(
                    "INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)",
                    (chunk_id, SOURCE_ID, chunk["ordinal"], chunk["start"], chunk["end"], chunk["text"],
                     json.dumps(_terms(chunk["text"]), ensure_ascii=False),
                     json.dumps(chunk["vector"], separators=(",", ":"))),
                )
            db.execute("INSERT INTO audit_log(event, created_at) VALUES('index', ?)", (_now(),))
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM sources WHERE id=?", (SOURCE_ID,)).fetchone()
            queries = db.execute("SELECT COUNT(*) FROM audit_log WHERE event='query'").fetchone()[0]
        if row is None:
            return {"state": "pending", "source_count": 0, "chunk_count": 0, "query_count": queries,
                    "message": "视频字幕尚未完成索引。"}
        return {
            "state": row["status"], "source_count": 1, "chunk_count": row["chunk_count"],
            "segment_count": row["segment_count"], "duration_seconds": row["duration_seconds"],
            "query_count": queries, "indexed_at": row["indexed_at"], "schema_version": row["version"],
            "source": {"id": row["id"], "title": row["title"], "url": row["url"], "language": row["language"]},
        }

    def search(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        question = _clean(query)
        if len(question) < 2:
            raise ValueError("请输入至少 2 个字符的问题。")
        limit = min(10, max(1, int(limit)))
        q_terms = Counter(_terms(question))
        q_vector = _vector(question)
        anchors = [term for term in DOMAIN_TERMS if term in question]
        with self._connect() as db:
            rows = db.execute("SELECT * FROM chunks WHERE source_id=? ORDER BY ordinal", (SOURCE_ID,)).fetchall()
        candidates: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            terms = Counter(json.loads(row["terms"]))
            lexical = sum(min(count, terms.get(term, 0)) for term, count in q_terms.items())
            lexical = lexical / (sum(q_terms.values()) or 1)
            vector = {int(key): float(value) for key, value in json.loads(row["vector"]).items()}
            semantic = _cosine(q_vector, vector)
            exact = 1.0 if question.lower() in row["text"].lower() else 0.0
            anchor = sum(min(3, row["text"].count(term)) / 3 for term in anchors) / (len(anchors) or 1)
            intent = 0.0
            if any(term in question for term in ("定义", "什么是", "是什么")) and any(term in row["text"] for term in ("定义", "概念", "是指", "本质")):
                intent = 1.0
            if any(term in question for term in ("形成", "规则", "确认", "怎么")) and any(term in row["text"] for term in ("形成", "规则", "确认", "条件")):
                intent = 1.0
            chapter = 0.0
            for term in anchors:
                bounds = CHAPTERS.get(term)
                if bounds and bounds[0] <= row["start_seconds"] < bounds[1]:
                    chapter = 1.0
                    break
            score = 0.33 * semantic + 0.23 * min(1.0, lexical) + 0.20 * anchor + 0.07 * intent + 0.04 * exact + 0.13 * chapter
            candidates.append((score, row))
        ranked = sorted(candidates, key=lambda item: item[0], reverse=True)[:limit]
        return [{
            "id": row["id"], "title": SOURCE_TITLE, "text": row["text"],
            "start_seconds": row["start_seconds"], "end_seconds": row["end_seconds"],
            "timestamp": _timestamp(row["start_seconds"]), "url": _watch_url(row["start_seconds"]),
            "score": round(score, 4), "source_id": SOURCE_ID,
        } for score, row in ranked if score > 0]

    def query(self, question: str, limit: int = 6) -> dict[str, Any]:
        evidence = self.search(question, limit)
        with self._connect() as db:
            db.execute(
                "INSERT INTO audit_log(event, query_hash, result_count, created_at) VALUES('query', ?, ?, ?)",
                (hashlib.sha256(question.encode("utf-8")).hexdigest(), len(evidence), _now()),
            )
        strong = [item for item in evidence if item["score"] >= 0.18]
        if not strong:
            answer = "当前视频证据不足以回答这个问题。请换用更具体的缠论术语，例如分型、笔、线段、中枢、背驰或买卖点。"
            confidence = "low"
        else:
            excerpts: list[str] = []
            for item in strong[:3]:
                sentences = [part.strip() for part in re.split(r"(?<=[。！？])", item["text"]) if part.strip()]
                if len(sentences) > 1:
                    excerpt = "".join(sentences[:2])
                else:
                    positions = [item["text"].find(term) for term in DOMAIN_TERMS if term in question and term in item["text"]]
                    start = max(0, min(positions) - 70) if positions else 0
                    excerpt = item["text"][start:start + 300]
                excerpts.append(excerpt[:300])
            answer = "根据视频中命中的内容：" + "\n\n".join(f"{index + 1}. {text}" for index, text in enumerate(excerpts))
            confidence = "high" if strong[0]["score"] >= 0.42 else "medium"
        return {
            "question": question, "answer": answer, "confidence": confidence,
            "citations": evidence, "retrieval": {"method": "local-hybrid-v1", "returned": len(evidence)},
            "notice": "回答仅依据已索引的视频字幕；用于学习研究，不构成投资建议。",
        }
