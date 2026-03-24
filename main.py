import os
import time

if __name__ == "__main__":
    from strategy import STRATEGIES

    strategy_name = os.getenv("STRATEGY", "day_trading")
    init_fn = STRATEGIES.get(strategy_name)
    if init_fn is None:
        raise SystemExit(f"未知策略: {strategy_name}，可选: {list(STRATEGIES.keys())}")

    init_fn()
    while True:
        time.sleep(1)