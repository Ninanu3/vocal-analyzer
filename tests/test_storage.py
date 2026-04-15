"""
tests/test_storage.py
CSV 저장소 단위 테스트 (외부 API 없이 실행 가능).
"""
import os
import sys
import tempfile
import csv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import configparser
from core.storage import get_storage, compute_personal_avg


def _make_csv_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg["storage"] = {"type": "csv", "csv_path": path, "sheets_id": ""}
    return cfg


def test_csv_save_and_read():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        tmp_path = f.name

    try:
        cfg     = _make_csv_config(tmp_path)
        storage = get_storage(cfg)

        result = {
            "mode": "baseline", "jitter": 0.82, "shimmer": 2.91,
            "hnr": 22.4, "f1": 580.0, "f2": 1240.0, "held_note_count": 0,
        }
        storage.save("user_001", result)
        storage.save("user_001", {**result, "jitter": 0.90})

        sessions = storage.get_recent("user_001", 5)
        assert len(sessions) == 2
        assert sessions[0]["jitter"] == 0.82
        assert sessions[1]["jitter"] == 0.90
        print("✅ test_csv_save_and_read 통과")
    finally:
        os.remove(tmp_path)


def test_csv_user_isolation():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        tmp_path = f.name

    try:
        cfg     = _make_csv_config(tmp_path)
        storage = get_storage(cfg)

        r = {"mode": "baseline", "jitter": 1.0, "shimmer": 3.0,
             "hnr": 20.0, "f1": 500.0, "f2": 1100.0, "held_note_count": 0}
        storage.save("user_A", r)
        storage.save("user_B", {**r, "jitter": 0.5})

        a_sessions = storage.get_recent("user_A", 5)
        b_sessions = storage.get_recent("user_B", 5)
        assert len(a_sessions) == 1
        assert len(b_sessions) == 1
        assert a_sessions[0]["jitter"] == 1.0
        assert b_sessions[0]["jitter"] == 0.5
        print("✅ test_csv_user_isolation 통과")
    finally:
        os.remove(tmp_path)


def test_personal_avg_needs_4():
    sessions_3 = [
        {"jitter": 0.8, "shimmer": 2.5, "hnr": 22.0},
        {"jitter": 0.9, "shimmer": 2.7, "hnr": 21.5},
        {"jitter": 0.7, "shimmer": 2.3, "hnr": 22.5},
    ]
    assert compute_personal_avg(sessions_3) is None
    print("✅ test_personal_avg_needs_4 통과")


def test_personal_avg_computed():
    sessions_4 = [
        {"jitter": 0.8, "shimmer": 2.5, "hnr": 22.0},
        {"jitter": 0.9, "shimmer": 2.7, "hnr": 21.5},
        {"jitter": 0.7, "shimmer": 2.3, "hnr": 22.5},
        {"jitter": 1.0, "shimmer": 3.0, "hnr": 21.0},
    ]
    avg = compute_personal_avg(sessions_4)
    assert avg is not None
    assert abs(avg["jitter"] - 0.85) < 0.01
    print("✅ test_personal_avg_computed 통과")


if __name__ == "__main__":
    tests = [
        test_csv_save_and_read,
        test_csv_user_isolation,
        test_personal_avg_needs_4,
        test_personal_avg_computed,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__} 실패: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    print(f"\n결과: {passed}/{len(tests)} 통과" + (" 🎉" if failed == 0 else f"  ({failed}개 실패)"))
    sys.exit(0 if failed == 0 else 1)
