"""
tests/test_feedback.py
외부 라이브러리 없이 실행 가능한 피드백 로직 단위 테스트.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.feedback import build_message, build_history_message, _get_thresholds


# ──────────────────────────────────────────────
# 기준값 테스트
# ──────────────────────────────────────────────
def test_thresholds_남성_30대():
    t = _get_thresholds(30, "남")
    assert t["jitter_max"]  == 1.04
    assert t["shimmer_max"] == 3.81
    assert t["hnr_min"]     == 20.0
    print("✅ test_thresholds_남성_30대 통과")


def test_thresholds_여성_30대():
    t = _get_thresholds(30, "여")
    assert t["shimmer_max"] == 3.31
    assert t["hnr_min"]     == 21.0
    print("✅ test_thresholds_여성_30대 통과")


def test_thresholds_40대_여유_적용():
    t30 = _get_thresholds(39, "남")
    t40 = _get_thresholds(40, "남")
    assert t40["jitter_max"]  > t30["jitter_max"]
    assert t40["shimmer_max"] > t30["shimmer_max"]
    assert t40["hnr_min"]     < t30["hnr_min"]
    print("✅ test_thresholds_40대_여유_적용 통과")


# ──────────────────────────────────────────────
# 정상 결과 메시지
# ──────────────────────────────────────────────
def test_build_message_all_good():
    result = {
        "mode": "baseline", "valid": True,
        "jitter": 0.80, "shimmer": 2.50, "hnr": 22.0,
        "f1": 580.0, "f2": 1240.0, "held_note_count": 0,
        "error_msg": None,
    }
    msg = build_message(result, 30, "남")
    assert "✅" in msg
    assert "0.80%" in msg
    assert "22.0dB" in msg
    assert "SOVT" in msg
    print("✅ test_build_message_all_good 통과")


def test_build_message_jitter_over():
    result = {
        "mode": "baseline", "valid": True,
        "jitter": 1.60, "shimmer": 2.50, "hnr": 22.0,
        "f1": 580.0, "f2": 1240.0, "held_note_count": 0,
        "error_msg": None,
    }
    msg = build_message(result, 30, "남")
    assert "⚠️" in msg
    assert "SOVT" in msg
    print("✅ test_build_message_jitter_over 통과")


def test_build_message_invalid():
    result = {
        "mode": "baseline", "valid": False,
        "jitter": 0, "shimmer": 0, "hnr": 0,
        "f1": 0, "f2": 0, "held_note_count": 0,
        "error_msg": "재녹음 필요",
    }
    msg = build_message(result, 30, "남")
    assert "❌" in msg
    assert "재녹음 필요" in msg
    print("✅ test_build_message_invalid 통과")


def test_build_message_personal_avg():
    result = {
        "mode": "baseline", "valid": True,
        "jitter": 0.90, "shimmer": 2.80, "hnr": 21.5,
        "f1": 560.0, "f2": 1200.0, "held_note_count": 0,
        "error_msg": None,
    }
    personal_avg = {"jitter": 0.75, "shimmer": 2.60, "hnr": 22.0}
    msg = build_message(result, 30, "남", personal_avg=personal_avg)
    assert "개인 평균 대비" in msg
    print("✅ test_build_message_personal_avg 통과")


def test_build_message_song_mode():
    result = {
        "mode": "song", "valid": True,
        "jitter": 0.95, "shimmer": 3.00, "hnr": 20.5,
        "f1": 550.0, "f2": 1180.0, "held_note_count": 4,
        "error_msg": None,
    }
    baseline = {"valid": True, "jitter": 0.80, "shimmer": 2.50}
    msg = build_message(result, 30, "남", baseline_result=baseline)
    assert "노래 구간 분석" in msg
    assert "4개" in msg
    assert "베이스라인 대비" in msg
    print("✅ test_build_message_song_mode 통과")


# ──────────────────────────────────────────────
# 이력 메시지
# ──────────────────────────────────────────────
def test_build_history_empty():
    msg = build_history_message([])
    assert "이력이 없습니다" in msg
    print("✅ test_build_history_empty 통과")


def test_build_history_with_data():
    sessions = [
        {"timestamp": "2026-04-10 14:00:00", "mode": "baseline",
         "jitter": 0.82, "shimmer": 2.91, "hnr": 22.4},
        {"timestamp": "2026-04-12 15:00:00", "mode": "song",
         "jitter": 1.10, "shimmer": 3.20, "hnr": 19.8},
    ]
    msg = build_history_message(sessions)
    assert "2026-04-10" in msg
    assert "0.82%" in msg
    print("✅ test_build_history_with_data 통과")


# ──────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        test_thresholds_남성_30대,
        test_thresholds_여성_30대,
        test_thresholds_40대_여유_적용,
        test_build_message_all_good,
        test_build_message_jitter_over,
        test_build_message_invalid,
        test_build_message_personal_avg,
        test_build_message_song_mode,
        test_build_history_empty,
        test_build_history_with_data,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__} 실패: {e}")
            failed += 1

    print(f"\n결과: {passed}/{len(tests)} 통과" + (" 🎉" if failed == 0 else f"  ({failed}개 실패)"))
    sys.exit(0 if failed == 0 else 1)
