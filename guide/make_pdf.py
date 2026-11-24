# -*- coding: utf-8 -*-
"""site/index.html → 인쇄용 PDF (../폰_자동응답_설명서.pdf)"""
import subprocess
from pathlib import Path
HERE = Path(__file__).parent
PRINT_CSS = """@page{size:A4;margin:14mm}
@media print{html,body{background:#fff!important}.cmd button,.chk,nav.toc,.videos{display:none!important}
.wrap{max-width:none}ol.steps>li,.card,details,tr{break-inside:avoid}
.cmd code{white-space:pre-wrap;word-break:break-all;overflow:visible}.tbl{overflow:visible}
#videos:after{content:'영상 2편(① 폰 설치 · ② 매일 쓰는 법)은 온라인 설명서 페이지에서 볼 수 있습니다.';font-size:14px}}
</style>"""
s = (HERE / "site/index.html").read_text(encoding="utf-8").replace("</style>", PRINT_CSS, 1)
doc = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
       + s + "<script>document.querySelectorAll('details').forEach(d=>d.open=true)</script></head></html>")
tmp = (HERE / "site/_print.html").resolve()
tmp.write_text(doc, encoding="utf-8")
out = (HERE / "../폰_자동응답_설명서.pdf").resolve()
subprocess.run([r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "--headless=new", "--disable-gpu",
                "--user-data-dir=" + str((HERE / "out/work/edge").resolve()), "--no-pdf-header-footer",
                "--virtual-time-budget=8000", "--print-to-pdf=" + str(out), tmp.as_uri()], capture_output=True)
tmp.unlink()
print(out, out.stat().st_size)
