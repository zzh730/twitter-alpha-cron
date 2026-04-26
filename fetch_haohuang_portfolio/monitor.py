import argparse
import datetime as dt
import json
import re
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Sequence
from zoneinfo import ZoneInfo


DEFAULT_WATCHLIST_URL = "https://www.tradingview.com/watchlists/326877343/"
DEFAULT_SNAPSHOT_PATH = "./data/portfolio_snapshot.json"
DEFAULT_TIMEZONE = "America/New_York"


@dataclass
class WatchlistSnapshot:
    id: int
    name: str
    modified: str
    holdings: List[str]
    fetched_at: str


@dataclass
class PositionChanges:
    added: List[str]
    removed: List[str]
    unchanged: List[str]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed)


@dataclass
class SnapshotUpdateResult:
    is_baseline: bool
    changes: PositionChanges
    current: WatchlistSnapshot
    previous: Optional[WatchlistSnapshot]
    markdown: str

    @property
    def should_alert(self) -> bool:
        return self.is_baseline or self.changes.has_changes


@dataclass
class MarketSession:
    open_at: dt.datetime
    close_at: dt.datetime


class StaticMarketCalendar:
    def __init__(self, sessions: Sequence[MarketSession]):
        self.sessions = list(sessions)

    def sessions_for(self, day: dt.date) -> List[MarketSession]:
        return [
            session
            for session in self.sessions
            if session.open_at.date() <= day <= session.close_at.date()
        ]


class BuiltinNyseCalendar:
    def __init__(self, timezone: str = DEFAULT_TIMEZONE):
        self.timezone = ZoneInfo(timezone)

    def sessions_for(self, day: dt.date) -> List[MarketSession]:
        if day.weekday() >= 5 or day in self._market_holidays(day.year):
            return []

        close_hour = 13 if day in self._early_close_days(day.year) else 16
        open_local = dt.datetime.combine(day, dt.time(9, 30), tzinfo=self.timezone)
        close_local = dt.datetime.combine(day, dt.time(close_hour, 0), tzinfo=self.timezone)
        return [
            MarketSession(
                open_at=open_local.astimezone(dt.timezone.utc),
                close_at=close_local.astimezone(dt.timezone.utc),
            )
        ]

    def _market_holidays(self, year: int) -> set[dt.date]:
        return {
            self._observed_fixed(year, 1, 1),
            self._nth_weekday(year, 1, 0, 3),
            self._nth_weekday(year, 2, 0, 3),
            self._good_friday(year),
            self._last_weekday(year, 5, 0),
            self._observed_fixed(year, 6, 19),
            self._observed_fixed(year, 7, 4),
            self._nth_weekday(year, 9, 0, 1),
            self._nth_weekday(year, 11, 3, 4),
            self._observed_fixed(year, 12, 25),
        }

    def _early_close_days(self, year: int) -> set[dt.date]:
        thanksgiving = self._nth_weekday(year, 11, 3, 4)
        christmas_eve = dt.date(year, 12, 24)
        july_third = dt.date(year, 7, 3)
        return {
            day
            for day in [thanksgiving + dt.timedelta(days=1), christmas_eve, july_third]
            if day.weekday() < 5 and day not in self._market_holidays(year)
        }

    @staticmethod
    def _observed_fixed(year: int, month: int, day: int) -> dt.date:
        actual = dt.date(year, month, day)
        if actual.weekday() == 5:
            return actual - dt.timedelta(days=1)
        if actual.weekday() == 6:
            return actual + dt.timedelta(days=1)
        return actual

    @staticmethod
    def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> dt.date:
        current = dt.date(year, month, 1)
        while current.weekday() != weekday:
            current += dt.timedelta(days=1)
        return current + dt.timedelta(days=7 * (nth - 1))

    @staticmethod
    def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
        next_month = dt.date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        current = next_month - dt.timedelta(days=1)
        while current.weekday() != weekday:
            current -= dt.timedelta(days=1)
        return current

    @staticmethod
    def _good_friday(year: int) -> dt.date:
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return dt.date(year, month, day) - dt.timedelta(days=2)


class NyseMarketCalendar:
    def __init__(self, timezone: str = DEFAULT_TIMEZONE):
        self.timezone = timezone
        try:
            import pandas_market_calendars as market_calendars
        except ImportError:
            self._fallback = BuiltinNyseCalendar(timezone)
            self._calendar = None
            return
        self._calendar = market_calendars.get_calendar("NYSE")
        self._fallback = None

    def sessions_for(self, day: dt.date) -> List[MarketSession]:
        if self._fallback is not None:
            return self._fallback.sessions_for(day)

        schedule = self._calendar.schedule(start_date=day.isoformat(), end_date=day.isoformat())
        sessions: List[MarketSession] = []
        for _, row in schedule.iterrows():
            open_at = row["market_open"].to_pydatetime()
            close_at = row["market_close"].to_pydatetime()
            sessions.append(MarketSession(open_at=open_at, close_at=close_at))
        return sessions


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _extract_json_object(text: str, object_start: int) -> str:
    depth = 0
    in_string = False
    escaped = False

    for index in range(object_start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[object_start : index + 1]

    raise ValueError("Could not find the end of the TradingView watchlist payload.")


def parse_watchlist_html(html: str, fetched_at: Optional[dt.datetime] = None) -> WatchlistSnapshot:
    marker = '"sharedWatchlist"'
    marker_index = html.find(marker)
    if marker_index < 0:
        raise ValueError("TradingView watchlist payload was not found.")

    list_match = re.search(r'"list"\s*:\s*\{', html[marker_index:])
    if not list_match:
        raise ValueError("TradingView watchlist list payload was not found.")

    object_start = marker_index + list_match.end() - 1
    payload = json.loads(_extract_json_object(html, object_start))
    symbols = payload.get("symbols", [])
    holdings = [symbol for symbol in symbols if isinstance(symbol, str) and not symbol.startswith("###")]
    fetched = fetched_at or _now_utc()

    return WatchlistSnapshot(
        id=int(payload.get("id", 0)),
        name=str(payload.get("name", "")),
        modified=str(payload.get("modified", "")),
        holdings=holdings,
        fetched_at=fetched.isoformat(),
    )


def fetch_watchlist(url: str = DEFAULT_WATCHLIST_URL, timeout: int = 20) -> WatchlistSnapshot:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="ignore")
    return parse_watchlist_html(html)


