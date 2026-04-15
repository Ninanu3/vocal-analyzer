"""
modes/cloud_mode.py
===================
클라우드 방식 — GCP Cloud Functions용 파일 생성 + 배포 안내.

실제 분석은 GCP 위에서 돌아가므로,
이 파일의 역할은:
  1. deploy/ 폴더에 Cloud Function 소스 생성
  2. deploy.bat 생성
  3. 사용자에게 배포 순서 안내
"""

import configparser
import os
import textwrap
import tkinter as tk
from tkinter import messagebox

# ──────────────────────────────────────────────
# Cloud Function 메인 핸들러 (배포될 코드)
# ──────────────────────────────────────────────
_CF_MAIN_PY = '''\
"""
Cloud Function 진입점 — Telegram Webhook 수신
"""
import os
import json
import tempfile
import requests
import functions_framework

from core.analyzer  import analyze
from core.feedback  import build_message
from core.storage   import get_storage
import configparser

TOKEN  = os.environ["TELEGRAM_TOKEN"]
BASE   = f"https://api.telegram.org/bot{TOKEN}"


def _send(chat_id, text):
    requests.post(f"{BASE}/sendMessage", json={"chat_id": chat_id, "text": text})


def _download_file(file_id: str) -> str:
    r = requests.get(f"{BASE}/getFile", params={"file_id": file_id}).json()
    file_path = r["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    ext = os.path.splitext(file_path)[1] or ".flac"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False, dir="/tmp")
    tmp.write(requests.get(url).content)
    tmp.close()
    return tmp.name


@functions_framework.http
def webhook(request):
    body = request.get_json(silent=True)
    if not body:
        return "ok", 200

    msg = body.get("message") or body.get("edited_message")
    if not msg:
        return "ok", 200

    chat_id = str(msg["chat"]["id"])
    text    = msg.get("text", "")

    # 파일 수신
    audio = msg.get("audio") or msg.get("document") or msg.get("voice")
    if audio:
        file_size = audio.get("file_size", 0)
        if file_size > 20 * 1024 * 1024:
            _send(chat_id, "❌ 파일이 20MB를 초과합니다. 더 짧은 구간으로 나눠서 전송해 주세요.")
            return "ok", 200

        _send(chat_id, "⏳ 분석 중입니다...")
        tmp_path = None
        try:
            tmp_path = _download_file(audio["file_id"])
            result   = analyze(tmp_path)

            cfg = configparser.ConfigParser()
            cfg["user"]    = {"age": os.environ.get("USER_AGE","30"),
                               "gender": os.environ.get("USER_GENDER","남")}
            cfg["storage"] = {"type": os.environ.get("STORAGE_TYPE","csv"),
                               "sheets_id": os.environ.get("SHEETS_ID",""),
                               "csv_path": "/tmp/vocal_log.csv"}
            storage = get_storage(cfg)
            sessions = storage.get_all(chat_id)

            from core.storage  import compute_personal_avg
            from core.feedback import build_message
            personal_avg = compute_personal_avg(sessions)
            msg_text = build_message(result,
                                     int(cfg["user"]["age"]),
                                     cfg["user"]["gender"],
                                     personal_avg)
            storage.save(chat_id, result)
            _send(chat_id, msg_text)

        except Exception as e:
            _send(chat_id, f"❌ 오류가 발생했습니다.\\n{e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        return "ok", 200

    # 텍스트 명령
    if text.startswith("/start"):
        _send(chat_id, "🎤 발성 분석 봇에 오신 걸 환영합니다!\\nFLAC 또는 WAV 파일을 전송하면 자동으로 분석해 드립니다.")
    elif text.startswith("/history"):
        cfg = configparser.ConfigParser()
        cfg["storage"] = {"type": os.environ.get("STORAGE_TYPE","csv"),
                           "sheets_id": os.environ.get("SHEETS_ID",""),
                           "csv_path": "/tmp/vocal_log.csv"}
        storage  = get_storage(cfg)
        sessions = storage.get_recent(chat_id, 5)
        from core.feedback import build_history_message
        _send(chat_id, build_history_message(sessions))

    return "ok", 200
'''

