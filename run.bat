@echo off
chcp 65001 > nul
title 발성 분석 봇

:: Python 존재 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 설치 후 다시 실행하세요.
    pause
    exit /b 1
)

:: 의존성 설치 확인 (최초 1회)
if not exist ".deps_installed" (
    echo 의존성 설치 중 — 최초 1회만 실행됩니다...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [오류] 의존성 설치에 실패했습니다.
        pause
        exit /b 1
    )
    echo. > .deps_installed
    echo 설치 완료!
)

:: 메인 실행
python main.py

if errorlevel 1 (
    echo.
    echo [오류] 프로그램 실행 중 문제가 발생했습니다.
    pause
)
