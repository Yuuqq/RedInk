@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: CSS Lab AI图文生成器 - Windows 一体化启动（仅后端，使用已构建的前端静态资源）
:: 访问: http://localhost:12398

title CSS Lab AI图文生成器（Standalone）

cd /d "%~dp0\.."

:: Force UTF-8 for Python I/O
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cls
echo.
echo ╔═══════════════════════════════════════════════╗
echo ║     CSS Lab AI图文生成器 - Standalone (Win)   ║
echo ╚═══════════════════════════════════════════════╝
echo.

echo [INFO] 检查环境依赖...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 未安装！
    pause
    exit /b 1
)

if not exist "frontend\\dist\\index.html" (
    echo [WARN] 未检测到前端构建产物: frontend\\dist\\index.html
    echo        你可以先执行：
    echo        cd frontend ^&^& npm install ^&^& npm run build
    echo        或使用 scripts\\start-windows.bat 以开发模式启动前端
    echo.
)

where uv >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set USE_UV=1
) else (
    set USE_UV=0
)

echo.
echo [INFO] 安装后端依赖...
if %USE_UV% equ 1 (
    uv sync
) else (
    pip install -e . -q
)

echo.
echo [INFO] 启动后端（将自动托管 frontend/dist）...
if %USE_UV% equ 1 (
    start "CSSLab-Standalone-12398" cmd /k "color 1F && title CSS Lab Standalone [12398] && uv run python -m backend.app"
) else (
    start "CSSLab-Standalone-12398" cmd /k "color 1F && title CSS Lab Standalone [12398] && python -m backend.app"
)

timeout /t 2 /nobreak >nul
start http://localhost:12398

echo.
echo [OK] 已启动： http://localhost:12398
echo 按任意键关闭此窗口（服务会继续运行）...
pause >nul
