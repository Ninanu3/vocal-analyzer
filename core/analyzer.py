"""
core/analyzer.py
================
발성 분석 엔진 (parselmouth + librosa).
Cloud Function, 폴링 봇, 로컬 감시 모드 모두 이 모듈을 공유한다.

반환 형식:
{
    "mode":             "baseline" | "song",
    "jitter":           float,   # %
    "shimmer":          float,   # %
    "hnr":              float,   # dB
    "f1":               float,   # Hz
    "f2":               float,   # Hz
    "held_note_count":  int,     # 노래 모드만, 아니면 0
    "valid":            bool,
    "error_msg":        str | None,
    "problem_spots":    list[dict],
    "pitch_zone_stats": dict | None,
}
"""

import math
import os
import tempfile
import traceback

import numpy as np

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
BASELINE_MAX_SEC   = 30.0   # 이 길이 이하면 베이스라인 모드
JITTER_OUTLIER_PCT = 2.0    # 이상치 필터 기준 (%)
HNR_OUTLIER_DB     = 5.0    # 이상치 필터 기준 (dB)
VALID_RATIO_MIN    = 0.50   # 유효 구간 비율이 이 값 미만이면 재녹음 필요

HELD_MIN_SEC       = 0.8    # held note 최소 길이 (초)
HELD_F0_STD_MAX    = 20.0   # held note 판정용 f0 표준편차 최대 (Hz) — 자연 노래 기준

SILENCE_TRIM_SEC   = 0.3    # 앞뒤 무음 trim 길이 (초)
TARGET_SR          = 44100  # 목표 샘플링 레이트

EMPTY_RESULT = {
    "mode": "baseline",
    "jitter": 0.0,
    "shimmer": 0.0,
    "hnr": 0.0,
    "f1": 0.0,
    "f2": 0.0,
    "held_note_count": 0,
    "valid": False,
    "error_msg": None,
    "problem_spots": [],
    "pitch_zone_stats": None,
    "f2_std": 0.0,
    "voice_breaks":       [],   # 목소리 갈라짐 타임스탬프
    "fatigue":            None, # 피로도 분석
    "breath_pattern":     None, # 호흡 패턴
    "vibrato":            None, # 비브라토 분석
    "spectral_centroid":  0.0,  # 음색 무게 (스펙트럼 무게 중심 Hz)
    "f0_mean":            0.0,  # 유성음 구간 평균 기본주파수 Hz
}


# ──────────────────────────────────────────────
# 유틸 함수
# ──────────────────────────────────────────────
def _hz_to_note(hz: float) -> str:
    """주파수(Hz) → 음이름 (예: 330.0 → 'E4')."""
    if hz <= 0:
        return "?"
    semitones = round(12 * math.log2(hz / 440.0))
    names = ["A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"]
    octave = 4 + (semitones + 9) // 12
    return f"{names[semitones % 12]}{octave}"


def _moving_avg(arr, w):
    """단순 이동 평균 (numpy convolve)."""
    return np.convolve(arr, np.ones(w) / w, mode='same')


# ──────────────────────────────────────────────
# 전처리
# ──────────────────────────────────────────────
def _convert_to_wav(src_path: str) -> str:
    """
    pydub로 임의 포맷 → WAV (44100 Hz, mono, 16bit) 변환.
    반환: 임시 WAV 파일 경로 (호출자가 삭제 책임)
    """
    from pydub import AudioSegment

    audio = AudioSegment.from_file(src_path)
    audio = audio.set_frame_rate(TARGET_SR).set_channels(1).set_sample_width(2)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    audio.export(tmp.name, format="wav")
    return tmp.name


def _trim_silence(wav_path: str) -> str:
    """앞뒤 SILENCE_TRIM_SEC 만큼 잘라낸 새 WAV 반환."""
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(wav_path)
    trim_ms = int(SILENCE_TRIM_SEC * 1000)
    duration_ms = len(audio)

    if duration_ms <= trim_ms * 2:
        return wav_path  # 너무 짧으면 그대로

    trimmed = audio[trim_ms : duration_ms - trim_ms]
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    trimmed.export(tmp.name, format="wav")
    return tmp.name


def _get_duration_sec(wav_path: str) -> float:
    from pydub import AudioSegment
    return len(AudioSegment.from_wav(wav_path)) / 1000.0


