from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Iterable
from zoneinfo import ZoneInfo

import markdown2
import pandas as pd
import yfinance as yf


TZ = ZoneInfo("Europe/Chisinau")

# Premium-minimal palette
BG = "#F8FAFC"
CARD = "#FFFFFF"
TEXT = "#0F172A"
SUBTEXT = "#64748B"
BORDER = "#E2E8F0"
BLUE = "#2563EB"
BLUE_SOFT = "#EFF6FF"
GREEN = "#16A34A"
GREEN_SOFT = "#F0FDF4"
RED = "#DC2626"
RED_SOFT = "#FEF2F2"
AMBER = "#D97706"
AMBER_SOFT = "#FFFBEB"
MUTED = "#94A3B8"


@dataclass
class Stock:
    ticker: str
    name: str
    details: str = ""
    score: int | None = None
    trend: str = "N/A"
    signal: str = "N/A"


def newest_file(files: Iterable[Path]) -> Path | None:
    items = [p for p in files if p.is_file()]
    return max(items, key=lambda p: p.stat().st_mtime) if items else None


def reports_in(folder: Path) -> tuple[Path | None, Path | None]:
    stock_reports = [
        p
        for p in folder.glob("report_*.md")
        if re.fullmatch(r"report_\d{8}\.md", p.name)
    ]
    market_reports = list(folder.glob("market_review_*.md"))
    return newest_file(stock_reports), newest_file(market_reports)


def no_emoji(value: str) -> str:
    # Removes the most common emoji/pictograph ranges while preserving Romanian text.
    return re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F]",
        "",
        str(value or ""),
    ).strip()


