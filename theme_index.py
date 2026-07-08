# -*- coding: utf-8 -*-
"""AI硬件拥挤度总指数 TCI (Theme Crowding Index, 0-100)。

把5个标的x7个子指标压缩成一个数字:

    TCI = 0.45 x 强度 + 0.30 x 广度 + 0.25 x 持续

    强度 level       = 当日可用标的综合分的等权均值 (0-100)
    广度 breadth     = 综合分>=80的标的占比 x 100 (0-100)
    持续 persistence = 过去10个交易日中"广度占比>=60%"的天数比例 x 100

设计逻辑(对应回测结论):
  - 单一标的过热(强度高、广度低) => 指数中性, 只是个股问题
  - 全篮子同时过热(广度高)且持续多日 => 主题级拥挤, 历史上才有深回撤
  - 三成分都有界且同量纲, 无需再做百分位, 阈值可直接标定

用法: python theme_index.py   (依赖 out/crowding_*.csv, 先跑 crowding_engine.py)
输出: out/theme_index.csv, 打印验证报告
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")

TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]

W_LEVEL, W_BREADTH, W_PERSIST = 0.45, 0.30, 0.25
HOT = 80.0          # 单标的"过热"线
BROAD_FRAC = 0.6    # 广度占比>=60% 记为"共振日"
PERSIST_WIN = 10    # 持续窗口


def build() -> pd.DataFrame:
    scores, rets = {}, {}
    for n in TARGETS:
        df = pd.read_csv(os.path.join(OUT_DIR, f"crowding_{n}.csv"),
                         parse_dates=["date"]).set_index("date")
        scores[n] = df["score"]
        rets[n] = df["close"].pct_change(fill_method=None)

    sc = pd.DataFrame(scores).sort_index().ffill(limit=3)
    rt = pd.DataFrame(rets).sort_index()

    avail = sc.notna().sum(axis=1)
    level = sc.mean(axis=1)
    breadth_frac = (sc >= HOT).sum(axis=1) / avail.replace(0, np.nan)
    resonant = (breadth_frac >= BROAD_FRAC).astype(float)
    persistence = resonant.rolling(PERSIST_WIN, min_periods=PERSIST_WIN).mean() * 100

    tci = W_LEVEL * level + W_BREADTH * breadth_frac * 100 + W_PERSIST * persistence
    tci[avail < 3] = np.nan  # 少于3个标的时不出数

    nav = (1 + rt.mean(axis=1).fillna(0)).cumprod()

    out = pd.DataFrame({
        "tci": tci, "level": level, "breadth_pct": breadth_frac * 100,
        "persistence": persistence, "n_avail": avail, "theme_nav": nav,
    })
    return out.dropna(subset=["tci"])


def fwd_maxdd(nav: pd.Series, horizon: int) -> pd.Series:
    v = nav.values
    res = []
    for i in range(len(v)):
        end = min(i + horizon + 1, len(v))
        if end - i < 5:
            res.append(np.nan)
            continue
        res.append((v[i:end].min() / v[i] - 1) * 100)
    return pd.Series(res, index=nav.index)


def main():
    df = build()
    df.round(3).to_csv(os.path.join(OUT_DIR, "theme_index.csv"))

    print("=" * 92)
    print(f"TCI样本: {df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d}, {len(df)}个交易日")
    print(f"分布: 中位数={df['tci'].median():.1f}  P80={df['tci'].quantile(.8):.1f}  "
          f"P90={df['tci'].quantile(.9):.1f}  P95={df['tci'].quantile(.95):.1f}  最大={df['tci'].max():.1f}")

    # 1) 分档 vs 主题篮子未来20日最大回撤
    df["fwd20"] = fwd_maxdd(df["theme_nav"], 20)
    df["fwd40"] = fwd_maxdd(df["theme_nav"], 40)
    near = df["theme_nav"] / df["theme_nav"].rolling(250, min_periods=60).max() >= 0.85
    sel = df[near].dropna(subset=["fwd20"])
    bins = [0, 40, 55, 70, 80, 101]
    labels = ["<40", "40-55", "55-70", "70-80", ">=80"]
    sel = sel.copy()
    sel["bucket"] = pd.cut(sel["tci"], bins=bins, labels=labels, right=False)
    g20 = sel.groupby("bucket", observed=True)["fwd20"]
    g40 = sel.groupby("bucket", observed=True)["fwd40"]
    rep = pd.DataFrame({
        "days": g20.count(),
        "fwd20_中位回撤%": g20.median().round(2),
        "P(fwd20<=-10%)": (g20.apply(lambda x: (x <= -10).mean()) * 100).round(1),
        "P(fwd20<=-15%)": (g20.apply(lambda x: (x <= -15).mean()) * 100).round(1),
        "fwd40_中位回撤%": g40.median().round(2),
        "P(fwd40<=-15%)": (g40.apply(lambda x: (x <= -15).mean()) * 100).round(1),
    })
    print("\n1) TCI分档 vs 主题篮子(等权5标的)未来回撤  [仅距250日高点15%以内的日子]")
    print(rep.to_string())

    # 2) 红区时段(TCI>=80)清单
    print("\n2) TCI>=80 的历史时段:")
    mask = df["tci"] >= 80
    groups = (mask != mask.shift()).cumsum()
    for g, seg in df[mask].groupby(groups[mask]):
        s, e = seg.index[0], seg.index[-1]
        i_end = df.index.get_loc(e)
        fwd = df["theme_nav"].iloc[i_end: i_end + 61]
        peak = df["theme_nav"].loc[s:e].max()
        dd = (fwd.min() / peak - 1) * 100 if len(fwd) else np.nan
        print(f"   {s:%Y-%m-%d} ~ {e:%Y-%m-%d}  {len(seg):2d}天  TCI峰值={seg['tci'].max():.1f}  "
              f"时段后60日主题最大回撤={dd:.1f}%")

    # 3) 主题重大顶部捕获 (随后40日主题回撤>=15%)
    print("\n3) 主题重大顶部(随后40日等权篮子回撤>=15%)时的TCI:")
    nav = df["theme_nav"]
    tops = []
    v = nav.values
    for i in range(10, len(v) - 5):
        if v[i] != v[max(0, i - 10): i + 11].max():
            continue
        seg = v[i: min(i + 41, len(v))]
        if seg.min() / seg[0] - 1 <= -0.15:
            if tops and i - tops[-1] < 30:
                if v[i] > v[tops[-1]]:
                    tops[-1] = i
                continue
            tops.append(i)
    for i in tops:
        d = df.index[i]
        pre = df["tci"].iloc[max(0, i - 5): i + 1].max()
        seg = v[i: min(i + 41, len(v))]
        dd = (seg.min() / seg[0] - 1) * 100
        flag = "命中(>=70)" if pre >= 70 else ("边缘(60-70)" if pre >= 60 else "漏报")
        print(f"   {d:%Y-%m-%d}  顶前5日TCI峰值={pre:.1f}  后40日回撤={dd:.1f}%  {flag}")

    # 4) 关键日期读数
    print("\n4) 关键日期读数:")
    for d in ["2024-06-18", "2025-11-10", "2026-02-02", "2026-05-13", "2026-06-03",
              "2026-06-18", "2026-06-25", "2026-07-01"]:
        if d in df.index.strftime("%Y-%m-%d").tolist():
            r = df.loc[d]
            print(f"   {d}  TCI={r['tci']:.1f}  (强度{r['level']:.1f} 广度{r['breadth_pct']:.0f} "
                  f"持续{r['persistence']:.0f}  n={r['n_avail']:.0f})")

    # 5) 最近走势
    print("\n5) 最近15个交易日:")
    print(df[["tci", "level", "breadth_pct", "persistence", "theme_nav"]].tail(15).round(1).to_string())


if __name__ == "__main__":
    main()