# ──────────────────────────────────────────────
# parselmouth 분석 (단일 WAV 구간)
# ──────────────────────────────────────────────
def _parselmouth_analyze(wav_path: str) -> dict:
    """
    parselmouth로 Jitter, Shimmer, HNR, F1/F2 산출.
    반환: {"jitter": float, "shimmer": float, "hnr": float, "f1": float, "f2": float}
    """
    import parselmouth
    from parselmouth.praat import call

    snd = parselmouth.Sound(wav_path)

    # ── PointProcess (성대 진동 주기)
    point_process = call(snd, "To PointProcess (periodic, cc)", 75, 500)

    # ── Jitter (local) %
    jitter = call(point_process, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
    jitter_pct = jitter * 100.0 if jitter is not None else 0.0

    # ── Shimmer (local) %
    shimmer = call(
        [snd, point_process],
        "Get shimmer (local)",
        0, 0, 0.0001, 0.02, 1.3, 1.6,
    )
    shimmer_pct = shimmer * 100.0 if shimmer is not None else 0.0

    # ── HNR (dB)
    harmonicity = call(snd, "To Harmonicity (cc)", 0.01, 75, 0.1, 1.0)
    hnr = call(harmonicity, "Get mean", 0, 0)
    hnr_db = hnr if hnr is not None else 0.0

    # ── Formants F1, F2
    formant = call(snd, "To Formant (burg)", 0, 5, 5500, 0.025, 50)
    f1_values, f2_values = [], []
    duration = snd.duration
    step = 0.01  # 10ms 간격으로 샘플링
    t = step
    while t < duration - step:
        v1 = call(formant, "Get value at time", 1, t, "Hertz", "Linear")
        v2 = call(formant, "Get value at time", 2, t, "Hertz", "Linear")
        if v1 and not np.isnan(v1):
            f1_values.append(v1)
        if v2 and not np.isnan(v2):
            f2_values.append(v2)
        t += step

    f1 = float(np.mean(f1_values)) if f1_values else 0.0
    f2 = float(np.mean(f2_values)) if f2_values else 0.0

    return {
        "jitter":  round(jitter_pct, 4),
        "shimmer": round(shimmer_pct, 4),
        "hnr":     round(hnr_db, 2),
        "f1":      round(f1, 1),
        "f2":      round(f2, 1),
    }


# ──────────────────────────────────────────────
# 이상치 필터
# ──────────────────────────────────────────────
def _apply_outlier_filter(metrics_list: list[dict], total_count: int) -> tuple[dict | None, str | None]:
    """
    Jitter > 2% 또는 HNR < 5dB 구간 제외 후 평균 산출.
    유효 비율이 50% 미만이면 None 반환.
    """
    valid = [
        m for m in metrics_list
        if m["jitter"] <= JITTER_OUTLIER_PCT and m["hnr"] >= HNR_OUTLIER_DB
    ]

    if total_count == 0:
        return None, "분석 가능한 구간이 없습니다."

    ratio = len(valid) / total_count
    if ratio < VALID_RATIO_MIN:
        return None, (
            f"유효 구간이 전체의 {ratio*100:.0f}%로 부족합니다. "
            f"조용한 환경에서 재녹음해 주세요."
        )

    avg = {
        "jitter":  round(float(np.mean([m["jitter"]  for m in valid])), 4),
        "shimmer": round(float(np.mean([m["shimmer"] for m in valid])), 4),
        "hnr":     round(float(np.mean([m["hnr"]     for m in valid])), 2),
        "f1":      round(float(np.mean([m["f1"]      for m in valid])), 1),
        "f2":      round(float(np.mean([m["f2"]      for m in valid])), 1),
    }
    return avg, None


# ──────────────────────────────────────────────
# pyin 실행 (공통 기반)
# ──────────────────────────────────────────────
def _run_pyin(wav_path: str):
    """
    librosa.pyin으로 f0, voiced_flag, voiced_prob, frame_times, y, sr 반환.
    반환: (f0, voiced_flag, voiced_prob, frame_times, y, sr)
    """
    import librosa

    y, sr = librosa.load(wav_path, sr=None, mono=True)
    hop_length = 512
    frame_length = 2048

    f0, voiced_flag, voiced_prob = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C6"),
        sr=sr,
        hop_length=hop_length,
        frame_length=frame_length,
    )

    frame_times = librosa.frames_to_time(
        np.arange(len(f0)), sr=sr, hop_length=hop_length
    )

    return f0, voiced_flag, voiced_prob, frame_times, y, sr


