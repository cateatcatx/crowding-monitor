"""Refresh source charts and explicitly estimated daily history, retaining last-good data."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import struct
import tempfile
import time
from urllib.parse import urlparse

import requests
from digitize_forward_pe import VERSION, digitize

HERE = Path(__file__).resolve().parent
CACHE_FILE = HERE / "data" / "FORWARD_PE.json"
SOURCE_ROOT = "https://yardeni.com/charts/domestic-industry-briefings/s-p-500-information-technology/"
CHARTS = [
    {"key": "hardware", "label": "AI 硬件代理 · 半导体", "industry": "S&P 500 Semiconductors",
     "slug": "semiconductors", "title": "S&P 500 SEMICONDUCTORS: FORWARD P/E"},
    {"key": "software", "label": "AI 软件代理 · 应用软件", "industry": "S&P 500 Application Software",
     "slug": "application-software", "title": "S&P 500 APPLICATION SOFTWARE: FORWARD P/E"},
]
BEIJING = timezone(timedelta(hours=8))


class ChartParser(HTMLParser):
    def __init__(self, title):
        super().__init__()
        self.title = title
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        alt = attrs.get("alt", "")
        # Match the valuation chart, not stock prices or earnings growth.
        if tag == "img" and alt.split(": ", 1)[-1].rstrip("*").strip() == self.title:
            self.urls.append(attrs.get("src", ""))


def parse_chart_url(html, title):
    parser = ChartParser(title)
    parser.feed(html)
    urls = set(parser.urls)
    if len(urls) != 1:
        raise ValueError("未找到唯一的 Forward P/E 原图")
    url = urls.pop()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "product.datastream.com":
        raise ValueError("Forward P/E 图源域名发生变化")
    return url


def validate_png(content):
    if (len(content) < 10000 or content[:8] != b"\x89PNG\r\n\x1a\n"
            or content[12:16] != b"IHDR" or content[-12:] != b"\0\0\0\0IEND\xaeB`\x82"):
        raise ValueError("图源未返回完整 PNG，保留上次原图")
    width, height = struct.unpack(">II", content[16:24])
    if width < 800 or height < 400:
        raise ValueError("图源尺寸异常，保留上次原图")


def fetch_chart(config):
    source_url = SOURCE_ROOT + config["slug"]
    response = requests.get(source_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    image_url = parse_chart_url(response.text, config["title"])
    response = requests.get(image_url, timeout=45)
    response.raise_for_status()
    validate_png(response.content)
    return {
        "key": config["key"], "label": config["label"], "industry": config["industry"],
        "source_url": source_url, "image_url": image_url,
        "image_base64": base64.b64encode(response.content).decode("ascii"),
        # Retrieval time is not the date of the underlying financial observation.
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }


def read_cache(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("charts"), dict):
            return {"charts": {}}
        return data
    except (OSError, ValueError):
        return {"charts": {}}


def prepare_chart(config, previous, attempts=3):
    last_error = None
    for attempt in range(attempts):
        try:
            fresh = fetch_chart(config)
            old_series = previous.get("digitized") or {}
            if (fresh["image_base64"] == previous.get("image_base64")
                    and old_series.get("version") == VERSION):
                series = old_series
            else:
                series = digitize(base64.b64decode(fresh["image_base64"]))
                if old_series.get("asof", "") > series["asof"]:
                    raise ValueError("图源返回更旧数据，保留上次曲线")
                observations = {p["date"]:p for p in old_series.get("observations", [])}
                observations.update({p["date"]:p for p in series["observations"]})
                series["observations"] = [observations[d] for d in sorted(observations)]
                # Recorded legend readings take precedence over pixel estimates.
                indices = {d:i for i,d in enumerate(series["dates"])}
                for point in series["observations"]:
                    if point["date"] in indices:
                        i = indices[point["date"]]
                        for field in ["values", "low", "high"]:
                            series[field][i] = point["value"]
            fresh["digitized"] = series
            fresh["last_checked_at"] = datetime.now(timezone.utc).isoformat()
            return fresh
        except Exception as exc:
            last_error = exc
            if attempt+1 < attempts:
                time.sleep(3 * (attempt+1))
    raise RuntimeError(str(last_error))


def refresh_cache(path=CACHE_FILE, attempts=3):
    path = Path(path)
    data = read_cache(path)
    warnings = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [(config, pool.submit(prepare_chart, config,
                 data["charts"].get(config["key"], {}), attempts)) for config in CHARTS]
        for config, job in jobs:
            try:
                data["charts"][config["key"]] = job.result()
            except Exception as exc:
                message = f"{config['label']}：{exc}"
                warnings.append(message)
                previous = data["charts"].get(config["key"], {})
                if not isinstance(previous, dict):
                    previous = {}
                previous["error"] = message
                previous["last_checked_at"] = datetime.now(timezone.utc).isoformat()
                data["charts"][config["key"]] = previous
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return warnings


def assemble_forward_pe(path=CACHE_FILE, now=None):
    data = read_cache(path)
    current = now or datetime.now(timezone.utc)
    charts = []
    for config in CHARTS:
        cached = data["charts"].get(config["key"], {})
        item = {"key": config["key"], "label": config["label"], "industry": config["industry"],
                "source_url": SOURCE_ROOT + config["slug"], "available": False}
        try:
            validate_png(base64.b64decode(cached["image_base64"], validate=True))
            fetched = datetime.fromisoformat(cached["fetched_at"])
            if fetched.tzinfo is None:
                raise ValueError("缓存时间缺少时区")
            item.update(available=True, image_src="data:image/png;base64," + cached["image_base64"],
                        fetched_at=fetched.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M"),
                        cache_stale=(current - fetched).total_seconds() > 4 * 86400,
                        error=cached.get("error"))
            series = cached.get("digitized")
            if series and series.get("version") == VERSION:
                item["digitized"] = series
                item["data_stale"] = (current.date() - datetime.fromisoformat(series["asof"]).date()).days > 7
            item["last_checked_at"] = cached.get("last_checked_at", cached["fetched_at"])
        except (ValueError, KeyError, TypeError):
            item["error"] = "Forward P/E 原图暂不可用，请更新数据或查看来源。"
        charts.append(item)
    return {"available": any(c["available"] for c in charts), "charts": charts,
            "basis": "价格 ÷ 未来12个月一致预期每股经营盈利（NTM），单位：倍",
            "source": "Yardeni Research / LSEG Datastream / S&P"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    warnings = [] if args.no_fetch else refresh_cache(attempts=max(1,args.attempts))
    for chart in assemble_forward_pe()["charts"]:
        series = chart.get("digitized", {})
        print(f"{chart['label']}: {series.get('asof', '未反推')} "
              f"{len(series.get('dates', []))} 个日历日估算; "
              f"横向分辨率 {series.get('days_per_pixel', '—')} 日/像素")
        if not series:
            warnings.append(f"{chart['label']} 缺少反推数据")
        elif chart.get("data_stale"):
            warnings.append(f"{chart['label']} 原图日期超过7天未更新")
    if warnings:
        raise SystemExit("; ".join(warnings))
