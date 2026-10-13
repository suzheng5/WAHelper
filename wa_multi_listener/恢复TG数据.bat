@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
echo 正在恢复 Telegram 完整数据（账号/通讯录/任务）...
C:\Users\lenovo\Desktop\AI\.venv\Scripts\python.exe scripts\restore_tg_data.py
if errorlevel 1 (
  echo 恢复失败，请检查备份是否存在。
  pause
  exit /b 1
)
echo.
echo 恢复完成。请完全退出程序后重新打开，并切换到 Telegram 标签。
pause
