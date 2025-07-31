#!/usr/bin/env python3
"""
Local development setup script for GitResume.

This script helps set up the development environment and provides
instructions for running the application locally.
"""

import os
import sys
import subprocess
from pathlib import Path


def check_python_version():
    """Check if Python version is 3.11 or higher."""
    if sys.version_info < (3, 11):
        print("❌ Python 3.11 or higher is required.")
        print(f"Current version: {sys.version}")
        return False
    print(f"✅ Python version: {sys.version}")
    return True


def check_git_installation():
    """Check if Git is installed."""
    try:
        result = subprocess.run(['git', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Git installed: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ Git is not installed or not in PATH.")
    print("Please install Git from: https://git-scm.com/downloads")
    return False


def create_env_file():
    """Create a .env file from the example if it doesn't exist."""
    env_file = Path(".env")
    example_file = Path("env.example.yaml")
    
    if env_file.exists():
        print("✅ .env file already exists")
        return True
    
    if not example_file.exists():
        print("❌ env.example.yaml not found")
        return False
    
    # Create a basic .env file
    env_content = """# Local Development Environment Variables
# Copy this file to .env and fill in your actual values

ENVIRONMENT=development
SESSION_SECRET_KEY=your-secret-key-here-change-this

# GitHub OAuth (required for login and user contributions feature)
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret
GITHUB_TOKEN=your_github_token
CALLBACK_URL=http://localhost:8000/callback

# Redis (optional - will fall back to memory if not available)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_USERNAME=
REDIS_PASSWORD=

# AI Providers (at least one required)
AI_PROVIDER=gemini

# Gemini API (Google AI Studio)
GEMINI_API_KEYS=your_gemini_api_key_here
GEMINI_MODEL_VERSION=gemini-1.5-flash

# OpenAI (optional alternative)
OPENAI_API_KEYS=your_openai_api_key_here
OPENAI_MODEL_VERSION=gpt-3.5-turbo

# Other optional providers
GROQ_API_KEYS=
CLAUDE_API_KEYS=

# Analytics (optional)
API_ANALYTICS_KEY=

# Security
CLOUDFLARE_ONLY=false
"""
    
    with open(env_file, 'w') as f:
        f.write(env_content)
    
    print("✅ Created .env file from template")
    print("⚠️  Please edit .env file and add your API keys")
    return True


def install_dependencies():
    """Install Python dependencies."""
    print("📦 Installing Python dependencies...")
    
    try:
        # Try to upgrade pip first, but continue even if it fails (permission issues on Windows)
        print("  Attempting to upgrade pip...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip', '--user'], 
                         check=True, capture_output=True)
            print("  ✅ Pip upgraded successfully")
        except subprocess.CalledProcessError:
            try:
                # Try without --user flag
                subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'], 
                             check=True, capture_output=True)
                print("  ✅ Pip upgraded successfully")
            except subprocess.CalledProcessError:
                print("  ⚠️  Pip upgrade failed (permission issue), continuing with current version...")
        
        # Install requirements - try user install first for Windows compatibility
        print("  Installing project dependencies...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '--user'], check=True)
            print("✅ Dependencies installed successfully (user install)")
        except subprocess.CalledProcessError:
            # Fallback to system install
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True)
            print("✅ Dependencies installed successfully (system install)")
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        print("\n💡 Manual installation:")
        print("Try running: pip install -r requirements.txt --user")
        print("Or: python -m pip install -r requirements.txt --user")
        return False


def print_setup_instructions():
    """Print setup and run instructions."""
    print("\n" + "="*60)
    print("🚀 GITRESUME LOCAL DEVELOPMENT SETUP")
    print("="*60)
    
    print("\n📋 NEXT STEPS:")
    print("1. Edit the .env file and add your API keys:")
    print("   - Get Gemini API key from: https://makersuite.google.com/app/apikey")
    print("   - Or get OpenAI API key from: https://platform.openai.com/api-keys")
    print("   - GitHub token from: https://github.com/settings/tokens (optional)")
    
    print("\n2. Run the application:")
    print("   python app.py")
    print("   # or")
    print("   uvicorn app:app --reload --host 0.0.0.0 --port 8000")
    
    print("\n3. Open your browser to:")
    print("   http://localhost:8000")
    
    print("\n🔧 CONFIGURATION NOTES:")
    print("- At minimum, you need one AI provider API key (Gemini or OpenAI)")
    print("- GitHub token is optional but required for:")
    print("  - Private repositories")
    print("  - User-specific commit analysis")
    print("- Redis is optional (will use memory cache if not available)")
    
    print("\n📝 TESTING THE NEW FEATURE:")
    print("1. Make sure you have a GitHub token in your .env file")
    print("2. Go to the web interface")
    print("3. Check 'Analyze only my contributions' checkbox")
    print("4. Enter a repository URL where you have commits")
    print("5. The tool will filter and show only your contributions")
    
    print("\n💡 TROUBLESHOOTING:")
    print("- If you get import errors, try: pip install --upgrade -r requirements.txt")
    print("- If you get permission errors, try: pip install -r requirements.txt --user")
    print("- On Windows, you might need to run as Administrator for system-wide installs")
    print("- If Redis connection fails, it will fall back to memory cache")
    print("- Check logs for detailed error messages")
    print("- Make sure your GitHub token has repo access permissions")
    
    print("\n🔧 MANUAL SETUP (if automated setup fails):")
    print("1. Install dependencies manually:")
    print("   pip install -r requirements.txt --user")
    print("2. Create .env file and add your API keys")
    print("3. Run: python app.py")


def main():
    """Main setup function."""
    print("🔧 Setting up GitResume for local development...")
    
    success = True
    
    # Check prerequisites
    if not check_python_version():
        success = False
    
    if not check_git_installation():
        success = False
    
    if not success:
        print("\n❌ Prerequisites not met. Please fix the issues above.")
        return False
    
    # Setup environment
    if not create_env_file():
        success = False
    
    if not install_dependencies():
        success = False
    
    if success:
        print("\n✅ Setup completed successfully!")
        print_setup_instructions()
    else:
        print("\n❌ Setup failed. Please check the errors above.")
    
    return success


if __name__ == "__main__":
    main()