# ──────────────────────────────────────────────
# 음색 특성 (spectral centroid + f0_mean)
# ──────────────────────────────────────────────
def _compute_voice_features(y, sr, f0, voiced_flag) -> dict:
    """
    spectral_centroid: 음색 무게 중심 (Hz). 낮으면 두껍고 어두운 음색, 높으면 얇고 밝은 음색.
    f0_mean: voiced 구간 평균 기본주파수 (Hz). 성부 추정에 사용.
    """
    import librosa

    try:
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        sc_mean = float(np.mean(centroid))
    except Exception:
        sc_mean = 0.0

    try:
        voiced_f0 = [
            float(f0[i])
            for i in range(len(f0))
            if bool(voiced_flag[i]) and not np.isnan(float(f0[i])) and float(f0[i]) > 0
        ]
        f0_mean = float(np.mean(voiced_f0)) if voiced_f0 else 0.0
    except Exception:
        f0_mean = 0.0

    return {
        "spectral_centroid": round(sc_mean, 1),
        "f0_mean":           round(f0_mean, 1),
    }


# ──────────────────────────────────────────────
# held note 구간 추출
# ──────────────────────────────────────────────
def _extract_held_segments(f0, voiced_flag, frame_times) -> list[tuple[float, float, float]]:
    """
    안정된 held note 구간 [(start_sec, end_sec, median_f0), ...] 반환.
    """
    held_segments = []
    in_segment = False
    seg_start = 0.0
    seg_f0_vals = []

    for i in range(len(frame_times)):
        t = float(frame_times[i])
        voiced = bool(voiced_flag[i])
        f0_val = float(f0[i])

        if voiced and not np.isnan(f0_val):
            if not in_segment:
                in_segment = True
                seg_start = t
                seg_f0_vals = [f0_val]
            else:
                seg_f0_vals.append(f0_val)
        else:
            if in_segment:
                seg_end = t
                duration = seg_end - seg_start
                if (
                    duration >= HELD_MIN_SEC
                    and np.std(seg_f0_vals) < HELD_F0_STD_MAX
                ):
                    median_f0 = float(np.median(seg_f0_vals))
                    held_segments.append((seg_start, seg_end, median_f0))
                in_segment = False
                seg_f0_vals = []

    # 마지막 구간 처리
    if in_segment and len(seg_f0_vals) > 0:
        seg_end = float(frame_times[-1])
        duration = seg_end - seg_start
        if duration >= HELD_MIN_SEC and np.std(seg_f0_vals) < HELD_F0_STD_MAX:
            median_f0 = float(np.median(seg_f0_vals))
            held_segments.append((seg_start, seg_end, median_f0))

    return held_segments


# ──────────────────────────────────────────────
# 성구 전환 탐지
# ──────────────────────────────────────────────
def _detect_register_breaks(f0, voiced_flag, frame_times) -> list[dict]:
    """
    연속 voiced 프레임에서 F0 비율이 1.40 이상 또는 0.714 이하로 급변하는 지점 탐지.
    직전 voiced 프레임이 최소 8개 이상일 때만 판정.
    2초 이내 중복 제거, 최대 5개 반환.
    """
    breaks = []
    consecutive_voiced = 0
    prev_f0 = None

    for i in range(len(frame_times)):
        voiced = bool(voiced_flag[i])
        f0_val = float(f0[i])

        if voiced and not np.isnan(f0_val):
            if prev_f0 is not None and consecutive_voiced >= 8:
                ratio = f0_val / prev_f0
                if ratio >= 1.40 or ratio <= 0.714:
                    t = float(frame_times[i])
                    direction = "상향" if ratio >= 1.40 else "하향"
                    breaks.append({
                        "time_sec": round(t, 2),
                        "from_note": _hz_to_note(prev_f0),
                        "to_note": _hz_to_note(f0_val),
                        "direction": direction,
                    })
            consecutive_voiced += 1
            prev_f0 = f0_val
        else:
            consecutive_voiced = 0
            prev_f0 = None

    # 2초 이내 중복 제거
    deduped = []
    for b in breaks:
        if not deduped or b["time_sec"] - deduped[-1]["time_sec"] > 2.0:
            deduped.append(b)
        if len(deduped) >= 5:
            break

    return deduped


