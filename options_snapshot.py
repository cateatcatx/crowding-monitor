# -*- coding: utf-8 -*-
"""期权维度拥挤度快照 (CBOE延迟全市场报价, 无需鉴权)。

拥挤度相关指标:
  - P/C ratio (按OI与当日成交量): 远低于1 = 多头拥挤(call投机盛)
  - 近月ATM隐含波动率: IV水平
  - 25Δ skew: OTM call IV - OTM put IV, 正值/收敛 = call抢筹(看涨投机拥挤)
  - 近月(<=45天)OTM call的OI占比: 投机筹码集中度
  - ATM IV期限结构: 各到期日ATM IV(倒挂=近月恐慌, 陡贴水利于卖put)
数据保存: out/{ticker}_options_snapshot.json
历史积累: data/IV_HISTORY.csv (每日一行/标的, 供网页画IV历史曲线)
"""
import csv
import json
import os
import re
import sys
from datetime import date, datetime

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
os.makedirs(OUT_DIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OCC_RE = re.compile(r"([A-Z]+)(\d{6})([CP])(\d{8})")


def fetch(ticker: str) -> dict:
    url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def analyze(ticker: str) -> dict:
    js = fetch(ticker)
    data = js["data"]
    spot = data.get("current_price") or data.get("close")
    raw_path = os.path.join(OUT_DIR, f"{ticker}_cboe_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(js, f)

    today = date.today()
    opts = []
    for o in data["options"]:
        m = OCC_RE.match(o["option"])
        if not m:
            continue
        _, ymd, cp, strike = m.groups()
        exp = datetime.strptime(ymd, "%y%m%d").date()
        opts.append({
            "exp": exp, "dte": (exp - today).days, "cp": cp,
            "strike": int(strike) / 1000.0,
            "iv": o.get("iv") or 0, "oi": o.get("open_interest") or 0,
            "vol": o.get("volume") or 0, "delta": o.get("delta") or 0,
        })

    calls = [o for o in opts if o["cp"] == "C"]
    puts = [o for o in opts if o["cp"] == "P"]
    oi_c, oi_p = sum(o["oi"] for o in calls), sum(o["oi"] for o in puts)
    v_c, v_p = sum(o["vol"] for o in calls), sum(o["vol"] for o in puts)

    # 近月组(7 <= dte <= 45)
    near = [o for o in opts if 7 <= o["dte"] <= 45]
    near_c = [o for o in near if o["cp"] == "C"]
    near_p = [o for o in near if o["cp"] == "P"]

    def atm_iv(group):
        cands = [o for o in group if abs(o["strike"] / spot - 1) <= 0.05 and o["iv"] > 0]
        return sum(o["iv"] for o in cands) / len(cands) if cands else None

    def skew25(cs, ps):
        c25 = [o for o in cs if 0.18 <= abs(o["delta"]) <= 0.32 and o["iv"] > 0]
        p25 = [o for o in ps if 0.18 <= abs(o["delta"]) <= 0.32 and o["iv"] > 0]
        if not c25 or not p25:
            return None, None, None
        civ = sum(o["iv"] for o in c25) / len(c25)
        piv = sum(o["iv"] for o in p25) / len(p25)
        return civ, piv, civ - piv

    civ, piv, skew = skew25(near_c, near_p)

    # 近月OTM call OI 占全部call OI比重(投机集中)
    otm_call_near_oi = sum(o["oi"] for o in near_c if o["strike"] > spot)
    total_call_oi = oi_c or 1

    # ATM IV期限结构: 每个到期日取现价±5%内合约的IV均值
    by_exp = {}
    for o in opts:
        if o["dte"] < 1 or o["dte"] > 200 or o["iv"] <= 0:
            continue
        if abs(o["strike"] / spot - 1) > 0.05:
            continue
        by_exp.setdefault((o["exp"], o["dte"]), []).append(o["iv"])
    term_structure = [
        {"exp": exp.strftime("%Y-%m-%d"), "dte": dte,
         "iv_pct": round(sum(ivs) / len(ivs) * 100, 1)}
        for (exp, dte), ivs in sorted(by_exp.items())
        if len(ivs) >= 2
    ]

    res = {
        "ticker": ticker,
        "spot": spot,
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_oi": oi_c + oi_p,
        "total_volume": v_c + v_p,
        "pc_ratio_oi": round(oi_p / oi_c, 3) if oi_c else None,
        "pc_ratio_vol": round(v_p / v_c, 3) if v_c else None,
        "near_atm_iv_pct": round(atm_iv(near) * 100, 1) if atm_iv(near) else None,
        "near_call25d_iv_pct": round(civ * 100, 1) if civ else None,
        "near_put25d_iv_pct": round(piv * 100, 1) if piv else None,
        "skew_call_minus_put_pct": round(skew * 100, 2) if skew is not None else None,
        "near_otm_call_oi_share_pct": round(otm_call_near_oi / total_call_oi * 100, 1),
        "term_structure": term_structure,
    }
    return res


IV_HISTORY_FILE = os.path.join(HERE, "data", "IV_HISTORY.csv")
IV_HISTORY_COLS = ["date", "ticker", "spot", "atm_iv_pct", "call25d_iv_pct",
                   "put25d_iv_pct", "skew_pct", "pc_ratio_vol", "pc_ratio_oi"]


def append_iv_history(results):
    """把当日快照按(date,ticker)去重后追加进历史CSV(同日多次运行取最后一次)。"""
    os.makedirs(os.path.dirname(IV_HISTORY_FILE), exist_ok=True)
    rows = {}
    if os.path.exists(IV_HISTORY_FILE):
        with open(IV_HISTORY_FILE, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[(r["date"], r["ticker"])] = {c: r.get(c, "") for c in IV_HISTORY_COLS}
    today = date.today().isoformat()
    for res in results:
        rows[(today, res["ticker"])] = {
            "date": today,
            "ticker": res["ticker"],
            "spot": res["spot"],
            "atm_iv_pct": res["near_atm_iv_pct"],
            "call25d_iv_pct": res["near_call25d_iv_pct"],
            "put25d_iv_pct": res["near_put25d_iv_pct"],
            "skew_pct": res["skew_call_minus_put_pct"],
            "pc_ratio_vol": res["pc_ratio_vol"],
            "pc_ratio_oi": res["pc_ratio_oi"],
        }
    with open(IV_HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=IV_HISTORY_COLS)
        w.writeheader()
        for key in sorted(rows):
            w.writerow(rows[key])


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["MU", "SNDK", "WDC"]
    results = []
    for t in tickers:
        try:
            r = analyze(t)
            results.append(r)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"{t}: FAILED {e}")
    with open(os.path.join(OUT_DIR, "options_snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    if results:
        append_iv_history(results)
