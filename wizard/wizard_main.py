"""
wizard/wizard_main.py
=====================
Setup Wizard 전체 흐름 제어.
config.ini 없을 때 main.py가 호출.
"""

import configparser
import tkinter as tk
from tkinter import messagebox

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    USE_CTK = True
except ImportError:
    USE_CTK = False

from wizard.step1_mode import Step1Mode
from wizard.step2_feedback import Step2Feedback
from wizard.step3_storage import Step3Storage

CONFIG_FILE = "config.ini"
WINDOW_W = 600
WINDOW_H = 520


class WizardApp:
    def __init__(self):
        if USE_CTK:
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()

        self.root.title("발성 분석 봇 — 초기 설정")
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.root.resizable(False, False)

        # 화면 가운데 배치
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - WINDOW_W) // 2
        y = (self.root.winfo_screenheight() - WINDOW_H) // 2
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}+{x}+{y}")

        # 결과 저장용 dict
        self.config_data: dict = {}

        # 현재 단계 프레임
        self._current_frame = None

        # 단계 이동 순서
        self._steps = [
            lambda: Step1Mode(self.root, self._on_step1_done),
            lambda: Step2Feedback(self.root, self.config_data, self._on_step2_done),
            lambda: Step3Storage(self.root, self.config_data, self._on_step3_done),
        ]
        self._step_idx = 0

        self._show_step(0)

    def _show_step(self, idx: int):
        if self._current_frame:
            self._current_frame.destroy()
        self._current_frame = self._steps[idx]()
        self._current_frame.pack(fill="both", expand=True, padx=20, pady=20)

    def _on_step1_done(self, data: dict):
        self.config_data.update(data)
        self._show_step(1)

    def _on_step2_done(self, data: dict):
        self.config_data.update(data)
        self._show_step(2)

    def _on_step3_done(self, data: dict):
        self.config_data.update(data)
        self._save_config()

    def _save_config(self):
        d = self.config_data
        cfg = configparser.ConfigParser()

        cfg["mode"] = {
            "execution": d.get("execution", "local"),
            "feedback":  d.get("feedback",  "local"),
        }
        cfg["user"] = {
            "age":    str(d.get("age", 30)),
            "gender": d.get("gender", "남"),
        }
        cfg["telegram"] = {
            "bot_token": d.get("bot_token", ""),
        }
        cfg["cloud"] = {
            "gcp_project_id": d.get("gcp_project_id", ""),
        }
        cfg["local"] = {
            "watch_folder": d.get("watch_folder", ""),
        }
        cfg["storage"] = {
            "type":     d.get("storage_type", "csv"),
            "sheets_id": d.get("sheets_id", ""),
            "csv_path":  d.get("csv_path", "vocal_log.csv"),
        }

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

        messagebox.showinfo(
            "설정 완료",
            "설정이 저장되었습니다.\n프로그램을 다시 시작하면 바로 실행됩니다.",
        )
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def run_wizard():
    app = WizardApp()
    app.run()
