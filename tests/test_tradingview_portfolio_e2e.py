import os
import unittest


class TradingViewPortfolioE2ETest(unittest.TestCase):
    def test_live_watchlist_fetch_matches_expected_public_holdings(self):
        if os.environ.get("RUN_TRADINGVIEW_E2E") != "1":
            self.skipTest("set RUN_TRADINGVIEW_E2E=1 to fetch the live TradingView watchlist")

        from fetch_haohuang_portfolio import monitor as portfolio_monitor

        snapshot = portfolio_monitor.fetch_watchlist(
            "https://www.tradingview.com/watchlists/326877343/"
        )

        self.assertEqual(snapshot.name, "portfolio")
        self.assertEqual(
            snapshot.holdings,
            ["CBOE:DRAM", "NASDAQ:MU", "NYSE:ATI", "NYSE:CRS", "NASDAQ:QCOM"],
        )


if __name__ == "__main__":
    unittest.main()
