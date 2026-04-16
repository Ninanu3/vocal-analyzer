"""
core/feedback.py  —  임상 기준값 비교 + 풍부한 결과 메시지 생성
"""
from datetime import datetime

# ──────────────────────────────────────────────
# 기준값 3단계: 임상 정상 / 프로 가수 / 최상급
# ──────────────────────────────────────────────
_BASE_THRESHOLDS = {
    "남": {"jitter_max": 1.04, "shimmer_max": 3.81, "hnr_min": 20.0},
    "여": {"jitter_max": 1.04, "shimmer_max": 3.31, "hnr_min": 21.0},
}
_SENIOR_MARGIN = 0.10

# 프로 가수 평균 (성악·팝 보컬 연구 기반)
PRO_BENCHMARKS = {
    "jitter_pro":  0.50,   # % 이하
    "shimmer_pro": 2.00,   # % 이하
    "hnr_pro":     25.0,   # dB 이상
    "jitter_elite":  0.30,
    "shimmer_elite": 1.20,
    "hnr_elite":     28.0,
}


def _get_thresholds(age: int, gender: str) -> dict:
    base = _BASE_THRESHOLDS.get(gender, _BASE_THRESHOLDS["남"]).copy()
    if age >= 40:
        base["jitter_max"]  *= (1 + _SENIOR_MARGIN)
        base["shimmer_max"] *= (1 + _SENIOR_MARGIN)
        base["hnr_min"]     *= (1 - _SENIOR_MARGIN)
    return base


# ──────────────────────────────────────────────
# 종합 점수 (0~100)
# ──────────────────────────────────────────────
def _calc_score(jitter, shimmer, hnr, thresh) -> int:
    j_score  = max(0, min(100, (1 - jitter  / (thresh["jitter_max"]  * 2)) * 100))
    sh_score = max(0, min(100, (1 - shimmer / (thresh["shimmer_max"] * 2)) * 100))
    h_score  = max(0, min(100, (hnr / (thresh["hnr_min"] * 1.5))           * 100))
    return int(round(h_score * 0.40 + j_score * 0.35 + sh_score * 0.25))


def _score_label(score: int) -> str:
    if score >= 90: return "🏆 최상"
    if score >= 75: return "🟢 양호"
    if score >= 55: return "🟡 보통"
    if score >= 35: return "🟠 주의"
    return "🔴 위험"


# ──────────────────────────────────────────────
# 체감 언어 (일반인이 알아듣는 설명)
# ──────────────────────────────────────────────
def _jitter_desc(jitter: float) -> str:
    if jitter <= 0.30: return "목소리 떨림 거의 없음 (프로 최상급)"
    if jitter <= 0.50: return "목소리 떨림 매우 안정적 (프로 수준)"
    if jitter <= 1.04: return "목소리 떨림 안정적"
    if jitter <= 1.50: return "약간의 떨림 감지 (피로 또는 긴장)"
    if jitter <= 2.00: return "뚜렷한 떨림 (성대 불안정)"
    return "심한 떨림 (성대 피로 or 질환 의심)"


def _shimmer_desc(shimmer: float) -> str:
    if shimmer <= 1.20: return "음량 매우 일정 (프로 최상급)"
    if shimmer <= 2.00: return "음량 일정 (프로 수준)"
    if shimmer <= 3.81: return "음량 대체로 일정"
    if shimmer <= 5.00: return "음량 흔들림 있음 (호흡 지지 부족)"
    return "심한 음량 흔들림 (성대 접촉 불규칙)"


def _hnr_desc(hnr: float) -> str:
    if hnr >= 28.0: return "매우 맑고 깨끗한 소리 (프로 최상급)"
    if hnr >= 25.0: return "맑고 깨끗한 소리 (프로 수준)"
    if hnr >= 20.0: return "맑은 소리"
    if hnr >= 15.0: return "약간 탁한 소리 (쉰 기운 있음)"
    if hnr >= 10.0: return "탁하고 거친 소리 (성대 피로)"
    return "심하게 탁한 소리 (성대 피로 or 점막 문제)"


def _formant_desc(f1: float, f2: float, gender: str) -> str:
    # 성구 추정
    f1_head = 620 if gender == "남" else 720
    register = "흉성 위주" if f1 < f1_head else "두성 위주"

    # 공명 밝기
    if f2 > 1800:
        resonance = "전진된 밝은 공명 (앞쪽 울림)"
    elif f2 > 1300:
        resonance = "균형 잡힌 공명"
    else:
        resonance = "후퇴된 어두운 공명 (뒤쪽 울림)"

    # 비음 힌트 (F1이 매우 낮을 경우)
    nasal_hint = ""
    if f1 < 350:
        nasal_hint = " / 비음 경향 가능성"

    return f"{register} / {resonance}{nasal_hint}"


