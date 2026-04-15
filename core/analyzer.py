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
    "error_msg":        str | None
}
"""

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
}


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


# ──────────────────────────────────────────────
# 노래 분석 (> 30초) — librosa pyin으로 held note 탐지
# ──────────────────────────────────────────────
def _detect_held_notes(wav_path: str) -> list[tuple[float, float]]:
    """
    librosa.pyin으로 frame별 f0, voiced_flag 추출.
    안정된 held note 구간 리스트 [(start_sec, end_sec), ...] 반환.
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

    held_segments = []
    in_segment = False
    seg_start = 0.0
    seg_f0_vals = []

    for i, (t, voiced, f0_val) in enumerate(zip(frame_times, voiced_flag, f0)):
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
                    held_segments.append((seg_start, seg_end))
                in_segment = False
                seg_f0_vals = []

    # 마지막 구간 처리
    if in_segment and len(seg_f0_vals) > 0:
        seg_end = frame_times[-1]
        duration = seg_end - seg_start
        if duration >= HELD_MIN_SEC and np.std(seg_f0_vals) < HELD_F0_STD_MAX:
            held_segments.append((seg_start, seg_end))

    return held_segments


def _extract_segment_wav(wav_path: str, start_sec: float, end_sec: float) -> str:
    """WAV에서 특정 구간 잘라 임시 파일로 반환."""
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(wav_path)
    seg = audio[int(start_sec * 1000) : int(end_sec * 1000)]
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    seg.export(tmp.name, format="wav")
    return tmp.name


def _analyze_song(wav_path: str) -> dict:
    result = dict(EMPTY_RESULT)
    result["mode"] = "song"

    try:
        held_segments = _detect_held_notes(wav_path)

        if not held_segments:
            result["error_msg"] = (
                "안정된 held note 구간을 탐지하지 못했습니다. "
                "1초 이상 일정한 음을 유지하는 구간이 필요합니다."
            )
            return result

        metrics_list = []
        tmp_files = []

        for start, end in held_segments:
            seg_wav = _extract_segment_wav(wav_path, start, end)
            tmp_files.append(seg_wav)
            try:
                m = _parselmouth_analyze(seg_wav)
                metrics_list.append(m)
            except Exception:
                pass  # 개별 구간 오류는 건너뜀

        # 임시 파일 정리
        for f in tmp_files:
            try:
                os.remove(f)
            except Exception:
                pass

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
