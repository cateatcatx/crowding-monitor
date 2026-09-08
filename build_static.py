# -*- coding: utf-8 -*-
"""把拥挤度看板构建成静态站点(用于 GitHub Pages)。

流程:
  1. 跑数据管线: fetch_data + SK海力士外资流向
     -> crowding_engine -> theme_index -> options_snapshot
     - fetch / options 为"尽力而为": 失败时用仓库里已有的 CSV(种子数据)继续构建, 并在页面顶部提示
     - engine / theme_index 为必需步骤, 失败则退出非零(避免部署坏页面)
  2. 复用 server.assemble_dashboard() 组装 dashboard.json
  3. 输出到 site/:  index.html, static/chart.umd.js, dashboard.json, .nojekyll

用法:
  python build_static.py            # 完整构建(CI 用)
  python build_static.py --no-fetch # 跳过抓取, 用现有数据(本地快速预览)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")


def run(script, *args, required=False, timeout=900):
    """跑一个子脚本。required=True 时失败抛异常; 否则返回错误摘要(成功返回 None)。"""
    try:
        r = subprocess.run(
            [sys.executable, "-X", "utf8", os.path.join(HERE, script), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=HERE, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if required:
            raise
        message = f"{script}: 超时({timeout}秒)，保留上次数据"
        print(f"[warn] {message}", flush=True)
        return message
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().replace("\n", " ")[-300:]
        if required:
            raise RuntimeError(f"{script} 失败: {msg}")
        print(f"[warn] {script} 非零退出: {msg}", flush=True)
        return f"{script}: {msg}"
    print(f"[ok] {script}", flush=True)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="跳过数据抓取, 用现有CSV")
    ap.add_argument("--skip-forward-pe", action="store_true", help="CI已单独刷新估值，避免重复抓取")
    ap.add_argument(
        "--strict-flow-freshness",
        action="store_true",
        help="要求外资流向日期追上SK海力士价格日期，并在未落地时重试",
    )
    args = ap.parse_args()

    notes = []
    if not args.no_fetch:
        n = run("fetch_data.py")
        if n:
            notes.append("部分行情抓取失败, 已使用上次数据: " + n[:140])
        n = run("relative_strength.py")
        if n:
            notes.append("SOXX/IGV刷新失败，沿用上次配对数据: " + n[:140])
        if not args.skip_forward_pe:
            n = run("forward_pe.py", timeout=360)
            if n:
                notes.append("Forward P/E刷新失败，沿用上次原图及估算: " + n[:140])
        flow_args = (
            ["--max-attempts", "4", "--retry-delay", "120"]
            if args.strict_flow_freshness
            else ["--skip-freshness-check"]
        )
        n = run("fetch_sk_hynix_foreign_flow.py", *flow_args, timeout=900)
        if n:
            notes.append("SK海力士外资流向抓取失败, 已使用上次数据: " + n[:140])

    # 必需步骤: 用现有(或刚抓取的)CSV 计算分数与总指数
    run("crowding_engine.py", required=True)
    run("theme_index.py", required=True)

    if not args.no_fetch:
        n = run("options_snapshot.py", "MU", "SNDK", "WDC", "SKHY")
        if n:
            notes.append("期权快照失败(主数据正常): " + n[:140])

    # 复用服务端的数据组装逻辑
    import server  # noqa: E402  (import 不会启动服务, 由 __main__ 守卫)
    data = server.assemble_dashboard()
    data["last_refresh"] = server.beijing_now_text()
    data["refreshing"] = False
    if notes:
        data["last_error"] = "; ".join(notes)

    # 组装 site/ 目录
    if os.path.isdir(SITE):
        if os.path.realpath(SITE) != os.path.join(os.path.realpath(HERE), "site"):
            raise RuntimeError("构建输出目录不在项目内")
        shutil.rmtree(SITE)
    os.makedirs(os.path.join(SITE, "static"), exist_ok=True)
    shutil.copy(os.path.join(HERE, "static", "index.html"), os.path.join(SITE, "index.html"))
    shutil.copy(os.path.join(HERE, "static", "chart.umd.js"),
                os.path.join(SITE, "static", "chart.umd.js"))
    shutil.copy(os.path.join(HERE, "static", "forward_pe.js"),
                os.path.join(SITE, "static", "forward_pe.js"))
    with open(os.path.join(SITE, "dashboard.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(SITE, ".nojekyll"), "w").close()  # 关闭 Jekyll 处理

    size = os.path.getsize(os.path.join(SITE, "dashboard.json")) // 1024
    print(f"[done] site/ 构建完成: TCI={data['tci']['value']} "
          f"日期={data['tci']['date']} dashboard.json={size}KB "
          f"{'(有告警)' if notes else ''}", flush=True)


if __name__ == "__main__":
    main()
