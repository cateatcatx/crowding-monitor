"""Digitize chart pixels; daily interpolation is explicitly NOT daily market data."""
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import re

import numpy as np
from PIL import Image

VERSION = 1


def ocr_image(image):
    from rapidocr_onnxruntime import RapidOCR
    # Each worker owns its engine; keep CI CPU and memory usage bounded.
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    result, _ = engine(np.asarray(image)[:, :, ::-1].copy())
    return result or []


def groups(indices):
    indices = np.asarray(indices)
    if not len(indices):
        return []
    return [float(np.mean(part)) for part in np.split(indices, np.where(np.diff(indices) > 1)[0] + 1)]


def chart_bounds(rgb):
    dark = np.max(rgb, axis=2) < 65
    horizontal = groups(np.flatnonzero(dark.sum(axis=1) > rgb.shape[1] * .8))
    if len(horizontal) < 2:
        raise ValueError("无法定位完整绘图区边框")
    top, bottom = int(round(horizontal[0])), int(round(horizontal[-1]))
    vertical = groups(np.flatnonzero(dark[top:bottom+1].sum(axis=0) > (bottom-top) * .85))
    if len(vertical) != 2 or bottom-top < rgb.shape[0] * .6:
        raise ValueError("绘图区布局改变，停止反推")
    return int(round(vertical[0])), top, int(round(vertical[1])), bottom


def fit_axis(points, minimum, tolerance):
    if len(points) < minimum:
        raise ValueError("可识别坐标刻度不足")
    points = np.asarray(points, dtype=float)
    fit = np.polyfit(points[:, 0], points[:, 1], 1)
    if np.max(np.abs(np.polyval(fit, points[:, 0]) - points[:, 1])) > tolerance:
        raise ValueError("坐标轴不是一致线性刻度，停止反推")
    return fit


