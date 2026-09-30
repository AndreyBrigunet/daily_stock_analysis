from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown2


def newest_file(files: list[Path]) -> Path | None:
    files = [f for f in files if f.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def find_reports(reports_dir: Path) -> tuple[Path | None, Path | None]:
    # Raport agregat: report_YYYYMMDD.md
    stock_reports = [
        p
        for p in reports_dir.glob("report_*.md")
        if re.fullmatch(r"report_\d{8}\.md", p.name)
    ]

    market_reports = list(reports_dir.glob("market_review_*.md"))

    return newest_file(stock_reports), newest_file(market_reports)


def build_html(markdown_text: str, title: str) -> str:
    body = markdown2.markdown(
        markdown_text,
        extras=[
            "tables",
            "fenced-code-blocks",
            "strike",
            "task_list",
        ],
    )

    return f"""<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">

<style>
@page {{
    size: A4;
    margin: 16mm 14mm 18mm 14mm;
}}

body {{
    font-family: "DejaVu Sans", "Noto Sans", Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #202124;
}}

h1 {{
    font-size: 22pt;
    margin-bottom: 18px;
}}

h2 {{
    font-size: 16pt;
    margin-top: 24px;
    border-bottom: 1px solid #dddddd;
    padding-bottom: 6px;
}}

h3 {{
    font-size: 12.5pt;
    margin-top: 18px;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0 18px 0;
    font-size: 9.5pt;
}}

th, td {{
    border: 1px solid #dddddd;
    padding: 6px 8px;
    vertical-align: top;
}}

th {{
    background: #f3f4f6;
    font-weight: 600;
}}

blockquote {{
    margin: 12px 0;
    padding: 8px 14px;
    border-left: 4px solid #888888;
    background: #f7f7f7;
}}

code {{
    font-family: "DejaVu Sans Mono", monospace;
    font-size: 9pt;
}}

a {{
    color: #333333;
    text-decoration: none;
}}

.page-break {{
    page-break-before: always;
}}

.pdf-title {{
    text-align: center;
    margin-bottom: 28px;
}}

.pdf-meta {{
    text-align: center;
    color: #666666;
    margin-bottom: 28px;
}}

.disclaimer {{
    margin-top: 30px;
    padding-top: 10px;
    border-top: 1px solid #cccccc;
    color: #666666;
    font-size: 8.5pt;
}}
</style>
</head>

<body>

<h1 class="pdf-title">{title}</h1>

<div class="pdf-meta">
Generat automat · {datetime.now(ZoneInfo("Europe/Chisinau")).strftime("%d.%m.%Y %H:%M")}
</div>

{body}

<div class="disclaimer">
Conținut generat cu ajutorul AI, exclusiv în scop informativ.
Nu constituie recomandare de investiții.
</div>

</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    stock_report, market_report = find_reports(reports_dir)

    if not stock_report and not market_report:
        raise SystemExit("Nu am găsit niciun raport Markdown.")

    sections: list[str] = []

    # Întâi piața SUA
    if market_report:
        sections.append(market_report.read_text(encoding="utf-8"))

    # Apoi acțiunile
    if stock_report:
        if sections:
            sections.append('<div class="page-break"></div>')
        sections.append(stock_report.read_text(encoding="utf-8"))

    combined_markdown = "\n\n".join(sections)

    now = datetime.now(ZoneInfo("Europe/Chisinau"))
    pdf_path = reports_dir / f"daily_stock_analysis_{now:%Y%m%d}.pdf"

    html = build_html(
        combined_markdown,
        "Analiza zilnică a acțiunilor",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        html_path = Path(temp_dir) / "report.html"
        html_path.write_text(html, encoding="utf-8")

        subprocess.run(
            [
                "xvfb-run",
                "-a",
                "wkhtmltopdf",
                "--encoding",
                "UTF-8",
                "--enable-local-file-access",
                "--quiet",
                str(html_path),
                str(pdf_path),
            ],
            check=True,
        )

    print(pdf_path)


if __name__ == "__main__":
    main()
