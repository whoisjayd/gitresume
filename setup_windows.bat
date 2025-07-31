@echo off
echo 🔧 GitResume Manual Setup for Windows
echo =====================================

echo.
echo 📋 Step 1: Fix pip installation
echo Downloading pip installer...
python -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', 'get-pip.py')"

if exist get-pip.py (
    echo Installing pip...
    python get-pip.py --user
    del get-pip.py
    echo ✅ Pip installed successfully
) else (
    echo ❌ Failed to download pip installer
    echo Please download it manually from: https://bootstrap.pypa.io/get-pip.py
    pause
    exit /b 1
)

echo.
echo 📦 Step 2: Installing dependencies
pip install -r requirements.txt --user
if %errorlevel% equ 0 (
    echo ✅ Dependencies installed successfully
) else (
    echo ❌ Failed to install dependencies
    echo Try running: python -m pip install -r requirements.txt --user
    pause
    exit /b 1
)

echo.
echo 🔧 Step 3: Environment setup
if not exist .env (
    echo Creating .env file...
    copy env.example.yaml .env
    echo ✅ .env file created
    echo ⚠️  Please edit .env file and add your API keys
) else (
    echo ✅ .env file already exists
)

echo.
echo 🚀 Setup completed!
echo =====================================
echo.
echo Next steps:
echo 1. Edit .env file and add your API keys:
echo    - GEMINI_API_KEYS=your_key (from https://makersuite.google.com/app/apikey)
echo    - GITHUB_TOKEN=your_token (from https://github.com/settings/tokens)
echo.
echo 2. Run the application:
echo    python app.py
echo.
echo 3. Open your browser to: http://localhost:8000
echo.
pause