_CF_REQUIREMENTS = """\
functions-framework==3.*
python-telegram-bot==20.*
google-cloud-firestore==2.*
google-api-python-client==2.*
google-auth==2.*
praat-parselmouth==0.4.*
librosa==0.10.*
pydub==0.25.*
numpy==1.*
requests==2.*
soundfile==0.12.*
"""

_DEPLOY_BAT = """\
@echo off
echo === GCP Cloud Function 배포 시작 ===

set /p TOKEN=Telegram Bot Token 입력:
set /p PROJECT=GCP Project ID 입력:
set /p SHEETS=Google Sheets ID (없으면 Enter):
set /p AGE=사용자 나이 입력:
set /p GENDER=사용자 성별 (남/여) 입력:

if "%SHEETS%"=="" (
    set STORAGE_TYPE=csv
) else (
    set STORAGE_TYPE=sheets
)

gcloud config set project %PROJECT%

gcloud functions deploy vocal-analyzer ^
  --runtime python311 ^
  --trigger-http ^
  --allow-unauthenticated ^
  --memory 1GB ^
  --timeout 120s ^
  --region asia-northeast3 ^
  --source deploy ^
  --entry-point webhook ^
  --set-env-vars TELEGRAM_TOKEN=%TOKEN%,SHEETS_ID=%SHEETS%,GCP_PROJECT_ID=%PROJECT%,STORAGE_TYPE=%STORAGE_TYPE%,USER_AGE=%AGE%,USER_GENDER=%GENDER%

echo.
echo === Webhook 등록 중 ===
for /f "tokens=*" %%i in ('gcloud functions describe vocal-analyzer --region asia-northeast3 --format="value(httpsTrigger.url)"') do set FUNC_URL=%%i
curl "https://api.telegram.org/bot%TOKEN%/setWebhook?url=%FUNC_URL%"

echo.
echo === 배포 완료 ===
echo Function URL: %FUNC_URL%
pause
"""


def run_cloud_mode(config: configparser.ConfigParser):
    """
    deploy/ 폴더에 Cloud Function 소스 생성 후 안내 다이얼로그 표시.
    """
    deploy_dir = os.path.join(os.getcwd(), "deploy")
    core_dir   = os.path.join(deploy_dir, "core")
    os.makedirs(core_dir, exist_ok=True)

    # Cloud Function 메인 파일
    with open(os.path.join(deploy_dir, "main.py"), "w", encoding="utf-8") as f:
        f.write(_CF_MAIN_PY)

    with open(os.path.join(deploy_dir, "requirements.txt"), "w", encoding="utf-8") as f:
        f.write(_CF_REQUIREMENTS)

    # core/ 모듈 복사
    import shutil
    src_core = os.path.join(os.getcwd(), "core")
    for fname in ["analyzer.py", "feedback.py", "storage.py", "__init__.py"]:
        src = os.path.join(src_core, fname)
        dst = os.path.join(core_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)

    # 배포 스크립트
    with open("deploy.bat", "w", encoding="utf-8") as f:
        f.write(_DEPLOY_BAT)

    # 안내 창
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        "클라우드 배포 준비 완료",
        textwrap.dedent("""\
            deploy/ 폴더와 deploy.bat 파일이 생성되었습니다.

            배포 순서:
            1. gcloud CLI가 설치되어 있어야 합니다.
               https://cloud.google.com/sdk/docs/install

            2. deploy.bat 를 더블클릭하면
               Telegram Token, GCP 정보를 입력받아
               자동으로 배포 + Webhook 등록합니다.

            3. 배포 완료 후 Telegram에서 봇에 파일을 전송하면
               자동으로 분석 결과를 받을 수 있습니다.
        """),
    )
    root.destroy()
