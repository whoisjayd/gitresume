#!/usr/bin/env python3
"""
Simple script to run GitResume locally with proper error handling.
"""

import os
import sys
import subprocess
from pathlib import Path


def check_env_file():
    """Check if .env file exists."""
    env_file = Path(".env")
    if not env_file.exists():
        print("❌ .env file not found!")
        print("Run: python setup_local.py")
        return False
    print("✅ .env file found")
    return True


def check_required_env_vars():
    """Check if required environment variables are set."""
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = []
    
    # Check for at least one AI provider
    ai_providers = {
        'GEMINI_API_KEYS': os.getenv('GEMINI_API_KEYS'),
        'OPENAI_API_KEYS': os.getenv('OPENAI_API_KEYS'),
        'GROQ_API_KEYS': os.getenv('GROQ_API_KEYS'),
        'CLAUDE_API_KEYS': os.getenv('CLAUDE_API_KEYS'),
    }
    
    has_ai_provider = any(key and key != 'your_key_here' for key in ai_providers.values())
    
    if not has_ai_provider:
        print("❌ No AI provider API key found!")
        print("Please set at least one of: GEMINI_API_KEYS, OPENAI_API_KEYS, GROQ_API_KEYS, CLAUDE_API_KEYS")
        return False
    
    print("✅ AI provider configured")
    return True


def run_app():
    """Run the FastAPI application."""
    try:
        print("🚀 Starting GitResume...")
        print("📍 Server will be available at: http://localhost:8000")
        print("Press Ctrl+C to stop")
        
        # Try to run with uvicorn first, fall back to direct execution
        try:
            subprocess.run([
                sys.executable, '-m', 'uvicorn', 
                'app:app', 
                '--reload', 
                '--host', '0.0.0.0', 
                '--port', '8000'
            ], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Uvicorn not available, running directly...")
            subprocess.run([sys.executable, 'app.py'], check=True)
            
    except KeyboardInterrupt:
        print("\n👋 GitResume stopped")
    except Exception as e:
        print(f"❌ Error running application: {e}")


def main():
    """Main function."""
    print("🔧 GitResume Local Runner")
    print("="*40)
    
    if not check_env_file():
        return
        
    if not check_required_env_vars():
        return
        
    run_app()


if __name__ == "__main__":
    main()
