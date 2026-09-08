"""SOXX/IGV rotation: paired daily closes, independent of TCI scoring."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import os
import tempfile

import numpy as np
import pandas as pd
import requests
from us_market_calendar import completed_daily_rows, market_context

HERE = Path(__file__).resolve().parent
CACHE_FILE = HERE / "data" / "SOXX_IGV.csv"
SOURCE = "Yahoo Finance daily close"


def clean_close(frame, column="close"):
    data = frame[["date", column]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna().sort_values("date").drop_duplicates("date", keep="last")
    return data[np.isfinite(data[column]) & (data[column] > 0)].set_index("date")[column]


def fetch_close(symbol):
    """Only completed daily bars; both legs use the same provider and basis."""
    errors = []
    for host in ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]:
        try:
            response = requests.get(
                f"https://{host}/v8/finance/chart/{symbol}",
                params={"range": "2y", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=25,
            )
            response.raise_for_status()
            result = response.json()["chart"]["result"][0]
            stamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
            rows = completed_daily_rows(stamps, closes)
            series = clean_close(pd.DataFrame(rows, columns=["date", "close"]))
            if len(series) < 61:
                raise ValueError(f"{symbol}: fewer than 61 valid completed sessions")
            return series
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as exc:
            errors.append(str(exc))
    raise RuntimeError(f"{symbol} daily prices unavailable: {'; '.join(errors)}")


def refresh_cache(path=CACHE_FILE):
    with ThreadPoolExecutor(max_workers=2) as pool:
        soxx, igv = list(pool.map(fetch_close, ["SOXX", "IGV"]))
    if soxx.index[-1] != igv.index[-1]:
        raise ValueError("SOXX/IGV latest dates differ; retaining previous paired cache")
    paired = pd.concat([soxx.rename("soxx"), igv.rename("igv")], axis=1, join="inner").dropna()
    if len(paired) < 61:
        raise ValueError("Not enough common sessions; retaining previous cache")
    path = Path(path)
    if path.exists():
        old = pd.read_csv(path)
        old_dates = pd.to_datetime(old.get("date"), errors="coerce")
        if old_dates.max() > paired.index[-1]:
            raise ValueError("Provider returned older data; retaining newer cache")
    paired["source"] = SOURCE
    paired["fetched_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace both legs together, so a dashboard read cannot see a partial pair.
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
        tmp = Path(handle.name)
    try:
        paired.to_csv(tmp, index_label="date")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return paired


def build_relative_strength(frame, now=None):
    soxx, igv = clean_close(frame, "soxx"), clean_close(frame, "igv")
    prices = pd.concat([soxx.rename("soxx"), igv.rename("igv")], axis=1, join="inner").dropna()
    if prices.empty:
        raise ValueError("No common valid positive closes")
    ratio = prices.soxx / prices.igv
    ma20, ma60 = ratio.rolling(20).mean(), ratio.rolling(60).mean()
    end = prices.index[-1]
    selected = prices[prices.index >= end - pd.DateOffset(years=1)]
    window_ratio = ratio.reindex(selected.index)
    base = window_ratio.iloc[0]
    market = market_context(end, now=now)
    fetched = pd.to_datetime(frame["fetched_at"], utc=True, errors="coerce").max() if "fetched_at" in frame else pd.NaT

    def number(value, digits=4):
        return round(float(value), digits) if pd.notna(value) and np.isfinite(value) else None

    def change(days):
        return number((ratio.iloc[-1] / ratio.iloc[-days-1] - 1) * 100, 2) if len(ratio) > days else None

    summary = {
        "ratio": number(ratio.iloc[-1]), "index": number(ratio.iloc[-1] / base * 100, 2),
        "ma20": number(ma20.iloc[-1]), "ma60": number(ma60.iloc[-1]),
        "above_ma20": bool(ratio.iloc[-1] > ma20.iloc[-1]) if pd.notna(ma20.iloc[-1]) else None,
        "above_ma60": bool(ratio.iloc[-1] > ma60.iloc[-1]) if pd.notna(ma60.iloc[-1]) else None,
        "change_5d_pct": change(5), "change_20d_pct": change(20), "change_60d_pct": change(60),
    }
    return {
        "available": True, "asof": end.strftime("%Y-%m-%d"),
        "stale": market["missing_sessions"] > 0,
        "market": market,
        "fetched_at": fetched.isoformat() if pd.notna(fetched) else None,
        "source": str(frame["source"].iloc[-1]) if "source" in frame else SOURCE,
        "basis": "日线收盘价比值，不含分红再投资；不是RSI或估值指标",
        "base_date": selected.index[0].strftime("%Y-%m-%d"),
        "summary": summary,
        "series": {
            "dates": selected.index.strftime("%Y-%m-%d").tolist(),
            "ratio": [number(v) for v in window_ratio],
            "index": [number(v / base * 100) for v in window_ratio],
            "ma20": [number(v / base * 100) for v in ma20.reindex(selected.index)],
            "ma60": [number(v / base * 100) for v in ma60.reindex(selected.index)],
            "soxx": [number(v) for v in selected.soxx],
            "igv": [number(v) for v in selected.igv],
        },
    }


def assemble_relative_strength(path=CACHE_FILE, now=None):
    try:
        return build_relative_strength(pd.read_csv(path), now=now)
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as exc:
        return {"available": False, "error": f"SOXX/IGV数据暂不可用：{exc}"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args()
    if not args.no_fetch:
        refresh_cache()
    result = assemble_relative_strength()
    if not result["available"]:
        raise SystemExit(result["error"])
    print(f"SOXX/IGV {result['asof']}: {result['summary']}")
