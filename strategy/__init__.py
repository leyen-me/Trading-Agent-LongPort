"""
策略模块。main 每次只运行一种策略，通过 STRATEGIES 字典选择。
"""
from .day_trading.day_trading import init as init_day_trading

# 可运行策略的入口，新增策略时在此注册
STRATEGIES = {
    "day_trading": init_day_trading,
}