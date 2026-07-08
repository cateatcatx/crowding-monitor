# -*- coding: utf-8 -*-
"""拉取拥挤度监控所需的日线数据。

数据源:
- 美股/ETF: 新浪财经 (经akshare stock_us_daily, 免费无鉴权)
- 韩股/KOSPI: Naver Finance siseJson 接口 (与 hynix_volatility/server.py 相同)

输出: data/ 目录下每个标的一个CSV (date,open,high,low,close,volume)
"""
import os
import re
import sys
import time
from datetime import date

import akshare as ak
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
START = "20220101"

# 美股标的: 存储/AI硬件核心 + 基准
US_TICKERS = ["MU", "SNDK", "WDC", "STX", "NVDA", "AMD", "SOXX", "SPY", "DRAM"]

# 韩股: SK海力士 / 三星电子 / KOSPI指数
NAVER_SYMBOLS = {
    "000660": "SK_HYNIX",
    "005930": "SAMSUNG",
    "KOSPI": "KOSPI",
}


def fetch_us(symbol: str) -> pd.DataFrame:
    raw = ak.stock_us_daily(symbol=symbol, adjust="")
    if raw is None or raw.empty:
        raise RuntimeError(f"sina no data for {symbol}")
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= pd.Timestamp(START)]
    return df[["date", "open", "high", "low", "close", "volume"]]


def fetch_naver(symbol: str) -> pd.DataFrame:
    url = "https://api.finance.naver.com/siseJson.naver"
    params = {
        "symbol": symbol,
        "requestType": "1",
        "startTime": START,
        "endTime": f"{date.today():%Y%m%d}",
        "timeframe": "day",
    }
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    rows = []
    for m in re.finditer(
        r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', r.text
    ):
        d, o, h, l, c, v = m.groups()
        rows.append((d, float(o), float(h), float(l), float(c), float(v)))
    if not rows:
        raise RuntimeError(f"naver no data for {symbol}")
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df


def main():
    ok, fail = [], []
    for name in US_TICKERS:
        try:
            df = fetch_us(name)
            df.to_csv(os.path.join(DATA_DIR, f"{name}.csv"), index=False)
            ok.append(f"{name}({len(df)}行, 最新{df['date'].iloc[-1]:%Y-%m-%d})")
        except Exception as e:
            fail.append(f"{name}: {e}")
        time.sleep(0.8)

    for sym, name in NAVER_SYMBOLS.items():
        try:
            df = fetch_naver(sym)
            df.to_csv(os.path.join(DATA_DIR, f"{name}.csv"), index=False)
            ok.append(f"{name}({len(df)}行, 最新{df['date'].iloc[-1]:%Y-%m-%d})")
        except Exception as e:
            fail.append(f"{name}: {e}")
        time.sleep(0.8)

    print("成功:")
    for s in ok:
        print("  ", s)
    if fail:
        print("失败:")
        for s in fail:
            print("  ", s)
        sys.exit(1)


if __name__ == "__main__":
    main()
