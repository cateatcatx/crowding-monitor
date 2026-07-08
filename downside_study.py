# -*- coding: utf-8 -*-
"""下跌空间测算: 历史类比 + 关键价位 + 期权隐含波动定价。"""
import json
import os
import re
from datetime import date, datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]
OCC_RE = re.compile(r"([A-Z]+)(\d{6})([CP])(\d{8})")


def load(n):
    return pd.read_csv(os.path.join(OUT_DIR, f"crowding_{n}.csv"), parse_dates=["date"]).set_index("date")


print("=" * 100)
print("1) 关键价位 (基于收盘价)")
for n in TARGETS:
    df = load(n)
    c = df["close"]
    last = c.iloc[-1]
    peak_d = c.loc["2026-06-01":"2026-06-30"].idxmax()
    peak = c.loc[peak_d]
    # 本轮起涨点: 2026-04-01以来最低收盘
    low_d = c.loc["2026-03-01":"2026-05-01"].idxmin()
    low = c.loc[low_d]
    run = peak - low
    fib = {"23.6%": peak - 0.236 * run, "38.2%": peak - 0.382 * run,
           "50%": peak - 0.5 * run, "61.8%": peak - 0.618 * run}
    ma50 = c.rolling(50).mean().iloc[-1]
    ma100 = c.rolling(100).mean().iloc[-1]
    ma200 = c.rolling(200).mean().iloc[-1]
    print(f"\n[{n}] 现价 {last:,.0f}   6月峰 {peak:,.0f} ({peak_d:%m/%d})   已回撤 {(last/peak-1)*100:.1f}%")
    print(f"   起涨点 {low:,.0f} ({low_d:%m/%d}), 本轮涨幅 {(peak/low-1)*100:.0f}%")
    print("   斐波那契回撤位: " + "  ".join(
        f"{k}={v:,.0f}({(v/last-1)*100:+.1f}%)" for k, v in fib.items()))
    print(f"   MA50={ma50:,.0f}({(ma50/last-1)*100:+.1f}%)  MA100={ma100:,.0f}({(ma100/last-1)*100:+.1f}%)  "
          f"MA200={ma200:,.0f}({(ma200/last-1)*100:+.1f}%)")

print()
print("=" * 100)
print("2) 历史类比: 各标的历次'重大顶部'的峰谷回撤深度")
print("   (拥挤出清型 vs 周期顶型)")
# 手工整理: 每个顶部的实际峰谷(用收盘价在顶部后120日内最低点)
for n in TARGETS:
    df = load(n)
    c = df["close"]
    tops = {
        "MU": ["2024-06-18", "2025-11-10", "2026-02-02", "2026-03-18"],
        "SNDK": ["2025-11-12", "2026-02-03", "2026-03-19"],
        "WDC": ["2025-11-10", "2026-03-19"],
        "SK_HYNIX": ["2024-07-11", "2026-02-26"],
        "SAMSUNG": ["2024-07-09", "2026-02-26"],
    }[n]
    rows = []
    for t in tops:
        t = pd.Timestamp(t)
        if t not in c.index:
            t = c.index[c.index.get_indexer([t], method="nearest")[0]]
        i = c.index.get_loc(t)
        seg = c.iloc[i: i + 121]
        trough_d = seg.idxmin()
        dd = (seg.min() / c.loc[t] - 1) * 100
        days = c.index.get_loc(trough_d) - i
        rows.append(f"{t:%y/%m}顶: {dd:.0f}% ({days}日)")
    print(f"   {n:9s} " + " | ".join(rows))

# 主题篮子当前回撤 vs 历史
tdf = pd.read_csv(os.path.join(OUT_DIR, "theme_index.csv"), parse_dates=["date"]).set_index("date")
nav = tdf["theme_nav"]
peak = nav.loc["2026-06-01":"2026-06-30"].max()
print(f"\n   主题篮子: 6月峰值至今 {(nav.iloc[-1]/peak-1)*100:.1f}%  "
      f"(2025/11轮: -16.4%; 2026/02轮: -9.5%; 2024周期顶轮: -18.3%; 2024-08单股极值 MU -45%)")

print()
print("=" * 100)
print("3) 期权市场定价的区间 (CBOE快照)")
for tk in ["MU", "SNDK", "WDC"]:
    f = os.path.join(OUT_DIR, f"{tk}_cboe_raw.json")
    if not os.path.exists(f):
        continue
    js = json.load(open(f, encoding="utf-8"))
    data = js["data"]
    spot = data.get("current_price") or data.get("close")
    today = date.today()
    opts = []
    for o in data["options"]:
        m = OCC_RE.match(o["option"])
        if not m:
            continue
        _, ymd, cp, k = m.groups()
        exp = datetime.strptime(ymd, "%y%m%d").date()
        dte = (exp - today).days
        opts.append({
            "dte": dte, "cp": cp, "k": int(k) / 1000.0,
            "bid": o.get("bid") or 0, "ask": o.get("ask") or 0,
            "delta": o.get("delta") or 0, "exp": exp,
        })
    for target_dte in (30, 90):
        cands = sorted({o["dte"] for o in opts if o["dte"] >= target_dte - 12})
        if not cands:
            continue
        dte = min(cands, key=lambda x: abs(x - target_dte))
        grp = [o for o in opts if o["dte"] == dte]
        # ATM straddle
        atm_k = min({o["k"] for o in grp}, key=lambda k: abs(k - spot))
        call = next((o for o in grp if o["cp"] == "C" and o["k"] == atm_k), None)
        put = next((o for o in grp if o["cp"] == "P" and o["k"] == atm_k), None)
        if not call or not put:
            continue
        stradd = (call["bid"] + call["ask"]) / 2 + (put["bid"] + put["ask"]) / 2
        move = stradd / spot * 100
        # 25/10-delta put strike
        puts = [o for o in grp if o["cp"] == "P" and o["delta"] != 0]
        p25 = min(puts, key=lambda o: abs(abs(o["delta"]) - 0.25), default=None)
        p10 = min(puts, key=lambda o: abs(abs(o["delta"]) - 0.10), default=None)
        line = (f"   [{tk}] {dte}天期: 跨式隐含波动 ±{move:.0f}% "
                f"(区间 {spot*(1-move/100):,.0f} ~ {spot*(1+move/100):,.0f})")
        if p25:
            line += f"   25Δput行权价 {p25['k']:,.0f} ({(p25['k']/spot-1)*100:.0f}%)"
        if p10:
            line += f"   10Δput {p10['k']:,.0f} ({(p10['k']/spot-1)*100:.0f}%)"
        print(line)
    print()
