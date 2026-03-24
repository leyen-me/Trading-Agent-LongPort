# push_module 架构

## 设计思路

与 LongPort 的 `set_on_candlestick` + `subscribe_candlesticks` 模式一致：

- **main 注册**：通过 `set_on_news(callback)` 注册回调
- **数据源负责发送**：Jin10 模块定时拉取，有新快讯时调用回调「推送」

```
┌─────────────────────────────────────────────────────────────────┐
│                          main.py                                 │
│                                                                   │
│   jin10_pusher = Jin10NewsPusher(interval_seconds=60)              │
│   jin10_pusher.set_on_news(on_jin10_news)   ← 注册回调            │
│   jin10_pusher.start()                       ← 启动后台拉取        │
│                                                                   │
│   def on_jin10_news(items: List[dict]):      ← 接收推送            │
│       for item in items:                                          │
│           trading_agent.chat(...)  # 或注入上下文 / 记录日志       │
└─────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │  callback(items)
                                    │
┌──────────────────────────────────┴──────────────────────────────┐
│                     push_module/jin10.py                           │
│                                                                   │
│   Jin10NewsPusher:                                                 │
│     - 定时 GET flash-api.jin10.com/get_flash_list                │
│     - 用 max_time 做增量：只把「新」快讯传给 callback               │
│     - 后台线程 daemon=True，不阻塞 main 退出                        │
└─────────────────────────────────────────────────────────────────┘
```

## 与 LongPort 的对比

| 项目       | LongPort (K线)     | Jin10 (快讯)          |
|------------|-------------------|------------------------|
| 推送方式   | 服务端 WebSocket  | 客户端定时轮询         |
| 注册方式   | `set_on_candlestick` | `set_on_news`       |
| 订阅方式   | `subscribe_candlesticks` | `start()`        |
| 回调参数   | `PushCandlestick`  | `List[dict]` 快讯列表  |

## 使用示例

```python
from push_module.jin10 import Jin10NewsPusher

def on_jin10_news(items):
    for item in items:
        content = item.get("data", {}).get("content", "")
        print(f"[金十] {content[:80]}...")

pusher = Jin10NewsPusher(interval_seconds=60)
pusher.set_on_news(on_jin10_news)
pusher.start()
```
