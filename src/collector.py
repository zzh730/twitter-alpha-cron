import argparse
import datetime as dt
import json
import logging
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from analysis import analyze_text
from storage import SeenStore

FIN_KEYWORDS = {
    "stock", "stocks", "equity", "equities", "earnings", "guidance", "revenue", "eps",
    "fed", "fomc", "cpi", "ppi", "gdp", "rates", "yield", "treasury", "bond", "macro",
    "option", "options", "flow", "gamma", "vol", "iv", "call", "put", "ticker", "market",
    "bitcoin", "btc", "ethereum", "eth", "crypto", "oil", "brent", "wti",
}


def _is_financial_relevant(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in FIN_KEYWORDS)


@dataclass
class CandidateTweet:
    url: str
    source: str  # following|feed


def _load_config(path: str) -> Dict:
    raw = Path(path).read_text(encoding="utf-8")
    # Minimal parser: expect JSON-compatible YAML subset.
    # Recommend users keep quoted strings and list syntax as in example.
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            "Config parsing failed. Use JSON format inside .yaml (JSON is valid YAML)."
        ) from e


def _safe_fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _parse_rss_links(xml_text: str) -> List[str]:
    root = ET.fromstring(xml_text)
    links = []
    for item in root.findall(".//item"):
        link = item.findtext("link")
        if link and "/status/" in link:
            links.append(link)
    return links


def _normalize_x_url(url: str) -> str:
    u = urllib.parse.urlparse(url)
    if "twitter.com" in u.netloc or "x.com" in u.netloc:
        return f"https://x.com{u.path}"
    # nitter style: /user/status/id
    return f"https://x.com{u.path}"


def _collect_candidates(config: Dict) -> List[CandidateTweet]:
    instances = config.get("nitter_instances", [])
    following = config.get("following_handles", [])
    keywords = config.get("feed_keywords", [])
    per_source_limit = int(config.get("per_source_limit", 30))

    candidates: List[CandidateTweet] = []

    # following first
    for handle in following:
        fetched = False
        for inst in instances:
            url = f"{inst.rstrip('/')}/{handle}/rss"
            try:
                xml_text = _safe_fetch(url)
                links = _parse_rss_links(xml_text)[:per_source_limit]
                for link in links:
                    candidates.append(CandidateTweet(url=_normalize_x_url(link), source="following"))
                fetched = True
                break
            except Exception as e:
                logging.warning("following RSS failed for %s via %s: %s", handle, inst, e)
        if not fetched:
            logging.warning("all nitter instances failed for handle=%s", handle)

    # feed fallback
    for kw in keywords:
        q = urllib.parse.quote_plus(kw)
        fetched = False
        for inst in instances:
            url = f"{inst.rstrip('/')}/search/rss?f=tweets&q={q}"
            try:
                xml_text = _safe_fetch(url)
                links = _parse_rss_links(xml_text)[:per_source_limit]
                for link in links:
                    candidates.append(CandidateTweet(url=_normalize_x_url(link), source="feed"))
                fetched = True
                break
            except Exception as e:
                logging.warning("feed RSS failed for query=%s via %s: %s", kw, inst, e)
        if not fetched:
            logging.warning("all nitter instances failed for keyword=%s", kw)

    # dedup preserving priority/order
    seen = set()
    unique: List[CandidateTweet] = []
    for c in candidates:
        if c.url not in seen:
            seen.add(c.url)
            unique.append(c)
    return unique


def _fetch_tweet_details(fetcher_script: str, url: str) -> Dict:
    cmd = ["python3", fetcher_script, "--url", url]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or "fetch_tweet failed")
    return json.loads(p.stdout)


def _format_markdown(items: List[Dict]) -> str:
    if not items:
        return "No new tweets after dedup."

    lines = ["# X Trading/Investing Feed", ""]
    for i, it in enumerate(items, start=1):
        lines.extend(
            [
                f"## {i}. {it['author']} (@{it['screen_name']}) [{it['source']}]",
                f"- URL: {it['url']}",
                f"- Time: {it['created_at']}",
                f"- Sentiment: {it['sentiment']} (score={it['sentiment_score']})",
                f"- Tickers: {', '.join(it['tickers']) if it['tickers'] else 'None'}",
                f"- Macro tags: {', '.join(it['macro_tags']) if it['macro_tags'] else 'None'}",
                f"- Text: {it['text'].replace(chr(10), ' ')}",
                "",
            ]
        )
    return "\n".join(lines)


def run(config_path: str) -> Tuple[List[Dict], str]:
    config = _load_config(config_path)

    fetcher_script = config["fetcher_script"]
    max_new_items = int(config.get("max_new_items", 30))
    db_path = config.get("dedup_db", "./data/seen_tweets.db")

    store = SeenStore(db_path)
    out: List[Dict] = []
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    try:
        candidates = _collect_candidates(config)
        logging.info("collected %d candidates", len(candidates))

        for c in candidates:
            if len(out) >= max_new_items:
                break
            try:
                details = _fetch_tweet_details(fetcher_script, c.url)
                tweet = details.get("tweet", {})
                tweet_id = details.get("tweet_id") or c.url.rsplit("/", 1)[-1]
                if store.is_seen(tweet_id):
                    continue

                text = tweet.get("article", {}).get("full_text") if tweet.get("is_article") else tweet.get("text", "")
                if not _is_financial_relevant(text or ""):
                    continue

                analysis = analyze_text(text or "")

                record = {
                    "url": c.url,
                    "tweet_id": tweet_id,
                    "source": c.source,
                    "author": tweet.get("author", ""),
                    "screen_name": tweet.get("screen_name", details.get("username", "")),
                    "created_at": tweet.get("created_at", ""),
                    "text": text or "",
                    **analysis,
                }
                out.append(record)
                store.mark_seen(tweet_id, c.url, c.source, now)
            except Exception as e:
                logging.warning("failed processing %s: %s", c.url, e)

        return out, _format_markdown(out)
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect trading/investing tweets with dedup + analysis.")
    parser.add_argument("--config", default="config.yaml", help="Path to config file (JSON format accepted).")
    parser.add_argument("--output-json", default="", help="Optional JSON output path")
    parser.add_argument("--output-md", default="", help="Optional markdown output path")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    items, md = run(args.config)

    print(md)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
