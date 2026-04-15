@echo off
chcp 65001 > nul
title 발성 분석 봇 — EXE 빌드

echo === PyInstaller EXE 빌드 시작 ===
echo.

:: PyInstaller 설치 확인
pip show pyinstaller > nul 2>&1
if errorlevel 1 (
    echo PyInstaller 설치 중...
    pip install pyinstaller
)

:: 이전 빌드 정리
if exist dist   rmdir /s /q dist
if exist build  rmdir /s /q build

:: 빌드 실행
pyinstaller ^
  --onefile ^
  --windowed ^
  --name "vocal-analyzer" ^
  --add-data "core;core" ^
  --add-data "wizard;wizard" ^
  --add-data "modes;modes" ^
  --add-data "ui;ui" ^
  --hidden-import parselmouth ^
  --hidden-import librosa ^
  --hidden-import customtkinter ^
  --hidden-import watchdog ^
  --hidden-import google.oauth2.service_account ^
  --hidden-import googleapiclient.discovery ^
  main.py

if errorlevel 1 (
    echo.
    echo [오류] 빌드에 실패했습니다.
    pause
    exit /b 1
)

echo.
echo === 빌드 완료 ===
echo dist\vocal-analyzer.exe 파일을 배포하세요.
echo.
echo 주의: EXE 파일 크기가 200~400MB일 수 있습니다.
echo       (parselmouth, librosa 등 포함)
pause
