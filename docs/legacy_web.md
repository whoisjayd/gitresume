# Legacy Web Application

## Why was the old web app removed?

The original GitResume started as a monolithic FastAPI web application hosted at `gitresume.live`. While functional, it faced several challenges:

1.  **Maintenance Overhead**: Managing a live deployment, database, and Redis instance required significant time and financial resources.
2.  **Scalability**: Handling large repository clones on a single server was resource-intensive.
3.  **Local-First Preference**: Many developers prefer to run analysis tools locally on their own machines without authenticating via OAuth or uploading code to a third-party service.

## Transition to CLI-First

GitResume has been refactored into a **CLI-first** tool. This move offers:

- **Privacy**: No need for GitHub OAuth; it works on your local clones.
- **Portability**: Installable via `pip` or `uv`.
- **Flexibility**: Generate resumes as Markdown or JSON, and view them via a lightweight local dashboard (`gitresume web`).

The core logic remains the same, but the delivery mechanism is now optimized for individual developer use.