# ──────────────────────────────────────────────
# 비음 경향 탐지
# ──────────────────────────────────────────────
def _estimate_nasal_spots(y, sr) -> list[dict]:
    """
    librosa STFT로 nasal 밴드(200~500Hz) / vowel 밴드(500~3000Hz) 에너지 비율 계산.
    이동평균 평활화 후 평균 + 1.5 * 표준편차 초과 구간 중 0.5초 이상 지속 구간 탐지.
    지속시간 긴 순 상위 3개 반환.
    """
    import librosa

    hop_length = 512
    n_fft = 2048

    stft = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    nasal_mask = (freqs >= 200) & (freqs <= 500)
    vowel_mask = (freqs >= 500) & (freqs <= 3000)

    nasal_energy = stft[nasal_mask, :].sum(axis=0)
    vowel_energy = stft[vowel_mask, :].sum(axis=0)

    # 0 나누기 방지
    denom = vowel_energy.copy()
    denom[denom < 1e-10] = 1e-10
    ratio = nasal_energy / denom

    # 이동 평균 평활화
    smoothed = _moving_avg(ratio, w=10)

    mean_r = float(np.mean(smoothed))
    std_r = float(np.std(smoothed))
    threshold = mean_r + 1.5 * std_r

    frame_times = librosa.frames_to_time(
        np.arange(len(smoothed)), sr=sr, hop_length=hop_length
    )
    frame_dur = float(frame_times[1] - frame_times[0]) if len(frame_times) > 1 else (hop_length / sr)

    # 임계값 초과 구간 탐지
    spots = []
    in_spot = False
    spot_start = 0.0

    for i in range(len(smoothed)):
        if smoothed[i] > threshold:
            if not in_spot:
                in_spot = True
                spot_start = float(frame_times[i])
        else:
            if in_spot:
                duration = float(frame_times[i]) - spot_start
                if duration >= 0.5:
                    spots.append({
                        "time_sec": round(spot_start, 2),
                        "duration_sec": round(duration, 2),
                    })
                in_spot = False

    # 마지막 구간
    if in_spot:
        duration = float(frame_times[-1]) - spot_start
        if duration >= 0.5:
            spots.append({
                "time_sec": round(spot_start, 2),
                "duration_sec": round(duration, 2),
            })

    # 지속시간 긴 순 상위 3개
    spots.sort(key=lambda x: x["duration_sec"], reverse=True)
    return spots[:3]


# ──────────────────────────────────────────────
# 음역대별 통계 (노래 모드)
# ──────────────────────────────────────────────
def _compute_pitch_zone_stats(seg_data: list[dict]) -> dict | None:
    """
    held note 구간별 median_f0를 기준으로 3등분 (percentile 33/66).
    각 구간별 Jitter/Shimmer/HNR 평균 + 구간 수 + 음이름 범위 반환.
    """
    if not seg_data:
        return None

    f0_values = [d["f0_hz"] for d in seg_data if d.get("f0_hz", 0) > 0]
    if not f0_values:
        return None

    p33 = float(np.percentile(f0_values, 33))
    p66 = float(np.percentile(f0_values, 66))

    zones = {"저음": [], "중음": [], "고음": []}
    for d in seg_data:
        hz = d.get("f0_hz", 0)
        if hz <= 0:
            continue
        if hz <= p33:
            zones["저음"].append(d)
        elif hz <= p66:
            zones["중음"].append(d)
        else:
            zones["고음"].append(d)

    result = {}
    for zone_name, items in zones.items():
        if not items:
            result[zone_name] = None
            continue
        f0_list = [d["f0_hz"] for d in items]
        result[zone_name] = {
            "jitter":  round(float(np.mean([d["jitter"]  for d in items])), 4),
            "shimmer": round(float(np.mean([d["shimmer"] for d in items])), 4),
            "hnr":     round(float(np.mean([d["hnr"]     for d in items])), 2),
            "f1":      round(float(np.mean([d["f1"] for d in items])), 1),
            "f2":      round(float(np.mean([d["f2"] for d in items])), 1),
            "count":   len(items),
            "range":   f"{_hz_to_note(min(f0_list))}~{_hz_to_note(max(f0_list))}",
        }

    return result


