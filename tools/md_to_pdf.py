#!/usr/bin/env python3
"""Markdown(+mermaid) → PDF 변환 (headless Chrome 인쇄).

mermaid 코드펜스를 <pre class="mermaid">로 넘겨 브라우저에서 렌더링한 뒤
PDF로 인쇄한다. mermaid.js는 HTML에 인라인되므로 렌더링 자체는 오프라인이며,
최초 1회만 tools/vendor/mermaid.min.js로 내려받는다 (이후 재사용).

사용:
  python3 tools/md_to_pdf.py docs/07_데이터흐름.md -o docs/pdf/07_데이터흐름.pdf
"""
from __future__ import annotations

import argparse
import base64
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

MERMAID_FENCE = re.compile(r"^```mermaid\n(.*?)^```\n", re.DOTALL | re.MULTILINE)
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"
DEFAULT_MERMAID = Path(__file__).parent / "vendor" / "mermaid.min.js"


def ensure_mermaid(path: Path) -> Path:
    """mermaid.min.js가 없으면 1회 다운로드 (저장소에는 커밋하지 않는다)."""
    if path.is_file():
        return path
    import urllib.request

    print(f"mermaid.js 다운로드: {MERMAID_URL}")
    path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(MERMAID_URL, path)
    return path

CSS = """
@page { size: A4; margin: 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: "Noto Sans CJK KR", "DejaVu Sans", sans-serif;
       font-size: 10.5pt; line-height: 1.6; color: #1a1a1a; margin: 0; }
h1 { font-size: 20pt; border-bottom: 2px solid #333; padding-bottom: 6px;
     margin: 0 0 14px; }
h2 { font-size: 14pt; margin: 20px 0 8px; padding-bottom: 3px;
     border-bottom: 1px solid #ccc; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14px 0 6px; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt;
       background: #f4f4f4; padding: 1px 4px; border-radius: 3px; }
pre { background: #f7f7f7; border: 1px solid #e0e0e0; border-radius: 4px;
      padding: 8px 10px; overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8.5pt; line-height: 1.45; }
table { border-collapse: collapse; width: 100%; margin: 10px 0;
        font-size: 9pt; page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 5px 7px; text-align: left;
         vertical-align: top; }
th { background: #efefef; font-weight: 600; }
blockquote { border-left: 3px solid #bbb; margin: 10px 0; padding: 2px 12px;
             color: #555; }
/* 다이어그램: 페이지 폭·높이 안에 들어오게 축소 (넘치면 빈 페이지가 생긴다) */
.mermaid { text-align: center; margin: 14px 0; page-break-inside: avoid; }
.mermaid svg { max-width: 100%; max-height: 250mm; height: auto; }
a { color: #0b5cad; text-decoration: none; }
hr { border: none; border-top: 1px solid #ddd; margin: 18px 0; }
"""

HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<style>{css}</style>
<script src="data:text/javascript;base64,{mermaid_b64}"></script>
</head><body>
{body}
<script>
// 축소 인쇄를 견디도록 다이어그램 글꼴을 키운다
mermaid.initialize({{
  startOnLoad: false, theme: 'neutral',
  themeVariables: {{ fontSize: '18px', fontFamily: 'Noto Sans CJK KR, sans-serif' }},
  flowchart: {{ useMaxWidth: true, nodeSpacing: 30, rankSpacing: 35 }},
  sequence: {{ useMaxWidth: true }},
}});
mermaid.run().then(() => {{ document.title = 'ready:' + document.title; }});
</script>
</body></html>
"""


def convert(md_path: Path, out_pdf: Path, mermaid_js: Path) -> None:
    text = md_path.read_text(encoding="utf-8")

    # mermaid 블록을 플레이스홀더로 보호 (markdown 변환에서 제외)
    blocks: list[str] = []

    def stash(m):
        blocks.append(m.group(1))
        return f"\n@@MERMAID{len(blocks) - 1}@@\n"

    text = MERMAID_FENCE.sub(stash, text)

    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "toc", "sane_lists"]
    )
    for i, code in enumerate(blocks):
        placeholder = f"<p>@@MERMAID{i}@@</p>"
        div = f'<pre class="mermaid">{code.strip()}</pre>'
        body = body.replace(placeholder, div).replace(f"@@MERMAID{i}@@", div)

    html = HTML.format(
        title=md_path.stem,
        css=CSS,
        mermaid_b64=base64.b64encode(mermaid_js.read_bytes()).decode(),
        body=body,
    )

    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        sys.exit("google-chrome / chromium을 찾을 수 없습니다")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.html"
        src.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                chrome, "--headless", "--disable-gpu", "--no-sandbox",
                f"--user-data-dir={tmp}/profile",
                "--virtual-time-budget=20000",   # mermaid 렌더 대기
                "--no-pdf-header-footer",
                f"--print-to-pdf={out_pdf}",
                src.as_uri(),
            ],
            check=True, capture_output=True,
        )
    print(f"생성: {out_pdf} ({out_pdf.stat().st_size // 1024:,} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Markdown(+mermaid) → PDF")
    parser.add_argument("markdown", type=Path)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument(
        "--mermaid-js", type=Path, default=DEFAULT_MERMAID,
        help=f"mermaid.min.js 경로 (기본: {DEFAULT_MERMAID}, 없으면 자동 다운로드)",
    )
    args = parser.parse_args()
    convert(args.markdown, args.out, ensure_mermaid(args.mermaid_js))
    return 0


if __name__ == "__main__":
    sys.exit(main())
