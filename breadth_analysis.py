# -*- coding: utf-8 -*-
"""红区广度分析: 同时处于score>=80的标的数量, 作为主题级升级信号。"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]

scores = {}
for n in TARGETS:
    df = pd.read_csv(os.path.join(OUT_DIR, f"crowding_{n}.csv"), parse_dates=["date"]).set_index("date")
    scores[n] = df["score"]
sc = pd.DataFrame(scores).ffill(limit=3)

breadth = (sc >= 80).sum(axis=1)
theme = sc.mean(axis=1)

# 等权主题净值(近似, 用五标的收益均值)
closes = {}
for n in TARGETS:
    df = pd.read_csv(os.path.join(OUT_DIR, f"crowding_{n}.csv"), parse_dates=["date"]).set_index("date")
    closes[n] = df["close"]
px = pd.DataFrame(closes).ffill(limit=3)
theme_ret = px.pct_change().mean(axis=1)
theme_nav = (1 + theme_ret.fillna(0)).cumprod()

out = pd.DataFrame({"breadth": breadth, "theme_score": theme, "theme_nav": theme_nav})
out.round(4).to_csv(os.path.join(OUT_DIR, "breadth.csv"))

# 广度>=4 的连续时段
mask = breadth >= 4
groups = (mask != mask.shift()).cumsum()
print("广度>=4/5 的历史时段, 及时段结束后主题篮子的后续60日最大回撤:")
rows = []
for g, seg in out[mask].groupby(groups[mask]):
    start_d, end_d = seg.index[0], seg.index[-1]
    i_end = out.index.get_loc(end_d)
    nav_fwd = out["theme_nav"].iloc[i_end: i_end + 61]
    base = out["theme_nav"].loc[start_d:end_d].max()
    dd = (nav_fwd.min() / base - 1) * 100 if len(nav_fwd) else np.nan
    rows.append({
        "start": start_d.strftime("%Y-%m-%d"), "end": end_d.strftime("%Y-%m-%d"),
        "days": len(seg), "theme_score_max": round(seg["theme_score"].max(), 1),
        "fwd60_theme_maxdd%": round(dd, 1),
    })
print(pd.DataFrame(rows).to_string(index=False))

print("\n2026年5月以来 每日广度与主题分:")
recent = out.loc["2026-05-01":].copy()
recent["breadth"] = recent["breadth"].astype(int)
print(recent.round(2).to_string())
