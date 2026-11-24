@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ==================================================
echo   나의 투자도우미 (My Investment Assistant) 시작
echo   창을 닫으면 서버가 종료됩니다. 최소화해서 두세요!
echo ==================================================

:: 2초 뒤 브라우저 자동 열기
start "" /b cmd /c "timeout /t 2 /nobreak > nul & start http://127.0.0.1:5000"

:: 가상환경 파이썬으로 Flask 서버 실행
.\venv\Scripts\python.exe app.py

echo.
echo 서버가 종료되었습니다.
pause
