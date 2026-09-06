# -*- coding: utf-8 -*-
"""AI硬件股拥挤度日常监控 —— 一键运行, 输出红黄绿灯报告。

用法:
    python daily_monitor.py            # 拉数据+算分+期权快照+打印报告
    python daily_monitor.py --no-fetch # 跳过拉数据(用已有CSV)

信号体系(基于2023-2026回测标定):
  个股综合分  <60 绿 | 60-75 黄(偏热) | 75-85 橙(过热) | >=85 红(拥挤极值)
  主题广度    >=80分的标的数量: >=3 警戒, >=4 极值(历史上仅5段, 段后60日主题最大回撤中位数-16%)
  触发规则    红区武装(15日内曾>=85) + 收盘跌破MA20 => 执行减仓/对冲
"""
import argparse
import io
import os
import subprocess
import sys

import numpy as np
import pandas as pd

# Windows控制台默认GBK, 强制UTF-8避免中文/符号报错
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
TARGETS = ["MU", "SNDK", "WDC", "SK_HYNIX", "SAMSUNG"]

LEVELS = [(85, "红[拥挤极值]"), (75, "橙[过热]"), (60, "黄[偏热]"), (0, "绿[正常]")]


def level(score):
    if pd.isna(score):
        return "?"
    for th, name in LEVELS:
        if score >= th:
            return name
    return "绿[正常]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-options", action="store_true")
    args = ap.parse_args()

    py = sys.executable
    if not args.no_fetch:
        print(">>> 拉取最新日线 ...")
        subprocess.run([py, os.path.join(HERE, "fetch_data.py")], check=False)
        print(">>> 拉取SOXX/IGV相对强度 ...")
        subprocess.run([py, os.path.join(HERE, "relative_strength.py")], check=False)
        print(">>> 拉取SK海力士外资流向 ...")
        subprocess.run(
            [
                py,
                os.path.join(HERE, "fetch_sk_hynix_foreign_flow.py"),
                "--skip-freshness-check",
            ],
            check=False,
        )
    print(">>> 计算拥挤度 ...")
    subprocess.run([py, os.path.join(HERE, "crowding_engine.py")],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run([py, os.path.join(HERE, "theme_index.py")],
                   check=True, stdout=subprocess.DEVNULL)
    if not args.no_options:
        print(">>> 期权快照 ...")
        subprocess.run([py, os.path.join(HERE, "options_snapshot.py"), "MU", "SNDK", "WDC"],
                       check=False, stdout=subprocess.DEVNULL)

    print()
    print("=" * 100)
    print("AI硬件/存储 交易拥挤度日报")
    print("=" * 100)
    from relative_strength import assemble_relative_strength
    rotation = assemble_relative_strength()
    if rotation["available"]:
        print(f"SOXX/IGV 相对强度 ({rotation['asof']}): {rotation['summary']}")
        if rotation["stale"]:
            print("提示: SOXX/IGV数据日期已滞后，请检查更新。")
    else:
        print(rotation["error"])

    rows = []
    scores = {}
    for name in TARGETS:
        df = pd.read_csv(os.path.join(OUT_DIR, f"crowding_{name}.csv"),
                         parse_dates=["date"]).set_index("date")
        last = df.iloc[-1]
        scores[name] = df["score"]
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        armed = df["score"].rolling(15, min_periods=1).max().iloc[-1] >= 85
        crack = last["close"] < ma20
        rows.append({
            "标的": name,
            "日期": df.index[-1].strftime("%m-%d"),
            "收盘": round(last["close"], 1),
            "综合分": round(last["score"], 1),
            "状态": level(last["score"]),
            "成交热度": round(last["turnover"], 0),
            "均线偏离": round(last["extension"], 0),
            "动量": round(last["momentum"], 0),
            "波动": round(last["volatility"], 0),
            "篮子相关": round(last["basket_corr"], 0),
            "红区武装": "是" if armed else "-",
            "破MA20": "是" if crack else "-",
            "触发减仓": "<<是>>" if (armed and crack) else "-",
        })
    report = pd.DataFrame(rows)
    print(report.to_string(index=False))

    sc = pd.DataFrame(scores).ffill(limit=3)
    breadth = int((sc.iloc[-1] >= 80).sum())
    theme = sc.iloc[-1].mean()
    print(f"\n主题综合分: {theme:.1f}   红橙广度(>=80分标的数): {breadth}/5"
          f"   {'!! 主题级警报' if breadth >= 4 else ('! 主题警戒' if breadth >= 3 else '')}")

    tci_path = os.path.join(OUT_DIR, "theme_index.csv")
    if os.path.exists(tci_path):
        tdf = pd.read_csv(tci_path, parse_dates=["date"]).set_index("date")
        t = tdf.iloc[-1]
        def tci_level(x):
            if x >= 80: return "红[主题拥挤极值]"
            if x >= 70: return "橙[主题过热]"
            if x >= 55: return "黄[主题偏热]"
            return "绿[正常]"
        print(f"\n*** TCI 主题总指数: {t['tci']:.1f}  {tci_level(t['tci'])} ***"
              f"   = 0.45x强度({t['level']:.1f}) + 0.30x广度({t['breadth_pct']:.0f})"
              f" + 0.25x持续({t['persistence']:.0f})")
        recent = tdf["tci"].tail(6)
        print("    近6日: " + "  ".join(f"{d:%m-%d}={v:.0f}" for d, v in recent.items()))
        print("    阈值参考: >=80红(20日内主题回撤>=10%概率61%) | 70-80橙 | 55-70黄 | <55绿")

    opt_path = os.path.join(OUT_DIR, "options_snapshot.json")
    if os.path.exists(opt_path):
        import json
        with open(opt_path, encoding="utf-8") as f:
            opts = json.load(f)
        print("\n期权维度 (CBOE延迟报价):")
        odf = pd.DataFrame(opts)
        cols = ["ticker", "spot", "near_atm_iv_pct", "skew_call_minus_put_pct",
                "pc_ratio_vol", "pc_ratio_oi", "near_otm_call_oi_share_pct"]
        print(odf[cols].rename(columns={
            "ticker": "标的", "spot": "现价", "near_atm_iv_pct": "近月ATM_IV%",
            "skew_call_minus_put_pct": "skew(C-P)%", "pc_ratio_vol": "PC比(量)",
            "pc_ratio_oi": "PC比(OI)", "near_otm_call_oi_share_pct": "近月OTM_call集中%",
        }).to_string(index=False))
        print("  解读: skew转正/收敛至>-3% + PC比(量)<0.7 = call投机拥挤; IV低+skew平 = 买保护的好时机")

    print("\n操作对照 (回测标定):")
    print("  橙区(>=75): 停止加仓; 若IV处于低位, 买3个月5-10%OTM put spread(此时最便宜)")
    print("  红区(>=85): 建collar(卖5-8%OTM call + 买10%OTM put)或减仓20-30%; 广度>=4时主题整体降杠杆")
    print("  红区武装+破MA20: 执行减至半仓; 站回MA20且分数<60再恢复")
    print("  历史基数: 红区首触发后40日内回撤<=-10%概率56%, <=-15%概率25%; 但40日最大涨幅中位数+16% => 用期权保护优于清仓")


if __name__ == "__main__":
    main()
