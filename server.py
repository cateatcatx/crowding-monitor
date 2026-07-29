# -*- coding: utf-8 -*-
"""AI硬件股拥挤度日报 Web看板。

- GET  /               静态页面
- GET  /api/dashboard  全部指标JSON(从 out/*.csv 组装)
- POST /api/refresh    触发数据刷新(后台线程跑 fetch->engine->tci->options)
- 服务端自带定时器: 每30分钟检查一次, 数据超过6小时自动刷新

启动: python server.py  (默认 127.0.0.1:5690)
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd
from flask import Flask, jsonify, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
FOREIGN_FLOW_FILE = os.path.join(HERE, "data", "SK_HYNIX_FOREIGN_FLOW.csv")
IV_HISTORY_FILE = os.path.join(HERE, "data", "IV_HISTORY.csv")
IV_TICKERS = ["MU", "SNDK", "WDC"]
PORT = 5690

TARGETS = [
    {"key": "MU", "label": "美光 MU", "cur": "$"},
    {"key": "SNDK", "label": "闪迪 SNDK", "cur": "$"},
    {"key": "WDC", "label": "西数 WDC", "cur": "$"},
    {"key": "SK_HYNIX", "label": "SK海力士", "cur": "₩"},
    {"key": "SAMSUNG", "label": "三星电子", "cur": "₩"},
]
SUB_COLS = ["turnover", "vol_share", "extension", "momentum", "rsi", "volatility", "basket_corr"]

STALE_SECONDS = 6 * 3600
CHECK_INTERVAL = 30 * 60

app = Flask(__name__, static_folder="static")

_refresh_lock = threading.Lock()
_state = {"refreshing": False, "last_refresh": None, "last_error": None}


# ---------------- 数据刷新 ----------------

def _run(script, *args):
    r = subprocess.run(
        [sys.executable, "-X", "utf8", os.path.join(HERE, script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=HERE, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{script} 失败: {(r.stderr or r.stdout)[-500:]}")


def refresh_pipeline():
    if not _refresh_lock.acquire(blocking=False):
        return  # 已有刷新在跑
    _state["refreshing"] = True
    _state["last_error"] = None
    try:
        warnings = []
        _run("fetch_data.py")
        try:
            _run("fetch_sk_hynix_foreign_flow.py", "--skip-freshness-check")
        except Exception as e:  # 补充数据失败时沿用种子CSV
            warnings.append(f"SK海力士外资流向失败(已沿用上次数据): {e}")
        _run("crowding_engine.py")
        _run("theme_index.py")
        try:
            _run("options_snapshot.py", "MU", "SNDK", "WDC")
        except Exception as e:  # 期权源偶发失败不影响主数据
            warnings.append(f"期权快照失败(主数据正常): {e}")
        _state["last_error"] = "; ".join(warnings) if warnings else None
        _state["last_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        _state["last_error"] = str(e)
    finally:
        _state["refreshing"] = False
        _refresh_lock.release()


def data_age_seconds():
    f = os.path.join(OUT_DIR, "theme_index.csv")
    if not os.path.exists(f):
        return 1e9
    return time.time() - os.path.getmtime(f)


def auto_refresh_loop():
    while True:
        try:
            if data_age_seconds() > STALE_SECONDS:
                refresh_pipeline()
        except Exception:
            pass
        time.sleep(CHECK_INTERVAL)


# ---------------- 数据组装 ----------------

def load_stock(key):
    df = pd.read_csv(os.path.join(OUT_DIR, f"crowding_{key}.csv"),
                     parse_dates=["date"]).set_index("date")
    return df


def status_of(score):
    if pd.isna(score):
        return "na"
    if score >= 85:
        return "red"
    if score >= 75:
        return "orange"
    if score >= 60:
        return "yellow"
    return "green"


def tci_status(v):
    if v >= 80:
        return "red"
    if v >= 70:
        return "orange"
    if v >= 55:
        return "yellow"
    return "green"


def _json_float(value, digits=2):
    return round(float(value), digits) if pd.notna(value) else None


def assemble_foreign_flow(quote_asof=None):
    """组装 SK 海力士 ALL（KRX+NXT）及分市场外资流向。"""
    if not os.path.exists(FOREIGN_FLOW_FILE):
        return None

    df = pd.read_csv(FOREIGN_FLOW_FILE, dtype={"ticker": str})
    required = {
        "date",
        "market",
        "foreign_net_shares",
        "foreign_holding_ratio_pct",
    }
    if not required.issubset(df.columns):
        return None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in [
        "foreign_net_shares",
        "institution_net_shares",
        "individual_net_shares",
        "foreign_holding_ratio_pct",
        "close_krw",
        "volume_shares",
    ]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df = (
        df.dropna(subset=["date", "foreign_net_shares"])
        .sort_values(["date", "market"])
        .drop_duplicates(["date", "market"], keep="last")
    )
    if df.empty:
        return None

    market_frames = {
        market: df[df["market"] == market].sort_values("date")
        for market in ["ALL", "KRX", "NXT"]
    }
    if market_frames["ALL"].empty:
        return None

    primary = market_frames["ALL"]
    latest = primary.iloc[-1]
    ratio_change = None
    if (
        len(primary) >= 2
        and pd.notna(latest.get("foreign_holding_ratio_pct"))
        and pd.notna(primary.iloc[-2].get("foreign_holding_ratio_pct"))
    ):
        ratio_change = round(float(
            latest["foreign_holding_ratio_pct"]
            - primary.iloc[-2]["foreign_holding_ratio_pct"]
        ), 2)

    chart_df = primary.tail(90)
    recent_df = primary.tail(10).iloc[::-1]
    quote_date = pd.to_datetime(quote_asof, errors="coerce") if quote_asof else pd.NaT
    stale = bool(pd.notna(quote_date) and latest["date"].normalize() < quote_date.normalize())

    def int_or_none(row, column):
        value = row.get(column)
        return int(value) if pd.notna(value) else None

    def market_summary(market):
        selected = market_frames[market]
        if selected.empty:
            return None
        row = selected.iloc[-1]
        indexed_flow = selected.set_index("date")["foreign_net_shares"]

        def aligned_sum(days):
            values = indexed_flow.reindex(primary["date"].tail(days))
            if values.isna().any():
                return None
            return int(values.sum())

        return {
            "market": market,
            "asof": row["date"].strftime("%Y-%m-%d"),
            "latest_net_shares": int(row["foreign_net_shares"]),
            "sum_5d_net_shares": aligned_sum(5),
            "sum_20d_net_shares": aligned_sum(20),
        }

    def align_market(market, dates):
        selected = market_frames[market].set_index("date")["foreign_net_shares"]
        return [
            int(value) if pd.notna(value) else None
            for value in selected.reindex(dates)
        ]

    indexed = {
        market: frame.set_index("date")
        for market, frame in market_frames.items()
    }

    def recent_record(row):
        flow_date = row["date"]
        krx = indexed["KRX"].loc[flow_date] if flow_date in indexed["KRX"].index else None
        nxt = indexed["NXT"].loc[flow_date] if flow_date in indexed["NXT"].index else None
        return {
            "date": flow_date.strftime("%m-%d"),
            "foreign_net_shares": int(row["foreign_net_shares"]),
            "total_net_shares": int(row["foreign_net_shares"]),
            "krx_net_shares": int_or_none(krx, "foreign_net_shares")
            if krx is not None else None,
            "nxt_net_shares": int_or_none(nxt, "foreign_net_shares")
            if nxt is not None else None,
            "holding_ratio_pct": _json_float(
                row.get("foreign_holding_ratio_pct")
            ),
            "close_krw": int_or_none(krx, "close_krw")
            if krx is not None else None,
        }

    venues = {
        market: market_summary(market)
        for market in ["ALL", "KRX", "NXT"]
    }
    check_dates = primary["date"].tail(20)
    check_all = primary.set_index("date")["foreign_net_shares"].reindex(
        check_dates
    )
    check_krx = market_frames["KRX"].set_index("date")[
        "foreign_net_shares"
    ].reindex(check_dates)
    check_nxt = market_frames["NXT"].set_index("date")[
        "foreign_net_shares"
    ].reindex(check_dates)
    latest_component_ok = bool(
        venues["KRX"]
        and venues["NXT"]
        and venues["KRX"]["asof"] == venues["ALL"]["asof"]
        and venues["NXT"]["asof"] == venues["ALL"]["asof"]
        and not check_krx.isna().any()
        and not check_nxt.isna().any()
        and (check_all == check_krx + check_nxt).all()
    )

    return {
        "ticker": str(latest.get("ticker", "000660")).zfill(6),
        "label": "SK海力士",
        "market": "ALL",
        "market_label": "全市场（KRX+NXT）",
        "source": str(latest.get("source", "Naver Finance")),
        "source_url": str(latest.get(
            "source_url",
            "https://m.stock.naver.com/domestic/stock/000660/"
            "tradingTrend?marketType=ALL",
        )),
        "asof": latest["date"].strftime("%Y-%m-%d"),
        "quote_asof": quote_date.strftime("%Y-%m-%d") if pd.notna(quote_date) else None,
        "stale": stale,
        "latest_net_shares": int(latest["foreign_net_shares"]),
        "latest_direction": "inflow" if latest["foreign_net_shares"] > 0 else (
            "outflow" if latest["foreign_net_shares"] < 0 else "flat"
        ),
        "sum_5d_net_shares": int(
            primary["foreign_net_shares"].tail(5).sum()
        ),
        "sum_20d_net_shares": int(
            primary["foreign_net_shares"].tail(20).sum()
        ),
        "latest_holding_ratio_pct": _json_float(
            latest.get("foreign_holding_ratio_pct")
        ),
        "holding_ratio_change_pp": ratio_change,
        "venues": venues,
        "latest_component_ok": latest_component_ok,
        "value_basis": "shares",
        "expected_update_beijing": "19:30",
        "series": {
            "dates": [d.strftime("%y/%m/%d") for d in chart_df["date"]],
            "net_shares": [int(v) for v in chart_df["foreign_net_shares"]],
            "krx_net_shares": align_market("KRX", chart_df["date"]),
            "nxt_net_shares": align_market("NXT", chart_df["date"]),
            "holding_ratio_pct": [
                _json_float(v) for v in chart_df["foreign_holding_ratio_pct"]
            ],
        },
        "recent": [recent_record(row) for _, row in recent_df.iterrows()],
    }


def assemble_iv_history():
    """存储股ATM IV历史(来自每日快照积累), 近一年窗口。"""
    if not os.path.exists(IV_HISTORY_FILE):
        return None
    df = pd.read_csv(IV_HISTORY_FILE, parse_dates=["date"])
    df = df.dropna(subset=["date"]).sort_values("date")
    if df.empty:
        return None
    df = df[df["date"] >= df["date"].max() - pd.Timedelta(days=370)]
    dates = sorted(df["date"].unique())
    series = {}
    for tk in IV_TICKERS:
        sub = df[df["ticker"] == tk].set_index("date")["atm_iv_pct"].reindex(dates)
        series[tk] = [_json_float(v, 1) for v in sub]
    return {
        "dates": [pd.Timestamp(d).strftime("%y/%m/%d") for d in dates],
        "series": series,
    }


def assemble_dashboard():
    stocks = []
    score_series = {}
    rv_series = {}
    vol_pct_frames = {}
    close_frames = {}
    dates_union = None

    for t in TARGETS:
        df = load_stock(t["key"])
        last = df.iloc[-1]
        prev_close = df["close"].iloc[-2] if len(df) > 1 else np.nan
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        armed = bool(df["score"].rolling(15, min_periods=1).max().iloc[-1] >= 85)
        below = bool(last["close"] < ma20)
        hi250 = df["close"].rolling(250, min_periods=60).max().iloc[-1]

        subs = {}
        for c in SUB_COLS:
            v = last.get(c)
            subs[c] = round(float(v), 0) if pd.notna(v) else None

        rv = last.get("raw_realized_vol20")
        rv_1y = df["raw_realized_vol20"].dropna()
        rv_1y = rv_1y[rv_1y.index >= rv_1y.index[-1] - pd.Timedelta(days=370)]

        stocks.append({
            "key": t["key"],
            "label": t["label"],
            "cur": t["cur"],
            "date": df.index[-1].strftime("%Y-%m-%d"),
            "close": float(last["close"]),
            "chg_pct": round(float(last["close"] / prev_close - 1) * 100, 2) if pd.notna(prev_close) else None,
            "score": round(float(last["score"]), 1) if pd.notna(last["score"]) else None,
            "status": status_of(last["score"]),
            "subs": subs,
            "rv20": round(float(rv), 1) if pd.notna(rv) else None,
            "rv_1y_max": round(float(rv_1y.max()), 1) if len(rv_1y) else None,
            "rv_1y_med": round(float(rv_1y.median()), 1) if len(rv_1y) else None,
            "armed": armed,
            "below_ma20": below,
            "triggered": bool(armed and below),
            "dd_from_high": round(float(last["close"] / hi250 - 1) * 100, 1) if pd.notna(hi250) else None,
        })

        s = df["score"].dropna()
        s = s[s.index >= s.index[-1] - pd.Timedelta(days=285)]
        score_series[t["key"]] = {d.strftime("%y/%m/%d"): round(v, 1) for d, v in s.items()}
        idx = set(score_series[t["key"]].keys())
        dates_union = idx if dates_union is None else (dates_union | idx)

        rv_s = df["raw_realized_vol20"].dropna()
        rv_s = rv_s[rv_s.index >= rv_s.index[-1] - pd.Timedelta(days=285)]
        rv_series[t["key"]] = {d.strftime("%y/%m/%d"): round(v, 1) for d, v in rv_s.items()}

        vol_pct_frames[t["key"]] = df["volatility"]
        close_frames[t["key"]] = df["close"]

    score_dates = sorted(dates_union)
    score_chart = {
        "dates": score_dates,
        "series": {k: [score_series[k].get(d) for d in score_dates] for k in score_series},
    }
    rv_dates = sorted(set().union(*[set(v.keys()) for v in rv_series.values()]))
    rv_chart = {
        "dates": rv_dates,
        "series": {k: [rv_series[k].get(d) for d in rv_dates] for k in rv_series},
    }

    # 篮子波动率百分位均值(余震指标): <80 = 余震平息
    vp = pd.DataFrame(vol_pct_frames).sort_index().ffill(limit=3).mean(axis=1).dropna()
    vp_sel = vp[vp.index >= vp.index[-1] - pd.Timedelta(days=370)]
    vol_pct_chart = {
        "dates": [d.strftime("%y/%m/%d") for d in vp_sel.index],
        "values": [round(v, 1) for v in vp_sel],
    }
    vol_pct_now = round(float(vp.iloc[-1]), 0)

    tdf = pd.read_csv(os.path.join(OUT_DIR, "theme_index.csv"),
                      parse_dates=["date"]).set_index("date")
    tlast = tdf.iloc[-1]
    tsel = tdf[tdf.index >= tdf.index[-1] - pd.Timedelta(days=380)]

    # 各标的价格归一化(窗口起点=100), 对齐TCI日期; 跨市场休市日用前值填充
    price_series = {}
    for key, close in close_frames.items():
        aligned = close.reindex(tsel.index).ffill(limit=5)
        base = aligned.dropna()
        if base.empty:
            continue
        norm = aligned / base.iloc[0] * 100
        price_series[key] = [round(v, 1) if pd.notna(v) else None for v in norm]

    tci = {
        "date": tdf.index[-1].strftime("%Y-%m-%d"),
        "value": round(float(tlast["tci"]), 1),
        "status": tci_status(float(tlast["tci"])),
        "level": round(float(tlast["level"]), 1),
        "breadth_pct": round(float(tlast["breadth_pct"]), 0),
        "persistence": round(float(tlast["persistence"]), 0),
        "chart": {
            "dates": [d.strftime("%y/%m/%d") for d in tsel.index],
            "values": [round(v, 1) if pd.notna(v) else None for v in tsel["tci"]],
            "prices": price_series,
        },
        "recent": [
            {"date": d.strftime("%m-%d"), "value": round(v, 1)}
            for d, v in tdf["tci"].tail(6).items()
        ],
    }

    options = []
    opt_file = os.path.join(OUT_DIR, "options_snapshot.json")
    if os.path.exists(opt_file):
        with open(opt_file, encoding="utf-8") as f:
            options = json.load(f)

    n_red = sum(1 for s in stocks if s["status"] == "red")
    n_triggered = sum(1 for s in stocks if s["triggered"])
    breadth_n = sum(1 for s in stocks if (s["score"] or 0) >= 80)
    sk_hynix = next((s for s in stocks if s["key"] == "SK_HYNIX"), None)
    foreign_flow = assemble_foreign_flow(sk_hynix["date"] if sk_hynix else None)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_age_min": round(data_age_seconds() / 60),
        "refreshing": _state["refreshing"],
        "last_refresh": _state["last_refresh"],
        "last_error": _state["last_error"],
        "tci": tci,
        "stocks": stocks,
        "score_chart": score_chart,
        "rv_chart": rv_chart,
        "vol_pct_chart": vol_pct_chart,
        "vol_pct_now": vol_pct_now,
        "options": options,
        "iv_chart": assemble_iv_history(),
        "foreign_flow": foreign_flow,
        "summary": {"n_red": n_red, "n_triggered": n_triggered, "breadth": breadth_n},
    }


# ---------------- 路由 ----------------

@app.route("/api/dashboard")
def api_dashboard():
    try:
        return jsonify(assemble_dashboard())
    except Exception as e:
        return jsonify({"error": str(e), "refreshing": _state["refreshing"]}), 500


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if _state["refreshing"]:
        return jsonify({"started": False, "refreshing": True})
    threading.Thread(target=refresh_pipeline, daemon=True).start()
    return jsonify({"started": True, "refreshing": True})


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    threading.Thread(target=auto_refresh_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)
