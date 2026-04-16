# Changelog — vocal-analyzer (Project D)

모든 주요 변경사항을 이 파일에 기록합니다.  
형식: [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`

- **MAJOR**: 하위 호환 불가 변경 (구조 전면 개편)
- **MINOR**: 새 기능 추가 (하위 호환 유지)
- **PATCH**: 버그 수정 / 문서 수정

GitHub 저장소: https://github.com/Ninanu3/vocal-analyzer  
GitHub Releases: https://github.com/Ninanu3/vocal-analyzer/releases

---

## [1.1.0] — 2026-04-16

### 개선 및 버그 수정

#### 버그 수정
- **무한 분석 루프 수정** — Telegram이 60초마다 webhook을 재시도하는 문제 해결
  - 백그라운드 스레드로 분석을 처리하고 즉시 HTTP 200 반환
  - `update_id` 기반 중복 처리 방지 (`_SEEN_UPDATES` set + threading lock)

#### 기능 개선
- **분석 결과 대폭 강화** (`core/feedback.py`)
  - 종합 점수(0~100점) + 5단계 등급 표시 (최상/양호/보통/주의/위험)
  - 항목별 체감 언어 설명 (예: "목소리 떨림 매우 안정적 (프로 수준)")
  - 프로 가수 기준값 추가 (Jitter <0.5%, Shimmer <2.0%, HNR >25dB)
  - 프로 수준 달성도 이모지 진행 막대 `[████████░░] 82%`
  - 공명 특성 분석: 성구(흉성/두성), 공명 위치(밝음/균형/어두움), 비음 경향
  - 베이스라인 대비 트렌드 표시 (↑악화/↓개선/→유지)
  - 항목별 맞춤 훈련 권고 (SOVT, 립 트릴, 메사 디 보체 등)
- **`/help` 명령어 추가** — 각 수치(Jitter/Shimmer/HNR/F1/F2) 상세 설명

#### 기술 변경
- requirements.txt에서 미사용 패키지 제거 (`google-cloud-firestore`, `python-telegram-bot`)
- Cloud Function 메모리 2GB 유지 (OOM 방지)

---

## [1.0.0] — 2026-04-15

### 첫 번째 정식 릴리스

#### 추가
- **Setup Wizard** (`wizard/`) — 3단계 GUI 초기 설정
  - Step 1: 실행 방식 선택 (클라우드 / 폴링 / 로컬)
  - Step 2: 피드백 방식 + 나이·성별 + API 입력
  - Step 3: 저장 방식 선택 (Google Sheets or CSV)
- **분석 엔진** (`core/analyzer.py`)
  - 베이스라인 모드 (≤ 30초): Jitter, Shimmer, HNR, F1/F2
  - 노래 모드 (> 30초): librosa.pyin held note 탐지 후 parselmouth 분석
  - 이상치 필터: Jitter > 2% or HNR < 5dB 구간 자동 제외
- **피드백 생성** (`core/feedback.py`)
  - 나이·성별 기반 임상 기준값 적용
  - 40대 이상 10% 허용 여유
  - 4회 누적 후 개인 평균 기준 전환
  - 항목별 훈련 권고 멘트
- **저장소 추상화** (`core/storage.py`)
  - Google Sheets API 연동
  - 로컬 CSV 폴백 (API 키 없이 사용 가능)
- **실행 모드** (`modes/`)
  - `cloud_mode.py`: GCP Cloud Functions 배포 파일 자동 생성 + deploy.bat
  - `polling_mode.py`: 텔레그램 폴링 봇 (서버 없이 로컬 실행)
  - `local_mode.py`: 지정 폴더 감시 (watchdog)
- **로컬 UI** (`ui/display.py`)
  - Rich 터미널 컬러 출력
  - HTML 리포트 자동 생성 (`reports/` 폴더) + 브라우저 자동 오픈
- **Windows 배포**
  - `run.bat`: 의존성 자동 설치 + 실행
  - `build.bat`: PyInstaller 단일 EXE 빌드
  - `reset_config.bat`: 설정 초기화

#### 기술 스택
- Python 3.11+
- parselmouth 0.4.x, librosa 0.10.x, pydub 0.25.x
- python-telegram-bot 20.x
- customtkinter 5.x, rich 13.x, watchdog 4.x
- google-api-python-client 2.x

---

## 버전 다운로드

> Python 설치 불필요. 다운로드 후 더블클릭하면 바로 실행됩니다.

| 버전 | 날짜 | EXE 다운로드 | 크기 |
|------|------|-------------|------|
| [v1.0.0](https://github.com/Ninanu3/vocal-analyzer/releases/tag/v1.0.0) | 2026-04-15 | **[⬇ vocal-analyzer.exe](https://github.com/Ninanu3/vocal-analyzer/releases/download/v1.0.0/vocal-analyzer.exe)** | 149 MB |

---

## 수정 기여 방법

1. 이 저장소를 Fork
2. 브랜치 생성: `git checkout -b feature/기능명`
3. 변경 후 CHANGELOG.md 업데이트
4. Pull Request 생성

---

*이 파일은 Claude Code가 자동으로 관리합니다.*
