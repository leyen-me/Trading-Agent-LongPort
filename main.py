import time

if __name__ == "__main__":
    from strategy import init_day_trading
    init_day_trading()
    while True:
        time.sleep(1)