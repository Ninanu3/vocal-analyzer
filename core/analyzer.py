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

HELD_MIN_SEC       = 1.0    # held note 최소 길이 (초)
HELD_F0_STD_MAX    = 5.0    # held note 판정용 f0 표준편차 최대 (Hz)

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
    librosa.pyin으로 f0, voiced_flag, frame_times, y, sr 반환.
    반환: (f0, voiced_flag, frame_times, y, sr)
    """
    import librosa

    y, sr = librosa.load(wav_path, sr=None, mono=True)
    hop_length = 512
    frame_length = 2048

    f0, voiced_flag, _ = librosa.pyin(
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

    return f0, voiced_flag, frame_times, y, sr


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
            "jitter_avg":  round(float(np.mean([d["jitter"]  for d in items])), 4),
            "shimmer_avg": round(float(np.mean([d["shimmer"] for d in items])), 4),
            "hnr_avg":     round(float(np.mean([d["hnr"]     for d in items])), 2),
            "count":       len(items),
            "note_range":  f"{_hz_to_note(min(f0_list))}~{_hz_to_note(max(f0_list))}",
        }

    return result


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
        f0, voiced_flag, frame_times, y, sr = _run_pyin(wav_path)
        register_breaks = _detect_register_breaks(f0, voiced_flag, frame_times)
        nasal_spots = _estimate_nasal_spots(y, sr)
        # baseline은 seg_data=[] → Jitter/HNR 기반 spot 없음
        result["problem_spots"] = _build_problem_spots([], register_breaks, nasal_spots)
    except Exception:
        result["problem_spots"] = []

    return result


# ──────────────────────────────────────────────
# 노래 분석 (> 30초) — librosa pyin으로 held note 탐지
# ──────────────────────────────────────────────
def _analyze_song(wav_path: str) -> dict:
    result = dict(EMPTY_RESULT)
    result["mode"] = "song"

    try:
        # 1. pyin 한 번 실행 → f0, y, sr 재사용
        f0, voiced_flag, frame_times, y, sr = _run_pyin(wav_path)

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
        result["problem_spots"] = _build_problem_spots(seg_data, register_breaks, nasal_spots)
    except Exception:
        result["problem_spots"] = []

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
