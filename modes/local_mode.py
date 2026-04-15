"""
modes/local_mode.py
===================
로컬 전용 — watchdog으로 지정 폴더 감시.
새 오디오 파일 감지 시 자동 분석 → 로컬 화면 표시.
"""

import configparser
import logging
import os
import time

from core.analyzer  import analyze
from core.feedback  import build_message, build_history_message
from core.storage   import get_storage, compute_personal_avg

log = logging.getLogger(__name__)

AUDIO_EXTS = {".flac", ".wav", ".mp3", ".m4a", ".ogg", ".aac"}


def _is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


def run_local_mode(config: configparser.ConfigParser):
    from watchdog.observers import Observer
    from watchdog.events    import FileSystemEventHandler

    watch_folder = config.get("local", "watch_folder", fallback="").strip()
    age          = config.getint("user", "age", fallback=30)
    gender       = config.get("user", "gender", fallback="남")
    storage      = get_storage(config)

    # LOCAL_USER_ID: 로컬 모드는 단일 사용자이므로 고정 ID 사용
    LOCAL_ID = "local_user"

    if not watch_folder or not os.path.isdir(watch_folder):
        from ui.display import show_error
        show_error(
            "폴더 오류",
            f"감시 폴더를 찾을 수 없습니다:\n{watch_folder}\n\n"
            "config.ini의 [local] watch_folder 경로를 확인해 주세요."
        )
        return

    class AudioHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = event.src_path
            if not _is_audio(path):
                return

            # 파일이 완전히 쓰여질 때까지 잠깐 대기
            time.sleep(0.5)

            log.info(f"새 파일 감지: {path}")
            try:
                result       = analyze(path)
                sessions     = storage.get_all(LOCAL_ID)
                personal_avg = compute_personal_avg(sessions)

                baseline = None
                if result.get("mode") == "song":
                    base_sessions = [s for s in sessions if s.get("mode") == "baseline"]
                    if base_sessions:
                        last = base_sessions[-1]
                        baseline = {"valid": True, "jitter": last["jitter"], "shimmer": last["shimmer"]}

                feedback_text = build_message(result, age, gender, personal_avg, baseline)
                storage.save(LOCAL_ID, result)

                from ui.display import show_result
                show_result(result, feedback_text, source_file=path)

            except Exception as e:
                log.exception("분석 오류")
                from ui.display import show_error
                show_error("분석 오류", str(e))

    observer = Observer()
    observer.schedule(AudioHandler(), watch_folder, recursive=False)
    observer.start()

    log.info(f"로컬 감시 모드 시작 — 폴더: {watch_folder}")
    log.info("이 폴더에 FLAC/WAV 파일을 넣으면 자동으로 분석됩니다.")
    log.info("종료: Ctrl+C")

    # 시스템 트레이 아이콘 또는 메시지 창으로 실행 중 표시
    _show_tray_or_console(watch_folder)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def _show_tray_or_console(watch_folder: str):
    """실행 중임을 사용자에게 알리는 간단한 안내 창."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        "발성 분석 봇 — 로컬 감시 모드",
        f"📁 감시 폴더:\n{watch_folder}\n\n"
        "이 폴더에 FLAC/WAV 파일을 복사하면\n"
        "자동으로 분석 결과가 표시됩니다.\n\n"
        "이 창을 닫으면 백그라운드에서 계속 실행됩니다.\n"
        "(종료하려면 작업 표시줄에서 프로세스를 직접 종료)",
    )
    root.destroy()
