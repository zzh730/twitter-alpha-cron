import re
from typing import Dict, List

POSITIVE = {
    "beat", "bull", "bullish", "up", "rally", "breakout", "strong", "growth", "surge", "buy", "long"
}
NEGATIVE = {
    "miss", "bear", "bearish", "down", "dump", "weak", "recession", "risk", "sell", "short", "crash"
}

MACRO_TAG_KEYWORDS = {
    "fed": ["fomc", "fed", "powell", "rate cut", "rate hike", "dot plot"],
    "inflation": ["cpi", "ppi", "inflation", "core pce", "pce"],
    "labor": ["nfp", "payroll", "unemployment", "jobless claims"],
    "growth": ["gdp", "pmis", "retail sales", "industrial production"],
    "energy": ["oil", "wti", "brent", "opec", "natgas"],
    "geopolitics": ["war", "sanction", "tariff", "taiwan", "middle east"],
    "crypto": ["btc", "bitcoin", "eth", "ethereum", "solana", "crypto"],
}

TICKER_PATTERN = re.compile(r"\$[A-Z]{1,6}\b")
ALLCAPS_PATTERN = re.compile(r"\b[A-Z]{2,5}\b")
COMMON_NON_TICKERS = {"USD", "FOMC", "CPI", "PPI", "GDP", "PMI", "ETF", "CEO", "AI"}


def analyze_text(text: str) -> Dict:
    lower = text.lower()
    words = re.findall(r"[a-zA-Z']+", lower)

    pos = sum(1 for w in words if w in POSITIVE)
    neg = sum(1 for w in words if w in NEGATIVE)
    score = pos - neg

    if score >= 2:
        sentiment = "bullish"
    elif score <= -2:
        sentiment = "bearish"
    else:
        sentiment = "neutral"

    tickers = set(m[1:] for m in TICKER_PATTERN.findall(text))
    for tok in ALLCAPS_PATTERN.findall(text):
        if tok not in COMMON_NON_TICKERS and 2 <= len(tok) <= 5:
            tickers.add(tok)

    macro_tags: List[str] = []
    for tag, kws in MACRO_TAG_KEYWORDS.items():
        if any(k in lower for k in kws):
            macro_tags.append(tag)

    return {
        "sentiment": sentiment,
        "sentiment_score": score,
        "tickers": sorted(tickers),
        "macro_tags": macro_tags,
    }