# ──────────────────────────────────────────────
# 갈라짐 탐지
# ──────────────────────────────────────────────
def _detect_voice_breaks(f0, voiced_flag, voiced_prob, frame_times) -> list[dict]:
    """
    짧은 무성 구간(0.05~0.5초)이 유성음 사이에 끼어 있으면 갈라짐으로 판정.
    반환: [{"time_sec", "duration_sec", "note", "zone_hint"}, ...]
    """
    MIN_GAP = 0.05   # 50ms 미만은 무시 (측정 오차)
    MAX_GAP = 0.5    # 500ms 초과는 의도적 쉼표
    MIN_VOICED_CONTEXT = 0.3  # 앞뒤 이 시간 이상 유성음이 있어야 갈라짐으로 판정

    # voiced 구간 찾기
    segments = []  # (start_idx, end_idx, is_voiced)
    in_voiced = bool(voiced_flag[0])
    seg_start = 0
    for i in range(1, len(voiced_flag)):
        if bool(voiced_flag[i]) != in_voiced:
            segments.append((seg_start, i - 1, in_voiced))
            seg_start = i
            in_voiced = bool(voiced_flag[i])
    segments.append((seg_start, len(voiced_flag) - 1, in_voiced))

    breaks = []
    for idx, (s, e, is_v) in enumerate(segments):
        if is_v:
            continue
        dur = frame_times[e] - frame_times[s]
        if dur < MIN_GAP or dur > MAX_GAP:
            continue
        # 앞뒤 voiced context 확인
        has_before = idx > 0 and segments[idx-1][2] and \
                     (frame_times[segments[idx-1][1]] - frame_times[segments[idx-1][0]]) >= MIN_VOICED_CONTEXT
        has_after  = idx < len(segments)-1 and segments[idx+1][2] and \
                     (frame_times[segments[idx+1][1]] - frame_times[segments[idx+1][0]]) >= MIN_VOICED_CONTEXT
        if not (has_before and has_after):
            continue

        # 앞쪽 voiced 구간의 마지막 f0로 음이름 추정
        before_seg = segments[idx-1] if idx > 0 else None
        note = "?"
        zone_hint = "중음"
        if before_seg:
            f0_slice = [float(f0[i]) for i in range(before_seg[0], before_seg[1]+1)
                       if bool(voiced_flag[i]) and not np.isnan(float(f0[i]))]
            if f0_slice:
                median_f0 = float(np.median(f0_slice[-10:]))  # 마지막 10프레임
                note = _hz_to_note(median_f0)
                zone_hint = "저음" if median_f0 < 200 else ("고음" if median_f0 > 350 else "중음")

        breaks.append({
            "time_sec":    round(float(frame_times[s]), 2),
            "duration_sec": round(dur, 2),
            "note":         note,
            "zone_hint":    zone_hint,
        })

    # 1초 이내 중복 제거
    filtered, last_t = [], -999.0
    for b in sorted(breaks, key=lambda x: x["time_sec"]):
        if b["time_sec"] - last_t > 1.0:
            filtered.append(b)
            last_t = b["time_sec"]

    return filtered[:10]


# ──────────────────────────────────────────────
# 피로도 분석
# ──────────────────────────────────────────────
def _analyze_fatigue(seg_data: list[dict]) -> dict | None:
    """
    전반부 vs 후반부 세그먼트의 Jitter/HNR 비교 → 피로도 판정.
    세그먼트 4개 이상일 때만 의미있음.
    """
    if len(seg_data) < 4:
        return None

    mid = len(seg_data) // 2
    first_half  = seg_data[:mid]
    second_half = seg_data[mid:]

    def avg(segs, key):
        vals = [s[key] for s in segs if s.get(key, 0) > 0]
        return float(np.mean(vals)) if vals else 0.0

    j1, j2 = avg(first_half, "jitter"),  avg(second_half, "jitter")
    h1, h2 = avg(first_half, "hnr"),     avg(second_half, "hnr")

    dj = round(j2 - j1, 4)
    dh = round(h2 - h1, 2)

    if dj > 0.2 or dh < -1.5:
        verdict = "피로" if (dj > 0.3 or dh < -2.5) else "경미한 피로"
    elif dj < -0.1 and dh > 0.5:
        verdict = "워밍업됨"
    else:
        verdict = "안정"

    return {
        "jitter_first":  round(j1, 4),
        "jitter_second": round(j2, 4),
        "hnr_first":     round(h1, 2),
        "hnr_second":    round(h2, 2),
        "jitter_delta":  dj,
        "hnr_delta":     dh,
        "verdict":       verdict,
    }


