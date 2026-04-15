"""
core/feedback.py
================
임상 기준값 비교 + Telegram/로컬 결과 메시지 생성.
기준값은 이 파일에 하드코딩.
"""

from datetime import datetime

# ──────────────────────────────────────────────
# 임상 기준값 (나이·성별 기반)
# ──────────────────────────────────────────────
#
# 기본 기준 (20~40대)
_BASE_THRESHOLDS = {
    "남": {"jitter_max": 1.04, "shimmer_max": 3.81, "hnr_min": 20.0},
    "여": {"jitter_max": 1.04, "shimmer_max": 3.31, "hnr_min": 21.0},
}
# 40대 이상: 각 기준값에 10% 여유 추가
_SENIOR_MARGIN = 0.10


def _get_thresholds(age: int, gender: str) -> dict:
    """나이·성별에 맞는 기준값 반환."""
    base = _BASE_THRESHOLDS.get(gender, _BASE_THRESHOLDS["남"]).copy()
    if age >= 40:
        base["jitter_max"]  *= (1 + _SENIOR_MARGIN)
        base["shimmer_max"] *= (1 + _SENIOR_MARGIN)
        base["hnr_min"]     *= (1 - _SENIOR_MARGIN)
    return base


# ──────────────────────────────────────────────
# 훈련 권고 멘트
# ──────────────────────────────────────────────
_ADVICE_ALL_GOOD = (
    "전반적으로 양호합니다.\n"
    "   SOVT 5분 워밍업 후 연습 시작을 권장합니다."
)

_ADVICE_JITTER = (
    "성대 진동 불안정 신호입니다.\n"
    "   → 권고: SOVT(빨대 발성) 5분, 립 트릴 스케일"
)

_ADVICE_SHIMMER = (
    "성대 접촉 불규칙 신호입니다.\n"
    "   → 권고: 허밍 스케일 5분, 낮은 볼륨 레가토 연습"
)

_ADVICE_HNR = (
    "노이즈 비율이 높습니다 — 성대 피로 또는 점막 부종 의심.\n"
    "   → 권고: 당일 고강도 연습 자제, 수분 보충, 충분한 휴식"
)

_ADVICE_MULTIPLE = (
    "복합적인 발성 불안정 신호입니다.\n"
    "   → 권고: 오늘은 SOVT 위주 가벼운 워밍업만, 강도 높은 연습 자제"
)


def _status_icon(value: float, threshold: float, higher_is_better: bool) -> str:
    if higher_is_better:
        return "✅" if value >= threshold else "⚠️"
    else:
        return "✅" if value <= threshold else "⚠️"


# ──────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────
def build_message(
    result: dict,
    age: int,
    gender: str,
    personal_avg: dict | None = None,
    baseline_result: dict | None = None,
) -> str:
    """
    분석 결과 dict → Telegram/로컬 출력용 텍스트 반환.

    Parameters
    ----------
    result          : analyzer.analyze() 반환값
    age             : 사용자 나이
    gender          : "남" | "여"
    personal_avg    : 과거 4회 이상 누적 시 평균값 dict (선택)
    baseline_result : 노래 모드 시 베이스라인 비교용 (선택)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    thresh = _get_thresholds(age, gender)

    # ── 오류 케이스
    if not result.get("valid"):
        msg = result.get("error_msg") or "알 수 없는 오류"
        return f"❌ 분석 실패\n{msg}"

    jitter  = result["jitter"]
    shimmer = result["shimmer"]
    hnr     = result["hnr"]
    f1      = result["f1"]
    f2      = result["f2"]

    j_ok  = jitter  <= thresh["jitter_max"]
    sh_ok = shimmer <= thresh["shimmer_max"]
    h_ok  = hnr     >= thresh["hnr_min"]

    j_icon  = "✅" if j_ok  else "⚠️"
    sh_icon = "✅" if sh_ok else "⚠️"
    h_icon  = "✅" if h_ok  else "⚠️"

    mode_label = "베이스라인" if result["mode"] == "baseline" else "노래"

    lines = [
        f"🎤 발성 분석 완료 [{mode_label}] — {now}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Jitter    {jitter:.2f}%   {j_icon}  (기준 < {thresh['jitter_max']:.2f}%)",
        f"Shimmer   {shimmer:.2f}%   {sh_icon}  (기준 < {thresh['shimmer_max']:.2f}%)",
        f"HNR       {hnr:.1f}dB  {h_icon}  (기준 > {thresh['hnr_min']:.1f}dB)",
        f"F1        {f1:.0f}Hz",
        f"F2        {f2:.0f}Hz",
    ]

    # ── 개인 평균 비교 (4회 이상 누적 시)
    if personal_avg:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        diff_j  = jitter  - personal_avg.get("jitter",  jitter)
        diff_sh = shimmer - personal_avg.get("shimmer", shimmer)
        diff_h  = hnr     - personal_avg.get("hnr",     hnr)
        lines.append("📊 개인 평균 대비")
        lines.append(f"   Jitter   {diff_j:+.2f}%")
        lines.append(f"   Shimmer  {diff_sh:+.2f}%")
        lines.append(f"   HNR      {diff_h:+.1f}dB")

    # ── 노래 모드 추가 정보
    if result["mode"] == "song":
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🎵 노래 구간 분석 (탐지된 held note: {result['held_note_count']}개)")
        if baseline_result and baseline_result.get("valid"):
            diff_j  = jitter  - baseline_result["jitter"]
            diff_sh = shimmer - baseline_result["shimmer"]
            lines.append(f"   베이스라인 대비 Jitter  {diff_j:+.2f}%")
            lines.append(f"   베이스라인 대비 Shimmer {diff_sh:+.2f}%")

    # ── 훈련 권고
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    bad_count = sum([not j_ok, not sh_ok, not h_ok])

    if bad_count == 0:
        lines.append(f"💪 오늘 권고: {_ADVICE_ALL_GOOD}")
    elif bad_count >= 2:
        lines.append(f"⚠️  오늘 권고: {_ADVICE_MULTIPLE}")
    else:
        if not j_ok:
            lines.append(f"⚠️  Jitter {jitter:.2f}% — 기준 초과")
            lines.append(f"→ {_ADVICE_JITTER}")
        if not sh_ok:
            lines.append(f"⚠️  Shimmer {shimmer:.2f}% — 기준 초과")
            lines.append(f"→ {_ADVICE_SHIMMER}")
        if not h_ok:
            lines.append(f"⚠️  HNR {hnr:.1f}dB — 기준 미달")
            lines.append(f"→ {_ADVICE_HNR}")

    return "\n".join(lines)


def build_history_message(sessions: list[dict]) -> str:
    """최근 N회 분석 이력 메시지 생성."""
    if not sessions:
        return "📋 분석 이력이 없습니다."

    lines = ["📋 최근 분석 이력", "━━━━━━━━━━━━━━━━━━━━"]
    for s in sessions:
        ts = s.get("timestamp", "")
        mode = "베이스" if s.get("mode") == "baseline" else "노래 "
        lines.append(
            f"[{mode}] {ts}  "
            f"J:{s.get('jitter', 0):.2f}%  "
            f"Sh:{s.get('shimmer', 0):.2f}%  "
            f"HNR:{s.get('hnr', 0):.1f}dB"
        )
    return "\n".join(lines)
