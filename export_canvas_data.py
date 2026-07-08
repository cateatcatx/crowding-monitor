# -*- coding: utf-8 -*-
"""导出Canvas所需的紧凑JSON数据。"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]
SINCE = "2025-09-01"


def load(name):
    return pd.read_csv(os.path.join(OUT_DIR, f"crowding_{name}.csv"),
                       parse_dates=["date"]).set_index("date")


# 以MU的交易日历为主轴, 其他标的ffill对齐
master = load("MU").loc[SINCE:].index
cats = [d.strftime("%y/%m/%d") for d in master]

score_series = {}
px_series = {}
for name in TARGETS:
    df = load(name)
    s = df["score"].reindex(master, method="ffill")
    c = df["close"].reindex(master, method="ffill")
    base = c.dropna().iloc[0]
    score_series[name] = [round(x, 1) if pd.notna(x) else None for x in s]
    px_series[name] = [round(x / base * 100, 1) if pd.notna(x) else None for x in c]

current = []
for name in TARGETS:
    df = load(name)

    last = df.iloc[-1]
    ma20 = df["close"].rolling(20).mean().iloc[-1]
    armed = df["score"].rolling(15, min_periods=1).max().iloc[-1] >= 85
    peak_close = df["close"].loc["2026-06-01":"2026-06-30"].max()
    current.append({
        "peak_score_jun": round(float(df["score"].loc["2026-06-01":"2026-06-30"].max()), 1),
        "name": name,
        "date": df.index[-1].strftime("%m-%d"),
        "close": float(last["close"]),
        "score": round(float(last["score"]), 1),
        "turnover": round(float(last["turnover"]), 0),
        "vol_share": round(float(last["vol_share"]), 0) if pd.notna(last["vol_share"]) else None,
        "extension": round(float(last["extension"]), 0),
        "momentum": round(float(last["momentum"]), 0),
        "rsi": round(float(last["rsi"]), 0),
        "volatility": round(float(last["volatility"]), 0),
        "basket_corr": round(float(last["basket_corr"]), 0),
        "armed": bool(armed),
        "below_ma20": bool(last["close"] < ma20),
        "dd_from_jun_peak": round((last["close"] / peak_close - 1) * 100, 1),
    })

theme = pd.read_csv(os.path.join(OUT_DIR, "breadth.csv"), parse_dates=["date"]).set_index("date")
theme_score = [round(x, 1) if pd.notna(x) else None
               for x in theme["theme_score"].reindex(master, method="ffill")]
theme_breadth = [int(x) if pd.notna(x) else 0
                 for x in theme["breadth"].reindex(master, method="ffill")]

tci_df = pd.read_csv(os.path.join(OUT_DIR, "theme_index.csv"), parse_dates=["date"]).set_index("date")
tci_daily = [round(x, 1) if pd.notna(x) else None
             for x in tci_df["tci"].reindex(master, method="ffill")]
tci_parts = {
    c: [round(x, 1) if pd.notna(x) else None
        for x in tci_df[c].reindex(master, method="ffill")]
    for c in ["level", "breadth_pct", "persistence"]
}
# 全历史周度TCI(展示2024-04等早期红区时段)
wk = tci_df["tci"].resample("W-FRI").last().dropna()
tci_weekly = {
    "cats": [d.strftime("%y/%m/%d") for d in wk.index],
    "vals": [round(x, 1) for x in wk],
}

out = {
    "cats": cats,
    "px": px_series,
    "score": score_series,
    "theme_score": theme_score,
    "theme_breadth": theme_breadth,
    "tci": tci_daily,
    "tci_parts": tci_parts,
    "tci_weekly": tci_weekly,
    "current": current,
}
with open(os.path.join(OUT_DIR, "canvas_data.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"exported, {len(cats)} dates, size={os.path.getsize(os.path.join(OUT_DIR, 'canvas_data.json'))//1024}KB")
