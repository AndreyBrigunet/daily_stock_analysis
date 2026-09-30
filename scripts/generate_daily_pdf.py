

def price_snapshot(df: pd.DataFrame):
    if df.empty:
        return "N/A", "N/A", "neutral"
    c = pd.to_numeric(df.Close, errors="coerce").dropna()
    if c.empty:
        return "N/A", "N/A", "neutral"
    now, prev = float(c.iloc[-1]), float(c.iloc[-2] if len(c) > 1 else c.iloc[-1])
    pct = (now / prev - 1) * 100 if prev else 0
    cls = "positive" if pct > 0 else "negative" if pct < 0 else "neutral"
    return f"${now:,.2f}", f"{pct:+.2f}%", cls


def sentiment(text: str):
    t = no_emoji(text).lower()
    p = sum(t.count(k) for k in ("pozitiv", "ascendent", "constructiv", "bullish", "avans", "creșter"))
    n = sum(t.count(k) for k in ("negativ", "descendent", "defensiv", "bearish", "scăder", "slăbici"))
    return "Pozitiv" if p >= n + 2 else "Prudent" if n >= p + 2 else "Neutru"


def risk(text: str):
    t = no_emoji(text).lower()
    high = sum(t.count(k) for k in ("risc ridicat", "volatilitate ridicată", "incertitudine ridicată"))
    low = sum(t.count(k) for k in ("risc scăzut", "volatilitate redusă"))
    return "Ridicat" if high >= 2 else "Scăzut" if low >= 2 and not high else "Mediu"


def sigclass(s: str):
    s = s.lower()
    return "positive" if any(k in s for k in ("cump", "buy")) else "negative" if any(k in s for k in ("vinde", "sell")) else "warning"


def badge(text: str):
    return f'<span class="badge badge-{sigclass(text)}">{html.escape(text or "N/A")}</span>'


def section_card(title, body):
    t = title.lower()
    ico = "shield" if "risc" in t else "target" if "plan" in t or "acți" in t else "news" if "știr" in t or "actualiz" in t else "chart" if "date" in t or "data" in t else "trend" if "concluz" in t else "info"
    return f'<div class="content-card"><div class="card-title">{icon(ico,17,BLUE)}<span>{html.escape(title)}</span></div><div class="markdown">{md(body)}</div></div>'


def ro_date(dt: datetime):
    months = ["ianuarie","februarie","martie","aprilie","mai","iunie","iulie","august","septembrie","octombrie","noiembrie","decembrie"]
    return f"{dt.day} {months[dt.month-1]} {dt.year}"


def executive(stocks, market_md, data, now):
    scores = [s.score for s in stocks if s.score is not None]
    avg = round(sum(scores)/len(scores)) if scores else 0
    sent, rk = sentiment(market_md), risk(market_md + "\n" + "\n".join(s.details for s in stocks))
    tickers = " · ".join(s.ticker for s in stocks[:5]) or "Piața SUA"
    kpis = [("chart","Sentiment piață",sent),("gauge","Scor mediu",f"{avg}/100"),("shield","Nivel risc",rk),("stack","Analizate",f"{len(stocks)} acțiuni")]
    kpi_html = "".join(f'<td><div class="kpi"><div class="kpi-icon">{icon(i,19,BLUE)}</div><small>{html.escape(l)}</small><strong>{html.escape(v)}</strong></div></td>' for i,l,v in kpis)
    cards = []
    for s in stocks[:3]:
        px, ch, cls = price_snapshot(data.get(s.ticker, pd.DataFrame()))
        cards.append(f'''<td><div class="stock-card"><div class="stock-top"><div><b>{s.ticker}</b><small>{html.escape(s.name)}</small></div>{badge(s.signal)}</div><div class="price">{px}<span class="{cls}">{ch}</span></div>{candles(data.get(s.ticker,pd.DataFrame()).tail(44),300,92)}<div class="micro"><span>Scor <b>{s.score if s.score is not None else 'N/A'}</b></span><span>Trend <b>{html.escape(s.trend)}</b></span></div></div></td>''')
    return f'''<section class="page"><div class="top"><div><div class="eyebrow">PIAȚA SUA · RAPORT ZILNIC</div><h1>Analiza zilnică a acțiunilor</h1><p>{ro_date(now)} · {html.escape(tickers)}</p></div><div class="time">{icon('clock',16,MUTED)} Generat {now:%H:%M}</div></div><table class="kpi-row"><tr>{kpi_html}</tr></table><div class="summary"><b>{icon('info',18,BLUE)} Rezumatul zilei</b><p>Raportul urmărește contextul pieței SUA și <strong>{len(stocks)}</strong> acțiuni. Sentimentul general este <strong>{sent.lower()}</strong>, scorul mediu este <strong>{avg}/100</strong>, iar nivelul general de risc este <strong>{rk.lower()}</strong>. Accentul este pus pe trend, niveluri tehnice, riscuri și un plan de acțiune simplu.</p></div><div class="label">Acțiunile urmărite</div><table class="stocks-row"><tr>{''.join(cards)}</tr></table><div class="foot"><span>Analiză automată · date de piață + context AI</span><span>Nu constituie recomandare de investiții.</span></div></section>'''


