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
def _build_advice(j_ok, sh_ok, h_ok, jitter, shimmer, hnr,
                  result: dict | None = None) -> list[str]:
    bad = sum([not j_ok, not sh_ok, not h_ok])

    # result에서 컨텍스트 추출
    _r = result or {}
    fatigue_d       = _r.get("fatigue") or {}
    fatigue_verdict = fatigue_d.get("verdict", "") if isinstance(fatigue_d, dict) else ""
    has_breaks      = bool(_r.get("voice_breaks", []))
    breath_d        = _r.get("breath_pattern") or {}
    short_breath    = (
        breath_d.get("avg_phrase_sec", 99) < 4.0
        or breath_d.get("mid_phrase_count", 0) >= 2
    )
    zones       = _r.get("pitch_zone_stats") or {}
    zone_jitters = {k: v["jitter"] for k, v in zones.items() if v}
    worst_zone  = max(zone_jitters, key=zone_jitters.get) if zone_jitters else None
    vibrato_d   = _r.get("vibrato") or {}

    if bad == 0:
        lines = ["💪 오늘 권고"]
        tips = []

        if jitter > PRO_BENCHMARKS["jitter_pro"]:
            if has_breaks:
                tips.append("갈라짐이 있었어요 → 호흡 지지를 유지한 상태로 스타카토 릴리즈 5분")
                tips.append("  ↳ 호흡-성대 협조가 잡히면 갈라짐이 줄고 Jitter도 같이 내려가요")
            elif worst_zone and zone_jitters[worst_zone] > jitter * 1.4:
                tips.append(f"{worst_zone} 구간 집중 연습 → 그 음역대 가볍게 허밍 스케일 5분")
                tips.append(f"  ↳ {worst_zone}에서 성대 접촉이 불안정해요. 허밍으로 포지션을 먼저 잡아요")
            else:
                tips.append("떨림 정밀 개선 → 혀 트릴(/r/) 스케일 또는 혀끝 진동 연습 5분")
                tips.append("  ↳ 조음기관 협조력이 올라가면 성대 진동이 정교해지고 Jitter가 낮아져요")

        if shimmer > PRO_BENCHMARKS["shimmer_pro"]:
            if short_breath:
                tips.append("호흡 지지 강화 → 낮은 볼륨(pp) 롱 노트 유지 10초 × 5회")
                tips.append("  ↳ 호흡 흐름이 고르면 음압 변동(Shimmer)이 자연스럽게 줄어요")
            else:
                tips.append("다이나믹 컨트롤 → pp에서 mf까지 일정 속도로 올리는 크레셴도 연습")
                tips.append("  ↳ 성대 접촉압의 일관성이 높아지면서 음량 안정성(Shimmer)이 좋아져요")

        if hnr < PRO_BENCHMARKS["hnr_pro"]:
            tips.append("맑기 개선 → SOVT(빨대 발성) 워밍업 5분")
            tips.append("  ↳ 성대 반폐쇄 상태에서 접촉 효율이 높아지고, 배음이 풍부해져 HNR이 올라가요")

        if vibrato_d.get("has_vibrato") and vibrato_d.get("rate_hz", 0) < 5.0:
            tips.append("비브라토 속도가 느려요(wobble) → 복부 지지 강화 + 빠른 스타카토 릴리즈 연습")
            tips.append("  ↳ 지지 근육이 강해지면 비브라토 속도가 올라가요(목표 5~7Hz)")

        if not tips:
            tips.append("프로 수준 유지 중! 레퍼토리 확장이나 고강도 스케일 연습 가능해요")
        for t in tips:
            if t.startswith("  ↳"):
                lines.append(f"   {t}")
            else:
                lines.append(f"   → {t}")
        return lines

    lines = []
    if bad >= 2:
        if fatigue_verdict == "피로":
            lines.append("⚠️  복합 불안정 + 피로 감지 — 오늘은 완전 휴식 권장")
            lines.append("   → 발성 완전 자제 / 미지근한 물 충분히 / 수면 우선")
            lines.append("   ↳ 피로한 상태에서 무리하면 성대 결절 위험이 올라가요")
        else:
            lines.append("⚠️  복합 불안정 — 오늘은 워밍업만 권장")
            lines.append("   → SOVT(빨대 발성) 5분 — 성대 부하 없이 혈류만 살리기")
            lines.append("   ↳ 반폐쇄 상태로 성대 부담을 최소화하면서 점막을 깨워요")
            lines.append("   → 고강도 연습 자제 / 수분 보충")
        return lines

    if not j_ok:
        lines.append("⚠️  떨림 초과 — 성대 진동 불안정")
        if fatigue_verdict in ("피로", "경미한 피로"):
            lines.append("   → 피로가 원인일 가능성 높아요 → SOVT(빨대) 5분만")
            lines.append("   ↳ 피로한 성대에 무리한 트릴은 역효과예요. 빨대 발성이 가장 안전해요")
            lines.append("   → 고강도 연습 자제 + 충분한 수분 섭취")
        elif has_breaks:
            lines.append("   → 갈라짐 동반 떨림 → 호흡부터 체크 (복식호흡 상태로 가볍게 허밍 5분)")
            lines.append("   ↳ 갈라짐+떨림은 호흡-성대 협조 부족 신호예요. 허밍으로 연결감을 먼저 만들어요")
        else:
            lines.append("   → SOVT(빨대 발성) 5분")
            lines.append("   ↳ 성대 접촉 효율을 높여서 Jitter를 낮춰줘요")
            lines.append("   → 스타카토 릴리즈 연습 — 짧게 끊어 성대 접촉 타이밍 훈련")
            lines.append("   ↳ 접촉 타이밍이 정확해지면 사이클 간 편차(Jitter)가 빠르게 감소해요")

    if not sh_ok:
        lines.append("⚠️  음량 흔들림 — 호흡 지지 부족")
        if short_breath:
            lines.append("   → 호흡이 짧아요 → 복식호흡 재훈련 우선 (허리 옆 팽창 확인)")
            lines.append("   ↳ 호흡 지지가 안정되면 성대에 가는 압력이 고르게 되어 Shimmer가 내려가요")
        else:
            lines.append("   → 낮은 볼륨(pp) 롱 노트 10초 유지 × 5회")
            lines.append("   ↳ 일정한 서브글로탈 압력을 유지하는 근육을 훈련해 음량 안정성을 높여요")
            lines.append("   → 허밍 레가토 스케일 5분")
            lines.append("   ↳ 공명 활용이 늘면 적은 호흡으로도 음량이 안정되고 Shimmer가 줄어요")

    if not h_ok:
        lines.append("⚠️  탁한 소리 — 성대 피로 또는 점막 부종")
        if fatigue_verdict == "피로":
            lines.append("   → 발성 중단 + 미지근한 물 500mL + 최소 2시간 휴식")
            lines.append("   ↳ 탁한 소리 + 피로 징후는 점막 부종 신호예요. 쉬면 HNR이 회복돼요")
        else:
            lines.append("   → 오늘 고강도 연습 자제")
            lines.append("   → SOVT(빨대) 지글링 3분 — 저강도 진동으로 점막 컨디셔닝")
            lines.append("   ↳ 점막 부종이 빠지면 성대 접촉이 깨끗해지고 HNR이 올라가요")
            lines.append("   → 2일 이상 탁함 지속 시 음성 전문의 상담 권장")

    return lines


