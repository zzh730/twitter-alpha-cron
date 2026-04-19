import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import collector  # noqa: E402


class ReportFormatTest(unittest.TestCase):
    def test_format_markdown_highlights_target_accounts_in_chinese(self):
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
            },
        ]

        md = collector._format_markdown(items, ["zerohedge"])

        self.assertIn("# X 交易监控摘要", md)
        self.assertIn("## 重点观察账户", md)
        self.assertIn("- 本轮整体观点：", md)
        self.assertIn("- 交易/市场解读：", md)
        self.assertIn("## 其他市场推文", md)
        self.assertLess(md.index("## 重点观察账户"), md.index("## 其他市场推文"))

    def test_format_markdown_empty_state_is_chinese(self):
        self.assertEqual(collector._format_markdown([], []), "本轮去重后没有新的推文。")


if __name__ == "__main__":
    unittest.main()
