# -*- coding: utf-8 -*-
"""验证拥挤度信号的实战价值。

1. 信号时间线: 每个标的首次进入红区(>=85)的日期 vs 6.25回撤起点
2. 命中率: 近高点状态下 P(未来20日最大回撤<=-15%) 按分数分档
3. 规则回测: "红区退出"策略 vs 买入持有 (2023-01至今)
   规则: 昨日score>=85且价格距250日高点15%以内 -> 今日空仓; score回落<70 -> 恢复持仓
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")

TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]


def load_scores(name):
    return pd.read_csv(os.path.join(OUT_DIR, f"crowding_{name}.csv"),
                       parse_dates=["date"]).set_index("date")


def hit_rate(out: pd.DataFrame, horizon: int = 20, dd_cut: float = -15.0):
    c = out["close"]
    v = c.values
    fwd = []
    for i in range(len(v)):
        end = min(i + horizon + 1, len(v))
        if end - i < 5:
            fwd.append(np.nan)
            continue
        fwd.append((v[i:end].min() / v[i] - 1) * 100)
    df = pd.DataFrame({
        "score": out["score"],
        "fwd": fwd,
        "near": c / c.rolling(250, min_periods=60).max() >= 0.85,
    }, index=out.index).dropna()
    df = df[df["near"]]
    bins = [0, 60, 75, 85, 101]
    labels = ["<60", "60-75", "75-85", ">=85"]
    df["bucket"] = pd.cut(df["score"], bins=bins, labels=labels, right=False)
    g = df.groupby("bucket", observed=True)["fwd"]
    return pd.DataFrame({
        "days": g.count(),
        f"P(20日内回撤<={dd_cut:.0f}%)": (g.apply(lambda x: (x <= dd_cut).mean()) * 100).round(1),
    })


def regime_backtest(out: pd.DataFrame, start="2023-01-01", arm=85.0,
                    arm_lookback=15, reduced=0.5, disarm=60.0):
    """两段式规则: "拥挤武装 + 趋势破位" 才降仓。

    armed: 过去arm_lookback日内综合分曾>=arm (拥挤状态"武装")
    crack: 收盘跌破20日均线
    armed且crack -> 仓位降到reduced; 收盘收复20日均线 或 分数<disarm -> 恢复满仓
    """
    df = out.loc[start:].copy()
    ret = df["close"].pct_change().fillna(0)
    ma20 = df["close"].rolling(20).mean()
    armed = df["score"].rolling(arm_lookback, min_periods=1).max() >= arm
    below = df["close"] < ma20

    pos, cur = [], 1.0
    for i in range(len(df)):
        if i == 0:
            pos.append(cur)
            continue
        # 用前一日信号决定今日仓位(避免前视)
        if armed.iloc[i - 1] and below.iloc[i - 1]:
            cur = reduced
        elif (not below.iloc[i - 1]) or (pd.notna(df["score"].iloc[i - 1]) and df["score"].iloc[i - 1] < disarm):
            cur = 1.0
        pos.append(cur)
    df["pos"] = pos
    df["strat_ret"] = ret * df["pos"]

    def stats(r):
        eq = (1 + r).cumprod()
        dd = (eq / eq.cummax() - 1).min() * 100
        total = (eq.iloc[-1] - 1) * 100
        return total, dd

    bh_total, bh_dd = stats(ret)
    st_total, st_dd = stats(df["strat_ret"])
    reduced_pct = (df["pos"] < 1.0).mean() * 100
    return {
        "买入持有_总收益%": round(bh_total, 0),
        "买入持有_最大回撤%": round(bh_dd, 1),
        "策略_总收益%": round(st_total, 0),
        "策略_最大回撤%": round(st_dd, 1),
        "降仓时间占比%": round(reduced_pct, 1),
    }, df[["close", "score", "pos"]]


def first_red_dates(out: pd.DataFrame, since="2026-04-01"):
    df = out.loc[since:]
    red = df[(df["score"] >= 85)]
    return red.index[0].strftime("%Y-%m-%d") if len(red) else None


def main():
    print("=" * 80)
    print("1) 2026年4月以来首次进入红区(score>=85)的日期  [回撤起点: 韩股6/23崩盘, 美股6/25见顶]")
    for name in TARGETS:
        out = load_scores(name)
        print(f"   {name:10s}: {first_red_dates(out)}")

    print()
    print("=" * 80)
    print("2) 近高点状态下, 未来20日出现>=15%回撤的概率:")
    for name in TARGETS:
        out = load_scores(name)
        print(f"\n[{name}]")
        print(hit_rate(out).to_string())

    print()
    print("=" * 80)
    print("3) 规则回测 2023-01至今: [15日内分数曾>=85 且 跌破MA20] -> 半仓; 收复MA20或分数<60 -> 满仓")
    rows = {}
    for name in TARGETS:
        out = load_scores(name)
        res, detail = regime_backtest(out)
        rows[name] = res
        detail.round(3).to_csv(os.path.join(OUT_DIR, f"regime_{name}.csv"))
    print(pd.DataFrame(rows).T.to_string())


if __name__ == "__main__":
    main()
