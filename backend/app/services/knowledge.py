"""Teacher knowledge base: store the teacher's notes as chunks and find the ones that answer a question.

Retrieval is BM25 keyword search that works for any script (Hindi, Punjabi, Tamil...). Because a
student may ask in Hindi while the notes are in English, the tutor also searches with a query the AI
rewrote in the notes' language. Embedding search can be added behind the same `search` function later.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass

from ..db import Database

# Split on spaces and punctuation, incl. Devanagari danda (। ॥). Matras stay inside the word.
_SPLIT = re.compile(r"[\s\.,;:!?\"'“”‘’()\[\]{}<>।॥\-–—/\\|*#=+_~`]+")
STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "is", "are", "was", "were", "to", "in", "on", "for", "what",
    "who", "which", "when", "where", "how", "why", "tell", "me", "about", "explain", "sir", "please",
    "का", "की", "के", "है", "हैं", "था", "थी", "थे", "में", "से", "को", "और", "क्या", "कौन", "बताइए",
    "बताओ", "समझाइए", "सर", "ने", "पर", "एक", "यह", "वह", "दा", "ਦੀ", "ਦੇ", "ਹੈ", "ਕੀ", "ਵਿੱਚ", "ਅਤੇ",
}


def tokenize(text: str) -> list[str]:
    return [w for w in (p.lower() for p in _SPLIT.split(text)) if w and w not in STOPWORDS]


def chunk_text(text: str, max_words: int = 180, overlap: int = 30) -> list[str]:
    """Split long notes into overlapping chunks of about max_words words, keeping paragraphs together."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current = [], []
    for para in paragraphs:
        words = para.split()
        if current and len(current) + len(words) > max_words:
            chunks.append(" ".join(current))
            current = current[-overlap:]
        current.extend(words)
        while len(current) > max_words:
            chunks.append(" ".join(current[:max_words]))
            current = current[max_words - overlap:]
    if current:
        chunks.append(" ".join(current))
    return chunks


@dataclass
class Hit:
    chunk_id: int
    source_title: str
    source_ref: str | None
    text: str
    score: float


class KnowledgeBase:
    def __init__(self, db: Database):
        self.db = db

    def add_document(self, teacher_id: str, title: str, text: str, source_ref: str | None = None,
                     language: str | None = None) -> int:
        chunks = chunk_text(text)
        for c in chunks:
            self.db.execute("INSERT INTO kb_chunks (teacher_id, source_title, source_ref, language, text) "
                            "VALUES (?, ?, ?, ?, ?)", (teacher_id, title, source_ref, language, c))
        return len(chunks)

    def search(self, teacher_id: str, queries: list[str], k: int = 4, min_coverage: float = 0.34) -> list[Hit]:
        """Top chunks for any of the queries. A chunk must contain at least min_coverage of a query's words."""
        rows = self.db.all("SELECT id, source_title, source_ref, text FROM kb_chunks WHERE teacher_id = ?",
                           (teacher_id,))
        if not rows:
            return []
        docs = [tokenize(r["text"]) for r in rows]
        n = len(docs)
        avgdl = sum(len(d) for d in docs) / n or 1
        df = Counter(w for d in docs for w in set(d))
        k1, b = 1.5, 0.75
        best: dict[int, float] = {}
        for q in queries:
            q_terms = set(tokenize(q))
            for i, d in enumerate(docs):
                tf = Counter(d)
                if not q_terms or len(q_terms & tf.keys()) / len(q_terms) < min_coverage:
                    continue
                s = 0.0
                for w in q_terms:
                    if w in tf:
                        idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                        s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avgdl))
                best[i] = max(best.get(i, 0.0), s)
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        return [Hit(rows[i]["id"], rows[i]["source_title"], rows[i]["source_ref"], rows[i]["text"], s)
                for i, s in ranked[:k] if s > 0]

    def find_verified(self, teacher_id: str, question: str, threshold: float = 0.75):
        """A teacher-approved answer to (nearly) the same question, if one exists."""
        q = set(tokenize(question))
        if not q:
            return None
        best, best_score = None, 0.0
        for row in self.db.all("SELECT * FROM verified_answers WHERE teacher_id = ? AND active = 1", (teacher_id,)):
            v = set(tokenize(row["question"]))
            score = len(q & v) / len(q | v) if v else 0
            if score > best_score:
                best, best_score = row, score
        return best if best_score >= threshold else None
