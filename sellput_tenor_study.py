# -*- coding: utf-8 -*-
"""卖put抄底的期限选择: 用CBOE期权链实测各到期日的IV期限结构与年化权利金。"""
import json
import os
import re
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
OCC_RE = re.compile(r"([A-Z]+)(\d{6})([CP])(\d{8})")

TARGET_DTES = [14, 30, 45, 75, 105]
TARGET_OTMS = [-0.12, -0.18, -0.25]


def load_chain(tk):
    js = json.load(open(os.path.join(OUT_DIR, f"{tk}_cboe_raw.json"), encoding="utf-8"))
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
        opts.append({
            "exp": exp, "dte": (exp - today).days, "cp": cp, "k": int(k) / 1000.0,
            "bid": o.get("bid") or 0, "ask": o.get("ask") or 0,
            "iv": o.get("iv") or 0, "delta": o.get("delta") or 0,
            "oi": o.get("open_interest") or 0, "vol": o.get("volume") or 0,
        })
    return spot, opts


def atm_iv(opts, dte):
    grp = [o for o in opts if o["dte"] == dte and o["iv"] > 0]
    spot_ks = sorted({o["k"] for o in grp})
    if not grp or not spot_ks:
        return None
    return None


def analyze(tk):
    spot, opts = load_chain(tk)
    print(f"\n{'='*100}\n[{tk}] 现价 ${spot:,.1f}  (CBOE延迟快照)")
    all_dtes = sorted({o["dte"] for o in opts if o["dte"] > 3})

    print(f"\n  ATM IV 期限结构:")
    line = []
    for td in TARGET_DTES:
        dte = min(all_dtes, key=lambda x: abs(x - td))
        grp = [o for o in opts if o["dte"] == dte and o["iv"] > 0 and abs(o["k"] / spot - 1) <= 0.03]
        if not grp:
            continue
        iv = sum(o["iv"] for o in grp) / len(grp) * 100
        line.append(f"{dte}天={iv:.0f}%")
    print("    " + "   ".join(line))

    print(f"\n  卖put收益率表 (mid价, 年化=权利金/行权价x365/DTE):")
    print(f"  {'到期':>6} {'行权价':>9} {'OTM':>6} {'Δ':>6} {'bid/ask':>15} {'权利金%':>7} {'年化%':>6} {'点差%':>6} {'OI':>7}")
    for td in TARGET_DTES:
        dte = min(all_dtes, key=lambda x: abs(x - td))
        puts = [o for o in opts if o["dte"] == dte and o["cp"] == "P" and o["bid"] > 0]
        if not puts:
            continue
        for otm in TARGET_OTMS:
            tgt = spot * (1 + otm)
            p = min(puts, key=lambda o: abs(o["k"] - tgt))
            mid = (p["bid"] + p["ask"]) / 2
            prem_pct = mid / p["k"] * 100
            ann = prem_pct * 365 / dte
            spr = (p["ask"] - p["bid"]) / mid * 100 if mid > 0 else 999
            print(f"  {dte:>5}天 {p['k']:>9,.0f} {p['k']/spot-1:>+5.0%} {p['delta']:>6.2f} "
                  f"{p['bid']:>7.2f}/{p['ask']:<7.2f} {prem_pct:>6.1f} {ann:>6.0f} {spr:>6.1f} {p['oi']:>7,.0f}")
        print()


for tk in ["MU", "SNDK"]:
    f = os.path.join(OUT_DIR, f"{tk}_cboe_raw.json")
    if os.path.exists(f):
        analyze(tk)
