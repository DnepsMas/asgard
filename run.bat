@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [setup] 已从 .env.example 生成 .env，请编辑填写凭据
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [setup] 创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [!] 需要 Python 3.10+，请先安装: https://python.org
        pause
        exit /b 1
    )
)

echo [setup] 安装/更新依赖...
.venv\Scripts\python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [!] 依赖安装失败
    pause
    exit /b 1
)

echo [run] 启动 Iris...
.venv\Scripts\python -m src %*
echo.
echo [done] 退出码: %errorlevel%
