# Security Policy

GitResume takes the security of your code and API keys seriously.

## Data Handling
- **Local-First**: GitResume is designed to run locally. Analysis happens on your machine.
- **Temporary Storage**: When analyzing a local repository, GitResume reads the files but does not upload them to any central server (except for the LLM provider you choose).
- **Artifacts**: Analysis results and resumes are stored in the `artifacts/` directory by default. This directory should be added to your `.gitignore` if you are working within a repository.

## API Keys
- **Redaction**: GitResume attempts to strip sensitive information before sending data to LLM providers. However, you should ensure your code doesn't contain hardcoded secrets.
- **Environment Variables**: Use `.env` or `env.yaml` to manage your API keys. Never commit these files to version control.
- **LLM Providers**: Data sent to providers (OpenAI, Gemini, Anthropic, etc.) is subject to their respective privacy policies. We recommend using providers that offer "zero data retention" for API calls if you have strict security requirements.

## Reporting a Vulnerability
If you discover a security vulnerability within GitResume, please open an issue on GitHub or contact the maintainer directly.