def digitize(content, now=None, ocr=None):
    image = Image.open(BytesIO(content)).convert("RGB")
    rgb = np.asarray(image)
    left, top, right, bottom = chart_bounds(rgb)
    dark = rgb.max(axis=2) < 65
    xticks = groups(np.flatnonzero(dark[bottom+3:bottom+11].sum(axis=0) >= 4))
    yticks = groups(np.flatnonzero(dark[:, max(0,left-9):left-2].sum(axis=1) >= 4))
    labels = ocr if ocr is not None else ocr_image(image)
    xpoints, ypoints, legend = [], [], None
    legend_bottom = top
    for box, text, confidence in labels:
        if confidence < .85:
            continue
        coords = np.asarray(box)
        x, y = coords.mean(axis=0)
        cleaned = text.strip()
        if re.fullmatch(r"(?:19|20)\d{2}", cleaned) and bottom < y < bottom+60:
            nearest = min(xticks, key=lambda tick: abs(tick-x)) if xticks else x
            if abs(nearest-x) <= 7:
                xpoints.append((nearest, date(int(cleaned), 1, 1).toordinal()))
        if re.fullmatch(r"\d{1,3}(?:\.\d+)?", cleaned) and x < left and top-15 < y < bottom+15:
            nearest = min(yticks, key=lambda tick: abs(tick-y)) if yticks else y
            if abs(nearest-y) <= 7:
                ypoints.append((nearest, float(cleaned)))
        match = re.search(r"\(([A-Za-z]{3})\s*(\d{1,2})\s*=\s*(\d+(?:\.\d+)?)\)", cleaned)
        if match and "Forward" in cleaned and top < y < top+(bottom-top)*.3:
            legend = match.groups()
            legend_bottom = max(legend_bottom, float(coords[:,1].max()))
        if cleaned.lower() == "recession" and y < top+(bottom-top)*.3:
            legend_bottom = max(legend_bottom, float(coords[:,1].max()))
    xfit = fit_axis(xpoints, 3, 8)  # calendar days
    yfit = fit_axis(ypoints, 3, .35)  # PE multiples
    if xfit[0] <= 0 or yfit[0] >= 0 or not legend:
        raise ValueError("无法核验日期/PE刻度或最新图例")

    # Blue curve only; exclude chart title/legend. Missing or hidden pixels stay missing.
    colors = rgb.astype(np.int16)
    blue = (colors[:,:,2] > 150) & (colors[:,:,2]-colors[:,:,0] > 90) & (colors[:,:,2]-colors[:,:,1] > 70)
    blue[:int(legend_bottom)+9] = False
    blue[:,:left+2] = False
    blue[:,right-1:] = False
    blue[bottom-1:] = False
    # A trace touching the masked legend can be clipped; omit those columns too.
    clipped = blue[int(legend_bottom)+9:int(legend_bottom)+17].any(axis=0)
    blue[:,clipped] = False
    xs = np.flatnonzero(blue.any(axis=0))
    if len(xs) < (right-left)*.65 or xs[-1]-xs[0] < (right-left)*.8:
        raise ValueError("曲线覆盖不足，停止反推")
    approximate_end = date.fromordinal(round(float(np.polyval(xfit, xs[-1]))))
    month = {name:i+1 for i,name in enumerate(['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'])}.get(legend[0].title())
    if month is None:
        raise ValueError("图例月份无法识别")
    candidates = [date(year, month, int(legend[1])) for year in [approximate_end.year-1, approximate_end.year, approximate_end.year+1]]
    asof = min(candidates, key=lambda d: abs((d-approximate_end).days))
    today = (now or datetime.now(timezone.utc)).date()
    if asof > today or abs((asof-approximate_end).days) > max(14, xfit[0]*3):
        raise ValueError("图例日期与曲线末端不符")
    latest = float(legend[2])
    last_y = np.flatnonzero(blue[:,xs[-1]])
    endpoint = float(np.polyval(yfit, np.median(last_y)))
    if abs(endpoint-latest) > max(1.0, abs(yfit[0])*8):
        raise ValueError("曲线末端与图例PE不符")

    # Native per-column samples preserve the image's true time resolution and envelope.
    samples = []
    for x in xs:
        ys = np.flatnonzero(blue[:,x])
        day = round(float(np.polyval(xfit, x)))
        if day >= asof.toordinal():
            continue
        values = np.polyval(yfit, ys)
        # A single x column can cover a violent multi-day move; do not hide its range.
        samples.append((day, float(np.median(values)), float(values.min()), float(values.max()), int(x)))
    if not samples:
        raise ValueError("未识别到历史曲线")
    samples.append((asof.toordinal(), latest, latest, latest, int(xs[-1])))
    days = np.arange(samples[0][0], asof.toordinal()+1)
    points = np.asarray(samples)
    values = np.interp(days, points[:,0], points[:,1])
    low = np.interp(days, points[:,0], points[:,2])
    high = np.interp(days, points[:,0], points[:,3])
    # Do not bridge occluded sections (e.g. software dot-com peak behind legend).
    missing = np.zeros(len(days), dtype=bool)
    for previous, current in zip(samples, samples[1:]):
        if current[4]-previous[4] > 3:
            missing |= (days > previous[0]) & (days < current[0])
    number = lambda v: round(float(v), 2)
    return {
        "version": VERSION, "method": "image_digitized_daily_interpolation",
        "asof": asof.isoformat(), "latest_legend_pe": latest,
        "days_per_pixel": round(float(xfit[0]), 2), "pe_per_pixel": round(abs(float(yfit[0])), 3),
        "bounds": [left,top,right,bottom], "pixel_samples": len(samples),
        "axis_years": len(xpoints), "axis_pe_ticks": len(ypoints),
        "endpoint_difference": round(abs(endpoint-latest), 3),
        "dates": [date.fromordinal(int(d)).isoformat() for d in days],
        "values": [None if gap else number(v) for v,gap in zip(values,missing)],
        "low": [None if gap else number(v) for v,gap in zip(low,missing)],
        "high": [None if gap else number(v) for v,gap in zip(high,missing)],
        "observations": [{"date": asof.isoformat(), "value": latest}],
    }
