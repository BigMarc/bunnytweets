@echo off
REM Build BunnyTweets desktop app for Windows.
REM
REM Usage:
REM   scripts\build.bat          Build the .exe
REM   scripts\build.bat clean    Remove build artifacts
REM
REM Prerequisites:
REM   pip install pyinstaller pystray
REM
REM Output:
REM   dist\BunnyTweets\BunnyTweets.exe

cd /d "%~dp0\.."

if "%~1"=="clean" (
    echo Cleaning build artifacts...
    rmdir /s /q build 2>nul
    rmdir /s /q dist 2>nul
    echo Done.
    exit /b 0
)

echo ========================================
echo   BunnyTweets Desktop - Build (Windows)
echo ========================================

REM Check for PyInstaller
where pyinstaller >nul 2>&1 || (
    echo ERROR: pyinstaller not found. Install it with:
    echo   pip install pyinstaller
    exit /b 1
)

REM Check for pystray
python -c "import pystray" 2>nul || (
    echo ERROR: pystray not found. Install it with:
    echo   pip install pystray
    exit /b 1
)

echo Building with PyInstaller...
pyinstaller bunnytweets.spec --noconfirm

echo.
echo Build complete!
echo   Executable: dist\BunnyTweets\BunnyTweets.exe
echo.
echo Run with: dist\BunnyTweets\BunnyTweets.exe
echo.
echo To create an installer, use Inno Setup or NSIS with the dist\BunnyTweets folder.
