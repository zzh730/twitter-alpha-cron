# twitter-alpha-cron

每次运行会优先抓 `following_handles` 的推文，再抓 `feed_keywords` 的搜索 RSS，随后调用 `x-tweet-fetcher` 获取原推全文，并做：

- dedup（SQLite）
- sentiment（bullish / neutral / bearish）
- 相关标的提取（ticker）
- 宏观标签（Fed / Inflation / Labor / Growth / Energy / Geopolitics / Crypto）

## 1) Setup

```bash
cd /Users/drzzh/.openclaw/workspace/twitter-alpha-cron
cp config.example.yaml config.yaml
```

编辑 `config.yaml`：
- `following_handles`: 你想优先看的账户
- `feed_keywords`: fallback 搜索词
- `nitter_instances`: RSS 源

> 说明：这里的 `config.yaml` 用的是 JSON 格式内容（JSON 是 YAML 子集），不依赖 PyYAML。

## 2) Run once

```bash
python3 run_once.py --config config.yaml
```

输出：
- `data/latest.json`
- `data/latest.md`

## 3) Schedule with OpenClaw Cron

`schedule.py` 支持 `10m` 到 `1d`。

### Hourly

```bash
python3 schedule.py --interval 1h --config config.yaml --channel discord --to channel:1475025575533084730
```

### Every 10 minutes

```bash
python3 schedule.py --interval 10m --config config.yaml --channel discord --to channel:1475025575533084730
```

### Daily

```bash
python3 schedule.py --interval 1d --config config.yaml --channel discord --to channel:1475025575533084730
```

## Notes

- `x-tweet-fetcher` 负责单条推文全文抓取，来源 URL 由 following RSS / keyword RSS 提供。
- Nitter 实例可用性会波动，建议配置多个实例。
- dedup 依据 tweet_id 持久化，避免重复推送。
