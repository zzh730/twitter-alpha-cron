import argparse
import datetime as dt
import json
import logging
import re
import subprocess
import sys
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

SOURCE_LABELS = {
    "following": "重点观察",
    "feed": "关键词发现",
}

SENTIMENT_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
}

MACRO_TAG_LABELS = {
    "fed": "美联储",
    "inflation": "通胀",
    "labor": "就业",
    "growth": "增长",
    "energy": "能源",
    "geopolitics": "地缘政治",
    "crypto": "加密资产",
}


def _is_financial_relevant(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in FIN_KEYWORDS)


@dataclass
class CandidateTweet:
    url: str
    source: str  # following|feed
    tweet_id: str = ""
    author_handle: str = ""


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


def _tweet_id_from_url(url: str) -> str:
    m = re.search(r"/status/(\d+)", url)
    return m.group(1) if m else ""


def _normalize_nitter_host(instance: str) -> str:
    instance = instance.strip()
    if not instance:
        return "nitter.net"
    if "://" not in instance:
        return instance.strip("/")
    return urllib.parse.urlparse(instance).netloc or "nitter.net"


def _fetcher_repo_candidates(config: Dict) -> List[Path]:
    root = Path(__file__).resolve().parent.parent
    candidates: List[Path] = []

    repo_dir = config.get("x_fetcher_repo_dir", "")
    if repo_dir:
        candidates.append(Path(repo_dir).expanduser())

    fetcher_script = config.get("fetcher_script", "")
    if fetcher_script:
        script_path = Path(fetcher_script).expanduser()
        if script_path.parent.name == "scripts":
            candidates.append(script_path.parent.parent)

    candidates.append(root / "third_party" / "x_tweet_fetcher")
    candidates.append(root / "vendor" / "x-tweet-fetcher")
    return candidates


def _resolve_fetcher_paths(config: Dict) -> Tuple[str, str]:
    configured_fetcher = config.get("fetcher_script", "")
    configured_path = Path(configured_fetcher).expanduser() if configured_fetcher else None

    for repo in _fetcher_repo_candidates(config):
        fetcher = repo / "scripts" / "fetch_tweet.py"
        discover = repo / "scripts" / "x_discover.py"
        if fetcher.exists() and discover.exists():
            return str(fetcher), str(discover)

    if configured_path and configured_path.exists():
        repo = configured_path.parent.parent if configured_path.parent.name == "scripts" else None
        discover = repo / "scripts" / "x_discover.py" if repo else None
        return str(configured_path), str(discover) if discover and discover.exists() else ""

    for repo in _fetcher_repo_candidates(config):
        fetcher = repo / "scripts" / "fetch_tweet.py"
        if fetcher.exists():
            return str(fetcher), ""

    return configured_fetcher, ""


def _run_json_command(cmd: List[str], ok_returncodes: Tuple[int, ...] = (0,)) -> Dict:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode not in ok_returncodes:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or f"command failed: {' '.join(cmd)}")

    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"command returned invalid JSON: {p.stdout[:300]}") from e


def _collect_following_via_fetcher(
    fetcher_script: str,
    handles: List[str],
    per_source_limit: int,
    camofox_port: int,
    nitter_instances: List[str],
) -> Tuple[List[CandidateTweet], List[str]]:
    candidates: List[CandidateTweet] = []
    failed_handles: List[str] = []
    nitter_hosts = [_normalize_nitter_host(inst) for inst in nitter_instances] or ["nitter.net"]

    for handle in handles:
        fetched = False
        for nitter_host in nitter_hosts:
            cmd = [
                sys.executable,
                fetcher_script,
                "--user",
                handle,
                "--limit",
                str(per_source_limit),
                "--port",
                str(camofox_port),
                "--nitter",
                nitter_host,
                "--lang",
                "en",
            ]
            try:
                data = _run_json_command(cmd)
                if data.get("error"):
                    raise RuntimeError(data["error"])

                for tweet in data.get("tweets", []):
                    tweet_id = str(tweet.get("tweet_id", "")).strip()
                    author_handle = (tweet.get("author", "") or "").lstrip("@")
                    if not tweet_id or not author_handle:
                        continue
                    candidates.append(
                        CandidateTweet(
                            url=f"https://x.com/{author_handle}/status/{tweet_id}",
                            source="following",
                            tweet_id=tweet_id,
                            author_handle=author_handle,
                        )
                    )
                fetched = True
                break
            except Exception as e:
                logging.warning(
                    "timeline fetch failed for %s via %s: %s",
                    handle,
                    nitter_host,
                    e,
                )
        if not fetched:
            failed_handles.append(handle)

    return candidates, failed_handles


