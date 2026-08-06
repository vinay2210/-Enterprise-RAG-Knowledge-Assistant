import unittest

from app.rag import vector_store


class VectorStoreTests(unittest.TestCase):
    def test_query_returns_empty_hits_when_embedder_fails(self):
        def raise_embedder_error(*args, **kwargs):
            raise RuntimeError("embedding unavailable")

        original_get_embedder = vector_store.get_embedder
        vector_store.get_embedder = raise_embedder_error
        try:
            self.assertEqual(vector_store.query("hello", top_k=3), [])
        finally:
            vector_store.get_embedder = original_get_embedder


if __name__ == "__main__":
    unittest.main()
