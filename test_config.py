#!/usr/bin/env python3
"""
Test script to verify GitResume configuration and identify issues.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

def check_environment():
    """Check environment configuration."""
    print("🔍 Checking GitResume Configuration...")
    print("="*50)
    
    # Load environment variables
    env_file = Path(".env")
    if not env_file.exists():
        print("❌ .env file not found!")
        return False
    
    load_dotenv()
    
    print("✅ .env file found")
    
    # Check required environment variables
    checks = {
        "GitHub OAuth": {
            "GITHUB_CLIENT_ID": os.getenv("GITHUB_CLIENT_ID"),
            "GITHUB_CLIENT_SECRET": os.getenv("GITHUB_CLIENT_SECRET"),
            "CALLBACK_URL": os.getenv("CALLBACK_URL"),
        },
        "Session": {
            "SESSION_SECRET_KEY": os.getenv("SESSION_SECRET_KEY"),
        },
        "AI Provider": {
            "GEMINI_API_KEYS": os.getenv("GEMINI_API_KEYS"),
            "OPENAI_API_KEYS": os.getenv("OPENAI_API_KEYS"),
        }
    }
    
    issues = []
    
    for category, vars in checks.items():
        print(f"\n📋 {category}:")
        for var_name, var_value in vars.items():
            if not var_value or var_value.startswith("your_"):
                print(f"  ❌ {var_name}: Not configured")
                issues.append(f"{var_name} is not properly configured")
            else:
                # Show partial value for security
                display_value = var_value[:10] + "..." if len(var_value) > 10 else var_value
                print(f"  ✅ {var_name}: {display_value}")
    
    # Check if at least one AI provider is configured
    has_ai_provider = False
    for provider in ["GEMINI_API_KEYS", "OPENAI_API_KEYS", "GROQ_API_KEYS", "CLAUDE_API_KEYS"]:
        value = os.getenv(provider)
        if value and not value.startswith("your_"):
            has_ai_provider = True
            break
    
    if not has_ai_provider:
        issues.append("No AI provider API key is configured")
    
    # Check callback URL format
    callback_url = os.getenv("CALLBACK_URL")
    if callback_url and not callback_url.startswith(("http://localhost", "https://")):
        issues.append("CALLBACK_URL should start with http://localhost for local development")
    
    print(f"\n🔍 Configuration Summary:")
    if issues:
        print("❌ Issues found:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print("✅ All required configuration appears to be set")
        return True

def test_imports():
    """Test if all required modules can be imported."""
    print("\n🧪 Testing Module Imports...")
    print("="*50)
    
    modules_to_test = [
        "fastapi",
        "github",
        "redis",
        "google.generativeai",
        "openai",
        "jinja2",
        "tree_sitter",
        "slowapi",
    ]
    
    failed_imports = []
    
    for module in modules_to_test:
        try:
            __import__(module)
            print(f"  ✅ {module}")
        except ImportError as e:
            print(f"  ❌ {module}: {e}")
            failed_imports.append(module)
    
    if failed_imports:
        print(f"\n❌ Failed to import: {', '.join(failed_imports)}")
        print("Try running: pip install -r requirements.txt --user")
        return False
    else:
        print(f"\n✅ All required modules import successfully")
        return True

def test_oauth_config():
    """Test GitHub OAuth configuration."""
    print("\n🔐 Testing GitHub OAuth Configuration...")
    print("="*50)
    
    load_dotenv()
    
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    callback_url = os.getenv("CALLBACK_URL")
    
    issues = []
    
    if not client_id or client_id == "your_github_client_id":
        issues.append("GITHUB_CLIENT_ID is not configured")
    else:
        print(f"  ✅ Client ID configured: {client_id[:8]}...")
    
    if not client_secret or client_secret == "your_github_client_secret":
        issues.append("GITHUB_CLIENT_SECRET is not configured")
    else:
        print(f"  ✅ Client Secret configured: {client_secret[:8]}...")
    
    if not callback_url:
        issues.append("CALLBACK_URL is not configured")
    elif callback_url == "http://localhost:8000/callback":
        print(f"  ✅ Callback URL configured: {callback_url}")
    else:
        print(f"  ⚠️  Callback URL: {callback_url}")
        print(f"     (Should be http://localhost:8000/callback for local development)")
    
    if issues:
        print(f"\n❌ OAuth Configuration Issues:")
        for issue in issues:
            print(f"  - {issue}")
        print(f"\n💡 To fix GitHub OAuth:")
        print(f"1. Go to: https://github.com/settings/developers")
        print(f"2. Create a new OAuth App with:")
        print(f"   - Application name: GitResume Local")
        print(f"   - Homepage URL: http://localhost:8000")
        print(f"   - Authorization callback URL: http://localhost:8000/callback")
        print(f"3. Copy the Client ID and Client Secret to your .env file")
        return False
    else:
        print(f"\n✅ OAuth configuration looks good")
        return True

def main():
    """Main test function."""
    print("🔧 GitResume Configuration Test")
    print("="*50)
    
    # Change to the script directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    all_good = True
    
    # Run tests
    if not check_environment():
        all_good = False
    
    if not test_imports():
        all_good = False
    
    if not test_oauth_config():
        all_good = False
    
    print("\n" + "="*50)
    if all_good:
        print("✅ All tests passed! GitResume should work correctly.")
        print("\n🚀 To start the application:")
        print("  python app.py")
        print("  # or")
        print("  python run_local.py")
        print("\n🌐 Then open: http://localhost:8000")
    else:
        print("❌ Some issues were found. Please fix them before running GitResume.")
        print("\n💡 Common solutions:")
        print("1. Edit .env file and add your API keys")
        print("2. Run: pip install -r requirements.txt --user")
        print("3. Set up GitHub OAuth app at: https://github.com/settings/developers")
    
    return all_good

if __name__ == "__main__":
    main()
