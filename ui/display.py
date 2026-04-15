"""
ui/display.py
=============
로컬 분석 결과 화면 표시.
- Rich 라이브러리로 터미널에 컬러 출력
- HTML 리포트 파일 자동 생성 후 브라우저 오픈
"""

import os
import webbrowser
from datetime import datetime
from pathlib import Path


# ──────────────────────────────────────────────
# 터미널 출력 (Rich)
# ──────────────────────────────────────────────
def _print_rich(result: dict, feedback_text: str):
    try:
        from rich.console import Console
        from rich.panel   import Panel
        from rich.text    import Text

        console = Console()
        color   = "green" if result.get("valid") else "red"
        panel   = Panel(
            Text(feedback_text, style="white"),
            title="[bold cyan]발성 분석 결과[/bold cyan]",
            border_style=color,
        )
        console.print(panel)
    except ImportError:
        # Rich 없으면 plain print
        print("\n" + "="*50)
        print(feedback_text)
        print("="*50 + "\n")


# ──────────────────────────────────────────────
# HTML 리포트 생성
# ──────────────────────────────────────────────
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>발성 분석 결과 — {date}</title>
<style>
  body {{ font-family: 'Malgun Gothic', sans-serif; background: #0f172a; color: #e2e8f0;
          display: flex; justify-content: center; padding: 40px 20px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 32px; max-width: 540px;
           width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,.4); }}
  h2 {{ color: #38bdf8; margin: 0 0 4px; font-size: 1.2rem; }}
  .subtitle {{ color: #94a3b8; font-size: .85rem; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  th {{ text-align: left; color: #64748b; font-size: .8rem;
        padding: 4px 8px; border-bottom: 1px solid #334155; }}
  td {{ padding: 8px 8px; border-bottom: 1px solid #1e293b; }}
  .ok   {{ color: #4ade80; font-weight: bold; }}
  .warn {{ color: #facc15; font-weight: bold; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 999px;
            font-size: .75rem; font-weight: bold; }}
  .badge-base {{ background: #1d4ed8; color: #fff; }}
  .badge-song {{ background: #7c3aed; color: #fff; }}
  .advice {{ background: #0f2a1e; border-left: 4px solid #22c55e;
             padding: 14px 18px; border-radius: 6px; font-size: .9rem;
             white-space: pre-line; color: #bbf7d0; }}
  .advice.warn {{ background: #2d1b00; border-left-color: #f59e0b; color: #fde68a; }}
  .meta {{ color: #475569; font-size: .78rem; margin-top: 20px; }}
</style>
</head>
<body>
<div class="card">
  <h2>🎤 발성 분석 결과</h2>
  <div class="subtitle">
    {date} &nbsp;
    <span class="badge {mode_badge}">{mode_label}</span>
  </div>

  <table>
    <tr>
      <th>항목</th><th>측정값</th><th>기준</th><th>상태</th>
    </tr>
    <tr>
      <td>Jitter</td>
      <td>{jitter:.2f}%</td>
      <td>&lt; {j_thresh:.2f}%</td>
      <td class="{j_cls}">{j_icon}</td>
    </tr>
    <tr>
      <td>Shimmer</td>
      <td>{shimmer:.2f}%</td>
      <td>&lt; {sh_thresh:.2f}%</td>
      <td class="{sh_cls}">{sh_icon}</td>
    </tr>
    <tr>
      <td>HNR</td>
      <td>{hnr:.1f} dB</td>
      <td>&gt; {h_thresh:.1f} dB</td>
      <td class="{h_cls}">{h_icon}</td>
    </tr>
    <tr><td>F1</td><td>{f1:.0f} Hz</td><td>—</td><td>—</td></tr>
    <tr><td>F2</td><td>{f2:.0f} Hz</td><td>—</td><td>—</td></tr>
    {held_row}
  </table>

  <div class="advice {advice_cls}">
{advice_text}
  </div>

  {source_line}
  <div class="meta">생성: {date}</div>
</div>
</body>
</html>
"""


def _build_html(result: dict, feedback_text: str, source_file: str = "") -> str:
    from core.feedback import _get_thresholds  # 내부 함수 참조

    # 기준값 (config 없이 기본값으로)
    thresh = {"jitter_max": 1.04, "shimmer_max": 3.81, "hnr_min": 20.0}

    j  = result.get("jitter",  0)
    sh = result.get("shimmer", 0)
    h  = result.get("hnr",     0)

    j_ok  = j  <= thresh["jitter_max"]
    sh_ok = sh <= thresh["shimmer_max"]
    h_ok  = h  >= thresh["hnr_min"]

    all_ok    = j_ok and sh_ok and h_ok
    mode      = result.get("mode", "baseline")
    held      = result.get("held_note_count", 0)

    held_row  = (
        f'<tr><td>Held Notes</td><td>{held}개</td><td>—</td><td>—</td></tr>'
        if mode == "song" else ""
    )

    # 권고 텍스트 추출 (feedback_text 마지막 블록)
    lines       = feedback_text.split("\n")
    advice_lines = []
    capture     = False
    for l in lines:
        if "━" in l and capture:
            break
        if "━" in l:
            capture = True
            continue
        if capture:
            advice_lines.append(l.strip())
    advice_text = "\n".join(advice_lines).strip() or feedback_text

    source_line = (
        f'<div class="meta">파일: {os.path.basename(source_file)}</div>'
        if source_file else ""
    )

    return _HTML_TEMPLATE.format(
        date       = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        mode_label = "베이스라인" if mode == "baseline" else "노래",
        mode_badge = "badge-base" if mode == "baseline" else "badge-song",
        jitter=j, shimmer=sh, hnr=h,
        f1=result.get("f1", 0), f2=result.get("f2", 0),
        j_thresh=thresh["jitter_max"],
        sh_thresh=thresh["shimmer_max"],
        h_thresh=thresh["hnr_min"],
        j_cls="ok" if j_ok else "warn",   j_icon="✅" if j_ok else "⚠️",
        sh_cls="ok" if sh_ok else "warn",  sh_icon="✅" if sh_ok else "⚠️",
        h_cls="ok" if h_ok else "warn",    h_icon="✅" if h_ok else "⚠️",
        held_row=held_row,
        advice_text=advice_text,
        advice_cls="" if all_ok else "warn",
        source_line=source_line,
    )


# ──────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────
def show_result(result: dict, feedback_text: str, source_file: str = ""):
    """터미널 출력 + HTML 리포트 생성 후 브라우저 오픈."""
    _print_rich(result, feedback_text)

    # HTML 저장
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    fname   = datetime.now().strftime("%Y%m%d_%H%M%S") + ".html"
    fpath   = reports_dir / fname
    html    = _build_html(result, feedback_text, source_file)

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(html)

    webbrowser.open(fpath.resolve().as_uri())


def show_error(title: str, message: str):
    """오류 팝업."""
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, message)
    root.destroy()
