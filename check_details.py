# -*- coding: utf-8 -*-
"""细节验证: 1) armed+MA10破位的触发日期(6月事件) 2) 主题分极值 3) DRAM ETF热度 4) MA10规则回测"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
DATA_DIR = os.path.join(HERE, "data")
TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]


def load_scores(name):
    return pd.read_csv(os.path.join(OUT_DIR, f"crowding_{name}.csv"),
                       parse_dates=["date"]).set_index("date")


def crack_dates(name, arm=85, lookback=15, ma=10, since="2026-05-01"):
    out = load_scores(name)
    armed = out["score"].rolling(lookback, min_periods=1).max() >= arm
    ma_s = out["close"].rolling(ma).mean()
    trig = out[(armed) & (out["close"] < ma_s)].loc[since:]
    if len(trig) == 0:
        return None
    first = trig.index[0]
    px = out.loc[first, "close"]
    later = out.loc[first:, "close"]
    return {
        "name": name, "trigger_date": first.strftime("%Y-%m-%d"),
        "trigger_px": px,
        "low_after": later.min(),
        "saved_pct": round((later.min() / px - 1) * 100, 1),
        "px_now": later.iloc[-1],
        "now_vs_trigger%": round((later.iloc[-1] / px - 1) * 100, 1),
    }


def backtest_ma10(name, start="2023-06-01", arm=85.0, lookback=15, reduced=0.5, disarm=55.0):
    out = load_scores(name)
    df = out.loc[start:].copy()
    ret = df["close"].pct_change().fillna(0)
    ma = df["close"].rolling(10).mean()
    armed = df["score"].rolling(lookback, min_periods=1).max() >= arm
    below = df["close"] < ma

    pos, cur = [], 1.0
    for i in range(len(df)):
        if i == 0:
            pos.append(cur)
            continue
        s = df["score"].iloc[i - 1]
        if cur == 1.0 and armed.iloc[i - 1] and below.iloc[i - 1]:
            cur = reduced
        elif cur < 1.0 and not below.iloc[i - 1]:
            cur = 1.0
        pos.append(cur)
    df["pos"] = pos
    df["strat_ret"] = ret * df["pos"]

    def stats(r):
        eq = (1 + r).cumprod()
        return (eq.iloc[-1] - 1) * 100, (eq / eq.cummax() - 1).min() * 100

    bh_t, bh_d = stats(ret)
    st_t, st_d = stats(df["strat_ret"])
    return {"BH收益%": round(bh_t), "BH回撤%": round(bh_d, 1),
            "策略收益%": round(st_t), "策略回撤%": round(st_d, 1),
            "降仓占比%": round((df["pos"] < 1).mean() * 100, 1)}


print("1) 6月事件: [15日内曾>=85 且 收盘跌破MA10] 的首次触发日")
rows = [r for n in TARGETS if (r := crack_dates(n))]
print(pd.DataFrame(rows).to_string(index=False))

print("\n2) 主题综合分(5标的均值)历史分布:")
theme = pd.read_csv(os.path.join(OUT_DIR, "theme_score.csv"), parse_dates=["date"]).set_index("date")["THEME"].dropna()
print(f"   样本{len(theme)}天, 6/25读数={theme.loc['2026-06-25']:.1f}, "
      f"历史百分位={100 * (theme <= theme.loc['2026-06-25']).mean():.1f}%")
print(f"   >=80的天数占比={100 * (theme >= 80).mean():.1f}%, 最大值={theme.max():.1f} ({theme.idxmax():%Y-%m-%d})")
hist_80 = theme[theme >= 80]
print(f"   历史上主题分>=80的时段: {hist_80.index.min():%Y-%m-%d} ~ {hist_80.index.max():%Y-%m-%d}, 共{len(hist_80)}天")
# 按月分布
print((hist_80.groupby(hist_80.index.to_period('M')).count()).to_string())

print("\n3) DRAM ETF(主题工具)日均成交额趋势:")
dram = pd.read_csv(os.path.join(DATA_DIR, "DRAM.csv"), parse_dates=["date"]).set_index("date")
dram["dv"] = dram["close"] * dram["volume"] / 1e6
print(dram["dv"].resample("W").mean().round(1).to_string())

print("\n4) MA10破位规则回测 (arm=85):")
rows = {n: backtest_ma10(n) for n in TARGETS}
print(pd.DataFrame(rows).T.to_string())
