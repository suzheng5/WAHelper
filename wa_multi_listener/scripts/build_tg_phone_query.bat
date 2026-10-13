@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set "PYTHONPATH="
echo 正在生成独立 TG 手机号查询工具...
"..\.venv\Scripts\pyinstaller.exe" ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name "TG账号手机号查询" ^
  --distpath "dist\WAHelper" ^
  --workpath "build\tg_phone_query" ^
  --specpath "build\tg_phone_query" ^
  --hidden-import "telethon" ^
  "scripts\query_tg_account_phones.py"
if errorlevel 1 exit /b 1
echo 已生成：dist\WAHelper\TG账号手机号查询.exe
