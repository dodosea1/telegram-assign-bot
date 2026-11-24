# -*- coding: utf-8 -*-
"""slides.py → 장면 PNG(Edge 헤드리스) + 한국어 음성(Windows TTS) → MP4(ffmpeg)

    python guide/make_video.py          # guide/out/ 에 설치.mp4, 매일사용.mp4
"""
import html
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from slides import DAILY, INSTALL  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "out"
WORK = OUT / "work"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
W, H = 1280, 720

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1280px;height:720px;overflow:hidden;font-family:'Malgun Gothic','Noto Sans KR',sans-serif;
 background:#0f1b2d;color:#e8eef7;display:flex}
.left{flex:1;padding:64px 40px 48px 72px;display:flex;flex-direction:column}
.tag{font-size:20px;color:#7fb4ff;letter-spacing:.5px;margin-bottom:14px}
h1{font-size:50px;font-weight:700;line-height:1.2}
.sub{font-size:25px;color:#9fb3cc;margin:12px 0 34px}
ul{list-style:none}
li{font-size:27px;line-height:1.35;margin:0 0 16px;padding-left:34px;position:relative}
li:before{content:'';position:absolute;left:4px;top:13px;width:12px;height:12px;border-radius:50%;background:#3d8bfd}
.foot{margin-top:auto;font-size:17px;color:#61748d}
.right{width:430px;display:flex;align-items:center;justify-content:center;padding-right:56px}
.phone{width:340px;height:640px;border-radius:40px;background:#05080d;padding:14px;box-shadow:0 0 0 2px #2b3a50,0 20px 60px #0008}
.scr{width:100%;height:100%;border-radius:28px;overflow:hidden;background:#fff;color:#111;display:flex;flex-direction:column;font-size:15px}
.bar{height:26px;font-size:12px;display:flex;justify-content:space-between;padding:5px 18px;color:#333}
/* browser */
.url{margin:4px 10px 8px;background:#eef1f5;border-radius:18px;padding:8px 14px;font-size:14px;color:#333}
.bh{font-size:26px;font-weight:700;text-align:center;margin:26px 0 8px}
.bt{padding:6px 22px;color:#444;font-size:15px}
.btn{margin:10px 22px;background:#2a7ae2;color:#fff;border-radius:8px;padding:12px;text-align:center;font-weight:700}
.inp{margin:4px 22px 8px;border:1.5px solid #9bb;border-radius:6px;padding:10px;color:#222}
.kv{display:flex;justify-content:space-between;margin:6px 22px;font-size:14px}.kv b{color:#c0392b}
.pop{margin:auto 14px 18px;background:#333;color:#fff;border-radius:12px;padding:14px;font-size:14px;line-height:1.4}
/* store */
.search{margin:8px 12px;border-radius:20px;background:#eef1f5;padding:10px 16px}
.app{display:flex;align-items:center;gap:12px;padding:14px 14px;border-bottom:1px solid #eee}
.ico{width:46px;height:46px;border-radius:12px;background:#111;color:#3f3;font:700 18px monospace;display:flex;align-items:center;justify-content:center}
.an{flex:1}.an b{display:block;font-size:16px}.an span{font-size:13px;color:#777}
.ib{background:#1976d2;color:#fff;border-radius:16px;padding:7px 14px;font-size:13px;font-weight:700}
/* settings */
.sh{font-size:22px;font-weight:700;padding:18px 20px 10px}
.row{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid #f0f0f0;font-size:16px}
.rd{width:20px;height:20px;border-radius:50%;border:2px solid #999}.rd.on{border:6px solid #2a7ae2}
.tg{width:42px;height:24px;border-radius:12px;background:#bbb;position:relative}.tg.on{background:#2a7ae2}
.tg:after{content:'';position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff}.tg.on:after{left:21px}
.hl{background:#fff6d6}
/* termux */
.term{background:#000;color:#ddd;flex:1;font:13.5px/1.55 Consolas,'D2Coding',monospace;padding:12px 12px;white-space:pre-wrap;word-break:break-all}
.term .g{color:#5f5}.term .y{color:#fd5}.term .c{color:#7cf}
.keys{background:#111;color:#ccc;display:flex;justify-content:space-around;padding:9px 0;font:12px monospace}
/* telegram */
.tgh{background:#517da2;color:#fff;padding:14px 16px;font-weight:700;font-size:17px}
.chat{flex:1;background:#c9d7e3;padding:12px 10px;display:flex;flex-direction:column;gap:9px;overflow:hidden}
.m{max-width:86%;padding:9px 12px;border-radius:12px;font-size:14px;line-height:1.45;white-space:pre-wrap;box-shadow:0 1px 1px #0002}
.m.in{background:#fff;align-self:flex-start}.m.out{background:#effdde;align-self:flex-end}.m.in2{background:#fff;align-self:flex-start;border-left:4px solid #517da2}
.inbar{background:#fff;padding:12px 14px;color:#999;font-size:14px}
/* home */
.home{flex:1;background:linear-gradient(160deg,#3a6ea5,#6b4f9e);padding:70px 26px;display:flex;flex-direction:column;gap:14px}
.wd{background:#000c;color:#fff;border-radius:14px;padding:8px 0}
.wd div{padding:14px 18px;font-size:17px;border-bottom:1px solid #fff2}.wd div:last-child{border:0}
.wl{color:#fffc;font-size:13px;margin-bottom:2px}
/* steps */
.steps{flex:1;background:#f4f7fb;padding:40px 22px;display:flex;flex-direction:column;gap:14px}
.st{background:#fff;border-radius:12px;padding:16px 16px;font-size:18px;font-weight:700;color:#21406b;box-shadow:0 1px 3px #0001}
"""


def esc(t):
    return html.escape(t)


def term_line(t):
    e = esc(t)
    if t.startswith("✅") or t.startswith("🟢"):
        return f'<span class="g">{e}</span>'
    if t.startswith("▶"):
        return f'<span class="y">{e}</span>'
    if "$ " in t:
        return f'<span class="c">{e}</span>'
    return e


def screen_html(s):
    k = s["kind"]
    bar = '<div class="bar"><span>9:41</span><span>▮▮▮ 📶 🔋</span></div>'
    if k == "browser":
        body = f'<div class="url">🔒 {esc(s["url"])}</div>'
        for r in s["rows"]:
            t = r[0]
            if t == "h": body += f'<div class="bh">{esc(r[1])}</div>'
            elif t == "t": body += f'<div class="bt">{esc(r[1])}</div>'
            elif t == "btn": body += f'<div class="btn">{esc(r[1])}</div>'
            elif t == "input": body += f'<div class="inp">{esc(r[1])}</div>'
            elif t == "kv": body += f'<div class="kv"><span>{esc(r[1])}</span><b>{esc(r[2])}</b></div>'
            elif t == "pop": body += f'<div class="pop">{esc(r[1])}</div>'
        return bar + body
    if k == "store":
        body = '<div class="sh">F-Droid</div>'
        for r in s["rows"]:
            if r[0] == "search": body += f'<div class="search">🔍 {esc(r[1])}</div>'
            else: body += (f'<div class="app"><div class="ico">&gt;_</div><div class="an"><b>{esc(r[1])}</b>'
                           f'<span>{esc(r[2])}</span></div><div class="ib">{esc(r[3])}</div></div>')
        return bar + body
    if k == "settings":
        body = f'<div class="sh">{esc(s["header"])}</div>'
        for r in s["rows"]:
            if r[0] == "sep": body += '<div style="height:16px;background:#f4f4f4"></div>'
            elif r[0] == "radio":
                body += f'<div class="row{" hl" if r[2] else ""}"><span>{esc(r[1])}</span><div class="rd{" on" if r[2] else ""}"></div></div>'
            elif r[0] == "toggle":
                body += f'<div class="row{" hl" if r[2] else ""}"><span>{esc(r[1])}</span><div class="tg{" on" if r[2] else ""}"></div></div>'
        return bar + body
    if k == "termux":
        lines = "\n".join(term_line(t) for t in s["lines"])
        return (f'<div class="bar" style="background:#000;color:#aaa"><span>9:41</span><span>Termux</span></div>'
                f'<div class="term">{lines}</div><div class="keys"><span>ESC</span><span>CTRL</span><span>ALT</span>'
                f'<span>TAB</span><span>↑</span><span>↓</span></div>')
    if k == "telegram":
        ms = "".join(f'<div class="m {d}">{esc(t)}</div>' for d, t in s["msgs"])
        return f'{bar}<div class="tgh">← {esc(s["chat"])}</div><div class="chat">{ms}</div><div class="inbar">메시지 입력…</div>'
    if k == "home":
        bs = "".join(f"<div>▶ {esc(b)}</div>" for b in s["buttons"])
        return (f'<div class="home"><div class="wl">Termux:Widget</div><div class="wd">{bs}</div>'
                f'<div style="margin-top:auto;display:flex;justify-content:space-around;font-size:30px">📞 💬 🌐 📷</div></div>')
    if k == "steps":
        return '<div class="steps">' + "".join(f'<div class="st">{esc(i)}</div>' for i in s["items"]) + "</div>"
    return ""


def slide_html(sl, idx, total, series):
    lis = "".join(f"<li>{esc(b)}</li>" for b in sl["bullets"])
    sub = f'<div class="sub">{esc(sl["sub"])}</div>' if sl["sub"] else '<div class="sub"></div>'
    return (f'<!doctype html><meta charset="utf-8"><style>{CSS}</style><body>'
            f'<div class="left"><div class="tag">{esc(series)} · {idx}/{total}</div><h1>{esc(sl["title"])}</h1>{sub}'
            f'<ul>{lis}</ul><div class="foot">텔레그램 배정 자동응답 · 화면은 이해를 돕기 위한 모형입니다</div></div>'
            f'<div class="right"><div class="phone"><div class="scr">{screen_html(sl["screen"])}</div></div></div></body>')


def tts(items, folder):
    """Windows 한국어 음성(Heami)으로 wav 생성."""
    lst = folder / "tts.json"
    lst.write_text(json.dumps([{"text": t, "out": str(o)} for t, o in items], ensure_ascii=False), encoding="utf-8")
    ps = folder / "tts.ps1"
    ps.write_text(
        "Add-Type -AssemblyName System.Speech\n"
        f"$items = Get-Content -Raw -Encoding UTF8 '{lst}' | ConvertFrom-Json\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "$s.SelectVoice('Microsoft Heami Desktop'); $s.Rate = 0\n"
        "foreach ($i in $items) { $s.SetOutputToWaveFile($i.out); $s.Speak($i.text); $s.SetOutputToNull() }\n",
        encoding="utf-8-sig")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], check=True)


def wav_len(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def build(name, series, slides):
    d = WORK / name
    d.mkdir(parents=True, exist_ok=True)
    total = len(slides)
    for i, sl in enumerate(slides, 1):
        hp = d / f"s{i:02d}.html"
        hp.write_text(slide_html(sl, i, total, series), encoding="utf-8")
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "--user-data-dir=" + str(WORK / "edge"),
                        f"--window-size={W},{H}", f"--screenshot={d / f's{i:02d}.png'}", hp.as_uri()],
                       check=True, capture_output=True)
    tts([(sl["say"], d / f"s{i:02d}.wav") for i, sl in enumerate(slides, 1)], d)
    segs = []
    for i in range(1, total + 1):
        png, wav, seg = d / f"s{i:02d}.png", d / f"s{i:02d}.wav", d / f"s{i:02d}.mp4"
        dur = wav_len(wav) + 1.2
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-i", str(wav),
                        "-af", "adelay=400|400,apad", "-t", f"{dur:.2f}", "-r", "15", "-c:v", "libx264", "-tune", "stillimage",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-ar", "44100", "-ac", "1", str(seg)], check=True)
        segs.append(seg)
    lst = d / "list.txt"
    lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
    out = OUT / f"{name}.mp4"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    "-movflags", "+faststart", str(out)], check=True)
    print(out, f"{sum(wav_len(d / f's{i:02d}.wav') + 1.2 for i in range(1, total + 1)):.0f}s",
          f"{out.stat().st_size / 1e6:.1f}MB")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    build("1_폰설치", "① 폰 설치", INSTALL)
    build("2_매일사용", "② 매일 쓰는 법", DAILY)
