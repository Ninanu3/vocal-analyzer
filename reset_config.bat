@echo off
chcp 65001 > nul
echo 설정을 초기화하면 다음 실행 시 Setup Wizard가 다시 시작됩니다.
set /p confirm=초기화하시겠습니까? (y/n):
if /i "%confirm%"=="y" (
    if exist config.ini del config.ini
    echo config.ini 삭제 완료. 다음 실행 시 Setup Wizard가 시작됩니다.
)
pause
