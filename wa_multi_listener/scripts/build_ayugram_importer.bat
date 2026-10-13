@echo off
chcp 65001 >nul
cd /d "%~dp0.."

set "PYTHON=..\.venv\Scripts\python.exe"
set "PYINSTALLER=..\.venv\Scripts\pyinstaller.exe"
if not exist "%PYTHON%" (
  echo 未找到构建环境：%PYTHON%
  pause
  exit /b 1
)

echo === 检查转换依赖 ===
"%PYTHON%" -m pip install opentele==1.15.1 PyQt5==5.15.11 PyQt5-sip PyQt5-Qt5 pycryptodome --no-deps
if errorlevel 1 goto :failed

echo.
echo === 构建 TG账号导入AyuGram.exe ===
"%PYINSTALLER%" scripts\import_tg_sessions_to_ayugram.py ^
  --name "TG账号导入AyuGram" ^
  --onefile ^
  --windowed ^
  --noconfirm ^
  --clean ^
  --distpath "dist\AyuGram导入工具" ^
  --workpath "build\ayugram_importer" ^
  --specpath "build\ayugram_importer" ^
  --collect-all opentele ^
  --collect-all telethon ^
  --collect-all Crypto ^
  --collect-all PyQt5 ^
  --hidden-import Crypto.Cipher.AES ^
  --icon "C:\Users\lenovo\Pictures\icon.ico"
if errorlevel 1 goto :failed

echo.
echo 构建完成：
echo dist\AyuGram导入工具\TG账号导入AyuGram.exe
pause
exit /b 0

:failed
echo.
echo 构建失败。
pause
exit /b 1