# ──────────────────────────────────────────────
# 호흡 패턴 분석
# ──────────────────────────────────────────────
def _analyze_breath_pattern(voiced_flag, frame_times) -> dict | None:
    """
    0.3~2.0초 무성 구간을 호흡으로 판정.
    """
    MIN_BREATH = 0.25
    MAX_BREATH = 2.0

    breaths = []
    in_gap = False
    gap_start = 0.0

    for t, v in zip(frame_times, voiced_flag):
        if not bool(v):
            if not in_gap:
                in_gap = True
                gap_start = float(t)
        else:
            if in_gap:
                dur = float(t) - gap_start
                if MIN_BREATH <= dur <= MAX_BREATH:
                    breaths.append({"time_sec": round(gap_start, 2), "duration_sec": round(dur, 2)})
                in_gap = False

    if not breaths:
        return None

    # 프레이즈 길이 계산
    phrase_lens = []
    for i in range(1, len(breaths)):
        gap = breaths[i]["time_sec"] - (breaths[i-1]["time_sec"] + breaths[i-1]["duration_sec"])
        if gap > 0:
            phrase_lens.append(gap)

    avg_phrase = round(float(np.mean(phrase_lens)), 1) if phrase_lens else 0.0

    # 짧은 프레이즈(<3초) 사이의 호흡 = 중간 호흡 (호흡 지지 부족 신호)
    mid_phrase_count = sum(1 for p in phrase_lens if 0 < p < 3.0)

    return {
        "count":             len(breaths),
        "avg_phrase_sec":    avg_phrase,
        "mid_phrase_count":  mid_phrase_count,
        "breaths":           breaths[:8],
    }


# ──────────────────────────────────────────────
# 비브라토 분석
# ──────────────────────────────────────────────
def _analyze_vibrato(f0, voiced_flag, frame_times, held_segments) -> dict | None:
    """
    held note 구간 f0에서 비브라토 분석.
    비브라토: 4~8Hz 주기의 f0 진동.
    """
    VIBRATO_MIN_HZ  = 4.0
    VIBRATO_MAX_HZ  = 8.0
    VIBRATO_MIN_EXT = 0.08   # 최소 0.08반음 진동폭 이상이어야 비브라토로 판정

    # hop_length/sr 계산 (프레임 간격)
    if len(frame_times) < 2:
        return None
    dt = float(frame_times[1] - frame_times[0])  # 초 단위

    rates, extents, vibrato_segs = [], [], 0

    for start, end, _ in held_segments:
        # 해당 구간 f0 추출
        mask = (frame_times >= start) & (frame_times <= end)
        seg_f0 = np.array([float(f0[i]) for i in range(len(f0))
                           if mask[i] and bool(voiced_flag[i]) and not np.isnan(float(f0[i]))])

        if len(seg_f0) < 16:   # FFT 최소 길이
            continue

        median_f0 = float(np.median(seg_f0))
        if median_f0 <= 0:
            continue

        # 반음 단위 편차
        semitones = 12 * np.log2(seg_f0 / median_f0)
        semitones -= semitones.mean()

        # FFT
        n = len(semitones)
        fft_mag = np.abs(np.fft.rfft(semitones))
        freqs   = np.fft.rfftfreq(n, d=dt)

        vib_mask = (freqs >= VIBRATO_MIN_HZ) & (freqs <= VIBRATO_MAX_HZ)
        if not vib_mask.any():
            continue

        peak_idx  = np.argmax(fft_mag[vib_mask])
        vib_freqs = freqs[vib_mask]
        vib_mags  = fft_mag[vib_mask]

        rate = float(vib_freqs[peak_idx])
        extent = float(vib_mags[peak_idx]) / n * 2   # 반음 진폭

        if extent >= VIBRATO_MIN_EXT:
            rates.append(rate)
            extents.append(extent)
            vibrato_segs += 1

    if not rates:
        return {
            "has_vibrato":      False,
            "rate_hz":          0.0,
            "extent_semitones": 0.0,
            "coverage_pct":     0,
        }

    coverage = round(vibrato_segs / max(len(held_segments), 1) * 100)
    return {
        "has_vibrato":      True,
        "rate_hz":          round(float(np.mean(rates)), 2),
        "extent_semitones": round(float(np.mean(extents)), 3),
        "coverage_pct":     coverage,
    }


