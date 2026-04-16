"""
core/chart.py
=============
matplotlib 기반 발성 분석 차트 생성.
Telegram sendPhoto로 전송할 PNG bytes를 반환한다.
"""
import io
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message="Glyph.*missing")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── 한글 폰트 자동 탐지 (없으면 영문 레이블 사용)
def _try_korean_font() -> bool:
    import matplotlib.font_manager as fm
    for name in ["NanumGothic", "Noto Sans KR", "Noto Sans CJK KR",
                 "Malgun Gothic", "AppleGothic"]:
        try:
            fm.findfont(fm.FontProperties(family=name), fallback_to_default=False)
            matplotlib.rcParams["font.family"] = name
            return True
        except Exception:
            pass
    return False

_KOREAN_FONT = _try_korean_font()


# ──────────────────────────────────────────────
# 색상 팔레트
# ──────────────────────────────────────────────
_GREEN  = "#4CAF50"
_YELLOW = "#FFC107"
_RED    = "#F44336"
_BLUE   = "#2196F3"
_GRAY   = "#9E9E9E"
_BG     = "#1E1E2E"   # 다크 배경
_FG     = "#CDD6F4"   # 밝은 텍스트


def _zone_color(value: float, low_good: bool, warn: float, bad: float) -> str:
    """값에 따라 색상 반환. low_good=True면 낮을수록 좋음."""
    if low_good:
        if value <= warn: return _GREEN
        if value <= bad:  return _YELLOW
        return _RED
    else:
        if value >= warn: return _GREEN
        if value >= bad:  return _YELLOW
        return _RED