# ──────────────────────────────────────────────
# Hz → 한국식 음이름 (feedback 내부용)
# ──────────────────────────────────────────────
def _hz_to_note_ko(hz: float) -> str:
    """주파수(Hz) → 한국식 음이름 (예: 146.8 → '3옥타브 레')."""
    import math
    if hz <= 0:
        return "?"
    semitones = round(12 * math.log2(hz / 440.0))
    ko_names  = ["라", "라♯", "시", "도", "도♯", "레", "레♯", "미", "파", "파♯", "솔", "솔♯"]
    octave    = 4 + (semitones + 9) // 12
    return f"{octave}옥타브 {ko_names[semitones % 12]}"


# ──────────────────────────────────────────────
# 목소리 타입 한 줄 힌트
# ──────────────────────────────────────────────
def _voice_type_hint(result: dict, gender: str) -> str:
    """단일 세션 f0_mean + spectral_centroid로 간단한 타입 힌트."""
    f0 = result.get("f0_mean", 0.0)
    sc = result.get("spectral_centroid", 0.0)
    if f0 <= 0:
        return ""

    # 성부
    if gender == "남":
        if f0 < 115:   vt = "베이스"
        elif f0 < 155: vt = "바리톤"
        elif f0 < 185: vt = "바리톤-테너"
        else:          vt = "테너"
    else:
        if f0 < 200:   vt = "알토"
        elif f0 < 250: vt = "메조소프라노"
        else:          vt = "소프라노"

    f0_note = _hz_to_note_ko(f0)

    # 음색 무게
    if sc > 0:
        if sc < 1500:   wt = "두꺼운 음색"
        elif sc < 2200: wt = "균형 잡힌 음색"
        else:           wt = "얇고 밝은 음색"
        return f"{vt} / {wt}  (평균 {f0_note})"
    return f"{vt}  (평균 {f0_note})"


