# -*- coding: utf-8 -*-
"""规则参数变体测试 + 红区首次触发事件研究。"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]


def load_scores(name):
    return pd.read_csv(os.path.join(OUT_DIR, f"crowding_{name}.csv"),
                       parse_dates=["date"]).set_index("date")


def backtest(out, start="2023-06-01", arm=80.0, arm_lookback=25, reduced=0.5, disarm=55.0):
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
        s = df["score"].iloc[i - 1]
        if cur == 1.0 and armed.iloc[i - 1] and below.iloc[i - 1]:
            cur = reduced
        elif cur < 1.0:
            # 恢复: 站回MA20 且 拥挤已释放(分数<disarm) —— 两者都要
            if (not below.iloc[i - 1]) and pd.notna(s) and s < disarm:
                cur = 1.0
            # 或者站回MA20且重新创出20日新高(趋势重新确认)
            elif not below.iloc[i - 1] and df["close"].iloc[i - 1] >= df["close"].iloc[max(0, i - 21):i].max():
                cur = 1.0
        pos.append(cur)
    df["pos"] = pos
    df["strat_ret"] = ret * df["pos"]

    def stats(r):
        eq = (1 + r).cumprod()
        dd = (eq / eq.cummax() - 1).min() * 100
        return (eq.iloc[-1] - 1) * 100, dd

    bh_t, bh_d = stats(ret)
    st_t, st_d = stats(df["strat_ret"])
    return {
        "BH收益%": round(bh_t), "BH回撤%": round(bh_d, 1),
        "策略收益%": round(st_t), "策略回撤%": round(st_d, 1),
        "降仓占比%": round((df["pos"] < 1).mean() * 100, 1),
    }


def first_cross_events(out, thr=85.0, cooloff=15):
    """首次上穿红区事件: 之前cooloff日内分数都<thr, 当日>=thr。"""
    s = out["score"]
    c = out["close"]
    events = []
    for i in range(cooloff, len(s)):
        if pd.isna(s.iloc[i]) or s.iloc[i] < thr:
            continue
        prev = s.iloc[i - cooloff:i].dropna()
        if len(prev) and (prev < thr).all():
            fwd20 = c.iloc[i: i + 21]
            fwd40 = c.iloc[i: i + 41]
            fwd60 = c.iloc[i: i + 61]
            events.append({
                "date": s.index[i].strftime("%Y-%m-%d"),
                "score": round(s.iloc[i], 1),
                "fwd20_maxdd%": round((fwd20.min() / c.iloc[i] - 1) * 100, 1),
                "fwd40_maxdd%": round((fwd40.min() / c.iloc[i] - 1) * 100, 1),
                "fwd60_maxdd%": round((fwd60.min() / c.iloc[i] - 1) * 100, 1) if len(fwd60) > 40 else None,
                "fwd40_ret%": round((fwd40.iloc[-1] / c.iloc[i] - 1) * 100, 1),
                "fwd40_maxgain%": round((fwd40.max() / c.iloc[i] - 1) * 100, 1),
            })
    return pd.DataFrame(events)


def main():
    print("=" * 90)
    print("A) 红区首次触发事件 (score首次>=85, 前15日均<85) —— 触发后20/40/60日内最大回撤:")
    all_ev = []
    for name in TARGETS:
        out = load_scores(name)
        ev = first_cross_events(out)
        if len(ev):
            ev.insert(0, "name", name)
            all_ev.append(ev)
    ev_df = pd.concat(all_ev, ignore_index=True)
    print(ev_df.to_string(index=False))
    ev_df.to_csv(os.path.join(OUT_DIR, "red_events.csv"), index=False)
    print(f"\n统计: {len(ev_df)}次触发, 40日内最大回撤中位数 {ev_df['fwd40_maxdd%'].median():.1f}%, "
          f"P(40日回撤<=-15%)={100 * (ev_df['fwd40_maxdd%'] <= -15).mean():.0f}%, "
          f"P(40日回撤<=-10%)={100 * (ev_df['fwd40_maxdd%'] <= -10).mean():.0f}%")

    print()
    print("=" * 90)
    print("B) 规则变体: [25日内曾>=80 且 跌破MA20]->半仓; [站回MA20且分数<55] 或 [站回MA20创20日新高]->满仓")
    rows = {}
    for name in TARGETS:
        rows[name] = backtest(load_scores(name))
    print(pd.DataFrame(rows).T.to_string())


if __name__ == "__main__":
    main()
