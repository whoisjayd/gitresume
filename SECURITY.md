# Security Policy

GitResume takes the security of your code and API keys seriously. For detailed information on data handling, API key redaction, and how we interact with LLM providers, please see our full [Security Documentation](docs/security.md).

## Reporting a Vulnerability

If you discover a security vulnerability, please do the following:

- **Do not** open a public issue.
- Report the vulnerability via [GitHub Security Advisories](https://github.com/whoisjayd/gitresume/security/advisories/new) or email the maintainer at `contactjaydeepsolanki@gmail.com`.
- We will respond within 48 hours and coordinate a fix.
- If the vulnerability is confirmed, we will release a patch and notify users.

## API Key Handling

- GitResume never stores your API keys on its own servers (it has none).
- Keys are only used to authenticate with your chosen LLM provider.
- We implement automated redaction to ensure keys do not appear in application logs.
