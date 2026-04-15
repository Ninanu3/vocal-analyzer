"""
wizard/step3_storage.py
=======================
Step 3 — 저장 방식 선택 (Google Sheets or CSV)
"""

import tkinter as tk
from tkinter import messagebox, filedialog

try:
    import customtkinter as ctk
    USE_CTK = True
except ImportError:
    USE_CTK = False


class Step3Storage(tk.Frame if not USE_CTK else ctk.CTkFrame):
    def __init__(self, parent, config_data: dict, on_done):
        super().__init__(parent)
        self._on_done = on_done

        self._storage_type = tk.StringVar(value="csv")
        self._sheets_id    = tk.StringVar()
        self._csv_path     = tk.StringVar(value="vocal_log.csv")

        self._build()

    def _build(self):
        title = tk.Label(
            self,
            text="Step 3 / 3 — 분석 결과 저장 방식",
            font=("Malgun Gothic", 13, "bold"),
            anchor="w",
        )
        title.pack(fill="x", pady=(0, 12))

        # ── CSV 옵션 카드
        csv_card = tk.Frame(self, relief="groove", bd=1, padx=12, pady=10)
        csv_card.pack(fill="x", pady=4)

        tk.Radiobutton(
            csv_card,
            text="📄  로컬 CSV 파일에 저장 (설정 불필요)",
            variable=self._storage_type,
            value="csv",
            font=("Malgun Gothic", 11, "bold"),
            command=self._update_visibility,
        ).pack(anchor="w")

        tk.Label(
            csv_card,
            text="별도 API 없이 이 PC에 CSV 파일로 날짜별 기록을 남깁니다.",
            font=("Malgun Gothic", 9),
            fg="#555555",
            justify="left",
        ).pack(anchor="w", padx=20)

        # CSV 경로 입력
        self._csv_frame = tk.Frame(csv_card)
        self._csv_frame.pack(fill="x", padx=20, pady=(6, 0))
        tk.Label(self._csv_frame, text="저장 파일명:", width=12, anchor="w", font=("Malgun Gothic", 10)).pack(side="left")
        tk.Entry(self._csv_frame, textvariable=self._csv_path, width=26, font=("Malgun Gothic", 10)).pack(side="left", padx=4)
        tk.Button(
            self._csv_frame, text="찾아보기",
            command=self._browse_csv,
            font=("Malgun Gothic", 9),
        ).pack(side="left")

        # ── Sheets 옵션 카드
        sheets_card = tk.Frame(self, relief="groove", bd=1, padx=12, pady=10)
        sheets_card.pack(fill="x", pady=4)

        tk.Radiobutton(
            sheets_card,
            text="📊  Google Sheets에 저장",
            variable=self._storage_type,
            value="sheets",
            font=("Malgun Gothic", 11, "bold"),
            command=self._update_visibility,
        ).pack(anchor="w")

        tk.Label(
            sheets_card,
            text="Google Sheets API로 스프레드시트에 날짜별 기록을 누적합니다.\n"
                 "서비스 계정 키 파일(service_account.json)이 필요합니다.",
            font=("Malgun Gothic", 9),
            fg="#555555",
            justify="left",
        ).pack(anchor="w", padx=20)

        # Sheets ID 입력
        self._sheets_frame = tk.Frame(sheets_card)
        self._sheets_frame.pack(fill="x", padx=20, pady=(6, 0))
        tk.Label(self._sheets_frame, text="Sheets ID:", width=12, anchor="w", font=("Malgun Gothic", 10)).pack(side="left")
        tk.Entry(self._sheets_frame, textvariable=self._sheets_id, width=36, font=("Malgun Gothic", 10)).pack(side="left")

        sheets_hint = tk.Label(
            sheets_card,
            text="  ※ Sheets URL에서 /d/ 와 /edit 사이의 문자열",
            font=("Malgun Gothic", 8),
            fg="#888888",
        )
        sheets_hint.pack(anchor="w", padx=20)

        # ── 버튼
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", pady=(20, 0))

        tk.Button(
            btn_frame, text="← 이전",
            font=("Malgun Gothic", 10),
            command=lambda: self._on_done({"_back": True}),
        ).pack(side="left")

        tk.Button(
            btn_frame, text="✅  설정 완료",
            font=("Malgun Gothic", 11),
            bg="#16A34A", fg="white", relief="flat",
            padx=20, pady=6,
            command=self._finish,
        ).pack(side="right")

        self._update_visibility()

    def _update_visibility(self):
        t = self._storage_type.get()
        # CSV 프레임은 csv 선택 시만 활성
        state = "normal" if t == "csv" else "disabled"
        for w in self._csv_frame.winfo_children():
            try:
                w.configure(state=state)
            except Exception:
                pass

        # Sheets 프레임은 sheets 선택 시만 활성
        state = "normal" if t == "sheets" else "disabled"
        for w in self._sheets_frame.winfo_children():
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _browse_csv(self):
        path = filedialog.asksaveasfilename(
            title="CSV 저장 위치 선택",
            defaultextension=".csv",
            filetypes=[("CSV 파일", "*.csv"), ("모든 파일", "*.*")],
            initialfile="vocal_log.csv",
        )
        if path:
            self._csv_path.set(path)

    def _finish(self):
        t = self._storage_type.get()

        if t == "sheets" and not self._sheets_id.get().strip():
            messagebox.showerror("입력 오류", "Google Sheets ID를 입력해 주세요.")
            return

        if t == "csv" and not self._csv_path.get().strip():
            messagebox.showerror("입력 오류", "CSV 파일 경로를 입력해 주세요.")
            return

        self._on_done({
            "storage_type": t,
            "sheets_id":    self._sheets_id.get().strip(),
            "csv_path":     self._csv_path.get().strip(),
        })
