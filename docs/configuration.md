# ⚙️ Configuration Guide

GitResume is highly configurable via environment variables and local configuration files.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY` | API key for Google Gemini models. | - |
| `OPENAI_API_KEY` | API key for OpenAI models. | - |
| `ANTHROPIC_API_KEY`| API key for Anthropic (Claude) models. | - |
| `GROQ_API_KEY` | API key for Groq models. | - |
| `GITRESUME_MODEL` | The LLM model to use for generation. | `gemini/gemini-1.5-flash` |
| `GITRESUME_ARTIFACTS_DIR` | Directory where analysis results are stored. | `./artifacts` |
| `GITRESUME_LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |

## Configuration Files

GitResume looks for configuration in the following order:

1.  **Environment Variables**: Highest priority.
2.  **`.env` file**: Key-value pairs in the current working directory.
3.  **`env.yaml` file**: YAML format configuration in the current working directory.

### Example `env.yaml`
```yaml
GEMINI_API_KEY: "your-gemini-key"
GITRESUME_MODEL: "gemini/gemini-1.5-pro"
GITRESUME_ARTIFACTS_DIR: "./my-artifacts"
```

## Model Selection

GitResume uses [LiteLLM](https://docs.litellm.ai/docs/providers), meaning you can use almost any provider. Use the provider prefix followed by the model name.

Examples:
- `gemini/gemini-1.5-flash`
- `openai/gpt-4o`
- `anthropic/claude-3-5-sonnet-20240620`
- `groq/llama3-70b-8192`

---

## 🔐 Data Redaction

By default, GitResume attempts to redact sensitive information (like API keys, passwords, and tokens) from the code context before sending it to the LLM.

You can customize redaction behavior (feature coming soon) to add your own patterns.
