"""
core/voice_profile.py
=====================
목소리 특성 분류 + 아티스트 추천 엔진.

classify_voice(sessions, gender) → profile dict
recommend_artists(profile, gender) → list of artist dicts
build_profile_text(profile, recs) → list of str  (feedback용)
"""

import numpy as np

# ──────────────────────────────────────────────
# 분류 임계값
# ──────────────────────────────────────────────

# 성부: 유성음 평균 F0(Hz) 기반
_MALE_VOICE_TYPE = [
    (0,   115, "베이스"),
    (115, 155, "바리톤"),
    (155, 185, "바리톤-테너"),
    (185, 999, "테너"),
]
_FEMALE_VOICE_TYPE = [
    (0,   200, "알토"),
    (200, 250, "메조소프라노"),
    (250, 999, "소프라노"),
]

# 음색 무게: spectral centroid(Hz) 기반
_WEIGHT_THRESH = [
    (0,    1500, "heavy"),   # 두꺼운
    (1500, 2200, "medium"),  # 균형
    (2200, 9999, "light"),   # 얇은
]
_WEIGHT_KO = {
    "heavy":  "두꺼운 음색",
    "medium": "균형 잡힌 음색",
    "light":  "얇고 밝은 음색",
}

# 공명 밝기: F2(Hz) 기반
_BRIGHTNESS_KO = {
    "dark":     "어두운(뒤쪽) 공명",
    "balanced": "균형 잡힌 공명",
    "bright":   "밝은(앞쪽) 공명",
}

# 기식성: HNR(dB) 기반
_BREATHINESS_KO = {
    "breathy":  "기식성 발성 (숨 섞임)",
    "balanced": "균형 잡힌 발성",
    "pressed":  "압축된 맑은 발성",
}


def _classify(value: float, thresholds: list) -> str:
    for lo, hi, label in thresholds:
        if lo <= value < hi:
            return label
    return thresholds[-1][2]


def _brightness_from_f2(f2: float, gender: str) -> str:
    lo, hi = (1300, 1700) if gender == "남" else (1400, 1900)
    if f2 < lo:  return "dark"
    if f2 < hi:  return "balanced"
    return "bright"


def _breathiness_from_hnr(hnr: float) -> str:
    if hnr < 18:  return "breathy"
    if hnr < 25:  return "balanced"
    return "pressed"