def compare_holdings(previous: Sequence[str], current: Sequence[str]) -> PositionChanges:
    previous_set = set(previous)
    current_set = set(current)
    return PositionChanges(
        added=[symbol for symbol in current if symbol not in previous_set],
        removed=[symbol for symbol in previous if symbol not in current_set],
        unchanged=[symbol for symbol in current if symbol in previous_set],
    )


def load_snapshot(path: Path) -> Optional[WatchlistSnapshot]:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return WatchlistSnapshot(
        id=int(data.get("id", 0)),
        name=str(data.get("name", "")),
        modified=str(data.get("modified", "")),
        holdings=list(data.get("holdings", [])),
        fetched_at=str(data.get("fetched_at", "")),
    )


def save_snapshot(path: Path, snapshot: WatchlistSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")


def _format_symbol_list(symbols: Sequence[str]) -> str:
    return ", ".join(symbols) if symbols else "None"


def _format_markdown(
    current: WatchlistSnapshot,
    previous: Optional[WatchlistSnapshot],
    changes: PositionChanges,
) -> str:
    lines = [
        "# TradingView Portfolio Monitor",
        "",
        f"- Watchlist: {current.name or 'unknown'} ({current.id})",
        f"- TradingView modified: {current.modified or 'unknown'}",
        f"- Fetched at: {current.fetched_at}",
        f"- Current holdings: {len(current.holdings)}",
        "",
    ]

    if previous is None:
        lines.extend(
            [
                "## Baseline",
                "",
                "First run saved the current TradingView holdings as the comparison baseline.",
                "",
                f"- Holdings: {_format_symbol_list(current.holdings)}",
            ]
        )
    elif changes.has_changes:
        lines.extend(
            [
                "## Position Changes",
                "",
                f"- Added: {_format_symbol_list(changes.added)}",
                f"- Removed: {_format_symbol_list(changes.removed)}",
                f"- Unchanged: {len(changes.unchanged)}",
            ]
        )
    else:
        lines.extend(
            [
                "## No position changes",
                "",
                f"- Holdings: {_format_symbol_list(current.holdings)}",
            ]
        )

    return "\n".join(lines)


def update_snapshot(snapshot_path: Path, current: WatchlistSnapshot) -> SnapshotUpdateResult:
    previous = load_snapshot(snapshot_path)
    changes = compare_holdings(previous.holdings if previous else [], current.holdings)
    save_snapshot(snapshot_path, current)
    return SnapshotUpdateResult(
        is_baseline=previous is None,
        changes=changes,
        current=current,
        previous=previous,
        markdown=_format_markdown(current=current, previous=previous, changes=changes),
    )


def is_market_open(now: dt.datetime, calendar) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now_utc = now.astimezone(dt.timezone.utc)
    local_day = now_utc.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
    return any(session.open_at <= now_utc < session.close_at for session in calendar.sessions_for(local_day))


def _load_config(path: str) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    raw = config_path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Config parsing failed. Use JSON format inside .yaml.") from exc


def run(config_path: str = "config.yaml", force: bool = False) -> SnapshotUpdateResult:
    config = _load_config(config_path)
    portfolio_config = config.get("portfolio_monitor", {})
    url = portfolio_config.get("watchlist_url", DEFAULT_WATCHLIST_URL)
    snapshot_path = Path(portfolio_config.get("snapshot_path", DEFAULT_SNAPSHOT_PATH))
    timezone = portfolio_config.get("market_timezone", DEFAULT_TIMEZONE)

    if not force:
        calendar = NyseMarketCalendar(timezone=timezone)
        if not is_market_open(_now_utc(), calendar):
            raise RuntimeError("US stock market is closed; skipping portfolio check.")

    current = fetch_watchlist(url)
    return update_snapshot(snapshot_path, current)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a TradingView portfolio watchlist for position changes.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--force", action="store_true", help="Fetch even when the NYSE market is closed.")
    parser.add_argument(
        "--include-no-change",
        action="store_true",
        help="Print a report even when the snapshot has no position changes.",
    )
    args = parser.parse_args()

    try:
        result = run(config_path=args.config, force=args.force)
    except RuntimeError as exc:
        if "market is closed" in str(exc):
            return 0
        raise

    if result.should_alert or args.include_no_change:
        print(result.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
