import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import collector  # noqa: E402
from storage import SeenStore  # noqa: E402


def tweet(tweet_id, handle="source"):
    return {
        "id": str(tweet_id),
        "url": f"https://x.com/{handle}/status/{tweet_id}",
        "text": f"$NVDA earnings update {tweet_id}",
        "createdAt": "2026-05-24T12:00:00Z",
        "retweetCount": 1,
        "replyCount": 2,
        "likeCount": 3,
        "viewCount": 4,
        "lang": "en",
        "author": {"userName": handle, "name": handle},
    }


class TwitterApiIoTest(unittest.TestCase):
    def test_list_pull_bootstraps_without_returning_old_tweets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SeenStore(str(Path(tmp) / "seen.db"))
            state = collector.PollState(str(Path(tmp) / "state.json"))

            with patch.dict(os.environ, {"TWITTERAPI_IO_KEY": "test-key"}):
                with patch.object(
                    collector.TwitterApiIoClient,
                    "list_timeline",
                    return_value=collector.TwitterApiPage(
                        tweets=[tweet(103), tweet(102), tweet(101)],
                        next_cursor="next",
                    ),
                ):
                    candidates = collector._collect_twitterapi_io_candidates(
                        {
                            "twitterapi_io": {
                                "list_id": "1616825136690397187",
                                "bootstrap_pages": 1,
                                "max_pages_per_run": 3,
                            }
                        },
                        store,
                        state,
                        "2026-05-24T12:00:00+00:00",
                    )

            self.assertEqual(candidates, [])
            self.assertTrue(store.is_seen("103"))
            self.assertEqual(state.get_high_water("list:1616825136690397187"), "103")
            store.close()

    def test_list_pull_paginates_until_seen_tweet_then_returns_only_new_tweets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SeenStore(str(Path(tmp) / "seen.db"))
            state = collector.PollState(str(Path(tmp) / "state.json"))
            state.set_high_water("list:1616825136690397187", "100")
            store.mark_seen("100", "https://x.com/source/status/100", "following", "then")

            pages = [
                collector.TwitterApiPage(tweets=[tweet(104), tweet(103)], next_cursor="p2"),
                collector.TwitterApiPage(tweets=[tweet(102), tweet(100)], next_cursor="p3"),
            ]

            def fake_list_timeline(list_id, cursor=""):
                self.assertEqual(list_id, "1616825136690397187")
                return pages.pop(0)

            with patch.dict(os.environ, {"TWITTERAPI_IO_KEY": "test-key"}):
                with patch.object(
                    collector.TwitterApiIoClient,
                    "list_timeline",
                    side_effect=fake_list_timeline,
                ):
                    candidates = collector._collect_twitterapi_io_candidates(
                        {
                            "twitterapi_io": {
                                "list_id": "1616825136690397187",
                                "max_pages_per_run": 3,
                            }
                        },
                        store,
                        state,
                        "2026-05-24T12:05:00+00:00",
                    )

            self.assertEqual([c.tweet_id for c in candidates], ["102", "103", "104"])
            self.assertEqual(state.get_high_water("list:1616825136690397187"), "104")
            self.assertTrue(store.is_seen("102"))
            store.close()

    def test_run_reports_new_twitterapi_tweet_even_after_collection_marks_id_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                """
                {
                  "twitterapi_io": {
                    "list_id": "1616825136690397187",
                    "max_pages_per_run": 1,
                    "bootstrap_pages": 1
                  },
                  "dedup_db": "%s",
                  "poll_state_path": "%s",
                  "max_new_items": 5
                }
                """
                % (str(Path(tmp) / "seen.db"), str(Path(tmp) / "poll_state.json")),
                encoding="utf-8",
            )
            state = collector.PollState(str(Path(tmp) / "poll_state.json"))
            state.set_high_water("list:1616825136690397187", "100")

            with patch.dict(os.environ, {"TWITTERAPI_IO_KEY": "test-key"}):
                with patch.object(
                    collector.TwitterApiIoClient,
                    "list_timeline",
                    return_value=collector.TwitterApiPage(tweets=[tweet(101, "trader")], next_cursor=""),
                ):
                    with patch.object(
                        collector,
                        "_summarize_tweet_cn",
                        return_value="NVDA 财报更新强化 AI 交易主线，关注盈利预期变化。",
                    ):
                        items, md = collector.run(str(config_path))

            self.assertEqual([item["tweet_id"] for item in items], ["101"])
            self.assertEqual(items[0]["chinese_summary"], "NVDA 财报更新强化 AI 交易主线，关注盈利预期变化。")
            self.assertIn("NVDA 财报更新强化 AI 交易主线", md)
            self.assertIn("https://x.com/trader/status/101", md)


if __name__ == "__main__":
    unittest.main()
