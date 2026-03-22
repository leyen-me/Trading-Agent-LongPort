# Trading-Agent-LongPort

基于 `LongPort` 行情/交易接口和 `OpenAI` 模型的日内交易 Agent。

当前特性：

- 订阅指定标的的 K 线推送
- 在盘前自动重置上下文并加载低频市场背景
- 在盘中基于最新 K 线、订单状态和交易思想进行决策
- 长时间收不到新 K 线时，自动触发收盘后复盘
- 支持通过 `trading_philosophy.md` 持续迭代交易思想

## 环境要求

- Python `3.12`
- LongPort 账户与 API 凭证
- OpenAI 兼容接口凭证

## 环境变量

至少需要配置：

```bash
OPENAI_API_KEY=your_openai_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

LONGPORT_APP_KEY=your_longport_app_key
LONGPORT_APP_SECRET=your_longport_app_secret
LONGPORT_ACCESS_TOKEN=your_longport_access_token

TRADE_SYMBOL=QQQ.US
TRADE_CYCLE=min_5
```

可选配置见 `config.py`。

## 本地运行

安装依赖：

```bash
pip install -r requirements.txt
```

启动：

```bash
python main.py
```

运行后会：

- 订阅 `TRADE_SYMBOL` 的 K 线
- 在 `.agent/` 下写入日志与历史
- 进程常驻，等待盘中推送事件

## Docker 部署

构建镜像：

```bash
docker build -t trading-agent-longport .
```

启动容器：

```bash
docker run --rm -it \
  -e OPENAI_API_KEY=your_openai_api_key \
  -e OPENAI_BASE_URL=https://api.openai.com/v1 \
  -e OPENAI_MODEL=gpt-4o-mini \
  -e LONGPORT_APP_KEY=your_longport_app_key \
  -e LONGPORT_APP_SECRET=your_longport_app_secret \
  -e LONGPORT_ACCESS_TOKEN=your_longport_access_token \
  -e TRADE_SYMBOL=QQQ.US \
  -e TRADE_CYCLE=min_5 \
  trading-agent-longport
```

`Dockerfile` 默认时区为 `America/New_York`。

## 目录说明

- `main.py`：主程序入口
- `config.py`：环境变量配置
- `tools/`：Agent 可调用工具
- `utils/`：行情和交易数据打包/解析工具
- `trading_philosophy.md`：交易思想
- `.agent/`：运行日志、任务和对话历史

## 注意事项

- 当前项目主要围绕单一交易标的运行
- 盘中未注入通用衍生品持仓信息，避免误用 `stock_positions`
- 自动复盘基于“长时间未收到新的确认 K 线”这一规则触发