# ──────────────────────────────────────────────
# 이모지 바 차트 (프로 기준 대비 %)
# ──────────────────────────────────────────────
def _bar(value: float, target: float, higher_is_better: bool, width: int = 10) -> str:
    """이모지 막대그래프. 100% = 프로 기준 도달."""
    if higher_is_better:
        ratio = min(value / target, 1.0)
    else:
        ratio = max(0.0, 1.0 - (value - target) / target) if value > target else 1.0
        ratio = min(ratio, 1.0)

    filled = int(round(ratio * width))
    bar    = "█" * filled + "░" * (width - filled)
    pct    = int(ratio * 100)
    return f"[{bar}] {pct}%"


# ──────────────────────────────────────────────
# 훈련 권고
# ──────────────────────────────────────────────
def _build_advice(j_ok, sh_ok, h_ok, jitter, shimmer, hnr) -> list[str]:
    bad = sum([not j_ok, not sh_ok, not h_ok])

    if bad == 0:
        # 프로 기준과 비교해서 더 구체적인 조언
        lines = ["💪 오늘 권고"]
        tips = []
        if jitter > PRO_BENCHMARKS["jitter_pro"]:
            tips.append("떨림 개선: 립 트릴 스케일 5분")
        if shimmer > PRO_BENCHMARKS["shimmer_pro"]:
            tips.append("음량 안정화: 메사 디 보체(크레셴도-데크레셴도) 연습")
        if hnr < PRO_BENCHMARKS["hnr_pro"]:
            tips.append("맑기 개선: SOVT(빨대) 워밍업 5분")
        if not tips:
            tips.append("프로 수준 유지 중! 고강도 연습 진행 가능")
        for t in tips:
            lines.append(f"   → {t}")
        return lines

    lines = []
    if bad >= 2:
        lines.append("⚠️  복합 불안정 — 오늘은 워밍업만 권장")
        lines.append("   → SOVT(빨대) 5분 + 립 트릴 5분")
        lines.append("   → 고강도 연습 자제 / 수분 보충")
        return lines

    if not j_ok:
        lines.append("⚠️  떨림 초과 — 성대 진동 불안정")
        lines.append("   → SOVT(빨대 발성) 5분")
        lines.append("   → 립 트릴 스케일 5분")
        lines.append("   → 과긴장 또는 피로 여부 체크")
    if not sh_ok:
        lines.append("⚠️  음량 흔들림 — 호흡 지지 부족")
        lines.append("   → 허밍 스케일 5분")
        lines.append("   → 낮은 볼륨 레가토 연습")
        lines.append("   → 복식호흡 재점검")
    if not h_ok:
        lines.append("⚠️  탁한 소리 — 성대 피로 또는 점막 부종")
        lines.append("   → 고강도 연습 당일 자제")
        lines.append("   → 수분 보충 + 충분한 휴식")
        lines.append("   → 2일 이상 지속 시 음성 전문의 상담")
    return lines


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

    now    = datetime.now().strftime("%Y-%m-%d %H:%M")
    thresh = _get_thresholds(age, gender)

    if not result.get("valid"):
        return f"❌ 분석 실패\n{result.get('error_msg') or '알 수 없는 오류'}"

    jitter  = result["jitter"]
    shimmer = result["shimmer"]
    hnr     = result["hnr"]
    f1      = result["f1"]
    f2      = result["f2"]
    mode    = result["mode"]

    j_ok  = jitter  <= thresh["jitter_max"]
    sh_ok = shimmer <= thresh["shimmer_max"]
    h_ok  = hnr     >= thresh["hnr_min"]

    j_icon  = "✅" if j_ok  else "⚠️"
    sh_icon = "✅" if sh_ok else "⚠️"
    h_icon  = "✅" if h_ok  else "⚠️"

    score      = _calc_score(jitter, shimmer, hnr, thresh)
    mode_label = "베이스라인" if mode == "baseline" else "노래"

    lines = [
        f"🎤 발성 분석 [{mode_label}] — {now}",
        f"종합 점수: {score}점  {_score_label(score)}",
        "",
        "━━ 수치 분석 ━━━━━━━━━━━━━━━━━━",
        f"Jitter   {jitter:.2f}%  {j_icon}",
        f"  ↳ {_jitter_desc(jitter)}",
        f"  ↳ 내 기준 <{thresh['jitter_max']:.2f}%  /  프로 <{PRO_BENCHMARKS['jitter_pro']}%",
        "",
        f"Shimmer  {shimmer:.2f}%  {sh_icon}",
        f"  ↳ {_shimmer_desc(shimmer)}",
        f"  ↳ 내 기준 <{thresh['shimmer_max']:.2f}%  /  프로 <{PRO_BENCHMARKS['shimmer_pro']}%",
        "",
        f"HNR      {hnr:.1f}dB  {h_icon}",
        f"  ↳ {_hnr_desc(hnr)}",
        f"  ↳ 내 기준 >{thresh['hnr_min']:.1f}dB  /  프로 >{PRO_BENCHMARKS['hnr_pro']}dB",
        "",
        "━━ 프로 기준 달성도 ━━━━━━━━━━━━",
        f"떨림(Jitter)   {_bar(jitter,  PRO_BENCHMARKS['jitter_pro'],  False)}",
        f"음량안정(Shim) {_bar(shimmer, PRO_BENCHMARKS['shimmer_pro'], False)}",
        f"맑기(HNR)      {_bar(hnr,     PRO_BENCHMARKS['hnr_pro'],     True)}",
        "",
        "━━ 공명 특성 ━━━━━━━━━━━━━━━━━━",
        f"F1 {f1:.0f}Hz / F2 {f2:.0f}Hz",
        f"  ↳ {_formant_desc(f1, f2, gender)}",
    ]

    # 노래 모드 추가
    if mode == "song":
        held = result.get("held_note_count", 0)
        reliability = "높음" if held >= 5 else "보통" if held >= 2 else "낮음"
        lines += [
            "",
            "━━ 노래 구간 분석 ━━━━━━━━━━━━━━",
            f"안정 구간 {held}개 탐지  (신뢰도: {reliability})",
        ]
        if baseline_result and baseline_result.get("valid"):
            dj  = jitter  - baseline_result["jitter"]
            dsh = shimmer - baseline_result["shimmer"]
            dh  = hnr     - baseline_result["hnr"]
            j_tr  = "↑악화" if dj  > 0.1  else "↓개선" if dj  < -0.1  else "→유지"
            sh_tr = "↑악화" if dsh > 0.2  else "↓개선" if dsh < -0.2  else "→유지"
            h_tr  = "↑개선" if dh  > 1.0  else "↓악화" if dh  < -1.0  else "→유지"
            lines += [
                f"베이스라인 대비:",
                f"  떨림 {dj:+.2f}% {j_tr}  /  음량 {dsh:+.2f}% {sh_tr}  /  맑기 {dh:+.1f}dB {h_tr}",
            ]

    # 개인 평균
    if personal_avg:
        dj  = jitter  - personal_avg.get("jitter",  jitter)
        dsh = shimmer - personal_avg.get("shimmer", shimmer)
        dh  = hnr     - personal_avg.get("hnr",     hnr)
        lines += [
            "",
            "━━ 내 평균 대비 ━━━━━━━━━━━━━━━━",
            f"떨림 {dj:+.2f}%  /  음량 {dsh:+.2f}%  /  맑기 {dh:+.1f}dB",
        ]

    # 훈련 권고
    lines += ["", "━━ 오늘 권고 ━━━━━━━━━━━━━━━━━━"]
    lines += _build_advice(j_ok, sh_ok, h_ok, jitter, shimmer, hnr)

    # /help 안내
    lines += ["", "📖 수치 설명: /help"]

    return "\n".join(lines)


def build_history_message(sessions: list[dict]) -> str:
    if not sessions:
        return "📋 분석 이력이 없습니다."
    lines = ["📋 최근 분석 이력", "━━━━━━━━━━━━━━━━━━━━"]
    for s in sessions:
        ts   = s.get("timestamp", "")[:16]
        mode = "베이스" if s.get("mode") == "baseline" else "노래 "
        j, sh, h = s.get("jitter", 0), s.get("shimmer", 0), s.get("hnr", 0)
        lines.append(f"[{mode}] {ts}")
        lines.append(f"  떨림:{j:.2f}%  음량:{sh:.2f}%  맑기:{h:.1f}dB")
    return "\n".join(lines)