# ──────────────────────────────────────────────
# problem_spots 빌드
# ──────────────────────────────────────────────
def _build_problem_spots(
    seg_data: list[dict],
    register_breaks: list[dict],
    nasal_spots: list[dict],
) -> list[dict]:
    """
    Jitter/HNR 기반 + 성구 전환 + 비음 경향을 합쳐 시간 순 정렬, 최대 10개 반환.
    """
    spots = []

    # 1. Jitter >= 1.5% (노래 모드 held note)
    for d in seg_data:
        j = d.get("jitter", 0.0)
        if j >= 1.5:
            severity = "위험" if j >= 2.0 else "경고"
            note = _hz_to_note(d.get("f0_hz", 0))
            spots.append({
                "time_sec": round(d.get("start_sec", 0.0), 2),
                "type": "jitter",
                "severity": severity,
                "detail": f"Jitter {j:.2f}% — {note} 부근",
            })

    # 2. HNR < 16.0dB (노래 모드 held note)
    for d in seg_data:
        h = d.get("hnr", 99.0)
        if h < 16.0:
            note = _hz_to_note(d.get("f0_hz", 0))
            spots.append({
                "time_sec": round(d.get("start_sec", 0.0), 2),
                "type": "hnr",
                "severity": "경고",
                "detail": f"탁함 HNR {h:.1f}dB — {note} 부근",
            })

    # 3. 성구 전환
    for b in register_breaks:
        spots.append({
            "time_sec": b["time_sec"],
            "type": "register_break",
            "severity": "경고",
            "detail": f"성구 전환 ({b['direction']}) {b['from_note']}→{b['to_note']}",
        })

    # 4. 비음 경향
    for n in nasal_spots:
        spots.append({
            "time_sec": n["time_sec"],
            "type": "nasal",
            "severity": "참고",
            "detail": f"비음 경향 ({n['duration_sec']:.1f}초 지속)",
        })

    # 시간 순 정렬, 최대 10개
    spots.sort(key=lambda x: x["time_sec"])
    return spots[:10]


# ──────────────────────────────────────────────
# WAV 구간 추출
# ──────────────────────────────────────────────
def _extract_segment_wav(wav_path: str, start_sec: float, end_sec: float) -> str:
    """WAV에서 특정 구간 잘라 임시 파일로 반환."""
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(wav_path)
    seg = audio[int(start_sec * 1000) : int(end_sec * 1000)]
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    seg.export(tmp.name, format="wav")
    return tmp.name


# ──────────────────────────────────────────────
# 베이스라인 분석 (≤ 30초)
# ──────────────────────────────────────────────
def _analyze_baseline(wav_path: str) -> dict:
    result = dict(EMPTY_RESULT)
    result["mode"] = "baseline"

    try:
        metrics = _parselmouth_analyze(wav_path)
        filtered, err = _apply_outlier_filter([metrics], 1)

        if filtered is None:
            result["error_msg"] = err
            return result

        result.update(filtered)
        result["valid"] = True

    except Exception:
        result["error_msg"] = "베이스라인 분석 중 오류가 발생했습니다."
        result["valid"] = False
        return result

    # 추가 분석 (실패해도 valid=True 유지)
    try:
        f0, voiced_flag, voiced_prob, frame_times, y, sr = _run_pyin(wav_path)
        register_breaks = _detect_register_breaks(f0, voiced_flag, frame_times)
        nasal_spots = _estimate_nasal_spots(y, sr)
        # baseline은 seg_data=[] → Jitter/HNR 기반 spot 없음
        result["problem_spots"] = _build_problem_spots([], register_breaks, nasal_spots)
    except Exception:
        result["problem_spots"] = []
        f0 = voiced_flag = voiced_prob = frame_times = None

    try:
        if f0 is not None:
            result["voice_breaks"]   = _detect_voice_breaks(f0, voiced_flag, voiced_prob, frame_times)
            result["breath_pattern"] = _analyze_breath_pattern(voiced_flag, frame_times)
    except Exception:
        pass

    try:
        if f0 is not None:
            vf = _compute_voice_features(y, sr, f0, voiced_flag)
            result.update(vf)
    except Exception:
        pass

    return result


