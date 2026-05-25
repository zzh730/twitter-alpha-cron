# twitter-alpha-cron

每次运行现在会优先用 TwitterAPI.io 拉取 X List 的最新推文：

- `twitterapi_io.list_id`: 每 5 分钟拉取这个 X List 的最新内容
- `TWITTERAPI_IO_KEY`: TwitterAPI.io API key，从环境变量读取
- `GEMINI_API_KEY`: Gemini API key，用来把每条推文总结成中文 1-2 句话
- `poll_state_path`: 记录每个来源最新见过的 tweet id
- 首次运行只建立 baseline，不发送历史推文
- 后续运行会继续翻页，直到遇到已见过的 tweet id 或达到 `max_pages_per_run`
- 输出只包含每条推文的中文投资摘要和 URL

如果没有配置 `twitterapi_io`，会退回旧的 `x-tweet-fetcher` 两段式抓取：

- `following_handles`: 先走 `fetch_tweet.py --user <handle>`，通过 Camofox + Nitter 抓 timeline
- `feed_keywords`: 先走 `x_discover.py --keywords ...`，优先用搜索发现 tweet URL
- 如果上面任一路径失败，再退回原来的 Nitter RSS
- 拿到 URL 后，再调用 `fetch_tweet.py --url ...` 抓原推全文/长文内容

- dedup（SQLite）
- sentiment（bullish / neutral / bearish）
- 相关标的提取（ticker）
- 宏观标签（Fed / Inflation / Labor / Growth / Energy / Geopolitics / Crypto）

## 1) Setup

```bash
cd /Users/zzh/projects/twitter-alpha-cron
cp config.example.yaml config.yaml
```

编辑 `config.yaml`：
- `twitterapi_io.list_id`: 你要监控的 X List ID，例如 `1616825136690397187`
- `TWITTERAPI_IO_KEY`: 放在环境变量里，不要写进配置文件
- `twitterapi_io.max_pages_per_run`: 每轮最多翻几页；每页最多 20 条
- `twitterapi_io.bootstrap_pages`: 首次建基线最多翻几页
- `summary.model`: 默认 `gemini-3-flash-preview`
- `x_fetcher_repo_dir`: `x-tweet-fetcher` 路径；默认已指向 repo 内置的 `third_party/x_tweet_fetcher`
- `following_handles`: 你想优先看的账户
- `feed_keywords`: fallback 搜索词
- `nitter_instances`: timeline/RSS 共用的 Nitter 源
- `camofox_port`: 默认 `9377`
- `discover_cache`: keyword search 的 URL cache

> 说明：这里的 `config.yaml` 用的是 JSON 格式内容（JSON 是 YAML 子集），不依赖 PyYAML。

## 1.5) Camofox

`following_handles` 的 timeline 抓取依赖 Camofox。推荐先启动：

```bash
git clone https://github.com/jo-inc/camofox-browser /tmp/camofox-browser
cd /tmp/camofox-browser
npm install
npm start
```

健康检查：

```bash
curl http://localhost:9377/tabs
```

如果 Camofox 没启动，collector 会自动退回 Nitter RSS，不会直接整条任务失败。

## 2) Run once

```bash
python3 run_once.py --config config.yaml
```

输出：
- `data/latest.json`
- `data/latest.md`

## 2.5) Camofox Regression Test

```bash
python3 -m unittest tests/test_camofox_e2e.py
```

这个测试会启动一个本地 fake Camofox server，跑真实的 `fetch_tweet.py --user` 子进程路径，并校验 timeline 抓取后没有遗留 tab/session。

## 3) Schedule with OpenClaw Cron

`schedule.py` 支持 `10m` 到 `1d`。

### Hourly

```bash
python3 schedule.py --interval 1h --config config.yaml --channel discord --to channel:1475025575533084730
```

### Every 5 minutes

```bash
python3 schedule.py --interval 5m --config config.yaml --channel discord --to channel:1475025575533084730
```

### Every 10 minutes

```bash
python3 schedule.py --interval 10m --config config.yaml --channel discord --to channel:1475025575533084730
```

### Daily

```bash
python3 schedule.py --interval 1d --config config.yaml --channel discord --to channel:1475025575533084730
```

## 4) TradingView Portfolio Monitor

Portfolio monitor 会读取公开 TradingView watchlist，忽略 `###` 开头的分组标题，只比较真实持仓 symbol。

手动检查一次（即使当前不是美股交易时间也抓取）：

```bash
python3 -m fetch_haohuang_portfolio.run_once --config config.yaml --force --include-no-change
```

安装 OpenClaw Discord cron：

```bash
python3 -m fetch_haohuang_portfolio.schedule --config config.yaml --channel discord --to channel:1475025575533084730
```

这个 cron 每 10 分钟在纽约时间工作日 9:00-16:59 之间唤醒一次，脚本内部会用 NYSE 日历做最终判断；非交易日、节假日、盘前和收盘后不会抓取或推送。

Live E2E 测试会真的抓取 TradingView 页面：

```bash
RUN_TRADINGVIEW_E2E=1 python3 -m unittest tests/test_tradingview_portfolio_e2e.py
```

## Notes

- 优先路径：TwitterAPI.io list timeline。
- `x-tweet-fetcher` 仍负责单条推文全文抓取。
- Nitter 实例可用性会波动，建议配置多个实例。
- dedup 依据 tweet_id 持久化，避免重复推送。
- `x_discover.py` 自带 cache；collector 还会再按 `tweet_id` 做 SQLite dedup。