# ──────────────────────────────────────────────
# 음역대 섹션
# ──────────────────────────────────────────────
def _build_range_section(result: dict) -> list[str]:
    """안정 음역대 + 전체 탐지 음역대 섹션."""
    stable = result.get("stable_range")
    full   = result.get("full_range")
    if not stable and not full:
        return []

    lines = ["━━ 음역대 분석 ━━━━━━━━━━━━━━━━━━"]

    if stable:
        lo_ko = stable["low_ko"]
        hi_ko = stable["high_ko"]
        lo    = stable["low"]
        hi    = stable["high"]
        held  = result.get("held_note_count", 0)
        rel   = "높음" if held >= 5 else "보통" if held >= 2 else "참고용"
        lines.append(f"✅ 안정 음역대:  {lo_ko} ~ {hi_ko}")
        lines.append(f"   ({lo} ~ {hi})  / 구간 {held}개 기반, 신뢰도 {rel}")

    if full:
        lo_ko = full["low_ko"]
        hi_ko = full["high_ko"]
        lo    = full["low"]
        hi    = full["high"]
        lines.append(f"📊 전체 탐지:   {lo_ko} ~ {hi_ko}")
        lines.append(f"   ({lo} ~ {hi})  / 불안정 구간 포함 5~95퍼센타일")

    # 안정↔전체 차이 코멘트
    if stable and full:
        stable_span = stable["high_hz"] - stable["low_hz"]
        full_span   = full["high_hz"]   - full["low_hz"]
        extra_low   = stable["low_hz"]  - full["low_hz"]   # 전체가 더 낮은 만큼
        extra_high  = full["high_hz"]   - stable["high_hz"] # 전체가 더 높은 만큼

        tips = []
        if extra_low > 30:
            tips.append(f"저음 {_hz_to_note_ko(full['low_hz'])} 부근은 불안정하게 탐지됨")
        if extra_high > 30:
            tips.append(f"고음 {_hz_to_note_ko(full['high_hz'])} 부근은 불안정하게 탐지됨")
        if tips:
            lines.append("  ↳ " + " / ".join(tips))

    return lines


# ──────────────────────────────────────────────
# 구간별 문제 탐지 섹션
# ──────────────────────────────────────────────
def _fmt_time(sec: float) -> str:
    """초 → M:SS 포맷."""
    m = int(sec) // 60
    s = int(sec) % 60
    return f"{m}:{s:02d}"


def _build_problem_spots_section(problem_spots: list[dict]) -> list[str]:
    lines = ["━━ 구간별 문제 탐지 ━━━━━━━━━━━━━━"]

    if not problem_spots:
        lines.append("✅ 특이 구간 없음")
        return lines

    type_emoji = {
        "jitter": "📳",
        "hnr": "😮‍💨",
        "register_break": "🎭",
        "nasal": "👃",
    }
    severity_emoji = {
        "위험": "🔴",
        "경고": "⚠️",
        "참고": "💡",
    }

    for spot in problem_spots:
        t = _fmt_time(spot.get("time_sec", 0.0))
        sev = spot.get("severity", "참고")
        stype = spot.get("type", "")
        detail = spot.get("detail", "")
        s_icon = severity_emoji.get(sev, "💡")
        t_icon = type_emoji.get(stype, "❓")
        lines.append(f"{s_icon} {t}  {t_icon} {detail}")

    return lines


# ──────────────────────────────────────────────
# 음역대별 분석 섹션
# ──────────────────────────────────────────────
def _jitter_zone_icon(jitter: float) -> str:
    if jitter <= 1.04: return "✅"
    if jitter <= 1.5:  return "🟡"
    return "⚠️"


def _hnr_zone_icon(hnr: float) -> str:
    if hnr >= 20.0: return "✅"
    if hnr >= 15.0: return "🟡"
    return "⚠️"


