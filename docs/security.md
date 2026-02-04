# Security & Data Handling

GitResume is built with a security-first, local-first mindset.

## Data Handling

- **Local-First**: GitResume is designed to run locally. Analysis of your source code happens entirely on your machine.
- **No Data Collection**: We do not collect telemetry or usage data.
- **LLM Interaction**: Only the necessary code context (stripped of non-essential files) is sent to the LLM provider you configure.
- **Artifacts**: Analysis results and resumes are stored in the `artifacts/` directory by default.
    - **Warning**: These artifacts contain structural information about your code. Ensure `artifacts/` is added to your `.gitignore`.

## API Key Security

- **Environment Variables**: API keys should be provided via environment variables or a local `.env`/`env.yaml` file.
- **Redaction**: GitResume uses regex patterns to identify and redact API keys and common secrets before they are sent to LLM providers or written to local logs.
- **Zero Storage**: We never persist your API keys to disk (except when you store them in your own `.env` file).

## LLM Providers

GitResume uses [LiteLLM](https://github.com/BerriAI/litellm) to communicate with providers.
- **Privacy**: Data sent to providers (OpenAI, Gemini, Anthropic, etc.) is subject to their respective privacy policies.
- **Recommendation**: For maximum privacy, use providers/models with "Zero Data Retention" (ZDR) policies for API usage.

## Reporting Vulnerabilities

Please see [SECURITY.md](../SECURITY.md) for instructions on how to report security issues.
