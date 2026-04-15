"""
modes/polling_mode.py
=====================
폴링 방식 — python-telegram-bot 으로 Telegram 서버에 주기적으로 접속,
파일 수신 시 로컬에서 분석 후 결과 전송.
이 스크립트가 실행 중인 동안만 작동.
"""

import configparser
import logging
import os
import tempfile

import requests

from core.analyzer  import analyze
from core.feedback  import build_message, build_history_message
from core.storage   import get_storage, compute_personal_avg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def run_polling_mode(config: configparser.ConfigParser):
    from telegram import Update
    from telegram.ext import (
        Application, CommandHandler, MessageHandler,
        ContextTypes, filters,
    )

    token   = config.get("telegram", "bot_token", fallback="").strip()
    age     = config.getint("user", "age", fallback=30)
    gender  = config.get("user", "gender", fallback="남")
    storage = get_storage(config)

    feedback_modes = config.get("mode", "feedback", fallback="local").split("+")
    send_telegram  = "telegram" in feedback_modes
    show_local     = "local"    in feedback_modes

    if not token:
        raise ValueError("config.ini에 telegram bot_token이 설정되지 않았습니다.")

    # ── 핸들러 ──────────────────────────────────
    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎤 발성 분석 봇에 오신 걸 환영합니다!\n"
            "FLAC 또는 WAV 파일을 전송하면 자동으로 분석해 드립니다.\n\n"
            "/history — 최근 분석 이력\n"
            "/reset   — 설정 초기화"
        )

    async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id  = str(update.effective_chat.id)
        sessions = storage.get_recent(chat_id, 5)
        await update.message.reply_text(build_history_message(sessions))

    async def handle_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        msg     = update.message

        audio = msg.audio or msg.document or msg.voice
        if not audio:
            return

        # 파일 크기 확인
        if hasattr(audio, "file_size") and audio.file_size and audio.file_size > 20 * 1024 * 1024:
            await msg.reply_text("❌ 파일이 20MB를 초과합니다. 더 짧은 구간으로 나눠서 전송해 주세요.")
            return

        await msg.reply_text("⏳ 분석 중입니다...")

        tmp_path = None
        try:
            # 파일 다운로드
            tg_file = await audio.get_file()
            ext = os.path.splitext(tg_file.file_path)[1] or ".flac"
            fd, tmp_path = tempfile.mkstemp(suffix=ext)
            os.close(fd)
            await tg_file.download_to_drive(tmp_path)

            # 분석
            result = analyze(tmp_path)

            # 개인 평균
            sessions     = storage.get_all(chat_id)
            personal_avg = compute_personal_avg(sessions)

            # 베이스라인 비교 (노래 모드 시)
            baseline = None
            if result.get("mode") == "song":
                base_sessions = [s for s in sessions if s.get("mode") == "baseline"]
                if base_sessions:
                    last = base_sessions[-1]
                    baseline = {"valid": True, "jitter": last["jitter"], "shimmer": last["shimmer"]}

            feedback_text = build_message(result, age, gender, personal_avg, baseline)

            # 텔레그램 응답
            if send_telegram:
                await msg.reply_text(feedback_text)

            # 로컬 화면
            if show_local:
                from ui.display import show_result
                show_result(result, feedback_text)

            # 저장
            storage.save(chat_id, result)

        except Exception as e:
            log.exception("분석 오류")
            await msg.reply_text(f"❌ 오류가 발생했습니다.\n{e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    # ── 앱 구성 및 실행 ──────────────────────────
    app = (
        Application.builder()
        .token(token)
        .build()
    )
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(
        MessageHandler(
            filters.AUDIO | filters.Document.ALL | filters.VOICE,
            handle_audio,
        )
    )

    log.info("폴링 모드 시작 — 봇이 실행 중입니다. 종료: Ctrl+C")
    app.run_polling(allowed_updates=["message"])