def _collect_following_via_rss(
    nitter_instances: List[str],
    handles: List[str],
    per_source_limit: int,
) -> List[CandidateTweet]:
    candidates: List[CandidateTweet] = []
    for handle in handles:
        fetched = False
        for inst in nitter_instances:
            url = f"{inst.rstrip('/')}/{handle}/rss"
            try:
                xml_text = _safe_fetch(url)
                links = _parse_rss_links(xml_text)[:per_source_limit]
                for link in links:
                    normalized = _normalize_x_url(link)
                    candidates.append(
                        CandidateTweet(
                            url=normalized,
                            source="following",
                            tweet_id=_tweet_id_from_url(normalized),
                            author_handle=handle,
                        )
                    )
                fetched = True
                break
            except Exception as e:
                logging.warning("following RSS failed for %s via %s: %s", handle, inst, e)
        if not fetched:
            logging.warning("all nitter instances failed for handle=%s", handle)
    return candidates


def _collect_keywords_via_discover(
    discover_script: str,
    keywords: List[str],
    per_source_limit: int,
    discover_cache: str,
    discover_fresh: bool,
) -> Tuple[List[CandidateTweet], bool]:
    if not keywords:
        return [], True

    cmd = [
        sys.executable,
        discover_script,
        "--keywords",
        ",".join(keywords),
        "--limit",
        str(per_source_limit),
        "--json",
    ]
    if discover_cache:
        cmd.extend(["--cache", discover_cache])
    if discover_fresh:
        cmd.append("--fresh")

    try:
        data = _run_json_command(cmd, ok_returncodes=(0, 1))
    except Exception as e:
        logging.warning("x_discover failed: %s", e)
        return [], False

    candidates: List[CandidateTweet] = []
    for found in data.get("finds", []):
        url = found.get("url", "")
        if "/status/" not in url:
            continue
        normalized = _normalize_x_url(url)
        candidates.append(
            CandidateTweet(
                url=normalized,
                source="feed",
                tweet_id=_tweet_id_from_url(normalized),
            )
        )
    return candidates, bool(candidates)


def _collect_keywords_via_rss(
    nitter_instances: List[str],
    keywords: List[str],
    per_source_limit: int,
) -> List[CandidateTweet]:
    candidates: List[CandidateTweet] = []
    for kw in keywords:
        q = urllib.parse.quote_plus(kw)
        fetched = False
        for inst in nitter_instances:
            url = f"{inst.rstrip('/')}/search/rss?f=tweets&q={q}"
            try:
                xml_text = _safe_fetch(url)
                links = _parse_rss_links(xml_text)[:per_source_limit]
                for link in links:
                    normalized = _normalize_x_url(link)
                    candidates.append(
                        CandidateTweet(
                            url=normalized,
                            source="feed",
                            tweet_id=_tweet_id_from_url(normalized),
                        )
                    )
                fetched = True
                break
            except Exception as e:
                logging.warning("feed RSS failed for query=%s via %s: %s", kw, inst, e)
        if not fetched:
            logging.warning("all nitter instances failed for keyword=%s", kw)
    return candidates


def _collect_candidates(config: Dict, fetcher_script: str, discover_script: str) -> List[CandidateTweet]:
    instances = config.get("nitter_instances", [])
    following = config.get("following_handles", [])
    keywords = config.get("feed_keywords", [])
    per_source_limit = int(config.get("per_source_limit", 30))
    camofox_port = int(config.get("camofox_port", 9377))
    discover_cache = config.get("discover_cache", "./data/x_discover_cache.json")
    discover_fresh = bool(config.get("discover_fresh", True))
    prefer_repo_discovery = bool(config.get("prefer_repo_discovery", True))

    candidates: List[CandidateTweet] = []

    # following first: prefer timeline fetch via x-tweet-fetcher + Camofox, then fall back to RSS.
    failed_handles = following
    if prefer_repo_discovery and fetcher_script and following:
        following_candidates, failed_handles = _collect_following_via_fetcher(
            fetcher_script=fetcher_script,
            handles=following,
            per_source_limit=per_source_limit,
            camofox_port=camofox_port,
            nitter_instances=instances,
        )
        candidates.extend(following_candidates)

    if failed_handles:
        candidates.extend(_collect_following_via_rss(instances, failed_handles, per_source_limit))

    # keyword discovery: prefer x_discover, fall back to RSS if the script/backends fail.
    discover_ok = False
    if prefer_repo_discovery and discover_script and keywords:
        feed_candidates, discover_ok = _collect_keywords_via_discover(
            discover_script=discover_script,
            keywords=keywords,
            per_source_limit=per_source_limit,
            discover_cache=discover_cache,
            discover_fresh=discover_fresh,
        )
        candidates.extend(feed_candidates)

    if keywords and not discover_ok:
        candidates.extend(_collect_keywords_via_rss(instances, keywords, per_source_limit))

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

    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"fetch_tweet returned invalid JSON: {p.stdout[:300]}") from e

    if data.get("error"):
        raise RuntimeError(data["error"])

    return data


