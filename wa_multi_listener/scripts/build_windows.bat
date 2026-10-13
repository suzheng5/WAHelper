@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo === 1/3 PyInstaller 打包（会清空 dist\WAHelper）===
set "PYTHONPATH="
"..\.venv\Scripts\pyinstaller.exe" build_windows.spec --noconfirm
if errorlevel 1 exit /b 1
echo.
echo === 2/3 finalize_dist（恢复用户数据 + 激活码管理 + 启动脚本）===
"..\.venv\Scripts\python.exe" scripts\finalize_dist.py
if errorlevel 1 exit /b 1
echo.
echo === 3/3 校验 ===
"..\.venv\Scripts\python.exe" -c "import json,os; p=r'dist\\WAHelper\\telegram\\config.json'; d=json.load(open(p,encoding='utf-8')); s=len(json.load(open(r'dist\\WAHelper\\telegram\\data\\schedules.json',encoding='utf-8-sig'))); n=len([x for x in os.listdir(r'dist\\WAHelper\\telegram\\sessions') if x.endswith('.session')]); print('api_id',d.get('api_id'),'accounts',len(d.get('accounts',[])),'schedules',s,'sessions',n)"
echo.
echo 完成。请用 dist\WAHelper\启动.bat 运行。
pause
