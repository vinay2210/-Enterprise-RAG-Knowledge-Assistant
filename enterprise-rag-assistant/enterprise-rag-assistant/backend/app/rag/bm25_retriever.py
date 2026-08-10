"""
In-Memory BM25 Sparse Keyword Search Indexer.

Provides fast BM25 (Okapi) exact keyword retrieval to complement dense vector
embeddings, ensuring technical IDs, codes, page titles, dates, and exact terms
in multi-page (3 to 500+ pages) documents are retrieved accurately.
"""
import math
import re
from collections import Counter
from threading import Lock
from app.utils.logger import logger


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.lock = Lock()
        # chunk_id -> dict with metadata & text
        self.corpus: dict[str, dict] = {}
        # chunk_id -> list of tokens
        self.doc_tokens: dict[str, list[str]] = {}
        # chunk_id -> doc length
        self.doc_lens: dict[str, int] = {}
        # token -> set of chunk_ids containing token
        self.df: dict[str, set[str]] = {}
        self.total_docs = 0
        self.avg_doc_len = 0.0

    def _tokenize(self, text: str) -> list[str]:
        if not text:
            return []
        return re.findall(r"\b[a-zA-Z0-9_]+\b", text.lower())

    def _recalculate_stats(self):
        self.total_docs = len(self.doc_lens)
        if self.total_docs > 0:
            self.avg_doc_len = sum(self.doc_lens.values()) / float(self.total_docs)
        else:
            self.avg_doc_len = 0.0

    def add_chunks(self, chunk_dicts: list[dict]):
        """chunk_dicts: list of dicts with keys: vector_id, text, parent_text, document_id, file_name, page_number, chunk_index"""
        with self.lock:
            for item in chunk_dicts:
                cid = item["vector_id"]
                full_text = f"{item.get('text', '')} {item.get('parent_text', '')}"
                tokens = self._tokenize(full_text)

                # Remove old token references if updating
                if cid in self.doc_tokens:
                    old_tokens = set(self.doc_tokens[cid])
                    for t in old_tokens:
                        if t in self.df:
                            self.df[t].discard(cid)

                self.corpus[cid] = item
                self.doc_tokens[cid] = tokens
                self.doc_lens[cid] = len(tokens)

                for token in set(tokens):
                    if token not in self.df:
                        self.df[token] = set()
                    self.df[token].add(cid)

            self._recalculate_stats()
            logger.debug(f"BM25 index updated with {len(chunk_dicts)} chunks. Total docs: {self.total_docs}")

    def delete_document(self, document_id: str):
        with self.lock:
            to_delete = [cid for cid, item in self.corpus.items() if item.get("document_id") == document_id]
            for cid in to_delete:
                tokens = set(self.doc_tokens.get(cid, []))
                for t in tokens:
                    if t in self.df:
                        self.df[t].discard(cid)

                self.corpus.pop(cid, None)
                self.doc_tokens.pop(cid, None)
                self.doc_lens.pop(cid, None)

            self._recalculate_stats()
            logger.info(f"BM25 index deleted {len(to_delete)} chunks for document {document_id}")

    def query(self, query_text: str, top_k: int = 10, file_names: list[str] | None = None) -> list[dict]:
        with self.lock:
            if not self.corpus or self.total_docs == 0:
                return []

            q_tokens = self._tokenize(query_text)
            if not q_tokens:
                return []

            # Filter candidate docs if file_names provided
            if file_names:
                file_set = set(file_names)
                candidate_ids = [cid for cid, item in self.corpus.items() if item.get("file_name") in file_set]
            else:
                candidate_ids = list(self.corpus.keys())

            if not candidate_ids:
                return []

            scores: dict[str, float] = {}

            for q_token in q_tokens:
                matching_docs = self.df.get(q_token, set())
                n_q = len(matching_docs)
                if n_q == 0:
                    continue

                # Okapi BM25 IDF
                idf = math.log((self.total_docs - n_q + 0.5) / (n_q + 0.5) + 1.0)
                if idf <= 0:
                    idf = 0.01

                for cid in candidate_ids:
                    if cid not in matching_docs:
                        continue
                    tokens = self.doc_tokens[cid]
                    f_q = tokens.count(q_token)
                    if f_q == 0:
                        continue

                    doc_len = self.doc_lens[cid]
                    denom = f_q + self.k1 * (1.0 - self.b + self.b * (doc_len / (self.avg_doc_len or 1.0)))
                    score = idf * (f_q * (self.k1 + 1.0)) / denom
                    scores[cid] = scores.get(cid, 0.0) + score

            if not scores:
                return []

            sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)[:top_k]

            results = []
            for cid in sorted_ids:
                item = dict(self.corpus[cid])
                item["score"] = round(scores[cid], 4)
                item["retrieval_source"] = "bm25"
                results.append(item)

            return results


_global_bm25 = BM25Index()


def get_bm25_index() -> BM25Index:
    return _global_bm25