def _build_pitch_zone_section(pitch_zone_stats: dict) -> list[str]:
    lines = ["━━ 음역대별 분석 ━━━━━━━━━━━━━━━━"]

    zone_order = ["저음", "중음", "고음"]
    for zone_name in zone_order:
        zone = pitch_zone_stats.get(zone_name)
        if zone is None:
            continue
        note_range = zone.get("range", "?~?")
        count = zone.get("count", 0)
        j = zone.get("jitter", 0.0)
        h = zone.get("hnr", 0.0)
        j_icon = _jitter_zone_icon(j)
        h_icon = _hnr_zone_icon(h)
        lines.append(f"{zone_name} ({note_range}, {count}구간)")
        lines.append(f"  떨림 {j:.2f}% {j_icon}  /  맑기 {h:.1f}dB {h_icon}")

    return lines


# ──────────────────────────────────────────────
# 갈라짐 탐지 섹션
# ──────────────────────────────────────────────
def _build_voice_breaks_section(voice_breaks: list) -> list[str]:
    if not voice_breaks:
        return ["━━ 갈라짐 탐지 ━━━━━━━━━━━━━━━━━━", "✅ 탐지된 갈라짐 없음"]
    zone_icon = {"저음": "🔵", "중음": "🟡", "고음": "🔴"}
    lines = ["━━ 갈라짐 탐지 ━━━━━━━━━━━━━━━━━━"]
    for b in voice_breaks:
        icon = zone_icon.get(b.get("zone_hint", "중음"), "⚡")
        lines.append(
            f"⚡ {_fmt_time(b['time_sec'])}  {icon}{b['zone_hint']}({b['note']}) "
            f"— {b['duration_sec']:.2f}초 갈라짐"
        )
    return lines


# ──────────────────────────────────────────────
# 비브라토 섹션
# ──────────────────────────────────────────────
def _build_vibrato_section(vibrato: dict) -> list[str]:
    if not vibrato:
        return []
    lines = ["━━ 비브라토 분석 ━━━━━━━━━━━━━━━━"]
    if not vibrato.get("has_vibrato"):
        lines.append("비브라토 미탐지 — 직선 발성 위주")
        lines.append("  ↳ 의도적 직선 발성이면 OK, 비브라토 연습 중이라면 계속 훈련 필요")
        return lines
    rate = vibrato["rate_hz"]
    ext  = vibrato["extent_semitones"]
    cov  = vibrato["coverage_pct"]
    if 5.0 <= rate <= 7.0:
        rate_label = f"{rate:.1f}Hz ✅ 정상"
    elif rate < 5.0:
        rate_label = f"{rate:.1f}Hz ⚠️ 느림 (wobble 경향)"
    else:
        rate_label = f"{rate:.1f}Hz ⚠️ 빠름 (tremolo 경향)"
    if ext < 0.2:
        ext_label = f"{ext:.2f}반음 — 거의 없음"
    elif ext <= 0.8:
        ext_label = f"{ext:.2f}반음 ✅ 적절"
    else:
        ext_label = f"{ext:.2f}반음 ⚠️ 넓음 (음정 불안정)"
    lines.append(f"속도: {rate_label}")
    lines.append(f"폭:   {ext_label}")
    lines.append(f"적용 구간: {cov}%의 held note에서 감지")
    return lines


# ──────────────────────────────────────────────
# 호흡 패턴 섹션
# ──────────────────────────────────────────────
def _build_breath_section(breath_pattern: dict) -> list[str]:
    if not breath_pattern:
        return []
    cnt   = breath_pattern["count"]
    avg_p = breath_pattern["avg_phrase_sec"]
    mid   = breath_pattern["mid_phrase_count"]
    lines = ["━━ 호흡 패턴 ━━━━━━━━━━━━━━━━━━━"]
    lines.append(f"호흡 횟수: {cnt}회  /  평균 프레이즈: {avg_p:.1f}초")
    if mid >= 2:
        lines.append(f"⚠️ 짧은 프레이즈 중간 호흡 {mid}회 — 호흡 지지 부족 가능성")
        lines.append("  ↳ 복식 호흡 훈련 + 롱 프레이즈 연습 권고")
    elif avg_p < 4.0:
        lines.append("⚠️ 프레이즈가 짧음 — 호흡을 자주 쉬고 있어요")
    else:
        lines.append("✅ 호흡 패턴 양호")
    return lines