def generate_chart(result: dict, prev_zones: dict | None = None) -> bytes | None:
    """
    발성 분석 결과로 PNG 차트 생성.
    pitch_zone_stats 없으면 None 반환.
    prev_zones가 있으면 grouped bar로 이전 세션과 비교.
    """
    zones = result.get("pitch_zone_stats")
    if not zones:
        return None

    zone_names  = ["저음", "중음", "고음"]
    zone_labels = zone_names if _KOREAN_FONT else ["Low", "Mid", "High"]
    present = [z for z in zone_names if zones.get(z)]
    if len(present) < 2:
        return None

    # ── 데이터 추출
    jitter_vals = [zones[z]["jitter"] if zones.get(z) else 0 for z in zone_names]
    f2_vals     = [zones[z]["f2"]     if zones.get(z) and zones[z].get("f2", 0) > 0 else None for z in zone_names]
    hnr_vals    = [zones[z]["hnr"]    if zones.get(z) else 0 for z in zone_names]
    has_f2      = any(v is not None and v > 0 for v in f2_vals)

    has_prev = bool(prev_zones)
    prev_jitter = [prev_zones.get(z, {}).get("jitter", 0) if prev_zones and prev_zones.get(z) else 0 for z in zone_names]
    prev_hnr    = [prev_zones.get(z, {}).get("hnr",    0) if prev_zones and prev_zones.get(z) else 0 for z in zone_names]
    prev_f2     = [prev_zones.get(z, {}).get("f2",     0) if prev_zones and prev_zones.get(z) else 0 for z in zone_names]

    f2_std = result.get("f2_std", 0)
    score  = result.get("score", None)  # 있으면 표시

    # ── Figure 설정
    n_plots = 3 if has_f2 else 2
    fig, axes = plt.subplots(1, n_plots, figsize=(4 * n_plots, 4.5))
    if n_plots == 1:
        axes = [axes]
    fig.patch.set_facecolor(_BG)

    x = np.arange(len(zone_names))
    bar_w = 0.55

    # ── subplot 1: Jitter
    ax1 = axes[0]
    ax1.set_facecolor(_BG)
    colors_j = [_zone_color(v, True, 1.04, 1.5) for v in jitter_vals]
    if has_prev:
        bar_w2 = 0.35
        bars_p = ax1.bar(x - bar_w2/2, prev_jitter, width=bar_w2,
                         color=colors_j, alpha=0.4,
                         label="prev", zorder=2)
        bars = ax1.bar(x + bar_w2/2, jitter_vals, width=bar_w2,
                       color=colors_j, label="now", zorder=3)
        ax1.legend(fontsize=8, facecolor="#2A2A3E", labelcolor=_FG, framealpha=0.8)
    else:
        bars = ax1.bar(x, jitter_vals, width=bar_w, color=colors_j, zorder=3)
    ax1.axhline(1.04, color=_YELLOW, linestyle="--", linewidth=1.2, label="Limit 1.04%", zorder=4)
    ax1.axhline(1.5,  color=_RED,    linestyle=":",  linewidth=1.0, label="Warn  1.5%",  zorder=4)
    ax1.set_xticks(x)
    ax1.set_xticklabels(zone_labels, color=_FG, fontsize=11)
    ax1.set_ylabel("Jitter (%)", color=_FG, fontsize=10)
    ax1.set_title("Jitter by Zone", color=_FG, fontsize=12, fontweight="bold")
    ax1.tick_params(colors=_FG)
    ax1.spines[:].set_color(_GRAY)
    for spine in ax1.spines.values():
        spine.set_color("#444466")
    ax1.yaxis.label.set_color(_FG)
    ax1.legend(fontsize=8, facecolor="#2A2A3E", labelcolor=_FG, framealpha=0.8)
    ax1.set_ylim(0, max(max(jitter_vals) * 1.4, 1.8))
    ax1.yaxis.grid(True, color="#333355", linewidth=0.5, zorder=0)
    # 값 레이블
    for bar, val in zip(bars, jitter_vals):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                 f"{val:.2f}%", ha="center", va="bottom", color=_FG, fontsize=9)

    # ── subplot 2: HNR
    ax2 = axes[1]
    ax2.set_facecolor(_BG)
    colors_h = [_zone_color(v, False, 20.0, 15.0) for v in hnr_vals]
    if has_prev:
        bar_w2 = 0.35
        bars2_p = ax2.bar(x - bar_w2/2, prev_hnr, width=bar_w2,
                          color=colors_h, alpha=0.4,
                          label="prev", zorder=2)
        bars2 = ax2.bar(x + bar_w2/2, hnr_vals, width=bar_w2,
                        color=colors_h, label="now", zorder=3)
        ax2.legend(fontsize=8, facecolor="#2A2A3E", labelcolor=_FG, framealpha=0.8)
    else:
        bars2 = ax2.bar(x, hnr_vals, width=bar_w, color=colors_h, zorder=3)
    ax2.axhline(20.0, color=_YELLOW, linestyle="--", linewidth=1.2, label="Limit 20dB", zorder=4)
    ax2.axhline(25.0, color=_GREEN,  linestyle=":",  linewidth=1.0, label="Pro   25dB", zorder=4)
    ax2.set_xticks(x)
    ax2.set_xticklabels(zone_labels, color=_FG, fontsize=11)
    ax2.set_ylabel("HNR (dB)", color=_FG, fontsize=10)
    ax2.set_title("HNR by Zone", color=_FG, fontsize=12, fontweight="bold")
    ax2.tick_params(colors=_FG)
    for spine in ax2.spines.values():
        spine.set_color("#444466")
    ax2.legend(fontsize=8, facecolor="#2A2A3E", labelcolor=_FG, framealpha=0.8)
    ax2.set_ylim(0, max(max(hnr_vals) * 1.2, 28))
    ax2.yaxis.grid(True, color="#333355", linewidth=0.5, zorder=0)
    for bar, val in zip(bars2, hnr_vals):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f"{val:.1f}", ha="center", va="bottom", color=_FG, fontsize=9)

    # ── subplot 3: F2 (공명 위치) — 있을 때만
    if has_f2 and n_plots == 3:
        ax3 = axes[2]
        ax3.set_facecolor(_BG)
        f2_plot = [v if v else 0 for v in f2_vals]
        colors_f2 = []
        for v in f2_plot:
            if v == 0:       colors_f2.append(_GRAY)
            elif v >= 1600:  colors_f2.append(_GREEN)
            elif v >= 1300:  colors_f2.append(_YELLOW)
            else:            colors_f2.append(_RED)
        if has_prev:
            prev_f2_plot = [v if v else 0 for v in prev_f2]
            bar_w2 = 0.35
            bars3_p = ax3.bar(x - bar_w2/2, prev_f2_plot, width=bar_w2,
                              color=colors_f2, alpha=0.4,
                              label="prev", zorder=2)
            bars3 = ax3.bar(x + bar_w2/2, f2_plot, width=bar_w2,
                            color=colors_f2, label="now", zorder=3)
            ax3.legend(fontsize=8, facecolor="#2A2A3E", labelcolor=_FG, framealpha=0.8)
        else:
            bars3 = ax3.bar(x, f2_plot, width=bar_w, color=colors_f2, zorder=3)
        ax3.axhline(1600, color=_GREEN,  linestyle="--", linewidth=1.2, label="Bright 1600Hz", zorder=4)
        ax3.axhline(1300, color=_RED,    linestyle=":",  linewidth=1.0, label="Dark   1300Hz", zorder=4)
        std_label = f"std ±{f2_std:.0f}Hz" if f2_std > 0 else ""
        ax3.set_xticks(x)
        ax3.set_xticklabels(zone_labels, color=_FG, fontsize=11)
        ax3.set_ylabel("F2 / Resonance (Hz)", color=_FG, fontsize=10)
        title = "F2 by Zone"
        if std_label:
            title += f"\n({std_label})"
        ax3.set_title(title, color=_FG, fontsize=12, fontweight="bold")
        ax3.tick_params(colors=_FG)
        for spine in ax3.spines.values():
            spine.set_color("#444466")
        ax3.legend(fontsize=8, facecolor="#2A2A3E", labelcolor=_FG, framealpha=0.8)
        ax3.set_ylim(0, max(v for v in f2_plot if v > 0) * 1.2 if any(v > 0 for v in f2_plot) else 2000)
        ax3.yaxis.grid(True, color="#333355", linewidth=0.5, zorder=0)
        for bar, val in zip(bars3, f2_plot):
            if val > 0:
                ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 10,
                         f"{val:.0f}", ha="center", va="bottom", color=_FG, fontsize=9)

    # ── 전체 타이틀
    mode_label = "Baseline" if result.get("mode") == "baseline" else "Song"
    fig.suptitle(f"Vocal Analysis [{mode_label}]", color=_FG, fontsize=13, fontweight="bold", y=1.01)

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=_BG, edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
