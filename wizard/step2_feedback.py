"""
wizard/step2_feedback.py
========================
Step 2 — 피드백 수신 방식 + 사용자 정보 (나이·성별) + 모드별 API 입력
"""

import tkinter as tk
from tkinter import messagebox, filedialog

try:
    import customtkinter as ctk
    USE_CTK = True
except ImportError:
    USE_CTK = False


class Step2Feedback(tk.Frame if not USE_CTK else ctk.CTkFrame):
    def __init__(self, parent, config_data: dict, on_done):
        super().__init__(parent)
        self._on_done = on_done
        self._execution = config_data.get("execution", "local")

        # 변수
        self._feedback_telegram = tk.BooleanVar(value=self._execution != "local")
        self._feedback_local    = tk.BooleanVar(value=True)
        self._age_var           = tk.StringVar(value="30")
        self._gender_var        = tk.StringVar(value="남")
        self._token_var         = tk.StringVar()
        self._gcp_var           = tk.StringVar()
        self._folder_var        = tk.StringVar()

        self._build()

    def _build(self):
        title = tk.Label(
            self,
            text="Step 2 / 3 — 피드백 방식 및 기본 정보",
            font=("Malgun Gothic", 13, "bold"),
            anchor="w",
        )
        title.pack(fill="x", pady=(0, 10))

        # ── 피드백 방식
        fb_frame = tk.LabelFrame(self, text="결과 수신 방식 (복수 선택 가능)", padx=10, pady=8)
        fb_frame.pack(fill="x", pady=4)

        if self._execution != "local":
            cb1 = tk.Checkbutton(
                fb_frame,
                text="텔레그램으로 받기",
                variable=self._feedback_telegram,
                font=("Malgun Gothic", 10),
            )
            cb1.pack(anchor="w")

        cb2 = tk.Checkbutton(
            fb_frame,
            text="이 PC 화면에서 보기 (HTML 리포트 생성)",
            variable=self._feedback_local,
            font=("Malgun Gothic", 10),
        )
        cb2.pack(anchor="w")

        # ── 사용자 정보
        user_frame = tk.LabelFrame(self, text="사용자 정보", padx=10, pady=8)
        user_frame.pack(fill="x", pady=4)

        age_row = tk.Frame(user_frame)
        age_row.pack(fill="x", pady=2)
        tk.Label(age_row, text="나이:", width=8, anchor="w", font=("Malgun Gothic", 10)).pack(side="left")
        tk.Entry(age_row, textvariable=self._age_var, width=6, font=("Malgun Gothic", 10)).pack(side="left")
        tk.Label(age_row, text="세", font=("Malgun Gothic", 10)).pack(side="left", padx=4)

        gender_row = tk.Frame(user_frame)
        gender_row.pack(fill="x", pady=2)
        tk.Label(gender_row, text="성별:", width=8, anchor="w", font=("Malgun Gothic", 10)).pack(side="left")
        tk.Radiobutton(gender_row, text="남", variable=self._gender_var, value="남", font=("Malgun Gothic", 10)).pack(side="left")
        tk.Radiobutton(gender_row, text="여", variable=self._gender_var, value="여", font=("Malgun Gothic", 10)).pack(side="left", padx=10)

        # ── 모드별 추가 입력
        if self._execution in ("cloud", "polling"):
            api_frame = tk.LabelFrame(self, text="Telegram 봇 설정", padx=10, pady=8)
            api_frame.pack(fill="x", pady=4)

            token_row = tk.Frame(api_frame)
            token_row.pack(fill="x", pady=2)
            tk.Label(token_row, text="Bot Token:", width=14, anchor="w", font=("Malgun Gothic", 10)).pack(side="left")
            tk.Entry(token_row, textvariable=self._token_var, width=34, font=("Malgun Gothic", 10), show="*").pack(side="left")

        if self._execution == "cloud":
            gcp_frame = tk.LabelFrame(self, text="GCP 설정", padx=10, pady=8)
            gcp_frame.pack(fill="x", pady=4)

            gcp_row = tk.Frame(gcp_frame)
            gcp_row.pack(fill="x", pady=2)
            tk.Label(gcp_row, text="GCP Project ID:", width=16, anchor="w", font=("Malgun Gothic", 10)).pack(side="left")
            tk.Entry(gcp_row, textvariable=self._gcp_var, width=28, font=("Malgun Gothic", 10)).pack(side="left")

        if self._execution == "local":
            folder_frame = tk.LabelFrame(self, text="감시 폴더 설정", padx=10, pady=8)
            folder_frame.pack(fill="x", pady=4)

            folder_row = tk.Frame(folder_frame)
            folder_row.pack(fill="x", pady=2)
            tk.Label(folder_row, text="폴더 경로:", width=10, anchor="w", font=("Malgun Gothic", 10)).pack(side="left")
            tk.Entry(folder_row, textvariable=self._folder_var, width=28, font=("Malgun Gothic", 10)).pack(side="left", padx=4)
            tk.Button(
                folder_row, text="찾아보기",
                command=self._browse_folder,
                font=("Malgun Gothic", 9),
            ).pack(side="left")

        # ── 버튼
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", pady=(12, 0))

        tk.Button(
            btn_frame, text="← 이전",
            font=("Malgun Gothic", 10),
            command=lambda: self._on_done({"_back": True}),
        ).pack(side="left")

        tk.Button(
            btn_frame, text="다음 →",
            font=("Malgun Gothic", 11),
            bg="#2563EB", fg="white", relief="flat",
            padx=20, pady=6,
            command=self._next,
        ).pack(side="right")

    def _browse_folder(self):
        path = filedialog.askdirectory(title="감시할 폴더를 선택하세요")
        if path:
            self._folder_var.set(path)

    def _next(self):
        # 유효성 검사
        try:
            age = int(self._age_var.get())
            assert 1 <= age <= 120
        except Exception:
            messagebox.showerror("입력 오류", "나이를 올바르게 입력해 주세요 (1~120).")
            return

        if self._execution in ("cloud", "polling") and not self._token_var.get().strip():
            messagebox.showerror("입력 오류", "Telegram Bot Token을 입력해 주세요.")
            return

        if self._execution == "cloud" and not self._gcp_var.get().strip():
            messagebox.showerror("입력 오류", "GCP Project ID를 입력해 주세요.")
            return

        if self._execution == "local" and not self._folder_var.get().strip():
            messagebox.showerror("입력 오류", "감시할 폴더를 선택해 주세요.")
            return

        # 피드백 모드 결정
        fb_parts = []
        if self._feedback_telegram.get():
            fb_parts.append("telegram")
        if self._feedback_local.get():
            fb_parts.append("local")
        if not fb_parts:
            messagebox.showerror("입력 오류", "결과 수신 방식을 하나 이상 선택해 주세요.")
            return

        self._on_done({
            "feedback":      "+".join(fb_parts),
            "age":           age,
            "gender":        self._gender_var.get(),
            "bot_token":     self._token_var.get().strip(),
            "gcp_project_id": self._gcp_var.get().strip(),
            "watch_folder":  self._folder_var.get().strip(),
        })