# ──────────────────────────────────────────────
# 피로도 섹션
# ──────────────────────────────────────────────
def _build_fatigue_section(fatigue: dict) -> list[str]:
    if not fatigue:
        return []
    v = fatigue["verdict"]
    dj = fatigue["jitter_delta"]
    dh = fatigue["hnr_delta"]
    icon = {"피로": "🔴", "경미한 피로": "🟡", "워밍업됨": "✅", "안정": "✅"}.get(v, "")
    lines = [f"━━ 발성 피로도 ━━━━━━━━━━━━━━━━━━",
             f"{icon} {v}"]
    lines.append(f"  떨림 변화: {dj:+.3f}%  /  맑기 변화: {dh:+.1f}dB  (전반→후반)")
    if v == "피로":
        lines.append("  ↳ 후반부 성대 피로 뚜렷. 쉬고 SOVT 워밍업 후 재도전 권고")
    elif v == "경미한 피로":
        lines.append("  ↳ 후반부에 발성이 약간 흔들림. 수분 보충 권고")
    elif v == "워밍업됨":
        lines.append("  ↳ 후반부가 더 안정적 — 워밍업이 잘 됐어요")
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
    prev_zone_stats: dict | None = None,   # 이전 세션 pitch_zone_stats
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

    # 목소리 타입 한 줄 (f0_mean 있을 때만)
    voice_type_line = _voice_type_hint(result, gender)

    lines = [
        f"🎤 발성 분석 [{mode_label}] — {now}",
        f"종합 점수: {score}점  {_score_label(score)}",
    ]
    if voice_type_line:
        lines.append(f"목소리 타입: {voice_type_line}  (세션 누적 시 정밀화)")
    lines += [
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

    # 음역대 분석 (stable_range / full_range)
    range_section = _build_range_section(result)
    if range_section:
        lines.append("")
        lines += range_section

    # (신규) 음역대별 분석 — pitch_zone_stats 있을 때만
    pitch_zone_stats = result.get("pitch_zone_stats")
    if pitch_zone_stats is not None:
        lines.append("")
        lines += _build_pitch_zone_section(pitch_zone_stats)

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

    # (신규) 구간별 문제 탐지 — 항상 표시
    problem_spots = result.get("problem_spots", [])
    lines.append("")
    lines += _build_problem_spots_section(problem_spots)

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

    # 갈라짐 탐지
    voice_breaks = result.get("voice_breaks", [])
    lines.append("")
    lines += _build_voice_breaks_section(voice_breaks)

    # 비브라토
    vibrato = result.get("vibrato")
    if vibrato is not None:
        lines.append("")
        lines += _build_vibrato_section(vibrato)

    # 호흡 패턴
    breath = result.get("breath_pattern")
    if breath is not None:
        lines.append("")
        lines += _build_breath_section(breath)

    # 피로도 (노래 모드에서 세그먼트 4개 이상일 때만 나옴)
    fatigue = result.get("fatigue")
    if fatigue is not None:
        lines.append("")
        lines += _build_fatigue_section(fatigue)

    # 코칭 피드백
    lines += [""]
    lines += _build_coaching_text(result, thresh, personal_avg, baseline_result, prev_zone_stats)

    # 훈련 권고
    lines += ["", "━━ 오늘 권고 ━━━━━━━━━━━━━━━━━━"]
    lines += _build_advice(j_ok, sh_ok, h_ok, jitter, shimmer, hnr, result=result)

    # /help 안내
    lines += ["", "📖 수치 설명: /help"]

    return "\n".join(lines)


def _build_coaching_text(
    result: dict,
    thresh: dict,
    personal_avg: dict | None = None,
    baseline_result: dict | None = None,
    prev_zone_stats: dict | None = None,
) -> list[str]:
    """자연어 코칭 피드백 생성."""
    jitter  = result["jitter"]
    shimmer = result["shimmer"]
    hnr     = result["hnr"]
    f2      = result["f2"]
    f2_std  = result.get("f2_std", 0.0)
    zones   = result.get("pitch_zone_stats") or {}
    spots   = result.get("problem_spots", [])
    sh_ok   = shimmer <= thresh["shimmer_max"]

    lines = []

    # 1. 이전 대비 비교
    ref = None
    if baseline_result and baseline_result.get("valid"):
        ref = baseline_result
    elif personal_avg:
        ref = personal_avg
    if ref:
        dj = jitter - ref.get("jitter", jitter)
        dh = hnr    - ref.get("hnr",    hnr)
        if dj > 0.15:
            lines.append(f"지난 녹음보다 떨림이 {dj:+.2f}% 늘었어요. 오늘 목 상태를 체크해보세요.")
        elif dj < -0.15:
            lines.append(f"지난 녹음보다 떨림이 {abs(dj):.2f}% 줄었어요. 발성이 안정되고 있어요 👍")
        if dh < -1.5:
            lines.append(f"소리가 지난 번보다 탁해졌어요. 성대 피로나 수분 부족일 수 있어요.")

    # 2. 공명 위치 (F2)
    if f2 > 0:
        if f2 < 1300:
            lines.append("공명이 목구멍 쪽에 쏠려 있어요. 소리를 앞니 뒤쪽으로 모으는 포워드 포지션 연습이 필요해요.")
        elif f2 < 1500:
            lines.append("공명이 약간 뒤쪽에 있어요. 조금 더 앞으로 모아주면 소리가 밝아질 거예요.")
        elif f2 > 1750:
            lines.append("공명 포지션이 앞쪽에 잘 잡혀 있어요.")

    # 3. F2 안정성
    if f2_std > 200:
        lines.append(f"공명 위치가 녹음 내내 크게 흔들렸어요 (편차 ±{f2_std:.0f}Hz). 발성 포지션이 아직 고정되지 않은 상태예요.")
    elif f2_std > 120:
        lines.append(f"공명 위치가 다소 불안정해요 (편차 ±{f2_std:.0f}Hz). 일관된 포지션 유지 연습이 필요해요.")

    # 4. 음역대별 비교
    if zones:
        # Jitter zone 비교
        zone_j = {k: v["jitter"] for k, v in zones.items() if v}
        if zone_j:
            worst = max(zone_j, key=zone_j.get)
            best  = min(zone_j, key=zone_j.get)
            if zone_j[worst] > zone_j[best] * 1.5 and zone_j[worst] > 0.8:
                lines.append(f"{best}은 안정적인데 {worst} 구간에서 떨림이 심해져요.")

        # F2 zone 하락 (고음 가면서 공명이 뒤로 물러나는지)
        zone_f2 = {k: v.get("f2", 0) for k, v in zones.items() if v and v.get("f2", 0) > 0}
        if "저음" in zone_f2 and "고음" in zone_f2 and zone_f2["저음"] > 0:
            f2_drop = zone_f2["저음"] - zone_f2["고음"]
            if f2_drop > 200:
                lines.append(
                    f"고음으로 올라갈수록 공명이 뒤로 물러나고 있어요 "
                    f"({zone_f2['저음']:.0f}Hz→{zone_f2['고음']:.0f}Hz). "
                    f"고음에서도 앞쪽 공명을 유지하는 게 핵심이에요."
                )

        # 고음 흉성 밀어올리기 감지 (고음 zone F1 높으면 흉성 유지)
        high_zone = zones.get("고음")
        low_zone  = zones.get("저음")
        if high_zone and low_zone:
            if high_zone.get("f1", 0) > 620 and low_zone.get("f1", 0) < high_zone.get("f1", 0):
                lines.append(
                    "고음 구간에서도 흉성을 밀어올리는 경향이 있어요. "
                    "이 음역대는 혼성(믹스 보이스)으로 전환하면 더 편하고 안전해요."
                )

    # 5. 성구 전환
    breaks = [s for s in spots if s["type"] == "register_break"]
    if breaks:
        times = ", ".join(_fmt_time(s["time_sec"]) for s in breaks[:2])
        lines.append(
            f"{times} 부근에서 성구 전환(목소리 갈라짐)이 있었어요. "
            f"이 음 부근이 흉-두성 전환 구간이에요. 믹스 보이스 연습이 필요해요."
        )

    # 6. 비음
    nasal = [s for s in spots if s["type"] == "nasal"]
    if len(nasal) >= 2:
        lines.append(
            "여러 구간에서 비음이 섞여요. "
            "연구개(목젖)를 올려 비강을 막는 연습이 도움이 돼요. "
            "→ 비음이 줄면 소리에 선명도와 울림이 생기고, "
            "HNR이 올라가며 공명이 입 앞쪽으로 더 잘 모여서 소리가 밝아져요."
        )
    elif len(nasal) == 1:
        lines.append(
            "한 구간에서 비음 경향이 있어요. "
            "그 음역대를 노래할 때 입천장(연구개)을 들어올리는 느낌을 유지해보세요."
        )

    # 7. HNR 낮음
    if hnr < 18 and hnr > 0:
        if not sh_ok:
            lines.append(
                "소리에 잡음이 많고 음량도 흔들려요. "
                "호흡 지지가 부족하면 성대가 효율적으로 닫히지 못해서 탁해져요. "
                "→ 복식호흡 + SOVT 훈련으로 호흡 지지를 잡으면 HNR이 올라가요."
            )
        else:
            lines.append(
                "전반적으로 소리에 잡음이 많아요. "
                "성대 점막이 건조하거나 피로한 상태일 때 이런 소리가 나요. "
                "→ 충분한 수분 + SOVT로 점막을 촉촉하게 유지하면 HNR이 회복돼요."
            )

    if not lines:
        if f2 > 1600:
            lines.append(
                "전반적으로 안정적인 발성이에요. "
                "공명 포지션도 앞쪽에 잘 잡혀 있어요. "
                "지금 발성 포지션을 기억해두고 고음 구간에서도 유지하는 게 다음 목표예요."
            )
        else:
            lines.append(
                "전반적으로 안정적인 발성이에요. "
                "공명을 앞니 뒤쪽(이 공명)으로 더 모아보세요. "
                "→ 포워드 포지션이 잡히면 소리가 밝아지고 음량도 올라가서 "
                "덜 힘들이고도 멀리 나가는 소리가 돼요."
            )

    # 8. 이전 녹음 대비 음역대별 변화
    if prev_zone_stats and zones:
        zone_lines = _build_zone_delta(zones, prev_zone_stats)
        if zone_lines:
            lines += zone_lines

    return ["━━ 코칭 피드백 ━━━━━━━━━━━━━━━━"] + [f"• {l}" for l in lines]


def _build_zone_delta(curr: dict, prev: dict) -> list[str]:
    """이전 세션 대비 음역대별 변화를 자연어로 설명."""
    ZONE_ORDER = ["저음", "중음", "고음"]

    # 임계값
    J_SIG  = 0.15   # Jitter 유의미 변화 (%)
    H_SIG  = 1.0    # HNR 유의미 변화 (dB)
    F2_SIG = 80.0   # F2 유의미 변화 (Hz)

    rows = []   # 표 형식 행
    narr = []   # 자연어 설명

    for zone in ZONE_ORDER:
        c = curr.get(zone)
        p = prev.get(zone)
        if not c or not p:
            continue

        dj  = c.get("jitter", 0) - p.get("jitter", 0)
        dh  = c.get("hnr",    0) - p.get("hnr",    0)
        df2 = c.get("f2",     0) - p.get("f2",     0)

        j_arr  = "↓✅" if dj < -J_SIG else ("↑⚠️" if dj > J_SIG else "→")
        h_arr  = "↑✅" if dh > H_SIG  else ("↓⚠️" if dh < -H_SIG else "→")
        f2_arr = "↑" if df2 > F2_SIG else ("↓" if df2 < -F2_SIG else "→")

        rows.append(
            f"  {zone}  떨림{j_arr}{dj:+.2f}%  맑기{h_arr}{dh:+.1f}dB  공명{f2_arr}{df2:+.0f}Hz"
        )

        # 자연어 설명 생성
        improvements = []
        worsenings   = []

        if dj < -J_SIG:   improvements.append("성대 안정성")
        elif dj > J_SIG:  worsenings.append("떨림")

        if dh > H_SIG:    improvements.append("발성 효율")
        elif dh < -H_SIG: worsenings.append("소리 맑기")

        if df2 > F2_SIG:
            improvements.append("공명 위치(앞으로)")
        elif df2 < -F2_SIG:
            worsenings.append(f"공명 위치(뒤로 {abs(df2):.0f}Hz)")

        if improvements and not worsenings:
            narr.append(f"{zone}에서 {', '.join(improvements)}이 나아졌어요.")
        elif worsenings and not improvements:
            narr.append(f"{zone}에서 {', '.join(worsenings)}이 나빠졌어요.")
        elif improvements and worsenings:
            narr.append(
                f"{zone} — {', '.join(improvements)} 개선, "
                f"{', '.join(worsenings)} 주의."
            )

    if not rows:
        return []

    result_lines = ["이전 녹음 대비 변화:"]
    result_lines += rows
    if narr:
        result_lines.append("")
        result_lines += [f"  • {n}" for n in narr]
    return result_lines


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
