"""Tests for BM25 module. Run standalone: python tests/test_bm25.py
Or via: python tests/run_all.py"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from user.bm25 import BM25Index, tokenize


class TokenizeTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(tokenize("Hello, world!"), ["hello", "world"])
        self.assertEqual(tokenize("Привет, мир!"), ["привет", "мир"])
        self.assertIn("любит", tokenize("Любит тёмный шоколад"))
        self.assertIn("шоколад", tokenize("Любит тёмный шоколад"))
        self.assertIn("favourite", tokenize("my favourite color is blue"))
        self.assertIn("color", tokenize("my favourite color is blue"))
        self.assertIn("blue", tokenize("my favourite color is blue"))

    def test_strips_stopwords(self):
        t = tokenize("Моё имя — Тимур")
        self.assertIn("имя", t)
        self.assertNotIn("твоё", t)
        self.assertNotIn("твой", t)

    def test_handles_hyphens_underscores(self):
        t = tokenize("open-source код для python-dev")
        self.assertIn("open-source", t)
        self.assertIn("python-dev", t)

    def test_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize(None), [])


class RussianStemmingTests(unittest.TestCase):
    def test_inflected_forms_match(self):
        idx = BM25Index()
        idx.add("a", "Живёт в Москве")
        idx.add("b", "Из Москвы")
        idx.add("c", "В Москву")
        idx.build()
        r = idx.topk("москва", k=3)
        ids = [i for i, _ in r]
        self.assertEqual(set(ids), {"a", "b", "c"}, f"expected all 3, got {ids}")


class EnglishStemmingTests(unittest.TestCase):
    def test_inflected_forms_match(self):
        idx = BM25Index()
        idx.add("a", "loves chocolate")
        idx.add("b", "loved chocolate")
        idx.add("c", "loving chocolate")
        idx.build()
        r = idx.topk("love chocolate", k=3)
        ids = [i for i, _ in r]
        self.assertIn("a", ids)
        self.assertIn("b", ids)
        self.assertIn("c", ids)


class IndexLifecycleTests(unittest.TestCase):
    def test_empty_index(self):
        idx = BM25Index()
        idx.build()
        self.assertEqual(idx.score("test"), [])
        self.assertEqual(idx.topk("test", k=3), [])
        self.assertEqual(len(idx), 0)

    def test_remove(self):
        idx = BM25Index()
        idx.add("a", "Любит тёмный шоколад")
        idx.add("b", "Живёт в Москве")
        idx.build()
        idx.remove("a")
        idx.build()
        self.assertEqual(idx.score("шоколад"), [], "expected empty after remove")
        self.assertNotIn("a", idx)

    def test_replace_existing_doc(self):
        idx = BM25Index()
        idx.add("a", "Любит тёмный шоколад")
        idx.build()
        idx.add("a", "Любит белый шоколад")
        idx.build()
        r = idx.topk("белый шоколад", k=1)
        self.assertEqual(r[0][0], "a")
        self.assertEqual(len(idx), 1)

    def test_auto_rebuild_on_score(self):
        idx = BM25Index()
        idx.add("x", "foo bar")
        idx.build()
        idx.add("y", "baz qux")  # без явного build
        r6 = idx.score("foo")
        self.assertEqual(r6[0][0], "x")
        r7 = idx.score("baz")
        self.assertEqual(r7[0][0], "y")

    def test_contains(self):
        idx = BM25Index()
        idx.add("x", "foo")
        self.assertIn("x", idx)
        self.assertNotIn("y", idx)

    def test_clear(self):
        idx = BM25Index()
        idx.add("x", "foo")
        idx.add("y", "bar")
        idx.build()
        idx.clear()
        idx.build()
        self.assertEqual(len(idx), 0)
        self.assertEqual(idx.score("foo"), [])


class RankingTests(unittest.TestCase):
    def test_basic_ranking(self):
        idx = BM25Index()
        idx.add("a", "Любит тёмный шоколад")
        idx.add("b", "Живёт в Москве")
        idx.add("c", "Работает программистом в Москве")
        idx.add("d", "Имеет кота по имени Барсик")
        idx.build()
        r = idx.topk("любимый шоколад", k=3)
        self.assertEqual(r[0][0], "a", f"expected 'a' on top, got {r[0]}")

    def test_multiple_matches(self):
        idx = BM25Index()
        idx.add("a", "Любит тёмный шоколад")
        idx.add("b", "Живёт в Москве")
        idx.add("c", "Работает программистом в Москве")
        idx.add("d", "Имеет кота по имени Барсик")
        idx.build()
        r = idx.topk("москва", k=3)
        ids = [i for i, _ in r]
        self.assertIn("b", ids)
        self.assertIn("c", ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
