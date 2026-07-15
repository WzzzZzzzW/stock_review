---
created: 2026-06-17
updated: 2026-06-17
tags: [datasource, runbook]
type: runbook
freshness: stable
related: ["[[Projects/股票分析]]", "[[Notes/数据源与代理坑]]"]
---

# baostock 用法

## Summary

baostock 是**单 socket、不能并发**的数据源。`stock_data.py` 用全局锁 + 熔断包装器保护它。
所有 baostock 调用都要走 `_bs_run`，不要裸调。

## 关键设施（stock_data.py）

- `import baostock as bs`（顶部）
- `_BS_LOCK` 全局锁；`_BS_LOCK_TIMEOUT=60`、`_BS_COOLDOWN=90`
- `_bs_run(work_fn, *, timeout, label)` — 包装器：拿不到锁→`BaostockBusy`；超时→`BaostockTimeout`；冷却中→`BaostockCooldown`
- `_bs_symbol(symbol)` → `"sh.600519"` / `"sz.000001"`
- 调用方统一 `except (BaostockBusy, BaostockTimeout, BaostockCooldown)` 降级，不让异常冒泡。

## 查日K字段

```
query_history_k_data_plus(code, "date,open,high,low,close,volume,amount,turn,pctChg,isST",
                          start_date=YYYY-MM-DD, end_date=YYYY-MM-DD,
                          frequency="d", adjustflag="2")
```
- 日期格式 **YYYY-MM-DD**（注意东财 akshare 用的是 YYYYMMDD，别混）。
- `pctChg`→`pct_change`；`isST`=="1" 表示 ST。
- 单会话内 `bs.login()` 一次、循环查询、`finally: bs.logout()`。

## Examples

- 回测兜底 `_baostock_history_batch` 就是单会话串行拉多只、`_bs_run` 保护、部分失败返回空帧。
