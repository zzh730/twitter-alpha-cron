import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path


class PortfolioMonitorTest(unittest.TestCase):
    def test_parse_tradingview_watchlist_ignores_section_labels(self):
        from fetch_haohuang_portfolio import monitor as portfolio_monitor

        html = """
        <script>
        window.initData = {
          "sharedWatchlist": {
            "list": {"id":326877343,"name":"portfolio","symbols":["###CPU","NASDAQ:MU","###SHORT TERM","NYSE:CRS"],"modified":"2026-04-25T18:37:19Z"}
          }
        };
        </script>
        """

        watchlist = portfolio_monitor.parse_watchlist_html(html)

        self.assertEqual(watchlist.name, "portfolio")
        self.assertEqual(watchlist.holdings, ["NASDAQ:MU", "NYSE:CRS"])

    def test_compare_snapshots_reports_added_and_removed_symbols(self):
        from fetch_haohuang_portfolio import monitor as portfolio_monitor

        changes = portfolio_monitor.compare_holdings(
            previous=["NASDAQ:MU", "NYSE:ATI"],
            current=["NASDAQ:MU", "NYSE:CRS"],
        )

        self.assertEqual(changes.added, ["NYSE:CRS"])
        self.assertEqual(changes.removed, ["NYSE:ATI"])
        self.assertEqual(changes.unchanged, ["NASDAQ:MU"])
        self.assertTrue(changes.has_changes)

    def test_first_run_saves_baseline_and_reports_current_holdings(self):
        from fetch_haohuang_portfolio import monitor as portfolio_monitor

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "portfolio_snapshot.json"
            watchlist = portfolio_monitor.WatchlistSnapshot(
                id=326877343,
                name="portfolio",
                modified="2026-04-25T18:37:19Z",
                holdings=["NASDAQ:MU", "NYSE:CRS"],
                fetched_at="2026-04-25T19:00:00+00:00",
            )

            result = portfolio_monitor.update_snapshot(snapshot_path, watchlist)

            self.assertTrue(result.is_baseline)
            self.assertIn("Baseline", result.markdown)
            self.assertIn("NASDAQ:MU", result.markdown)
            self.assertIn("NYSE:CRS", result.markdown)
            saved = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["holdings"], ["NASDAQ:MU", "NYSE:CRS"])

    def test_no_change_report_is_not_alertable(self):
        from fetch_haohuang_portfolio import monitor as portfolio_monitor

        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "portfolio_snapshot.json"
            snapshot_path.write_text(
                json.dumps(
                    {
                        "id": 326877343,
                        "name": "portfolio",
                        "modified": "old",
                        "holdings": ["NASDAQ:MU", "NYSE:CRS"],
                        "fetched_at": "2026-04-25T18:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            watchlist = portfolio_monitor.WatchlistSnapshot(
                id=326877343,
                name="portfolio",
                modified="new",
                holdings=["NASDAQ:MU", "NYSE:CRS"],
                fetched_at="2026-04-25T19:00:00+00:00",
            )

            result = portfolio_monitor.update_snapshot(snapshot_path, watchlist)

            self.assertFalse(result.is_baseline)
            self.assertFalse(result.should_alert)
            self.assertIn("No position changes", result.markdown)

    def test_market_guard_uses_calendar_open_and_closed_times(self):
        from fetch_haohuang_portfolio import monitor as portfolio_monitor

        open_time = dt.datetime(2026, 4, 24, 14, 0, tzinfo=dt.timezone.utc)
        closed_time = dt.datetime(2026, 4, 25, 14, 0, tzinfo=dt.timezone.utc)
        calendar = portfolio_monitor.StaticMarketCalendar(
            sessions=[
                portfolio_monitor.MarketSession(
                    open_at=dt.datetime(2026, 4, 24, 13, 30, tzinfo=dt.timezone.utc),
                    close_at=dt.datetime(2026, 4, 24, 20, 0, tzinfo=dt.timezone.utc),
                )
            ]
        )

        self.assertTrue(portfolio_monitor.is_market_open(open_time, calendar))
        self.assertFalse(portfolio_monitor.is_market_open(closed_time, calendar))

    def test_builtin_nyse_calendar_skips_holidays_and_handles_early_close(self):
        from fetch_haohuang_portfolio import monitor as portfolio_monitor

        calendar = portfolio_monitor.BuiltinNyseCalendar()
        good_friday = dt.datetime(2026, 4, 3, 15, 0, tzinfo=dt.timezone.utc)
        early_close_open = dt.datetime(2026, 11, 27, 17, 30, tzinfo=dt.timezone.utc)
        early_close_closed = dt.datetime(2026, 11, 27, 18, 30, tzinfo=dt.timezone.utc)

        self.assertFalse(portfolio_monitor.is_market_open(good_friday, calendar))
        self.assertTrue(portfolio_monitor.is_market_open(early_close_open, calendar))
        self.assertFalse(portfolio_monitor.is_market_open(early_close_closed, calendar))


if __name__ == "__main__":
    unittest.main()
