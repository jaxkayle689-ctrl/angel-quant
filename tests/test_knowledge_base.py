import json
import tempfile
import unittest
from pathlib import Path

from binance_quant.knowledge_base import KnowledgeBase, Segment, build_chunks


class KnowledgeBaseTest(unittest.TestCase):
    def fixture(self, directory: str) -> Path:
        path = Path(directory) / "transcript.json"
        path.write_text(json.dumps({"segments": [
            {"start": 10, "end": 18, "text": "顶分型由三根经过包含处理的K线组成，中间K线高点最高。"},
            {"start": 18, "end": 26, "text": "底分型中间K线低点最低，用于识别潜在转折。"},
            {"start": 30, "end": 40, "text": "笔连接相邻的顶分型和底分型，并满足独立K线要求。"},
            {"start": 42, "end": 55, "text": "连续三笔重叠的价格区间可以帮助识别中枢。"},
        ]}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_chunking_preserves_time_range_and_overlap(self):
        chunks = build_chunks([Segment(0, 2, "顶分型"), Segment(2, 4, "底分型"), Segment(4, 6, "中枢")], target_chars=4, overlap=1)
        self.assertEqual(chunks[0]["start"], 0)
        self.assertGreaterEqual(chunks[0]["end"], 4)
        self.assertIn("中枢", chunks[1]["text"])

    def test_index_is_idempotent_and_query_returns_timestamp_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = KnowledgeBase(Path(directory), self.fixture(directory))
            first = kb.status()
            kb.ensure_index()
            self.assertEqual(kb.status()["chunk_count"], first["chunk_count"])
            answer = kb.query("顶分型是什么")
            self.assertTrue(answer["citations"])
            self.assertEqual(answer["citations"][0]["timestamp"], "00:10")
            self.assertIn("t=10s", answer["citations"][0]["url"])
            self.assertEqual(kb.status()["query_count"], 1)

    def test_rejects_empty_question(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = KnowledgeBase(Path(directory), self.fixture(directory))
            with self.assertRaisesRegex(ValueError, "至少 2 个字符"):
                kb.query(" ")


if __name__ == "__main__":
    unittest.main()
