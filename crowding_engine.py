# -*- coding: utf-8 -*-
"""AI硬件股交易拥挤度引擎。

从日线OHLCV计算6个可回测的拥挤度子指标, 合成0-100综合拥挤度分数。

子指标(除RSI/相关性本身有界外, 均转为滚动历史百分位0-100):
  1. turnover    成交额热度: 20日平均美元成交额 / 250日平均美元成交额
  2. vol_share   成交额占比: 20日平均成交额占同市场篮子总成交额比重(中金式拥挤度)
  3. extension   价格偏离: 收盘价相对50日均线的偏离幅度
  4. momentum    动量过热: 60日累计收益率
  5. rsi         RSI(14)
  6. volatility  波动放大: 20日已实现波动率(年化) —— 高位放量+波动抬升是典型末段特征
  7. basket_corr 篮子共振: 存储篮子20日平均两两相关系数(全篮子共用)

综合分 = 加权平均(权重WEIGHTS, 对当日缺失的子项自动按剩余权重归一)。
经验分区: >=85 红色(拥挤极值), 75-85 橙色(过热), 60-75 黄色(偏热), <60 正常。

验证方法:
  A. 顶部捕获: 找出历史上所有"随后40个交易日内回撤>=18%"的局部顶,
     看顶部前5日内综合分最高值 —— 高分是否是重大顶部的必要条件。
  B. 红区风险: 比较 分数>=85 与 60-85 两种状态下未来20日最大回撤分布
     (都排除已深跌状态, 只看距250日高点15%以内的日子, 避免"低分=刚崩完"的偏差)。
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OUT_DIR = os.path.join(HERE, "out")
os.makedirs(OUT_DIR, exist_ok=True)

TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]
BASKET = ["MU", "SNDK", "WDC", "STX", "SK_HYNIX", "SAMSUNG"]
# 成交额占比的分母: 美股用SPY美元成交额, 韩股用KOSPI指数点位x成交量作市场活跃度代理
MARKET_PROXY = {
    "MU": "SPY", "SNDK": "SPY", "WDC": "SPY", "STX": "SPY",
    "SK_HYNIX": "KOSPI", "SAMSUNG": "KOSPI",
}

PCT_WINDOW = 500

WEIGHTS = {
    "turnover": 0.15,
    "vol_share": 0.10,
    "extension": 0.20,
    "momentum": 0.15,
    "rsi": 0.10,
    "volatility": 0.15,
    "basket_corr": 0.15,
}


def load(name: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA_DIR, f"{name}.csv"), parse_dates=["date"])
    df = df.sort_values("date").set_index("date")
    df["dollar_vol"] = df["close"] * df["volume"]
    df["ret"] = df["close"].pct_change()
    df["log_ret"] = np.log(df["close"]).diff()
    return df


def rolling_pctile(s: pd.Series, window: int = PCT_WINDOW, min_periods: int = 250) -> pd.Series:
    def pct(x):
        x = x[~np.isnan(x)]
        if len(x) < 30:
            return np.nan
        return (x[:-1] <= x[-1]).mean() * 100

    return s.rolling(window, min_periods=min_periods).apply(pct, raw=True)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


def basket_avg_corr(rets: pd.DataFrame, window: int = 20) -> pd.Series:
    """篮子20日平均两两相关系数。

    各市场交易日历不同: 每对在两者共同交易日上算滚动相关,
    再reindex回全日历并前向填充(限5日), 避免单一市场休市造成整段NaN。
    """
    cols = list(rets.columns)
    full_idx = rets.index
    corrs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pair = rets[[cols[i], cols[j]]].dropna()
            if len(pair) < window + 5:
                continue
            c = pair.iloc[:, 0].rolling(window, min_periods=window).corr(pair.iloc[:, 1])
            corrs.append(c.reindex(full_idx).ffill(limit=5))
    return pd.concat(corrs, axis=1).mean(axis=1)


def compute_stock(name: str, corr_series: pd.Series) -> pd.DataFrame:
    df = load(name)
    short_history = len(df) < 500
    min_p = 120 if short_history else 250

    raw = pd.DataFrame(index=df.index)
    raw["turnover_ratio"] = (
        df["dollar_vol"].rolling(20).mean()
        / df["dollar_vol"].rolling(250, min_periods=60).mean()
    )
    # 成交额占比: 相对市场基准的成交热度(市场整体放量时不误报)
    proxy = MARKET_PROXY.get(name)
    if proxy and os.path.exists(os.path.join(DATA_DIR, f"{proxy}.csv")):
        mkt = load(proxy)["dollar_vol"].reindex(df.index).ffill(limit=3)
        raw["vol_share"] = (
            df["dollar_vol"].rolling(20).mean() / mkt.rolling(20).mean()
        )
    else:
        raw["vol_share"] = np.nan
    raw["extension"] = df["close"] / df["close"].rolling(50).mean() - 1
    raw["momentum_60d"] = df["close"].pct_change(60)
    raw["rsi14"] = rsi(df["close"])
    raw["realized_vol20"] = df["log_ret"].rolling(20).std() * np.sqrt(252) * 100
    raw["basket_corr"] = corr_series.reindex(df.index).ffill(limit=5)

    sub = pd.DataFrame(index=df.index)
    sub["turnover"] = rolling_pctile(raw["turnover_ratio"], min_periods=min_p)
    sub["vol_share"] = rolling_pctile(raw["vol_share"], min_periods=min_p)
    sub["extension"] = rolling_pctile(raw["extension"], min_periods=min_p)
    sub["momentum"] = rolling_pctile(raw["momentum_60d"], min_periods=min_p)
    sub["rsi"] = raw["rsi14"]
    sub["volatility"] = rolling_pctile(raw["realized_vol20"], min_periods=min_p)
    sub["basket_corr"] = raw["basket_corr"] * 100

    # 加权平均, 对缺失子项按剩余权重归一
    w = pd.Series(WEIGHTS)
    weighted = sub[list(WEIGHTS)].mul(w, axis=1)
    avail_w = sub[list(WEIGHTS)].notna().mul(w, axis=1).sum(axis=1)
    score = weighted.sum(axis=1, min_count=3) / avail_w

    out = sub.copy()
    out["score"] = score
    out["close"] = df["close"]
    out["dollar_vol"] = df["dollar_vol"]
    for c in raw.columns:
        out[f"raw_{c}"] = raw[c]
    return out


def find_major_tops(close: pd.Series, dd_threshold: float = -0.18, horizon: int = 40,
                    sep: int = 30) -> list:
    """局部顶: 该日为其前后10日最高价, 且随后horizon日内最大回撤 <= dd_threshold。"""
    c = close.values
    tops = []
    for i in range(10, len(c) - 5):
        if c[i] != c[max(0, i - 10): i + 11].max():
            continue
        seg = c[i: min(i + horizon + 1, len(c))]
        if seg.min() / seg[0] - 1 <= dd_threshold:
            if tops and i - tops[-1] < sep:
                if c[i] > c[tops[-1]]:
                    tops[-1] = i
                continue
            tops.append(i)
    return [close.index[i] for i in tops]


def validate(name: str, out: pd.DataFrame) -> pd.DataFrame:
    """顶部捕获表: 每个重大顶的日期、随后40日实际最大回撤、顶前5日最高分。"""
    tops = find_major_tops(out["close"])
    rows = []
    for t in tops:
        i = out.index.get_loc(t)
        seg = out["close"].iloc[i: i + 41]
        dd = (seg.min() / seg.iloc[0] - 1) * 100
        pre = out["score"].iloc[max(0, i - 5): i + 1]
        rows.append({
            "top_date": t.strftime("%Y-%m-%d"),
            "close": out["close"].loc[t],
            "fwd40d_maxdd_pct": round(dd, 1),
            "score_at_top": round(out["score"].loc[t], 1) if pd.notna(out["score"].loc[t]) else None,
            "score_max_pre5d": round(pre.max(), 1) if pre.notna().any() else None,
        })
    return pd.DataFrame(rows)


def red_zone_stats(out: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    """距250日高点15%以内的日子里, 按分数分档统计未来20日最大回撤。"""
    c = out["close"]
    fwd_dd = []
    v = c.values
    for i in range(len(v)):
        end = min(i + horizon + 1, len(v))
        if end - i < 5:
            fwd_dd.append(np.nan)
            continue
        seg = v[i:end]
        fwd_dd.append((seg.min() / seg[0] - 1) * 100)
    df = pd.DataFrame({
        "score": out["score"],
        "fwd_dd": fwd_dd,
        "near_high": c / c.rolling(250, min_periods=60).max() >= 0.85,
    }, index=out.index).dropna()
    df = df[df["near_high"]]
    bins = [0, 60, 75, 85, 101]
    labels = ["<60", "60-75", "75-85", ">=85"]
    df["bucket"] = pd.cut(df["score"], bins=bins, labels=labels, right=False)
    g = df.groupby("bucket", observed=True)["fwd_dd"]
    return pd.DataFrame({
        "days": g.count(),
        "median_fwd_maxdd": g.median().round(2),
        "p10_fwd_maxdd": g.quantile(0.10).round(2),
        "worst_fwd_maxdd": g.min().round(2),
    })


def main():
    rets = {}
    for name in BASKET:
        f = os.path.join(DATA_DIR, f"{name}.csv")
        if os.path.exists(f):
            rets[name] = load(name)["ret"]
    corr = basket_avg_corr(pd.DataFrame(rets))
    corr.rename("basket_corr").to_csv(os.path.join(OUT_DIR, "basket_corr.csv"))

    all_out = {}
    for name in TARGETS:
        out = compute_stock(name, corr)
        out.round(4).to_csv(os.path.join(OUT_DIR, f"crowding_{name}.csv"))
        all_out[name] = out

    # 主题级拥挤度: 五标的综合分均值
    theme = pd.DataFrame({n: o["score"] for n, o in all_out.items()}).ffill(limit=3)
    theme["THEME"] = theme.mean(axis=1)
    theme.round(2).to_csv(os.path.join(OUT_DIR, "theme_score.csv"))

    for name, out in all_out.items():
        print("=" * 90)
        print(f"[{name}] 顶部捕获验证 (随后40日回撤>=18%的重大顶):")
        vt = validate(name, out)
        print(vt.to_string(index=False) if len(vt) else "  (无重大顶)")
        print(f"\n[{name}] 近高点状态下 分数 vs 未来20日最大回撤:")
        print(red_zone_stats(out).to_string())
        print(f"\n[{name}] 最近12个交易日:")
        cols = ["close", "score", "turnover", "vol_share", "extension", "momentum", "rsi", "volatility", "basket_corr"]
        print(out[cols].tail(12).round(1).to_string())
        print()

    print("=" * 90)
    print("6月事件窗口 主题及个股综合拥挤度:")
    print(theme.loc["2026-05-25":].round(1).to_string())


if __name__ == "__main__":
    main()
