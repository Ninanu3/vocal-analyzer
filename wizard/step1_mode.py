"""
wizard/step1_mode.py
====================
Step 1 — 실행 방식 선택 (클라우드 / 폴링 / 로컬 전용)
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

try:
    import customtkinter as ctk
    USE_CTK = True
except ImportError:
    USE_CTK = False


_MODES = [
    {
        "value": "cloud",
        "label": "☁️  클라우드 방식 (Webhook)",
        "desc": (
            "텔레그램에 파일을 올리면 GCP 서버가 자동으로 분석합니다.\n"
            "내 PC가 꺼져도 24시간 작동합니다.\n"
            "필요: GCP 계정, Telegram 봇 토큰"
        ),
    },
    {
        "value": "polling",
        "label": "🖥️  폴링 방식 (내 PC에서 실행)",
        "desc": (
            "별도 서버 없이 이 프로그램이 텔레그램 서버에 주기적으로 접속해\n"
            "파일을 받아 분석합니다.\n"
            "이 프로그램이 실행 중일 때만 작동합니다.\n"
            "필요: Telegram 봇 토큰 (GCP 불필요)"
        ),
    },
    {
        "value": "local",
        "label": "📁  로컬 전용 (폴더 감시)",
        "desc": (
            "텔레그램 없이 지정한 폴더에 파일을 넣으면\n"
            "이 PC 화면에서 바로 분석 결과를 볼 수 있습니다.\n"
            "완전 오프라인 동작 가능.\n"
            "필요: 없음"
        ),
    },
]


class Step1Mode(tk.Frame if not USE_CTK else ctk.CTkFrame):
    def __init__(self, parent, on_done):
        super().__init__(parent)
        self._on_done = on_done
        self._selected = tk.StringVar(value="cloud")
        self._build()

    def _build(self):
        # 제목
        title = tk.Label(
            self,
            text="Step 1 / 3 — 실행 방식을 선택하세요",
            font=("Malgun Gothic", 13, "bold"),
            anchor="w",
        )
        title.pack(fill="x", pady=(0, 12))

        # 옵션 카드들
        for mode in _MODES:
            self._make_card(mode)

        # 다음 버튼
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", pady=(16, 0))

        next_btn = tk.Button(
            btn_frame,
            text="다음 →",
            font=("Malgun Gothic", 11),
            bg="#2563EB",
            fg="white",
            relief="flat",
            padx=20,
            pady=6,
            command=self._next,
        )
        next_btn.pack(side="right")

    def _make_card(self, mode: dict):
        card = tk.Frame(self, relief="groove", bd=1, padx=12, pady=10)
        card.pack(fill="x", pady=4)

        header = tk.Frame(card)
        header.pack(fill="x")

        rb = tk.Radiobutton(
            header,
            text=mode["label"],
            variable=self._selected,
            value=mode["value"],
            font=("Malgun Gothic", 11, "bold"),
            anchor="w",
        )
        rb.pack(side="left")

        desc = tk.Label(
            card,
            text=mode["desc"],
            font=("Malgun Gothic", 9),
            fg="#555555",
            justify="left",
            anchor="w",
        )
        desc.pack(fill="x", padx=20)

        # 카드 클릭 시 선택
        for widget in [card, header, desc]:
            widget.bind("<Button-1>", lambda e, v=mode["value"]: self._selected.set(v))

    def _next(self):
        self._on_done({"execution": self._selected.get()})