def market_page(text):
    cards = [section_card(t,b) for t,b in market_sections(text)]
    left, right = "".join(cards[::2]), "".join(cards[1::2])
    return f'''<section class="page break"><div class="page-title">{icon('chart',22,BLUE)}<div><div class="eyebrow">MARKET OVERVIEW</div><h2>Recapitularea pieței SUA</h2></div></div><div class="chart-card"><div class="chart-head"><div><b>S&P 500 + Nasdaq</b><small>ultimele 3 luni · performanță normalizată</small></div>{icon('trend',19,BLUE)}</div>{market_chart()}</div><table class="cols"><tr><td>{left}</td><td>{right}</td></tr></table></section>'''


def stock_page(s: Stock, df: pd.DataFrame):
    px, ch, cls = price_snapshot(df)
    cards = [section_card(t,b) for t,b in stock_sections(s.details)]
    left, right = "".join(cards[::2]), "".join(cards[1::2])
    return f'''<section class="page break"><div class="hero"><div><div class="ticker-big">{s.ticker}</div><div class="name-big">{html.escape(s.name)}</div></div><div class="hero-right"><div class="price-big">{px}</div><span class="{cls}">{ch}</span> {badge(s.signal)}</div></div><div class="chart-card"><div class="chart-head"><div><b>Grafic candlestick</b><small>3 luni · MA20</small></div>{icon('candles',20,BLUE)}</div>{candles(df)}</div><table class="stock-kpis"><tr><td><small>Scor</small><b>{s.score if s.score is not None else 'N/A'}/100</b></td><td><small>Trend</small><b>{html.escape(s.trend)}</b></td><td><small>Semnal</small><b>{html.escape(s.signal)}</b></td><td><small>Orizont</small><b>1–4 săptămâni</b></td></tr></table><table class="cols"><tr><td>{left}</td><td>{right}</td></tr></table></section>'''


