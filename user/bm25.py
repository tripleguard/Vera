"""
BM25 (Best Matching 25) — in-memory реализация для гибридного поиска памяти.

Особенности:
- Без внешних зависимостей (только stdlib `re`, `math`, `collections.Counter`).
- Поддержка русского и английского (Unicode regex).
- Низкая аллокация: токенизация + IDF пересчитываются на `add()`,
  `score()` — O(N * |Q|) без аллокаций сверх необходимого.
- Параметры ранжирования: k1=1.5, b=0.75.

Размер корпуса ≤ 20 фактов + 10 полей профиля → score() за <1 мс.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Tuple


# Минимальная длина токена (фильтрует короткие служебные слова и шум).
_MIN_TOKEN_LEN = 3

# Токенизация: кириллица/латиница/цифры, дефис и подчёркивание — часть токена.
_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+(?:[-_][а-яёa-z0-9]+)*", re.IGNORECASE)

# Стоп-слова: короткие предлоги/союзы, которые не несут смысла.
# Список короткий — не выкидываем полезные термины.
_STOPWORDS = frozenset({
    "и", "в", "на", "с", "по", "для", "из", "это", "что", "как", "не",
    "the", "a", "an", "of", "to", "in", "on", "at", "is", "are", "be",
    "этот", "эта", "это", "эти", "тот", "та", "то", "те",
    "мой", "моя", "моё", "мои", "твой", "твоя", "твоё", "свой", "своя",
})

# Типичные окончания русских существительных/прилагательных/глаголов (от длинных к коротким).
# Стрипаем жадно: самое длинное совпадение, если после стрипа остаётся ≥ 3 символов.
_RU_ENDINGS = (
    "ями", "ами", "ях", "ах", "ев", "ов", "ой", "ей", "ым", "им",
    "ую", "юю", "ого", "его", "ому", "ему", "ыми", "ими",
    "а", "я", "о", "е", "у", "ю", "ы", "и", "й",
)

# Типичные английские суффиксы.
_EN_ENDINGS = (
    "ies", "ied", "ing", "ers", "est", "ies",
    "ied", "ies",
    "ed", "er", "es", "ly", "s",
)


def _light_stem(word: str) -> str:
    """
    Лёгкий стеммер: пытается отрезать типичное окончание.
    Возвращает исходное слово, если после стрипа остаётся < 3 символов.
    """
    if len(word) <= 4:
        return word
    # Сначала пробуем кириллические окончания
    if any("а" <= c <= "я" or c == "ё" for c in word):
        for end in _RU_ENDINGS:
            if word.endswith(end) and len(word) - len(end) >= 3:
                return word[: -len(end)]
    else:
        for end in _EN_ENDINGS:
            if word.endswith(end) and len(word) - len(end) >= 3:
                return word[: -len(end)]
    return word


def tokenize(text: str) -> List[str]:
    """
    Разбивает текст на токены: lowercase, min длина, без стоп-слов.
    Дополнительно: к каждому токену ≥5 символов добавляет его стем-форму
    для устойчивости к русским/английским словоизменениям
    («Москва» / «Москве» / «Москвы» → общий стем «москв»).
    """
    if not text:
        return []
    out: List[str] = []
    seen: set = set()
    for m in _TOKEN_RE.finditer(text.lower()):
        t = m.group(0)
        if len(t) < _MIN_TOKEN_LEN or t in _STOPWORDS:
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
        # Добавляем стем, если он отличается от оригинала
        if len(t) >= 5:
            stem = _light_stem(t)
            if stem != t and stem not in seen and len(stem) >= _MIN_TOKEN_LEN:
                seen.add(stem)
                out.append(stem)
    return out


class BM25Index:
    """
    BM25Okapi индекс. Использование:
        idx = BM25Index()
        idx.add("f1", "Любит тёмный шоколад")
        idx.add("f2", "Живёт в Москве")
        idx.build()  # обязательно после добавления, пересчитывает IDF
        top = idx.topk("любимый шоколад", k=3)  # [(id, score), ...]
    """

    __slots__ = ("_k1", "_b", "_docs", "_doc_lens", "_avgdl",
                 "_idf", "_built", "_doc_ids")

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs: Dict[str, List[str]] = {}      # doc_id -> tokens
        self._doc_lens: Dict[str, int] = {}        # doc_id -> |tokens|
        self._doc_ids: List[str] = []              # порядок добавления
        self._avgdl: float = 0.0
        self._idf: Dict[str, float] = {}
        self._built: bool = False

    def add(self, doc_id: str, text: str) -> None:
        """Добавляет документ. Аннулирует предыдущий `build()`."""
        tokens = tokenize(text)
        if doc_id in self._docs:
            # Замена существующего документа.
            self._doc_lens[doc_id] = len(tokens)
        else:
            self._doc_ids.append(doc_id)
            self._doc_lens[doc_id] = len(tokens)
        self._docs[doc_id] = tokens
        self._built = False

    def remove(self, doc_id: str) -> None:
        if doc_id in self._docs:
            del self._docs[doc_id]
            del self._doc_lens[doc_id]
            self._doc_ids = [d for d in self._doc_ids if d != doc_id]
            self._built = False

    def clear(self) -> None:
        self._docs.clear()
        self._doc_lens.clear()
        self._doc_ids.clear()
        self._avgdl = 0.0
        self._idf.clear()
        self._built = False

    def build(self) -> None:
        """Пересчитывает avgdl и IDF по корпусу. Вызывайте после всех `add()`."""
        n = len(self._docs)
        if n == 0:
            self._avgdl = 0.0
            self._idf = {}
            self._built = True
            return

        # Средняя длина документа.
        total = sum(self._doc_lens.values())
        self._avgdl = total / n

        # Document frequency для каждого токена.
        df: Counter = Counter()
        for tokens in self._docs.values():
            for t in set(tokens):
                df[t] += 1

        # IDF по формуле Robertson–Sparck Jones (с +1, чтобы не уходить в -∞).
        self._idf = {
            t: math.log((n - dfi + 0.5) / (dfi + 0.5) + 1.0)
            for t, dfi in df.items()
        }
        self._built = True

    def score(self, query: str) -> List[Tuple[str, float]]:
        """
        BM25Okapi по всем документам. Возвращает [(doc_id, score), ...]
        отсортированный по убыванию score. score >= 0.
        """
        if not self._built:
            self.build()
        q_tokens = tokenize(query)
        if not q_tokens or not self._docs:
            return []
        k1, b = self._k1, self._b
        avgdl = self._avgdl or 1.0
        results: List[Tuple[str, float]] = []
        for doc_id, doc_tokens in self._docs.items():
            if not doc_tokens:
                continue
            dl = self._doc_lens[doc_id]
            tf_map = Counter(doc_tokens)
            s = 0.0
            for qt in q_tokens:
                if qt not in self._idf:
                    continue
                tf = tf_map.get(qt, 0)
                if tf == 0:
                    continue
                idf = self._idf[qt]
                denom = tf + k1 * (1.0 - b + b * dl / avgdl)
                s += idf * (tf * (k1 + 1.0)) / denom
            if s > 0.0:
                results.append((doc_id, s))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def topk(self, query: str, k: int = 3) -> List[Tuple[str, float]]:
        """Top-k результатов. score не нормализованы — нормируйте сами (max → 1.0)."""
        return self.score(query)[:k]

    def __len__(self) -> int:
        return len(self._docs)

    def __contains__(self, doc_id: str) -> bool:
        return doc_id in self._docs
