@echo off
chcp 65001 >nul
echo ========================================
echo 论文阅读助手 - 设置每日自动运行
echo ========================================

REM 获取脚本所在目录
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM 创建Windows任务计划 - 每天早上8点运行
echo 创建定时任务...
schtasks /create /tn "论文阅读助手_每日论文" /tr "py -3 \"%SCRIPT_DIR%workflow.py\" --all" /sc daily /st 08:00 /f

echo.
echo 任务已创建！每天早上8点将自动运行工作流。
echo.
echo 可以使用以下命令查看任务状态:
echo   schtasks /query /tn "论文阅读助手_每日论文"
echo.
echo 或者删除任务:
echo   schtasks /delete /tn "论文阅读助手_每日论文" /f
echo.
pause
