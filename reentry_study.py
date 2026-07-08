# -*- coding: utf-8 -*-
"""再进场(加仓)时点研究。

问题: 拥挤崩盘后, 什么信号出现时加仓是安全的?

方法:
1. 案例复盘: 每段TCI红区(>=80)结束后, 主题篮子何时见底? 见底时各指标什么状态?
2. 规则测试: 对候选再进场信号, 统计信号日后20/40/60日主题篮子收益与期间最大回撤:
   A. TCI自70上方回落, 首次<55 (拥挤释放)
   B. A基础上 + 主题NAV站回20日均线 (趋势修复)
   C. 主题均分(强度)首次<60 (个股余震平息)
   D. B + 波动率子指标均值<80 (波动也回落)
3. MU单股案例: 2024-06 / 2025-11 / 2026-02 三轮崩盘后, 分数<60与站回MA20哪个先出现, 距底部多远。
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]

tdf = pd.read_csv(os.path.join(OUT_DIR, "theme_index.csv"), parse_dates=["date"]).set_index("date")
nav = tdf["theme_nav"]
ma20 = nav.rolling(20).mean()

vols = {}
for n in TARGETS:
    df = pd.read_csv(os.path.join(OUT_DIR, f"crowding_{n}.csv"), parse_dates=["date"]).set_index("date")
    vols[n] = df["volatility"]
vol_mean = pd.DataFrame(vols).ffill(limit=3).mean(axis=1).reindex(tdf.index).ffill(limit=3)

print("=" * 96)
print("1) 四段TCI红区结束后的见底过程")
mask = tdf["tci"] >= 80
groups = (mask != mask.shift()).cumsum()
episodes = []
for g, seg in tdf[mask].groupby(groups[mask]):
    if episodes and (seg.index[0] - episodes[-1][1]).days < 35:
        episodes[-1] = (episodes[-1][0], seg.index[-1])
    else:
        episodes.append((seg.index[0], seg.index[-1]))

for s, e in episodes:
    i_end = tdf.index.get_loc(e)
    fwd = tdf.iloc[i_end: i_end + 81]
    if len(fwd) < 10:
        # 当前这段还没走完
        print(f"\n红区 {s:%Y-%m-%d} ~ {e:%Y-%m-%d}: 仍在进行/样本不足")
        continue
    bot_d = fwd["theme_nav"].idxmin()
    bot_i = tdf.index.get_loc(bot_d)
    peak = tdf["theme_nav"].loc[s:e].max()
    dd = (fwd["theme_nav"].min() / peak - 1) * 100
    # 红区结束后TCI首次<55的日期
    after = tdf.loc[e:]
    t55 = after[after["tci"] < 55].index
    t55d = t55[0] if len(t55) else None
    # 强度首次<60
    l60 = after[after["level"] < 60].index
    l60d = l60[0] if len(l60) else None
    days_bot = bot_i - i_end
    print(f"\n红区 {s:%Y-%m-%d} ~ {e:%Y-%m-%d} (TCI峰值 {tdf['tci'].loc[s:e].max():.0f})")
    print(f"   主题见底: {bot_d:%Y-%m-%d} (红区结束后第{days_bot}个交易日), 高点回撤 {dd:.1f}%")
    if t55d is not None:
        gap = tdf.index.get_loc(t55d) - bot_i
        px_t55 = tdf['theme_nav'].loc[t55d]
        vs_bot = (px_t55 / fwd['theme_nav'].min() - 1) * 100
        print(f"   TCI<55: {t55d:%Y-%m-%d} ({'底后' if gap>=0 else '底前'}{abs(gap)}日, 价格高于底部{vs_bot:.1f}%)")
    if l60d is not None:
        gap = tdf.index.get_loc(l60d) - bot_i
        px_l60 = tdf['theme_nav'].loc[l60d]
        vs_bot = (px_l60 / fwd['theme_nav'].min() - 1) * 100
        print(f"   强度<60: {l60d:%Y-%m-%d} ({'底后' if gap>=0 else '底前'}{abs(gap)}日, 价格高于底部{vs_bot:.1f}%)")
    at_bot = tdf.loc[bot_d]
    print(f"   底部当天: TCI={at_bot['tci']:.0f} 强度={at_bot['level']:.0f} "
          f"波动均值={vol_mean.loc[bot_d]:.0f} NAV/MA20={nav.loc[bot_d]/ma20.loc[bot_d]*100-100:+.1f}%")

print()
print("=" * 96)
print("2) 候选再进场信号的前瞻收益 (主题等权篮子, 2023-2026)")

def fwd_stats(dates, label):
    rows = []
    for d in dates:
        i = tdf.index.get_loc(d)
        base = nav.iloc[i]
        f20 = nav.iloc[i: i + 21]
        f40 = nav.iloc[i: i + 41]
        f60 = nav.iloc[i: i + 61]
        if len(f60) < 41:
            continue
        rows.append({
            "signal_date": d.strftime("%Y-%m-%d"),
            "fwd20_ret%": round((f20.iloc[-1] / base - 1) * 100, 1),
            "fwd40_ret%": round((f40.iloc[-1] / base - 1) * 100, 1),
            "fwd60_ret%": round((f60.iloc[-1] / base - 1) * 100, 1) if len(f60) > 55 else None,
            "fwd40_maxdd%": round((f40.min() / base - 1) * 100, 1),
        })
    df = pd.DataFrame(rows)
    print(f"\n[{label}] {len(df)}次")
    if len(df):
        print(df.to_string(index=False))
    return df

# 信号A: TCI从>=70回落首次<55
sigA = []
armedA = False
for i in range(1, len(tdf)):
    t = tdf["tci"].iloc[i]
    if tdf["tci"].iloc[i - 1] >= 70:
        armedA = True
    if armedA and t < 55:
        sigA.append(tdf.index[i])
        armedA = False
fwd_stats(sigA, "A: TCI自70+回落首次<55 (拥挤释放)")

# 信号B: A之后, NAV首次站回MA20
sigB = []
for d in sigA:
    after = tdf.loc[d:].index
    for dd_ in after:
        if pd.notna(ma20.loc[dd_]) and nav.loc[dd_] > ma20.loc[dd_]:
            sigB.append(dd_)
            break
fwd_stats(sigB, "B: A + 主题NAV站回MA20 (趋势修复)")

# 信号C: 强度自75+回落首次<60
sigC = []
armedC = False
for i in range(1, len(tdf)):
    lv = tdf["level"].iloc[i]
    if tdf["level"].iloc[i - 1] >= 75:
        armedC = True
    if armedC and lv < 60:
        sigC.append(tdf.index[i])
        armedC = False
fwd_stats(sigC, "C: 主题强度自75+回落首次<60 (余震平息)")

# 信号D: B + 波动均值<80
sigD = []
for d in sigB:
    after = tdf.loc[d:].index
    for dd_ in after:
        if (pd.notna(ma20.loc[dd_]) and nav.loc[dd_] > ma20.loc[dd_]
                and pd.notna(vol_mean.loc[dd_]) and vol_mean.loc[dd_] < 80):
            sigD.append(dd_)
            break
fwd_stats(sigD, "D: B + 五标的波动率百分位均值<80 (波动也回落)")

print()
print("=" * 96)
print("3) MU 单股: 三轮崩盘后 分数<60 / 站回MA20 相对底部的时点")
mu = pd.read_csv(os.path.join(OUT_DIR, "crowding_MU.csv"), parse_dates=["date"]).set_index("date")
mu_ma20 = mu["close"].rolling(20).mean()
for top, bot_search_end in [("2024-06-18", "2024-12-31"), ("2025-11-10", "2026-01-31"), ("2026-02-02", "2026-05-31")]:
    seg = mu.loc[top:bot_search_end]
    bot_d = seg["close"].idxmin()
    bot_px = seg["close"].min()
    after = mu.loc[top:]
    s60 = after[after["score"] < 60].index
    s60d = s60[0] if len(s60) else None
    rec = after[(after["close"] > mu_ma20.reindex(after.index)) & (after.index > bot_d)].index
    recd = rec[0] if len(rec) else None
    print(f"\n顶 {top} -> 底 {bot_d:%Y-%m-%d} (${bot_px:.0f})")
    if s60d is not None:
        px = mu["close"].loc[s60d]
        print(f"   分数<60: {s60d:%Y-%m-%d}, 价格${px:.0f} (高于底部{(px/bot_px-1)*100:+.0f}%, "
              f"{'底前' if s60d < bot_d else '底后'})")
    if recd is not None:
        px = mu["close"].loc[recd]
        print(f"   底后首次站回MA20: {recd:%Y-%m-%d}, 价格${px:.0f} (高于底部{(px/bot_px-1)*100:+.0f}%)")

print()
print("=" * 96)
print("4) 当前状态核对 (最新交易日)")
last = tdf.iloc[-1]
print(f"   TCI={last['tci']:.1f} (<55 已满足)   强度={last['level']:.1f} (<60 未满足)")
print(f"   主题NAV/MA20 = {nav.iloc[-1]/ma20.iloc[-1]*100-100:+.1f}% (站回MA20 未满足)")
print(f"   波动率百分位均值 = {vol_mean.iloc[-1]:.0f} (<80 未满足)")
for n in TARGETS:
    df = pd.read_csv(os.path.join(OUT_DIR, f"crowding_{n}.csv"), parse_dates=["date"]).set_index("date")
    m = df["close"].rolling(20).mean().iloc[-1]
    print(f"   {n:9s} 分数={df['score'].iloc[-1]:5.1f}  收盘/MA20={df['close'].iloc[-1]/m*100-100:+6.1f}%  "
          f"波动分位={df['volatility'].iloc[-1]:3.0f}")