# ──────────────────────────────────────────────
# 아티스트 데이터베이스
# ──────────────────────────────────────────────
_MALE_ARTIST_DB = {
    "성시경": {
        "voice_types": ["바리톤"],
        "weight":      ["medium", "heavy"],
        "brightness":  ["balanced", "dark"],
        "breathiness": ["balanced"],
        "genre":       "발라드 / 팝",
        "songs":       ["거리에서", "너는 나의 봄이다", "희재"],
        "desc":        "부드럽고 따뜻한 중저음 바리톤",
    },
    "박효신": {
        "voice_types": ["바리톤-테너", "테너"],
        "weight":      ["medium"],
        "brightness":  ["balanced", "bright"],
        "breathiness": ["balanced", "pressed"],
        "genre":       "발라드 / R&B",
        "songs":       ["야생화", "숨", "I Love You"],
        "desc":        "서정적이면서 파워풀한 감성 테너",
    },
    "임창정": {
        "voice_types": ["바리톤"],
        "weight":      ["medium", "heavy"],
        "brightness":  ["balanced", "dark"],
        "breathiness": ["balanced"],
        "genre":       "발라드 / 트로트팝",
        "songs":       ["소주 한잔", "그때 또 다시", "이 순간"],
        "desc":        "정감 있는 감성 중저음 바리톤",
    },
    "이승철": {
        "voice_types": ["바리톤", "바리톤-테너"],
        "weight":      ["medium"],
        "brightness":  ["balanced"],
        "breathiness": ["balanced", "pressed"],
        "genre":       "발라드 / 팝",
        "songs":       ["안녕이라고 말하지마", "그녀가 처음 울던날", "내 곁에서 떠나가지 마"],
        "desc":        "강렬하고 감정 표현이 풍부한 바리톤",
    },
    "신승훈": {
        "voice_types": ["바리톤"],
        "weight":      ["medium"],
        "brightness":  ["balanced"],
        "breathiness": ["balanced"],
        "genre":       "발라드",
        "songs":       ["보이지 않는 사랑", "널 사랑하니", "I Believe"],
        "desc":        "맑고 안정적인 중음역 바리톤",
    },
    "김범수": {
        "voice_types": ["테너", "바리톤-테너"],
        "weight":      ["light", "medium"],
        "brightness":  ["bright", "balanced"],
        "breathiness": ["balanced", "pressed"],
        "genre":       "발라드 / 팝",
        "songs":       ["보고 싶다", "끝사랑", "제발"],
        "desc":        "감성적이고 맑은 고음 테너",
    },
    "이적": {
        "voice_types": ["바리톤", "바리톤-테너"],
        "weight":      ["light", "medium"],
        "brightness":  ["balanced"],
        "breathiness": ["balanced", "breathy"],
        "genre":       "인디 / 팝",
        "songs":       ["거짓말 거짓말 거짓말", "하늘을 달리다", "다행이다"],
        "desc":        "독특하고 서정적인 감성 보이스",
    },
    "임재범": {
        "voice_types": ["테너", "바리톤-테너"],
        "weight":      ["heavy", "medium"],
        "brightness":  ["dark", "balanced"],
        "breathiness": ["pressed"],
        "genre":       "록 발라드",
        "songs":       ["너를 위한 것이야", "이젠 그랬으면 좋겠네", "비상"],
        "desc":        "강렬하고 드라마틱한 록 테너",
    },
    "Bruno Mars": {
        "voice_types": ["바리톤", "바리톤-테너"],
        "weight":      ["medium"],
        "brightness":  ["balanced"],
        "breathiness": ["balanced"],
        "genre":       "팝 / R&B / 소울",
        "songs":       ["Just The Way You Are", "When I Was Your Man", "Grenade"],
        "desc":        "밝고 파워풀한 팝 소울 바리톤",
    },
    "John Legend": {
        "voice_types": ["바리톤", "바리톤-테너"],
        "weight":      ["medium"],
        "brightness":  ["balanced"],
        "breathiness": ["balanced", "breathy"],
        "genre":       "R&B / 소울 / 팝",
        "songs":       ["All of Me", "Ordinary People", "Stay With You"],
        "desc":        "부드럽고 감성적인 R&B 소울 바리톤",
    },
    "Sam Smith": {
        "voice_types": ["테너", "바리톤-테너"],
        "weight":      ["light", "medium"],
        "brightness":  ["bright", "balanced"],
        "breathiness": ["balanced", "breathy"],
        "genre":       "팝 / 소울",
        "songs":       ["Stay With Me", "Writing's On The Wall", "Lay Me Down"],
        "desc":        "맑고 감성적인 팝 소울 테너",
    },
    "Michael Buble": {
        "voice_types": ["바리톤"],
        "weight":      ["medium", "heavy"],
        "brightness":  ["balanced", "dark"],
        "breathiness": ["balanced"],
        "genre":       "재즈 팝 / 스윙",
        "songs":       ["Feeling Good", "Haven't Met You Yet", "Cry Me a River"],
        "desc":        "따뜻하고 풍성한 재즈 팝 바리톤",
    },
    "Ed Sheeran": {
        "voice_types": ["바리톤-테너", "바리톤"],
        "weight":      ["light", "medium"],
        "brightness":  ["balanced"],
        "breathiness": ["balanced"],
        "genre":       "팝 / 포크팝",
        "songs":       ["Perfect", "Thinking Out Loud", "Photograph"],
        "desc":        "친근하고 자연스러운 팝 포크 보이스",
    },
}

# 향후 여성 DB 확장 가능
_FEMALE_ARTIST_DB: dict = {}


