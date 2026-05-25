import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import collector  # noqa: E402


class ReportFormatTest(unittest.TestCase):
    def test_format_markdown_outputs_only_chinese_summary_and_url_per_tweet(self):
        items = [
            {
                "url": "https://x.com/zerohedge/status/111",
                "tweet_id": "111",
                "source": "following",
                "author": "zerohedge",
                "screen_name": "zerohedge",
                "created_at": "2026-04-18T01:02:03Z",
                "text": "Oil breakout and risk assets bid",
                "likes": 120,
                "retweets": 35,
                "views": 5600,
                "replies_count": 12,
                "is_note_tweet": False,
                "lang": "en",
                "quote": None,
                "sentiment": "bullish",
                "sentiment_score": 3,
                "tickers": ["XOM"],
                "macro_tags": ["energy"],
                "chinese_summary": "原油突破带动风险资产走强，重点关注 XOM 等能源股的顺势机会。",
            },
            {
                "url": "https://x.com/news/status/222",
                "tweet_id": "222",
                "source": "feed",
                "author": "news",
                "screen_name": "news",
                "created_at": "2026-04-18T02:03:04Z",
                "text": "CPI cooler than expected",
                "likes": 88,
                "retweets": 17,
                "views": 4300,
                "replies_count": 4,
                "is_note_tweet": False,
                "lang": "en",
                "quote": None,
                "sentiment": "neutral",
                "sentiment_score": 0,
                "tickers": [],
                "macro_tags": ["inflation"],
                "chinese_summary": "CPI 低于预期，可能缓和利率压力，对风险资产偏正面。",
            },
        ]

        md = collector._format_markdown(items, ["zerohedge"])

        self.assertIn("# X 交易监控摘要", md)
        self.assertIn("1. 原油突破带动风险资产走强", md)
        self.assertIn("https://x.com/zerohedge/status/111", md)
        self.assertIn("2. CPI 低于预期", md)
        self.assertNotIn("情绪判断", md)
        self.assertNotIn("互动数据", md)
        self.assertNotIn("原文：", md)
        self.assertNotIn("重点观察账户", md)

    def test_format_markdown_empty_state_is_chinese(self):
        self.assertEqual(collector._format_markdown([], []), "本轮去重后没有新的推文。")


if __name__ == "__main__":
    unittest.main()
