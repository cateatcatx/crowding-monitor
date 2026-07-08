# -*- coding: utf-8 -*-
"""按接货概率(|delta|)选行权价: 30/44天期, delta -0.25/-0.35/-0.50 的卖put参数。"""
import json
import os
import re
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
OCC_RE = re.compile(r"([A-Z]+)(\d{6})([CP])(\d{8})")

for tk in ["MU", "SNDK"]:
    f = os.path.join(OUT_DIR, f"{tk}_cboe_raw.json")
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
        opts.append({"dte": (exp - today).days, "cp": cp, "k": int(k) / 1000.0,
                     "bid": o.get("bid") or 0, "ask": o.get("ask") or 0,
                     "delta": o.get("delta") or 0, "oi": o.get("open_interest") or 0})
    all_dtes = sorted({o["dte"] for o in opts if o["dte"] > 3})
    print(f"\n[{tk}] 现价 ${spot:,.1f}")
    for td in (30, 44):
        dte = min(all_dtes, key=lambda x: abs(x - td))
        puts = [o for o in opts if o["dte"] == dte and o["cp"] == "P" and o["bid"] > 0 and o["delta"] != 0]
        for tgt_d in (-0.25, -0.35, -0.50):
            p = min(puts, key=lambda o: abs(o["delta"] - tgt_d))
            mid = (p["bid"] + p["ask"]) / 2
            cost = p["k"] - mid
            print(f"  {dte:>3}天  Δ{p['delta']:+.2f} (接货概率≈{abs(p['delta'])*100:.0f}%)  "
                  f"行权价 {p['k']:>8,.0f} ({p['k']/spot-1:+.0%})  mid {mid:>7.2f}  "
                  f"权利金 {mid/p['k']*100:4.1f}% (年化{mid/p['k']*365/dte*100:3.0f}%)  "
                  f"接货成本 {cost:>8,.0f} ({cost/spot-1:+.0%})  OI {p['oi']:,.0f}")