# ──────────────────────────────────────────────
# 인접 성부 판단
# ──────────────────────────────────────────────
_ADJACENT_TYPE = {
    "베이스":      {"베이스", "바리톤"},
    "바리톤":      {"베이스", "바리톤", "바리톤-테너"},
    "바리톤-테너": {"바리톤", "바리톤-테너", "테너"},
    "테너":        {"바리톤-테너", "테너"},
    "알토":        {"알토", "메조소프라노"},
    "메조소프라노": {"알토", "메조소프라노", "소프라노"},
    "소프라노":    {"메조소프라노", "소프라노"},
}


def _adjacent_level(a: str, b: str, levels: list) -> bool:
    if a not in levels or b not in levels:
        return False
    return abs(levels.index(a) - levels.index(b)) == 1


# ──────────────────────────────────────────────
# 목소리 프로필 분류
# ──────────────────────────────────────────────
def classify_voice(sessions: list[dict], gender: str) -> dict:
    """
    여러 세션을 평균해 목소리 프로필 반환.
    spectral_centroid / f0_mean 이 있는 최신 세션을 우선 사용.
    """
    if not sessions:
        return {}

    valid = [s for s in sessions if s.get("f0_mean", 0) > 0 and s.get("spectral_centroid", 0) > 0]

    f2_vals  = [s["f2"]  for s in sessions if s.get("f2",  0) > 0]
    hnr_vals = [s["hnr"] for s in sessions if s.get("hnr", 0) > 0]
    f2_mean  = float(np.mean(f2_vals))  if f2_vals  else 0.0
    hnr_mean = float(np.mean(hnr_vals)) if hnr_vals else 0.0

    brightness  = _brightness_from_f2(f2_mean, gender)  if f2_mean  else "balanced"
    breathiness = _breathiness_from_hnr(hnr_mean)       if hnr_mean else "balanced"

    if not valid:
        # 구 데이터 — f0_mean/SC 없음 → 성부·무게 미정
        return {
            "voice_type":        None,
            "weight":            None,
            "brightness":        brightness,
            "breathiness":       breathiness,
            "f0_mean":           0.0,
            "spectral_centroid": 0.0,
            "f2_mean":           round(f2_mean, 1),
            "hnr_mean":          round(hnr_mean, 2),
            "session_count":     len(sessions),
            "confidence":        "낮음 (구 데이터)",
        }

    f0_vals = [s["f0_mean"] for s in valid]
    sc_vals = [s["spectral_centroid"] for s in valid]
    f0_mean = float(np.mean(f0_vals))
    sc_mean = float(np.mean(sc_vals))

    thresholds = _MALE_VOICE_TYPE if gender == "남" else _FEMALE_VOICE_TYPE
    voice_type = _classify(f0_mean, thresholds)
    weight     = _classify(sc_mean, _WEIGHT_THRESH)

    n = len(valid)
    confidence = "높음" if n >= 5 else "보통" if n >= 3 else "낮음 (세션 부족)"

    return {
        "voice_type":        voice_type,
        "weight":            weight,
        "brightness":        brightness,
        "breathiness":       breathiness,
        "f0_mean":           round(f0_mean, 1),
        "spectral_centroid": round(sc_mean, 1),
        "f2_mean":           round(f2_mean, 1),
        "hnr_mean":          round(hnr_mean, 2),
        "session_count":     len(sessions),
        "confidence":        confidence,
    }


