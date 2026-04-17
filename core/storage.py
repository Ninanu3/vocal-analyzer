"""
core/storage.py
===============
분석 결과 저장 추상화.

config.ini [storage] type = sheets  → Google Sheets에 기록
config.ini [storage] type = csv     → 로컬 CSV 파일에 기록

두 방식 모두 동일한 save() / get_recent() 인터페이스 사용.
"""

import configparser
import csv
import json
import os
from datetime import datetime
from pathlib import Path

# CSV 헤더 (Sheets도 동일한 순서)
_HEADERS = [
    "chat_id", "date", "mode",
    "jitter", "shimmer", "hnr", "f1", "f2", "held_note_count",
    "zones_json",         # pitch_zone_stats JSON  (col 10, index 9)
    "spectral_centroid",  # 음색 무게 중심 Hz      (col 11, index 10)
    "f0_mean",            # 평균 기본주파수 Hz      (col 12, index 11)
]


def _parse_zones(s: str) -> dict | None:
    """JSON 문자열 → dict. 실패 시 None."""
    try:
        if not s:
            return None
        d = json.loads(s)
        return d if isinstance(d, dict) and d else None
    except Exception:
        return None


# ──────────────────────────────────────────────
# Google Sheets 백엔드
# ──────────────────────────────────────────────
class _SheetsStorage:
    def __init__(self, sheets_id: str):
        self.sheets_id = sheets_id
        self._service = None

    def _get_service(self):
        if self._service is None:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]

            if os.path.exists(creds_path):
                creds = service_account.Credentials.from_service_account_file(
                    creds_path, scopes=scopes
                )
            else:
                # Application Default Credentials (GCP 환경)
                import google.auth
                creds, _ = google.auth.default(scopes=scopes)

            self._service = build("sheets", "v4", credentials=creds)
        return self._service

    def _ensure_header(self):
        """헤더 행이 없으면 추가."""
        svc = self._get_service()
        res = (
            svc.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheets_id, range="sessions!A1:L1")
            .execute()
        )
        if not res.get("values"):
            svc.spreadsheets().values().append(
                spreadsheetId=self.sheets_id,
                range="sessions!A1",
                valueInputOption="RAW",
                body={"values": [_HEADERS]},
            ).execute()

    def save(self, chat_id: str, result: dict):
        self._ensure_header()
        svc = self._get_service()
        row = [
            str(chat_id),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            result.get("mode", ""),
            result.get("jitter", 0),
            result.get("shimmer", 0),
            result.get("hnr", 0),
            result.get("f1", 0),
            result.get("f2", 0),
            result.get("held_note_count", 0),
            json.dumps(result.get("pitch_zone_stats") or {}, ensure_ascii=False),
            result.get("spectral_centroid", 0),
            result.get("f0_mean", 0),
        ]
        svc.spreadsheets().values().append(
            spreadsheetId=self.sheets_id,
            range="sessions!A1",
            valueInputOption="RAW",
            body={"values": [row]},
        ).execute()

    def get_recent(self, chat_id: str, n: int = 5) -> list[dict]:
        svc = self._get_service()
        res = (
            svc.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheets_id, range="sessions!A2:L")
            .execute()
        )
        rows = res.get("values", [])
        # chat_id 필터 후 최근 n개
        matched = [r for r in rows if len(r) >= 9 and r[0] == str(chat_id)]
        recent = matched[-n:]
        return [
            {
                "chat_id":           r[0],
                "timestamp":         r[1],
                "mode":              r[2],
                "jitter":            float(r[3]),
                "shimmer":           float(r[4]),
                "hnr":               float(r[5]),
                "f1":                float(r[6]),
                "f2":                float(r[7]),
                "held_note_count":   int(r[8]) if r[8] else 0,
                "pitch_zone_stats":  _parse_zones(r[9] if len(r) > 9 else ""),
                "spectral_centroid": float(r[10]) if len(r) > 10 and r[10] else 0.0,
                "f0_mean":           float(r[11]) if len(r) > 11 and r[11] else 0.0,
            }
            for r in recent
        ]

    def get_all(self, chat_id: str) -> list[dict]:
        return self.get_recent(chat_id, n=99999)


# ──────────────────────────────────────────────
# CSV 백엔드
# ──────────────────────────────────────────────
class _CsvStorage:
    def __init__(self, csv_path: str):
        self.csv_path = Path(csv_path)
        self._ensure_file()

    def _ensure_file(self):
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        # 파일이 없거나 비어있으면 헤더 작성
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(_HEADERS)

    def save(self, chat_id: str, result: dict):
        row = [
            str(chat_id),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            result.get("mode", ""),
            result.get("jitter", 0),
            result.get("shimmer", 0),
            result.get("hnr", 0),
            result.get("f1", 0),
            result.get("f2", 0),
            result.get("held_note_count", 0),
            json.dumps(result.get("pitch_zone_stats") or {}, ensure_ascii=False),
            result.get("spectral_centroid", 0),
            result.get("f0_mean", 0),
        ]
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

    def _read_all(self) -> list[dict]:
        rows = []
        with open(self.csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
        return rows

    def get_recent(self, chat_id: str, n: int = 5) -> list[dict]:
        all_rows = self._read_all()
        matched = [r for r in all_rows if r.get("chat_id") == str(chat_id)]
        recent = matched[-n:]
        return [
            {
                "chat_id":           r["chat_id"],
                "timestamp":         r["date"],
                "mode":              r["mode"],
                "jitter":            float(r["jitter"]),
                "shimmer":           float(r["shimmer"]),
                "hnr":               float(r["hnr"]),
                "f1":                float(r["f1"]),
                "f2":                float(r["f2"]),
                "held_note_count":   int(r["held_note_count"]) if r["held_note_count"] else 0,
                "pitch_zone_stats":  _parse_zones(r.get("zones_json", "")),
                "spectral_centroid": float(r["spectral_centroid"]) if r.get("spectral_centroid") else 0.0,
                "f0_mean":           float(r["f0_mean"]) if r.get("f0_mean") else 0.0,
            }
            for r in recent
        ]

    def get_all(self, chat_id: str) -> list[dict]:
        return self.get_recent(chat_id, n=99999)


# ──────────────────────────────────────────────
# 개인 평균 계산 헬퍼
# ──────────────────────────────────────────────
def compute_personal_avg(sessions: list[dict]) -> dict | None:
    """세션 4개 이상일 때 평균 반환, 미만이면 None."""
    if len(sessions) < 4:
        return None

    import numpy as np
    valid = [s for s in sessions if s.get("jitter") is not None]
    if not valid:
        return None

    return {
        "jitter":  round(float(np.mean([s["jitter"]  for s in valid])), 4),
        "shimmer": round(float(np.mean([s["shimmer"] for s in valid])), 4),
        "hnr":     round(float(np.mean([s["hnr"]     for s in valid])), 2),
    }


# ──────────────────────────────────────────────
# 팩토리 함수 (외부에서 사용하는 유일한 진입점)
# ──────────────────────────────────────────────
def get_storage(config: configparser.ConfigParser):
    """
    config.ini를 읽어 적절한 storage 인스턴스 반환.
    """
    storage_type = config.get("storage", "type", fallback="csv").lower()
    if storage_type == "sheets":
        sheets_id = config.get("storage", "sheets_id", fallback="").strip()
        if not sheets_id:
            raise ValueError("sheets_id가 config.ini에 설정되지 않았습니다.")
        return _SheetsStorage(sheets_id)
    else:
        csv_path = config.get("storage", "csv_path", fallback="vocal_log.csv")
        return _CsvStorage(csv_path)