def _author_name(tweet: Dict) -> str:
    author = tweet.get("author", "")
    if isinstance(author, dict):
        return author.get("name", "")
    return author or ""


def _screen_name(tweet: Dict, details: Dict) -> str:
    screen_name = tweet.get("screen_name", "")
    if screen_name:
        return screen_name

    author = tweet.get("author", "")
    if isinstance(author, dict):
        return author.get("screen_name", "")

    return details.get("username", "")


def _extract_text(tweet: Dict) -> str:
    if tweet.get("is_article"):
        article = tweet.get("article", {})
        full_text = article.get("full_text", "")
        if full_text:
            return full_text
        preview = article.get("preview_text", "")
        if preview:
            return preview
    return tweet.get("text", "") or ""


def _normalize_handle(handle: str) -> str:
    return (handle or "").strip().lstrip("@").lower()


def _format_text_line(text: str) -> str:
    return (text or "").replace(chr(10), " ").strip()


def _format_number(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _join_or_default(values: List[str], default: str = "无") -> str:
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    return "、".join(cleaned) if cleaned else default


def _format_macro_tags(tags: List[str]) -> str:
    translated = [MACRO_TAG_LABELS.get(tag, tag) for tag in tags]
    return _join_or_default(translated)


def _is_target_user(item: Dict, target_handles: List[str]) -> bool:
    handle = _normalize_handle(item.get("screen_name", ""))
    targets = {_normalize_handle(h) for h in target_handles}
    return item.get("source") == "following" or (handle in targets if handle else False)


def _market_focus_label(item: Dict) -> str:
    macro_tags = item.get("macro_tags", [])
    tickers = item.get("tickers", [])
    if tickers:
        return f"相关标的集中在 {_join_or_default(tickers)}"
    if macro_tags:
        return f"重点落在 {_format_macro_tags(macro_tags)}"
    return "更偏向情绪/观点表达"


def _sentiment_cn(sentiment: str) -> str:
    return SENTIMENT_LABELS.get(sentiment, "中性")


def _per_tweet_market_view(item: Dict) -> str:
    sentiment = _sentiment_cn(item.get("sentiment", "neutral"))
    score = item.get("sentiment_score", 0)
    tickers = item.get("tickers", [])
    macro_tags = item.get("macro_tags", [])

    if score >= 2:
        stance = "这条更像是在强化做多/风险偏好回升的交易叙事"
    elif score <= -2:
        stance = "这条更像是在强化防守、回撤或做空方向的交易叙事"
    else:
        stance = "这条更多是在提供观察点，方向性没有那么极端"

    focus = _market_focus_label(item)
    macro_view = ""
    if macro_tags:
        macro_view = f"，并把市场注意力引向 {_format_macro_tags(macro_tags)}"

    return f"{stance}；作者当前语气为{sentiment}{macro_view}；{focus}。"


def _author_holistic_view(author_items: List[Dict]) -> str:
    total_score = sum(int(it.get("sentiment_score", 0)) for it in author_items)
    all_tickers: List[str] = []
    all_macro_tags: List[str] = []
    for item in author_items:
        all_tickers.extend(item.get("tickers", []))
        all_macro_tags.extend(item.get("macro_tags", []))

    if total_score >= 2:
        stance = "整体偏多，倾向强调上涨驱动、风险偏好或顺势交易机会"
    elif total_score <= -2:
        stance = "整体偏空，倾向强调风险释放、防守或下行交易机会"
    else:
        stance = "整体偏中性，更像是在给市场做信息补充和节奏提示"

    focus_parts = []
    if all_tickers:
        focus_parts.append(f"核心标的是 {_join_or_default(sorted(set(all_tickers)))}")
    if all_macro_tags:
        focus_parts.append(f"核心主题是 {_format_macro_tags(sorted(set(all_macro_tags)))}")
    if not focus_parts:
        focus_parts.append("内容更偏向盘面情绪、消息流或交易节奏")

    return f"{stance}；{ '；'.join(focus_parts) }。"


def _format_item_lines(item: Dict, index: int, include_trading_view: bool) -> List[str]:
    lines = [
        f"#### {index}. {item['author']} (@{item['screen_name']})",
        f"- 来源：{SOURCE_LABELS.get(item['source'], item['source'])}",
        f"- 链接：{item['url']}",
        f"- 时间：{item['created_at'] or '未知'}",
        f"- 情绪判断：{_sentiment_cn(item['sentiment'])}（score={item['sentiment_score']}）",
        f"- 涉及标的：{_join_or_default(item['tickers'])}",
        f"- 宏观主题：{_format_macro_tags(item['macro_tags'])}",
        f"- 互动数据：点赞 {_format_number(item.get('likes'))} / 转推 {_format_number(item.get('retweets'))} / 回复 {_format_number(item.get('replies_count'))} / 浏览 {_format_number(item.get('views'))}",
        f"- 原文：{_format_text_line(item['text'])}",
    ]
    if include_trading_view:
        lines.append(f"- 交易/市场解读：{_per_tweet_market_view(item)}")
    lines.append("")
    return lines


def _format_markdown(items: List[Dict], target_handles: List[str]) -> str:
    if not items:
        return "本轮去重后没有新的推文。"

    target_set = {_normalize_handle(h) for h in target_handles}
    target_items = [it for it in items if _is_target_user(it, target_handles)]
    other_items = [it for it in items if not _is_target_user(it, target_handles)]

    lines = ["# X 交易监控摘要", ""]

    if target_items:
        lines.extend(["## 重点观察账户", ""])
        ordered_handles = []
        seen_handles = set()
        for handle in target_handles:
            normalized = _normalize_handle(handle)
            if normalized and normalized not in seen_handles:
                ordered_handles.append(normalized)
                seen_handles.add(normalized)
        for item in target_items:
            normalized = _normalize_handle(item.get("screen_name", ""))
            if normalized and normalized not in seen_handles:
                ordered_handles.append(normalized)
                seen_handles.add(normalized)

        block_index = 1
        for handle in ordered_handles:
            author_items = [it for it in target_items if _normalize_handle(it.get("screen_name", "")) == handle]
            if not author_items:
                continue
            author_name = author_items[0].get("author") or handle
            lines.extend(
                [
                    f"### {block_index}. {author_name} (@{handle})",
                    f"- 本轮整体观点：{_author_holistic_view(author_items)}",
                    f"- 新推文数：{len(author_items)}",
                    "",
                ]
            )
            for idx, item in enumerate(author_items, start=1):
                lines.extend(_format_item_lines(item, idx, include_trading_view=True))
            block_index += 1

    if other_items:
        lines.extend(["## 其他市场推文", ""])
        for idx, item in enumerate(other_items, start=1):
            lines.extend(_format_item_lines(item, idx, include_trading_view=False))

    return "\n".join(lines)


def run(config_path: str) -> Tuple[List[Dict], str]:
    config = _load_config(config_path)

    fetcher_script, discover_script = _resolve_fetcher_paths(config)
    if not fetcher_script:
        raise ValueError("No fetcher_script found. Set fetcher_script or x_fetcher_repo_dir in config.")
    max_new_items = int(config.get("max_new_items", 30))
    db_path = config.get("dedup_db", "./data/seen_tweets.db")

    store = SeenStore(db_path)
    out: List[Dict] = []
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    try:
        candidates = _collect_candidates(config, fetcher_script, discover_script)
        logging.info("collected %d candidates", len(candidates))

        for c in candidates:
            if len(out) >= max_new_items:
                break
            candidate_tweet_id = c.tweet_id or _tweet_id_from_url(c.url)
            if candidate_tweet_id and store.is_seen(candidate_tweet_id):
                continue
            try:
                details = _fetch_tweet_details(fetcher_script, c.url)
                tweet = details.get("tweet", {})
                tweet_id = details.get("tweet_id") or candidate_tweet_id or c.url.rsplit("/", 1)[-1]
                if store.is_seen(tweet_id):
                    continue

                text = _extract_text(tweet)
                if not _is_financial_relevant(text):
                    continue

                analysis = analyze_text(text)

                record = {
                    "url": c.url,
                    "tweet_id": tweet_id,
                    "source": c.source,
                    "author": _author_name(tweet),
                    "screen_name": _screen_name(tweet, details),
                    "created_at": tweet.get("created_at", ""),
                    "text": text,
                    "likes": tweet.get("likes", 0),
                    "retweets": tweet.get("retweets", 0),
                    "views": tweet.get("views", 0),
                    "replies_count": tweet.get("replies_count", tweet.get("replies", 0)),
                    "is_note_tweet": tweet.get("is_note_tweet", False),
                    "lang": tweet.get("lang", ""),
                    "quote": tweet.get("quote"),
                    **analysis,
                }
                out.append(record)
                store.mark_seen(tweet_id, c.url, c.source, now)
            except Exception as e:
                logging.warning("failed processing %s: %s", c.url, e)

        return out, _format_markdown(out, config.get("following_handles", []))
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