def strip_md(value: str) -> str:
    text = no_emoji(value)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`>#~]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def md(value: str) -> str:
    return markdown2.markdown(
        value or "",
        extras=["tables", "fenced-code-blocks", "strike"],
    )


def ro_date(dt: datetime) -> str:
    months = [
        "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
        "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
    ]
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


def icon(name: str, size: int = 18, color: str = TEXT) -> str:
    """Small inline outline icons in a consistent Phosphor-like visual style."""
    common = (
        f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" '
        f'style="color:{color}">'
    )
    end = "</svg>"
    attrs = f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'

    paths = {
        "chart": f'<path {attrs} d="M4 19V5M4 19H20M7 15l4-5 3 3 5-7"/>',
        "candles": f'<path {attrs} d="M7 3v4M7 15v6M5 7h4v8H5zM17 3v7M17 18v3M15 10h4v8h-4z"/>',
        "trend": f'<path {attrs} d="M4 17l5-5 4 3 7-8M15 7h5v5"/>',
        "shield": f'<path {attrs} d="M12 3l7 3v5c0 4.8-2.7 8-7 10-4.3-2-7-5.2-7-10V6l7-3z"/><path {attrs} d="M12 8v5M12 16h.01"/>',
        "target": f'<circle {attrs} cx="12" cy="12" r="8"/><circle {attrs} cx="12" cy="12" r="3"/><path {attrs} d="M12 4V2M20 12h2"/>',
        "news": f'<path {attrs} d="M5 4h11v16H5zM16 8h3v10a2 2 0 0 1-2 2h-1M8 8h5M8 12h5M8 16h3"/>',
        "info": f'<circle {attrs} cx="12" cy="12" r="9"/><path {attrs} d="M12 11v6M12 7h.01"/>',
        "clock": f'<circle {attrs} cx="12" cy="12" r="9"/><path {attrs} d="M12 7v5l3 2"/>',
        "gauge": f'<path {attrs} d="M4 16a8 8 0 1 1 16 0M12 12l4-3M6 18h12"/>',
        "stack": f'<path {attrs} d="M12 3l8 4-8 4-8-4 8-4zM4 12l8 4 8-4M4 17l8 4 8-4"/>',
        "bolt": f'<path {attrs} d="M13 2L5 13h6l-1 9 9-13h-6l0-7z"/>',
    }
    return common + paths.get(name, paths["info"]) + end


def _extract_stock_meta(details: str) -> tuple[int | None, str, str]:
    clean = strip_md(details)

    score = None
    m = re.search(r"(?:Scor|Score)\s*[:|]?\s*(\d{1,3})(?:\s*/\s*100)?", clean, re.I)
    if m:
        try:
            score = max(0, min(100, int(m.group(1))))
        except ValueError:
            score = None

    signal = "N/A"
    signal_candidates = [
        "Cumpărare puternică", "Vânzare puternică", "Cumpără", "Păstrează",
        "Urmărește", "Vinde", "Strong Buy", "Strong Sell", "Buy", "Hold", "Watch", "Sell",
    ]
    lower = clean.lower()
    for candidate in signal_candidates:
        if candidate.lower() in lower:
            signal = candidate
            break

    trend = "N/A"
    trend_candidates = [
        "Puternic ascendent", "Puternic descendent", "Ascendent", "Descendent", "Lateral",
        "Strong Bullish", "Strong Bearish", "Bullish", "Bearish", "Sideways",
    ]
    for candidate in trend_candidates:
        if candidate.lower() in lower:
            trend = candidate
            break

    return score, trend, signal


def parse_stocks(stock_md: str) -> list[Stock]:
    """Parse stock sections generated by NotificationService.generate_dashboard_report()."""
    lines = stock_md.splitlines()
    starts: list[tuple[int, str, str]] = []

    # Summary lines look like:
    # 🟢 **Apple Inc.(AAPL)**: Păstrează | Scor 74 | Ascendent
    summary_meta: dict[str, tuple[int | None, str, str]] = {}
    summary_re = re.compile(
        r"\*\*.*?\(([A-Za-z0-9.\-^=]+)\)\*\*\s*:\s*(.*?)\s*\|\s*"
        r"(?:Scor|Score)\s*(\d{1,3})\s*\|\s*(.+?)\s*$",
        re.I,
    )
    for line in lines:
        m = summary_re.search(line.strip())
        if not m:
            continue
        ticker = m.group(1).upper()
        signal = strip_md(m.group(2)) or "N/A"
        score = max(0, min(100, int(m.group(3))))
        trend = strip_md(m.group(4)) or "N/A"
        summary_meta[ticker] = (score, trend, signal)

    # Detailed heading shape: ## 🟢 Apple Inc. (AAPL)
    heading_re = re.compile(r"^##\s+(.+?)\s*\(([A-Za-z0-9.\-^=]+)\)\s*$")
    for idx, line in enumerate(lines):
        match = heading_re.match(line.strip())
        if not match:
            continue
        name = strip_md(match.group(1)) or match.group(2).upper()
        ticker = match.group(2).upper()
        starts.append((idx, name, ticker))

    stocks: list[Stock] = []
    for pos, (start, name, ticker) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        details = "\n".join(lines[start + 1 : end]).strip()
        detail_score, detail_trend, detail_signal = _extract_stock_meta(details)
        score, trend, signal = summary_meta.get(
            ticker,
            (detail_score, detail_trend, detail_signal),
        )
        if trend == "N/A" and detail_trend != "N/A":
            trend = detail_trend
        if signal == "N/A" and detail_signal != "N/A":
            signal = detail_signal
        stocks.append(
            Stock(
                ticker=ticker,
                name=name,
                details=details,
                score=score,
                trend=trend,
                signal=signal,
            )
        )

    return stocks


def _split_sections(markdown_text: str, level: int = 3) -> list[tuple[str, str]]:
    marker = "#" * level
    heading = re.compile(rf"^{re.escape(marker)}\s+(.+?)\s*$")
    sections: list[tuple[str, str]] = []
    title: str | None = None
    body: list[str] = []

    for line in markdown_text.splitlines():
        m = heading.match(line.strip())
        if m:
            if title is not None:
                sections.append((strip_md(title), "\n".join(body).strip()))
            title = m.group(1)
            body = []
        elif title is not None:
            body.append(line)

    if title is not None:
        sections.append((strip_md(title), "\n".join(body).strip()))

    return [(t, b) for t, b in sections if t and b]


def market_sections(markdown_text: str) -> list[tuple[str, str]]:
    sections = _split_sections(markdown_text, 3)
    if sections:
        return sections
    # Graceful fallback if upstream changed heading depth.
    return [("Contextul pieței", markdown_text.strip())] if markdown_text.strip() else []


def stock_sections(markdown_text: str) -> list[tuple[str, str]]:
    sections = _split_sections(markdown_text, 3)
    if sections:
        return sections
    return [("Analiză", markdown_text.strip())] if markdown_text.strip() else []


def _normalize_yf_columns(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        # yfinance may return (Price, Ticker) or (Ticker, Price), depending on version/call.
        if ticker in out.columns.get_level_values(-1):
            try:
                out = out.xs(ticker, axis=1, level=-1, drop_level=True)
            except (KeyError, TypeError):
                pass
        elif ticker in out.columns.get_level_values(0):
            try:
                out = out.xs(ticker, axis=1, level=0, drop_level=True)
            except (KeyError, TypeError):
                pass

        if isinstance(out.columns, pd.MultiIndex):
            out.columns = [str(col[0]) for col in out.columns]

    out.columns = [str(c).title() for c in out.columns]
    return out


def ohlc(ticker: str, period: str = "3mo") -> pd.DataFrame:
    try:
        df = yf.download(
            ticker,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=12,
        )
        df = _normalize_yf_columns(df, ticker)
        required = ["Open", "High", "Low", "Close"]
        if not all(col in df.columns for col in required):
            return pd.DataFrame(columns=required)
        out = df[required].apply(pd.to_numeric, errors="coerce").dropna(how="any")
        return out.tail(66)
    except Exception as exc:
        print(f"[PDF] Date OHLC indisponibile pentru {ticker}: {exc}")
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"])


def price_snapshot(df: pd.DataFrame) -> tuple[str, str, str]:
    if df.empty or "Close" not in df:
        return "N/A", "N/A", "neutral"
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if close.empty:
        return "N/A", "N/A", "neutral"
    current = float(close.iloc[-1])
    previous = float(close.iloc[-2] if len(close) > 1 else close.iloc[-1])
    pct = ((current / previous) - 1.0) * 100.0 if previous else 0.0
    cls = "positive" if pct > 0 else "negative" if pct < 0 else "neutral"
    return f"${current:,.2f}", f"{pct:+.2f}%", cls


def _svg_empty(message: str, width: int, height: int) -> str:
    return (
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="10" fill="{BG}"/>'
        f'<text x="{width/2}" y="{height/2}" text-anchor="middle" fill="{SUBTEXT}" '
        f'font-family="DejaVu Sans, Arial" font-size="13">{html.escape(message)}</text></svg>'
    )


def candles(df: pd.DataFrame, width: int = 720, height: int = 230) -> str:
    if df.empty or len(df) < 2:
        return _svg_empty("Grafic indisponibil", width, height)

    data = df.tail(66).copy()
    for col in ("Open", "High", "Low", "Close"):
        if col not in data.columns:
            return _svg_empty("Grafic indisponibil", width, height)
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["Open", "High", "Low", "Close"])
    if len(data) < 2:
        return _svg_empty("Grafic indisponibil", width, height)

    pad_l, pad_r, pad_t, pad_b = 42, 10, 12, 23
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    low = float(data["Low"].min())
    high = float(data["High"].max())
    span = max(high - low, max(abs(high), 1.0) * 0.01)
    low -= span * 0.05
    high += span * 0.05

    def y(value: float) -> float:
        return pad_t + (high - value) / (high - low) * plot_h

    n = len(data)
    step = plot_w / max(n, 1)
    body_w = max(1.8, min(7.0, step * 0.58))

    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{CARD}"/>',
    ]

    # Grid and price labels.
    for i in range(4):
        frac = i / 3
        yy = pad_t + frac * plot_h
        value = high - frac * (high - low)
        parts.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width-pad_r}" y2="{yy:.1f}" stroke="{BORDER}" stroke-width="1"/>')
        parts.append(
            f'<text x="{pad_l-6}" y="{yy+3:.1f}" text-anchor="end" fill="{MUTED}" '
            f'font-family="DejaVu Sans, Arial" font-size="8">{value:.0f}</text>'
        )

    for idx, row in enumerate(data.itertuples(index=False)):
        x = pad_l + (idx + 0.5) * step
        op = float(getattr(row, "Open"))
        hi = float(getattr(row, "High"))
        lo = float(getattr(row, "Low"))
        cl = float(getattr(row, "Close"))
        color = GREEN if cl >= op else RED
        parts.append(f'<line x1="{x:.2f}" y1="{y(hi):.2f}" x2="{x:.2f}" y2="{y(lo):.2f}" stroke="{color}" stroke-width="1.15"/>')
        top = min(y(op), y(cl))
        bottom = max(y(op), y(cl))
        body_h = max(1.2, bottom - top)
        parts.append(
            f'<rect x="{x-body_w/2:.2f}" y="{top:.2f}" width="{body_w:.2f}" height="{body_h:.2f}" '
            f'rx="0.7" fill="{color}"/>'
        )

    ma20 = data["Close"].rolling(20).mean()
    points: list[str] = []
    for idx, value in enumerate(ma20):
        if pd.isna(value):
            continue
        x = pad_l + (idx + 0.5) * step
        points.append(f"{x:.2f},{y(float(value)):.2f}")
    if len(points) > 1:
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{BLUE}" stroke-width="1.5"/>')

    parts.append(f'<text x="{pad_l}" y="{height-6}" fill="{MUTED}" font-family="DejaVu Sans, Arial" font-size="8">3 luni</text>')
    parts.append(f'<text x="{width-pad_r}" y="{height-6}" text-anchor="end" fill="{BLUE}" font-family="DejaVu Sans, Arial" font-size="8">MA20</text>')
    parts.append("</svg>")
    return "".join(parts)


def _normalized_close(df: pd.DataFrame) -> list[float]:
    if df.empty or "Close" not in df:
        return []
    s = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(s) < 2:
        return []
    base = float(s.iloc[0])
    if not base:
        return []
    return [float(v) / base * 100.0 for v in s]


def market_chart(sp500: pd.DataFrame, nasdaq: pd.DataFrame, width: int = 720, height: int = 210) -> str:
    a = _normalized_close(sp500)
    b = _normalized_close(nasdaq)
    if len(a) < 2 or len(b) < 2:
        return _svg_empty("Date de piață indisponibile", width, height)

    values = a + b
    lo, hi = min(values), max(values)
    span = max(hi - lo, 2.0)
    lo -= span * 0.08
    hi += span * 0.08
    pad_l, pad_r, pad_t, pad_b = 38, 12, 18, 24
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def make_points(series: list[float]) -> str:
        pts: list[str] = []
        denom = max(len(series) - 1, 1)
        for i, value in enumerate(series):
            x = pad_l + (i / denom) * plot_w
            y = pad_t + (hi - value) / (hi - lo) * plot_h
            pts.append(f"{x:.2f},{y:.2f}")
        return " ".join(pts)

    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{CARD}"/>',
    ]
    for i in range(4):
        frac = i / 3
        yy = pad_t + frac * plot_h
        value = hi - frac * (hi - lo)
        parts.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width-pad_r}" y2="{yy:.1f}" stroke="{BORDER}"/>')
        parts.append(f'<text x="{pad_l-5}" y="{yy+3:.1f}" text-anchor="end" fill="{MUTED}" font-family="DejaVu Sans" font-size="8">{value:.0f}</text>')

    parts.append(f'<polyline points="{make_points(a)}" fill="none" stroke="{BLUE}" stroke-width="2.0"/>')
    parts.append(f'<polyline points="{make_points(b)}" fill="none" stroke="{TEXT}" stroke-width="1.8" stroke-dasharray="5 4"/>')
    parts.append(f'<circle cx="{width-175}" cy="13" r="4" fill="{BLUE}"/><text x="{width-166}" y="16" fill="{SUBTEXT}" font-family="DejaVu Sans" font-size="8">S&amp;P 500</text>')
    parts.append(f'<line x1="{width-88}" y1="13" x2="{width-73}" y2="13" stroke="{TEXT}" stroke-width="2" stroke-dasharray="4 3"/><text x="{width-67}" y="16" fill="{SUBTEXT}" font-family="DejaVu Sans" font-size="8">Nasdaq</text>')
    parts.append("</svg>")
    return "".join(parts)


def sentiment(text: str) -> str:
    t = strip_md(text).lower()
    positive = sum(t.count(k) for k in ("pozitiv", "ascendent", "constructiv", "bullish", "avans", "creșter"))
    negative = sum(t.count(k) for k in ("negativ", "descendent", "defensiv", "bearish", "scăder", "slăbici"))
    return "Pozitiv" if positive >= negative + 2 else "Prudent" if negative >= positive + 2 else "Neutru"


def risk(text: str) -> str:
    t = strip_md(text).lower()
    high = sum(t.count(k) for k in ("risc ridicat", "volatilitate ridicată", "incertitudine ridicată", "risc major"))
    low = sum(t.count(k) for k in ("risc scăzut", "volatilitate redusă", "risc redus"))
    return "Ridicat" if high >= 2 else "Scăzut" if low >= 2 and not high else "Mediu"


def sigclass(signal: str) -> str:
    s = strip_md(signal).lower()
    if any(k in s for k in ("cump", "strong buy", "buy")):
        return "positive"
    if any(k in s for k in ("vinde", "vânzare", "strong sell", "sell")):
        return "negative"
    return "warning"


def badge(text: str) -> str:
    value = text if text and text != "N/A" else "Păstrează"
    return f'<span class="badge badge-{sigclass(value)}">{html.escape(value)}</span>'


def section_card(title: str, body: str) -> str:
    t = title.lower()
    ico = (
        "shield" if "risc" in t
        else "target" if "plan" in t or "acți" in t or "nivel" in t
        else "news" if "știr" in t or "actualiz" in t or "catal" in t
        else "chart" if "date" in t or "piață" in t or "indicator" in t
        else "trend" if "concluz" in t or "perspect" in t or "trend" in t
        else "info"
    )
    return (
        '<div class="content-card">'
        f'<div class="card-title">{icon(ico, 17, BLUE)}<span>{html.escape(title)}</span></div>'
        f'<div class="markdown">{md(body)}</div>'
        '</div>'
    )


def _first_meaningful_paragraph(markdown_text: str, limit: int = 640) -> str:
    sections = market_sections(markdown_text)
    source = sections[0][1] if sections else markdown_text
    text = strip_md(source)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text or "Raportul sintetizează contextul pieței, trendul și principalele riscuri ale zilei."


def executive(stocks: list[Stock], market_md: str, stock_data: dict[str, pd.DataFrame], now: datetime) -> str:
    scores = [s.score for s in stocks if s.score is not None]
    avg = round(sum(scores) / len(scores)) if scores else 0
    sent = sentiment(market_md)
    rk = risk(market_md + "\n" + "\n".join(s.details for s in stocks))
    ticker_line = " · ".join(s.ticker for s in stocks[:5]) or "Piața SUA"
    if len(stocks) > 5:
        ticker_line += f" · +{len(stocks)-5}"

    kpis = [
        ("chart", "Sentiment piață", sent),
        ("gauge", "Scor mediu", f"{avg}/100" if scores else "N/A"),
        ("shield", "Nivel risc", rk),
        ("stack", "Analizate", f"{len(stocks)} instrumente"),
    ]
    kpi_html = "".join(
        f'<td><div class="kpi"><div class="kpi-icon">{icon(i, 19, BLUE)}</div>'
        f'<small>{html.escape(label)}</small><strong>{html.escape(value)}</strong></div></td>'
        for i, label, value in kpis
    )

    # Executive cards: first 3 tickers from the report.
    cards: list[str] = []
    for s in stocks[:3]:
        df = stock_data.get(s.ticker, pd.DataFrame())
        px, change, cls = price_snapshot(df)
        score_text = str(s.score) if s.score is not None else "N/A"
        cards.append(
            '<td><div class="stock-card">'
            '<div class="stock-top">'
            f'<div><b>{html.escape(s.ticker)}</b><small>{html.escape(s.name)}</small></div>{badge(s.signal)}'
            '</div>'
            f'<div class="price">{px}<span class="{cls}">{change}</span></div>'
            f'{candles(df.tail(44), 300, 92)}'
            '<div class="micro">'
            f'<span>Scor <b>{score_text}</b></span><span>Trend <b>{html.escape(s.trend)}</b></span>'
            '</div></div></td>'
        )

    return f'''<section class="page">
<div class="top">
  <div>
    <div class="eyebrow">PIAȚA SUA · RAPORT ZILNIC</div>
    <h1>Analiza zilnică a acțiunilor</h1>
    <p>{ro_date(now)} · {html.escape(ticker_line)}</p>
  </div>
  <div class="time">{icon('clock', 16, MUTED)} Generat {now:%H:%M}</div>
</div>
<table class="kpi-row"><tr>{kpi_html}</tr></table>
<div class="summary"><b>{icon('info', 18, BLUE)} Rezumatul zilei</b><p>{html.escape(_first_meaningful_paragraph(market_md))}</p></div>
<div class="label">Instrumente evidențiate</div>
<table class="stocks-row"><tr>{''.join(cards)}</tr></table>
<div class="foot"><span>Analiză automată · date de piață + context AI</span><span>Nu constituie recomandare de investiții.</span></div>
</section>'''


def _market_snapshot_cards(market_data: dict[str, pd.DataFrame]) -> str:
    items = [("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Dow Jones", "^DJI"), ("VIX", "^VIX")]
    cells: list[str] = []
    for label, ticker in items:
        px, change, cls = price_snapshot(market_data.get(ticker, pd.DataFrame()))
        cells.append(
            f'<td><div class="market-kpi"><small>{html.escape(label)}</small>'
            f'<b>{px}</b><span class="{cls}">{change}</span></div></td>'
        )
    return '<table class="market-kpis"><tr>' + "".join(cells) + '</tr></table>'


def market_page(text: str, market_data: dict[str, pd.DataFrame]) -> str:
    cards = [section_card(title, body) for title, body in market_sections(text)]
    left = "".join(cards[::2])
    right = "".join(cards[1::2])
    sp = market_data.get("^GSPC", pd.DataFrame())
    nd = market_data.get("^IXIC", pd.DataFrame())

    return f'''<section class="page break">
<div class="page-title">{icon('chart', 22, BLUE)}<div><div class="eyebrow">MARKET OVERVIEW</div><h2>Recapitularea pieței SUA</h2></div></div>
{_market_snapshot_cards(market_data)}
<div class="chart-card"><div class="chart-head"><div><b>S&P 500 + Nasdaq</b><small>ultimele 3 luni · performanță normalizată (100 = început)</small></div>{icon('trend', 19, BLUE)}</div>{market_chart(sp, nd)}</div>
<table class="cols"><tr><td>{left}</td><td>{right}</td></tr></table>
<div class="foot"><span>Market overview</span><span>Nu constituie recomandare de investiții.</span></div>
</section>'''


def stock_page(stock: Stock, df: pd.DataFrame) -> str:
    px, change, cls = price_snapshot(df)
    cards = [section_card(title, body) for title, body in stock_sections(stock.details)]
    left = "".join(cards[::2])
    right = "".join(cards[1::2])
    score_text = f"{stock.score}/100" if stock.score is not None else "N/A"
    risk_text = risk(stock.details)

    return f'''<section class="page break">
<div class="hero">
  <div><div class="ticker-big">{html.escape(stock.ticker)}</div><div class="name-big">{html.escape(stock.name)}</div></div>
  <div class="hero-right"><div class="price-big">{px}</div><span class="{cls}">{change}</span> {badge(stock.signal)}</div>
</div>
<div class="chart-card"><div class="chart-head"><div><b>Grafic candlestick</b><small>3 luni · MA20</small></div>{icon('candles', 20, BLUE)}</div>{candles(df)}</div>
<table class="stock-kpis"><tr>
<td><small>Scor</small><b>{html.escape(score_text)}</b></td>
<td><small>Trend</small><b>{html.escape(stock.trend)}</b></td>
<td><small>Semnal</small><b>{html.escape(stock.signal)}</b></td>
<td><small>Risc</small><b>{html.escape(risk_text)}</b></td>
</tr></table>
<table class="cols"><tr><td>{left}</td><td>{right}</td></tr></table>
<div class="foot"><span>{html.escape(stock.ticker)} · raport detaliat</span><span>Nu constituie recomandare de investiții.</span></div>
</section>'''


CSS = r'''
@page{size:A4;margin:8mm}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{font-family:"DejaVu Sans","Noto Sans",Arial,sans-serif;background:#F8FAFC;color:#0F172A;font-size:10pt;line-height:1.45}
.page{min-height:260mm;padding:2mm 1mm 7mm;position:relative;page-break-after:always}
.page:last-child{page-break-after:auto}.break{}.icon{vertical-align:-3px}.eyebrow{font-size:8pt;letter-spacing:1.45px;color:#2563EB;font-weight:700;margin-bottom:4px}h1{font-size:25pt;margin:0;line-height:1.12}h2{font-size:18pt;margin:0}.top{display:table;width:100%;margin-bottom:12px}.top>div{display:table-cell;vertical-align:top}.top p{color:#64748B;margin:6px 0}.time{text-align:right;color:#64748B;font-size:8.4pt;white-space:nowrap}.kpi-row,.stocks-row,.stock-kpis,.market-kpis,.cols{width:100%;table-layout:fixed;border-collapse:separate}.kpi-row{border-spacing:5px;margin-bottom:12px}.kpi{background:white;border:1px solid #E2E8F0;border-radius:11px;padding:9px;min-height:66px}.kpi-icon{float:right}.kpi small,.stock-kpis small,.market-kpis small{display:block;color:#64748B;font-size:7.6pt}.kpi strong{display:block;font-size:14pt;margin-top:7px}.summary,.content-card,.chart-card,.stock-card,.market-kpi{background:white;border:1px solid #E2E8F0;border-radius:12px}.summary{padding:11px 13px;margin-bottom:13px}.summary p{color:#334155;margin:6px 0 0;font-size:9.2pt}.label{text-transform:uppercase;letter-spacing:1px;color:#64748B;font-size:7.8pt;font-weight:700;margin-bottom:6px}.stocks-row{border-spacing:5px}.stocks-row td{vertical-align:top}.stock-card{padding:9px;min-height:218px}.stock-top{display:table;width:100%}.stock-top>div{display:table-cell}.stock-top b{display:block;font-size:13.5pt}.stock-top small{display:block;color:#64748B;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:128px}.stock-top .badge{float:right}.price{font-size:13pt;font-weight:700;margin:7px 0 3px}.price span{font-size:8.3pt;margin-left:5px}.positive{color:#16A34A}.negative{color:#DC2626}.neutral{color:#64748B}.micro{display:table;width:100%;background:#F8FAFC;border-radius:7px;padding:5px}.micro span{display:table-cell;width:50%;font-size:7.4pt;color:#64748B}.micro b{color:#0F172A}.badge{display:inline-block;border-radius:999px;padding:4px 7px;font-size:7.1pt;font-weight:700;border:1px solid}.badge-positive{color:#166534;background:#F0FDF4;border-color:#BBF7D0}.badge-negative{color:#991B1B;background:#FEF2F2;border-color:#FECACA}.badge-warning{color:#92400E;background:#FFFBEB;border-color:#FDE68A}.foot{position:absolute;bottom:1.5mm;left:1mm;right:1mm;border-top:1px solid #E2E8F0;padding-top:5px;color:#94A3B8;font-size:6.8pt}.foot span:last-child{float:right}.page-title{display:table;width:100%;margin-bottom:9px}.page-title>svg,.page-title>div{display:table-cell;vertical-align:middle}.page-title>div{padding-left:8px}.market-kpis{border-spacing:5px;margin-bottom:9px}.market-kpi{padding:7px 9px}.market-kpi b{display:block;font-size:10.5pt;margin-top:2px}.market-kpi span{font-size:7.5pt}.chart-card{padding:9px 11px;margin-bottom:9px}.chart-head{display:table;width:100%;margin-bottom:5px}.chart-head>div,.chart-head>svg{display:table-cell;vertical-align:middle}.chart-head small{display:block;color:#64748B;font-size:7.6pt;margin-top:2px}.chart-head>svg{float:right}.chart-svg{width:100%;height:auto;display:block}.cols{border-spacing:5px}.cols>tbody>tr>td{width:50%;vertical-align:top}.content-card{padding:8px 9px;margin-bottom:7px;page-break-inside:avoid}.card-title{border-bottom:1px solid #F1F5F9;padding-bottom:5px;margin-bottom:4px;font-weight:700;font-size:9pt}.card-title span{margin-left:5px}.markdown{font-size:8.05pt;color:#334155}.markdown p{margin:3px 0 4px}.markdown ul,.markdown ol{margin:3px 0 5px 16px;padding:0}.markdown li{margin:1px 0}.markdown blockquote{margin:4px 0;padding:4px 6px;background:#F8FAFC;border-left:3px solid #93C5FD}.markdown table{width:100%;border-collapse:collapse;margin:5px 0;table-layout:fixed}.markdown th,.markdown td{border-bottom:1px solid #E2E8F0;padding:3px 4px;text-align:left;vertical-align:top;word-wrap:break-word}.markdown th{font-size:7pt;color:#64748B;background:#F8FAFC}.markdown h1,.markdown h2,.markdown h3,.markdown h4{font-size:8.8pt;margin:5px 0 3px}.hero{display:table;width:100%;margin-bottom:8px}.hero>div{display:table-cell;vertical-align:top}.ticker-big{font-size:23pt;font-weight:800}.name-big{color:#64748B;margin-top:1px}.hero-right{text-align:right}.price-big{font-size:17pt;font-weight:750}.hero-right>.badge{margin-left:5px}.stock-kpis{border-spacing:5px;margin-bottom:8px}.stock-kpis td{width:25%;background:white;border:1px solid #E2E8F0;border-radius:9px;padding:7px 8px}.stock-kpis b{display:block;margin-top:2px;font-size:9.2pt}
'''


def build_html(
    stock_md: str,
    market_md: str,
    stocks: list[Stock],
    stock_data: dict[str, pd.DataFrame],
    market_data: dict[str, pd.DataFrame],
) -> str:
    now = datetime.now(TZ)
    pages = [executive(stocks, market_md, stock_data, now)]
    if market_md.strip():
        pages.append(market_page(market_md, market_data))
    pages.extend(stock_page(stock, stock_data.get(stock.ticker, pd.DataFrame())) for stock in stocks)

    return Template(
        '<!doctype html><html lang="ro"><head><meta charset="utf-8">'
        '<title>Analiza zilnică a acțiunilor</title><style>$css</style></head>'
        '<body>$pages</body></html>'
    ).safe_substitute(css=CSS, pages="\n".join(pages))


def _fallback_stocks_from_env() -> list[Stock]:
    raw = os.getenv("STOCK_LIST") or os.getenv("STOCK_LIST_CONFIG") or "AAPL,TSLA,NVDA"
    return [Stock(ticker=x.strip().upper(), name=x.strip().upper()) for x in raw.split(",") if x.strip()]


def _render_pdf(html_path: Path, output_path: Path) -> None:
    wkhtmltopdf = shutil.which("wkhtmltopdf")
    xvfb_run = shutil.which("xvfb-run")
    if not wkhtmltopdf:
        raise RuntimeError("wkhtmltopdf nu este instalat. În GitHub Actions instalează pachetul wkhtmltopdf.")

    command: list[str] = []
    if xvfb_run:
        command.extend([xvfb_run, "-a"])
    command.extend(
        [
            wkhtmltopdf,
            "--encoding", "UTF-8",
            "--enable-local-file-access",
            "--print-media-type",
            "--margin-top", "7",
            "--margin-right", "7",
            "--margin-bottom", "8",
            "--margin-left", "7",
            "--quiet",
            str(html_path),
            str(output_path),
        ]
    )
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generează raportul PDF premium pentru daily_stock_analysis.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--output", default="")
    parser.add_argument("--html-output", default="", help="Opțional: salvează și HTML-ul pentru debugging.")
    args = parser.parse_args()

    folder = Path(args.reports_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stock_file, market_file = reports_in(folder)

    if not stock_file and not market_file:
        raise SystemExit("Nu am găsit rapoarte Markdown în reports/.")

    stock_md = stock_file.read_text(encoding="utf-8") if stock_file else ""
    market_md = market_file.read_text(encoding="utf-8") if market_file else ""

    stocks = parse_stocks(stock_md)
    if not stocks:
        stocks = _fallback_stocks_from_env()

    print(f"[PDF] Instrumente detectate: {', '.join(s.ticker for s in stocks)}")

    stock_data = {stock.ticker: ohlc(stock.ticker) for stock in stocks}
    market_data = {ticker: ohlc(ticker) for ticker in ("^GSPC", "^IXIC", "^DJI", "^VIX")}

    html_text = build_html(stock_md, market_md, stocks, stock_data, market_data)

    if args.html_output:
        html_debug = Path(args.html_output)
        html_debug.parent.mkdir(parents=True, exist_ok=True)
        html_debug.write_text(html_text, encoding="utf-8")
        print(f"[PDF] HTML debug: {html_debug}")

    now = datetime.now(TZ)
    output = Path(args.output) if args.output else folder / f"daily_stock_analysis_{now:%Y%m%d}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        html_path = Path(temp_dir) / "report.html"
        html_path.write_text(html_text, encoding="utf-8")
        _render_pdf(html_path, output)

    print(output)


if __name__ == "__main__":
    main()