CSS = r'''
@page{size:A4;margin:9mm}*{box-sizing:border-box}html,body{margin:0}body{font-family:"DejaVu Sans","Noto Sans",Arial,sans-serif;background:#F8FAFC;color:#0F172A;font-size:10pt;line-height:1.45}.page{min-height:278mm;padding:2mm 1mm;position:relative}.break{page-break-before:always}.icon{vertical-align:-3px}.eyebrow{font-size:8pt;letter-spacing:1.5px;color:#2563EB;font-weight:700;margin-bottom:4px}h1{font-size:26pt;margin:0;line-height:1.12}h2{font-size:19pt;margin:0}.top{display:table;width:100%;margin-bottom:13px}.top>div{display:table-cell;vertical-align:top}.top p{color:#64748B;margin:6px 0}.time{text-align:right;color:#64748B;font-size:8.5pt;white-space:nowrap}.kpi-row,.stocks-row,.stock-kpis,.cols{width:100%;table-layout:fixed;border-collapse:separate}.kpi-row{border-spacing:6px;margin-bottom:13px}.kpi{background:white;border:1px solid #E2E8F0;border-radius:11px;padding:10px;min-height:68px}.kpi-icon{float:right}.kpi small,.stock-kpis small{display:block;color:#64748B;font-size:7.8pt}.kpi strong{display:block;font-size:15pt;margin-top:8px}.summary,.content-card,.chart-card,.stock-card{background:white;border:1px solid #E2E8F0;border-radius:12px}.summary{padding:12px 14px;margin-bottom:14px}.summary p{color:#334155;margin:7px 0 0}.label{text-transform:uppercase;letter-spacing:1px;color:#64748B;font-size:8pt;font-weight:700;margin-bottom:7px}.stocks-row{border-spacing:5px}.stocks-row td{vertical-align:top}.stock-card{padding:10px;min-height:230px}.stock-top{display:table;width:100%}.stock-top>div{display:table-cell}.stock-top b{display:block;font-size:14pt}.stock-top small{display:block;color:#64748B;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:125px}.stock-top .badge{float:right}.price{font-size:13.5pt;font-weight:750;margin:8px 0 4px}.price span{font-size:8.5pt;margin-left:6px}.positive{color:#16A34A}.negative{color:#DC2626}.neutral{color:#64748B}.micro{display:table;width:100%;background:#F8FAFC;border-radius:7px;padding:5px}.micro span{display:table-cell;width:50%;font-size:7.7pt;color:#64748B}.micro b{color:#0F172A}.badge{display:inline-block;border-radius:999px;padding:4px 7px;font-size:7.3pt;font-weight:700;border:1px solid}.badge-positive{color:#166534;background:#F0FDF4;border-color:#BBF7D0}.badge-negative{color:#991B1B;background:#FEF2F2;border-color:#FECACA}.badge-warning{color:#92400E;background:#FFFBEB;border-color:#FDE68A}.foot{position:absolute;bottom:2mm;left:1mm;right:1mm;border-top:1px solid #E2E8F0;padding-top:6px;color:#94A3B8;font-size:7pt}.foot span:last-child{float:right}.page-title{display:table;width:100%;margin-bottom:11px}.page-title>svg,.page-title>div{display:table-cell;vertical-align:middle}.page-title>div{padding-left:9px}.chart-card{padding:10px 12px;margin-bottom:11px}.chart-head{display:table;width:100%;margin-bottom:6px}.chart-head>div,.chart-head>svg{display:table-cell;vertical-align:middle}.chart-head small{display:block;color:#64748B;font-size:7.8pt;margin-top:2px}.chart-head>svg{float:right}.chart-svg{width:100%;height:auto;display:block}.cols{border-spacing:5px}.cols>tbody>tr>td{width:50%;vertical-align:top}.content-card{padding:9px 10px;margin-bottom:8px;page-break-inside:avoid}.card-title{border-bottom:1px solid #F1F5F9;padding-bottom:6px;margin-bottom:5px;font-weight:700;font-size:9.2pt}.card-title span{margin-left:5px}.markdown{font-size:8.35pt;color:#334155}.markdown p{margin:3px 0 5px}.markdown ul,.markdown ol{margin:4px 0 6px 17px;padding:0}.markdown li{margin:1px 0}.markdown blockquote{margin:5px 0;padding:5px 7px;background:#F8FAFC;border-left:3px solid #93C5FD}.markdown table{width:100%;border-collapse:collapse;margin:6px 0;table-layout:fixed}.markdown th,.markdown td{border-bottom:1px solid #E2E8F0;padding:3px 4px;text-align:left;vertical-align:top;word-wrap:break-word}.markdown th{font-size:7.2pt;color:#64748B;background:#F8FAFC}.markdown h1,.markdown h2,.markdown h3,.markdown h4{font-size:9pt;margin:6px 0 3px}.hero{display:table;width:100%;margin-bottom:9px}.hero>div{display:table-cell;vertical-align:top}.ticker-big{font-size:24pt;font-weight:800}.name-big{color:#64748B;margin-top:2px}.hero-right{text-align:right}.price-big{font-size:18pt;font-weight:780}.hero-right>.badge{margin-left:6px}.stock-kpis{border-spacing:5px;margin-bottom:10px}.stock-kpis td{width:25%;background:white;border:1px solid #E2E8F0;border-radius:9px;padding:7px 9px}.stock-kpis b{display:block;margin-top:2px;font-size:9.6pt}
'''


def build_html(stock_md, market_md, stocks, data):
    now = datetime.now(TZ)
    pages = [executive(stocks, market_md, data, now)]
    if market_md.strip():
        pages.append(market_page(market_md))
    pages += [stock_page(s, data.get(s.ticker, pd.DataFrame())) for s in stocks]
    return Template('<!doctype html><html lang="ro"><head><meta charset="utf-8"><title>Analiza zilnică a acțiunilor</title><style>$css</style></head><body>$pages</body></html>').safe_substitute(css=CSS,pages='\n'.join(pages))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--output", default="")
    args = p.parse_args()
    folder = Path(args.reports_dir); folder.mkdir(parents=True, exist_ok=True)
    stock_file, market_file = reports_in(folder)
    if not stock_file and not market_file:
        raise SystemExit("Nu am găsit rapoarte Markdown în reports/.")
    stock_md = stock_file.read_text(encoding="utf-8") if stock_file else ""
    market_md = market_file.read_text(encoding="utf-8") if market_file else ""
    stocks = parse_stocks(stock_md)
    if not stocks:
        raw = os.getenv("STOCK_LIST") or os.getenv("STOCK_LIST_CONFIG") or "AAPL,TSLA,NVDA"
        stocks = [Stock(x.strip().upper(), x.strip().upper()) for x in raw.split(",") if x.strip()]
    data = {s.ticker: ohlc(s.ticker) for s in stocks}
    html_text = build_html(stock_md, market_md, stocks, data)
    now = datetime.now(TZ)
    out = Path(args.output) if args.output else folder / f"daily_stock_analysis_{now:%Y%m%d}.pdf"
    with tempfile.TemporaryDirectory() as td:
        hp = Path(td)/"report.html"; hp.write_text(html_text, encoding="utf-8")
        subprocess.run(["xvfb-run","-a","wkhtmltopdf","--encoding","UTF-8","--enable-local-file-access","--print-media-type","--margin-top","7","--margin-right","7","--margin-bottom","8","--margin-left","7","--quiet",str(hp),str(out)], check=True)
    print(out)


if __name__ == "__main__":
    main()
