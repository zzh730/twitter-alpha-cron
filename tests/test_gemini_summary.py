import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import collector  # noqa: E402


class FakeGenai:
    def __init__(self, client):
        self.client = client
        self.calls = []

    def Client(self, api_key):
        self.calls.append(api_key)
        return self.client


class GeminiSummaryTest(unittest.TestCase):
    def test_summary_uses_google_genai_sdk_client(self):
        response = MagicMock()
        response.text = "NVDA 上调指引，强化 AI 需求主线，利好半导体链。"
        client = MagicMock()
        client.models.generate_content.return_value = response
        fake_genai = FakeGenai(client)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}):
            with patch.object(collector, "genai", fake_genai):
                summary = collector._summarize_tweet_cn(
                    "$NVDA raises guidance on AI demand",
                    "https://x.com/a/status/1",
                    {"tickers": ["NVDA"], "macro_tags": []},
                    {"summary": {"model": "gemini-3-flash-preview"}},
                )

        self.assertEqual(summary, "NVDA 上调指引，强化 AI 需求主线，利好半导体链。")
        self.assertEqual(fake_genai.calls, ["test-gemini-key"])
        client.models.generate_content.assert_called_once()


if __name__ == "__main__":
    unittest.main()