# ──────────────────────────────────────────────
# 노래 분석 (> 30초) — librosa pyin으로 held note 탐지
# ──────────────────────────────────────────────
def _analyze_song(wav_path: str) -> dict:
    result = dict(EMPTY_RESULT)
    result["mode"] = "song"

    try:
        # 1. pyin 한 번 실행 → f0, y, sr 재사용
        f0, voiced_flag, voiced_prob, frame_times, y, sr = _run_pyin(wav_path)

        # 2. held note 구간 추출
        held_segments = _extract_held_segments(f0, voiced_flag, frame_times)

        if not held_segments:
            result["error_msg"] = (
                "안정된 held note 구간을 탐지하지 못했습니다. "
                "1초 이상 일정한 음을 유지하는 구간이 필요합니다."
            )
            return result

        # 3. per-segment parselmouth 분석
        seg_data = []
        tmp_files = []

        for start, end, median_f0 in held_segments:
            seg_wav = _extract_segment_wav(wav_path, start, end)
            tmp_files.append(seg_wav)
            try:
                m = _parselmouth_analyze(seg_wav)
                m["f0_hz"] = median_f0
                m["start_sec"] = start
                seg_data.append(m)
            except Exception:
                pass  # 개별 구간 오류는 건너뜀

        # 임시 파일 정리
        for f in tmp_files:
            try:
                os.remove(f)
            except Exception:
                pass

        metrics_list = [{k: v for k, v in d.items() if k in ("jitter", "shimmer", "hnr", "f1", "f2")} for d in seg_data]
        filtered, err = _apply_outlier_filter(metrics_list, len(metrics_list))

        if filtered is None:
            result["error_msg"] = err
            result["held_note_count"] = len(held_segments)
            return result

        result.update(filtered)
        result["held_note_count"] = len(held_segments)
        result["valid"] = True

    except Exception:
        result["error_msg"] = "노래 분석 중 오류가 발생했습니다."
        result["valid"] = False
        return result

    # 4. 추가 분석 (실패해도 valid=True 유지)
    try:
        register_breaks = _detect_register_breaks(f0, voiced_flag, frame_times)
    except Exception:
        register_breaks = []

    try:
        nasal_spots = _estimate_nasal_spots(y, sr)
    except Exception:
        nasal_spots = []

    try:
        result["pitch_zone_stats"] = _compute_pitch_zone_stats(seg_data)
    except Exception:
        result["pitch_zone_stats"] = None

    try:
        f2_vals = [d["f2"] for d in seg_data if d.get("f2", 0) > 0]
        result["f2_std"] = round(float(np.std(f2_vals)), 1) if len(f2_vals) >= 2 else 0.0
    except Exception:
        result["f2_std"] = 0.0

    try:
        result["problem_spots"] = _build_problem_spots(seg_data, register_breaks, nasal_spots)
    except Exception:
        result["problem_spots"] = []

    try:
        result["voice_breaks"] = _detect_voice_breaks(f0, voiced_flag, voiced_prob, frame_times)
    except Exception:
        result["voice_breaks"] = []

    try:
        result["fatigue"] = _analyze_fatigue(seg_data)
    except Exception:
        result["fatigue"] = None

    try:
        result["breath_pattern"] = _analyze_breath_pattern(voiced_flag, frame_times)
    except Exception:
        result["breath_pattern"] = None

    try:
        result["vibrato"] = _analyze_vibrato(f0, voiced_flag, frame_times, held_segments)
    except Exception:
        result["vibrato"] = None

    try:
        vf = _compute_voice_features(y, sr, f0, voiced_flag)
        result.update(vf)
    except Exception:
        pass

    return result


# ──────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────
def analyze(file_path: str) -> dict:
    """
    FLAC/WAV/MP3 등 오디오 파일을 받아 분석 결과 dict 반환.
    /tmp 파일은 함수 내부에서 모두 정리한다.
    """
    result = dict(EMPTY_RESULT)
    wav_path = None
    trimmed_path = None

    try:
        # 1. WAV 변환
        wav_path = _convert_to_wav(file_path)

        # 2. 앞뒤 무음 trim
        trimmed_path = _trim_silence(wav_path)

        # 3. 길이 판별
        duration = _get_duration_sec(trimmed_path)

        # 4. 모드별 분석
        if duration <= BASELINE_MAX_SEC:
            result = _analyze_baseline(trimmed_path)
        else:
            result = _analyze_song(trimmed_path)

    except Exception:
        result["error_msg"] = f"파일 처리 중 오류: {traceback.format_exc(limit=2)}"
        result["valid"] = False

    finally:
        # 임시 파일 정리
        for p in [wav_path, trimmed_path]:
            if p and p != file_path:
                try:
                    os.remove(p)
                except Exception:
                    pass

    return result
