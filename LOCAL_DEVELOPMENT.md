# 🚀 GitResume - Local Development Guide

This guide will help you set up and run GitResume locally to test the new "My Contributions Only" feature.

## 📋 Prerequisites

1. **Python 3.11+** - [Download here](https://www.python.org/downloads/)
2. **Git** - [Download here](https://git-scm.com/downloads/)
3. **API Keys** (at least one):
   - **Gemini API Key** (Recommended) - [Get here](https://makersuite.google.com/app/apikey)
   - **OpenAI API Key** (Alternative) - [Get here](https://platform.openai.com/api-keys)
4. **GitHub Token** (Required for the new feature) - [Get here](https://github.com/settings/tokens)

## 🔧 Quick Setup

### Option 1: Automated Setup (Recommended)

```bash
# Run the setup script
python setup_local.py

# Edit the .env file with your API keys
# (The script will create a template for you)

# Run the application
python run_local.py
```

### Option 2: Manual Setup

1. **Install Dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

2. **Create Environment File:**
   ```bash
   # Copy the example environment file
   copy env.example.yaml .env
   # or on Linux/Mac:
   cp env.example.yaml .env
   ```

3. **Configure API Keys:**
   Edit `.env` file and add your keys:
   ```env
   # Required: At least one AI provider
   GEMINI_API_KEYS=your_gemini_api_key_here
   # or
   OPENAI_API_KEYS=your_openai_api_key_here
   
   # Required for "My Contributions" feature
   GITHUB_TOKEN=ghp_your_github_personal_access_token
   
   # Basic settings
   ENVIRONMENT=development
   SESSION_SECRET_KEY=dev-secret-key-change-this
   ```

4. **Run the Application:**
   ```bash
   python app.py
   # or
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

## 🧪 Testing the New Feature

### Setup for Testing "My Contributions Only"

1. **Ensure you have a GitHub token in your `.env` file**
2. **Find a repository where you have commits** (can be your own or a collaborative project)
3. **Make sure your GitHub token has `repo` access** (needed to read commit information)

### Testing Steps

1. **Start the application:**
   ```bash
   python run_local.py
   ```

2. **Open your browser to:** `http://localhost:8000`

3. **Test the new feature:**
   - Enter a repository URL where you have commits
   - ✅ **Check the "Analyze only my contributions" checkbox**
   - Enter your GitHub token (if not in environment)
   - Click "Generate Resume Content"

4. **Expected behavior:**
   - The system will clone the repository
   - Filter commits to find only yours
   - Analyze only files you've modified
   - Generate resume content based on your specific contributions
   - Show statistics about your contributions (commits, lines added/deleted, etc.)

### Testing Scenarios

#### Scenario 1: Your Own Repository
```
Repository: https://github.com/yourusername/your-repo
Expected: All content analyzed (since all commits are yours)
```

#### Scenario 2: Collaborative Repository
```
Repository: https://github.com/someorg/collaborative-project
Expected: Only your contributions analyzed and highlighted
```

#### Scenario 3: Fork Where You Contributed
```
Repository: https://github.com/original/project (where you have commits)
Expected: Only your specific commits and file changes analyzed
```

## 🔍 Feature Details

### What the "My Contributions Only" feature does:

1. **Authenticates** with GitHub using your token
2. **Identifies** your email addresses and username
3. **Filters** git commits to find only yours
4. **Analyzes** only files you've modified
5. **Generates** resume content focused on your specific contributions
6. **Provides** statistics about your impact:
   - Number of commits by you
   - Lines of code added/deleted
   - Files modified
   - Technologies you worked with

### UI Changes:

- ✅ New checkbox: "Analyze only my contributions"
- ℹ️ Info tooltip explaining the feature
- ⚠️ Warning when GitHub token is required
- 📊 Progress updates during filtering
- 📈 User-specific statistics in results

## 🐛 Troubleshooting

### Common Issues:

1. **"GitHub token is required" error:**
   - Make sure you have `GITHUB_TOKEN` in your `.env` file
   - Or enter it manually in the web interface

2. **"Invalid GitHub token" error:**
   - Check your token is valid and not expired
   - Ensure it has `repo` access permissions

3. **"No commits found" error:**
   - Make sure you actually have commits in the repository
   - Check that your email in GitHub matches your git config
   - Verify the repository URL is correct

4. **Import errors:**
   ```bash
   pip install --upgrade -r requirements.txt
   ```

5. **Redis connection warnings:**
   - These are safe to ignore for local development
   - The app will fall back to memory-based caching

### Debug Mode:

Add this to your `.env` for more detailed logging:
```env
ENVIRONMENT=development
```

### Check Your Git Configuration:

```bash
# Check your git email (should match your GitHub account)
git config --global user.email

# Check your GitHub username
git config --global user.name
```

## 📊 Expected Output

When testing with the "My Contributions Only" feature, you should see:

1. **Status updates** during processing:
   - "Cloning repository..."
   - "Filtering your contributions..."
   - "Found X files with your contributions"

2. **Personalized resume content** that focuses on:
   - Your specific coding contributions
   - Technologies you actually worked with
   - Achievements based on your commits
   - Interview questions relevant to your work

3. **User statistics** showing:
   - Total commits by you
   - Lines added/deleted by you
   - Files you modified
   - Your contribution impact

## 🚀 Next Steps

After testing locally:

1. **Verify the feature works** with different repositories
2. **Test edge cases** (empty repos, no user commits, etc.)
3. **Check the resume content quality** - it should be personalized to your contributions
4. **Test with both public and private repositories**
5. **Try with different AI providers** (Gemini vs OpenAI)

## 📞 Support

If you encounter issues:

1. Check the console logs for detailed error messages
2. Verify your API keys are correct
3. Ensure your GitHub token has proper permissions
4. Test with a simple repository first
5. Check that all dependencies are installed correctly

The feature adds significant value for developers working on collaborative projects who want to showcase their specific contributions rather than the entire project scope.