# ──────────────────────────────────────────────
# 아티스트 추천
# ──────────────────────────────────────────────
def recommend_artists(profile: dict, gender: str, top_n: int = 4) -> list[dict]:
    """
    프로필에 맞는 아티스트 상위 top_n개 반환.
    점수: 성부 40점 / 음색무게 25점 / 공명밝기 20점 / 기식성 15점
    """
    db          = _MALE_ARTIST_DB if gender == "남" else _FEMALE_ARTIST_DB
    voice_type  = profile.get("voice_type")
    weight      = profile.get("weight")
    brightness  = profile.get("brightness")
    breathiness = profile.get("breathiness")

    W_LEVELS = ["light", "medium", "heavy"]
    B_LEVELS = ["dark", "balanced", "bright"]
    T_LEVELS = ["breathy", "balanced", "pressed"]

    scored = []
    for name, data in db.items():
        score   = 0
        reasons = []

        # 성부 (40점)
        if voice_type:
            if voice_type in data["voice_types"]:
                score += 40
                reasons.append(f"성부({voice_type}) 일치")
            elif any(voice_type in _ADJACENT_TYPE.get(vt, set()) for vt in data["voice_types"]):
                score += 20
                reasons.append("성부 인접")

        # 음색 무게 (25점)
        if weight:
            if weight in data["weight"]:
                score += 25
                reasons.append(_WEIGHT_KO.get(weight, weight))
            elif any(_adjacent_level(weight, w, W_LEVELS) for w in data["weight"]):
                score += 12

        # 공명 밝기 (20점)
        if brightness:
            if brightness in data["brightness"]:
                score += 20
                reasons.append(_BRIGHTNESS_KO.get(brightness, brightness))
            elif any(_adjacent_level(brightness, b, B_LEVELS) for b in data["brightness"]):
                score += 10

        # 기식성 (15점)
        if breathiness:
            if breathiness in data["breathiness"]:
                score += 15
                reasons.append(_BREATHINESS_KO.get(breathiness, breathiness))
            elif any(_adjacent_level(breathiness, t, T_LEVELS) for t in data["breathiness"]):
                score += 7

        if score > 0:
            scored.append({
                "name":         name,
                "genre":        data["genre"],
                "songs":        data["songs"],
                "desc":         data["desc"],
                "match_reason": " / ".join(reasons) if reasons else "부분 일치",
                "score":        score,
            })

    scored.sort(key=lambda x: -x["score"])
    return scored[:top_n]


# ──────────────────────────────────────────────
# 텍스트 빌더 (feedback.py / main.py에서 사용)
# ──────────────────────────────────────────────
def build_profile_text(profile: dict, recs: list[dict]) -> list[str]:
    """목소리 프로필 + 아티스트 추천 텍스트 블록."""
    if not profile:
        return []

    vt   = profile.get("voice_type") or "분석 중"
    wt   = _WEIGHT_KO.get(profile.get("weight", ""),       "측정 중")
    br   = _BRIGHTNESS_KO.get(profile.get("brightness", ""), "")
    bt   = _BREATHINESS_KO.get(profile.get("breathiness", ""), "")
    conf = profile.get("confidence", "")
    sc   = profile.get("session_count", 0)
    f0   = profile.get("f0_mean", 0.0)
    sc_v = profile.get("spectral_centroid", 0.0)

    lines = ["━━ 내 목소리 프로필 ━━━━━━━━━━━━━━"]
    lines.append(f"성부 추정:    {vt}")
    lines.append(f"음색 무게:    {wt}")
    if br: lines.append(f"공명 위치:    {br}")
    if bt: lines.append(f"발성 스타일:  {bt}")
    if f0   > 0: lines.append(f"평균 음높이:  {f0:.0f}Hz")
    if sc_v > 0: lines.append(f"음색 중심:    {sc_v:.0f}Hz")
    lines.append(f"신뢰도: {conf}  ({sc}세션 기반)")

    if profile.get("voice_type") is None:
        lines.append("")
        lines.append("  ℹ️ 녹음을 더 쌓으면 성부·음색 무게가 정확해져요.")

    if recs:
        lines += [
            "",
            "━━ 어울리는 아티스트 ━━━━━━━━━━━━",
            "  목소리 타입·음색이 비슷한 아티스트예요.",
            "  (실력 비교 ✗  —  발성 타입 매칭)",
            "",
        ]
        for r in recs:
            songs_str = " / ".join(r["songs"][:2])
            lines.append(f"🎤 {r['name']}  [{r['genre']}]")
            lines.append(f"   {r['desc']}")
            lines.append(f"   추천곡: {songs_str}")
            lines.append(f"   매칭 근거: {r['match_reason']}")
            lines.append("")

    return lines
