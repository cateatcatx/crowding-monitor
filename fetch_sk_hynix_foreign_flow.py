# -*- coding: utf-8 -*-
"""抓取 SK 海力士（KRX: 000660）每日外资净买卖数据。

数据来自 Naver Finance 的 KRX 投资者趋势接口。正数表示外资净买入，
负数表示外资净卖出。该数据是股数口径，不是精确的韩元资金流。

输出:
    data/SK_HYNIX_FOREIGN_FLOW.csv
"""
from __future__ import annotations

import argparse
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "data" / "SK_HYNIX_FOREIGN_FLOW.csv"
DEFAULT_START = date(2025, 1, 1)
API_URL = "https://m.stock.naver.com/front-api/stock/domestic/trend"
SOURCE_URL = (
    "https://m.stock.naver.com/domestic/stock/000660/"
    "tradingTrend?marketType=KRX"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://m.stock.naver.com/",
}
OUTPUT_COLUMNS = [
    "date",
    "ticker",
    "market",
    "foreign_net_shares",
    "institution_net_shares",
    "individual_net_shares",
    "foreign_holding_ratio_pct",
    "close_krw",
    "volume_shares",
    "source",
    "source_url",
]


def parse_int(value) -> int | None:
    """把 '+689,697'、'-599' 等 Naver 文本转换为整数。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    cleaned = re.sub(r"[^\d+-]", "", text)
    if cleaned in {"", "+", "-"}:
        return None
    return int(cleaned)


def parse_pct(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("%", "").replace(",", "")
    if not text or text in {"-", "—"}:
        return None
    return float(text)


def normalize_record(raw: dict) -> dict:
    """规范一条 Naver 返回记录，字段名和单位在此处固定。"""
    bizdate = str(raw.get("bizdate", ""))
    parsed_date = datetime.strptime(bizdate, "%Y%m%d").date()
    net_shares = parse_int(raw.get("foreignerPureBuyQuant"))
    if net_shares is None:
        raise ValueError(f"{bizdate} 缺少外资净买卖股数")
    return {
        "date": parsed_date.isoformat(),
        "ticker": "000660",
        "market": "KRX",
        "foreign_net_shares": net_shares,
        "institution_net_shares": parse_int(raw.get("organPureBuyQuant")),
        "individual_net_shares": parse_int(raw.get("individualPureBuyQuant")),
        "foreign_holding_ratio_pct": parse_pct(raw.get("foreignerHoldRatio")),
        "close_krw": parse_int(raw.get("closePrice")),
        "volume_shares": parse_int(raw.get("accumulatedTradingVolume")),
        "source": "Naver Finance",
        "source_url": SOURCE_URL,
    }


def fetch_since(
    start: date,
    *,
    timeout: float = 20,
    sleep_seconds: float = 0.15,
    max_pages: int = 20,
) -> pd.DataFrame:
    """分页抓取 start（含）之后的数据；bizdate 是排他性翻页游标。"""
    rows: list[dict] = []
    cursor: str | None = None

    with requests.Session() as session:
        session.headers.update(HEADERS)
        for _ in range(max_pages):
            params = {
                "code": "000660",
                "marketType": "KRX",
                "pageSize": 50,
            }
            if cursor:
                params["bizdate"] = cursor

            response = session.get(API_URL, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("isSuccess"):
                raise RuntimeError(f"Naver 返回失败: {payload}")

            batch = payload.get("result") or []
            if not batch:
                break

            normalized = [normalize_record(item) for item in batch]
            rows.extend(normalized)
            oldest = min(datetime.strptime(r["date"], "%Y-%m-%d").date()
                         for r in normalized)
            if oldest <= start:
                break

            next_cursor = str(batch[-1].get("bizdate", ""))
            if not next_cursor or next_cursor == cursor:
                raise RuntimeError("Naver 分页游标没有前进")
            cursor = next_cursor
            if sleep_seconds:
                time.sleep(sleep_seconds)
        else:
            raise RuntimeError(f"达到分页上限 {max_pages}，请增大 --max-pages")

    if not rows:
        raise RuntimeError("Naver 没有返回外资流向数据")

    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result["date"] = pd.to_datetime(result["date"])
    result = result[result["date"].dt.date >= start]
    return result.sort_values("date").drop_duplicates("date", keep="last")


def load_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    existing = pd.read_csv(path, dtype={"ticker": str})
    missing = set(OUTPUT_COLUMNS) - set(existing.columns)
    if missing:
        raise RuntimeError(f"已有外资数据缺少字段: {sorted(missing)}")
    existing = existing[OUTPUT_COLUMNS].copy()
    existing["date"] = pd.to_datetime(existing["date"], errors="raise")
    return existing


def latest_reference_date(path: Path) -> date | None:
    """读取 SK 海力士价格文件的最新交易日，作为流向数据新鲜度基准。"""
    if not path.exists():
        return None
    frame = pd.read_csv(path, usecols=["date"])
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return dates.max().date() if not dates.empty else None


def validate_freshness(frame: pd.DataFrame, expected_date: date | None) -> date:
    latest_date = pd.to_datetime(frame["date"], errors="raise").max().date()
    if expected_date and latest_date < expected_date:
        raise RuntimeError(
            f"外资流向最新{latest_date:%Y-%m-%d}，"
            f"落后于价格交易日{expected_date:%Y-%m-%d}"
        )
    return latest_date


def save_merged(fetched: pd.DataFrame, output: Path, start: date) -> pd.DataFrame:
    existing = load_existing(output)
    combined = fetched.copy() if existing.empty else pd.concat(
        [existing, fetched], ignore_index=True
    )
    combined["date"] = pd.to_datetime(combined["date"], errors="raise")
    combined = combined[combined["date"].dt.date >= start]
    combined = combined.sort_values("date").drop_duplicates("date", keep="last")

    for column in [
        "foreign_net_shares",
        "institution_net_shares",
        "individual_net_shares",
        "close_krw",
        "volume_shares",
    ]:
        combined[column] = pd.to_numeric(combined[column], errors="coerce").astype("Int64")
    combined["foreign_holding_ratio_pct"] = pd.to_numeric(
        combined["foreign_holding_ratio_pct"], errors="coerce"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    combined.to_csv(temp_output, index=False, date_format="%Y-%m-%d",
                    columns=OUTPUT_COLUMNS)
    os.replace(temp_output, output)
    return combined


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期格式应为 YYYY-MM-DD") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取 SK 海力士 KRX 外资每日净买卖")
    parser.add_argument("--start", type=parse_iso_date, default=DEFAULT_START)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument(
        "--expected-price-file",
        type=Path,
        default=HERE / "data" / "SK_HYNIX.csv",
        help="用该价格CSV的最新交易日校验外资数据是否已落地",
    )
    parser.add_argument(
        "--skip-freshness-check",
        action="store_true",
        help="盘中构建时允许外资日终数据仍停留在前一交易日",
    )
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--retry-delay", type=float, default=60)
    args = parser.parse_args()
    if args.max_attempts < 1:
        raise SystemExit("--max-attempts 必须大于等于1")
    if args.retry_delay < 0:
        raise SystemExit("--retry-delay 不能为负数")

    # CI 会从缓存恢复上次结果，但不会回写仓库，所以每次至少重抓最近
    # 约18个月，再与历史合并，既能覆盖修订又不会无限翻页。
    rolling_start = date.today() - timedelta(days=550)
    fetch_start = args.start if not args.output.exists() else max(args.start, rolling_start)
    expected_date = (
        None if args.skip_freshness_check
        else latest_reference_date(args.expected_price_file)
    )
    combined = None
    for attempt in range(1, args.max_attempts + 1):
        try:
            fetched = fetch_since(
                fetch_start,
                timeout=args.timeout,
                sleep_seconds=args.sleep,
                max_pages=args.max_pages,
            )
            combined = save_merged(fetched, args.output, args.start)
            validate_freshness(combined, expected_date)
            break
        except Exception as exc:
            if attempt >= args.max_attempts:
                raise
            print(
                f"[warn] 第{attempt}次抓取未就绪: {exc}; "
                f"{args.retry_delay:g}秒后重试",
                flush=True,
            )
            time.sleep(args.retry_delay)

    if combined is None:
        raise RuntimeError("外资流向抓取没有生成数据")

    latest = combined.iloc[-1]
    total_5 = int(combined["foreign_net_shares"].tail(5).sum())
    print(
        f"SK海力士外资流向: {len(combined)}行, "
        f"最新{latest['date']:%Y-%m-%d} "
        f"{int(latest['foreign_net_shares']):+d}股, "
        f"近5日{total_5:+d}股 -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
