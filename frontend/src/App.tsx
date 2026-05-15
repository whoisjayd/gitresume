import { AlertTriangle, RotateCcw, TerminalSquare } from "lucide-react";
import { useState } from "react";
import { createGeneration, type CreateGenerationInput, type CreateGenerationResponse } from "./api/generations";
import { GenerationForm } from "./components/GenerationForm";
import { ProgressTimeline } from "./components/ProgressTimeline";
import { ResultPanel } from "./components/ResultPanel";
import { useGenerationStream } from "./hooks/useGenerationStream";

export default function App() {
  const [generation, setGeneration] = useState<CreateGenerationResponse | null>(null);
  const [lastInput, setLastInput] = useState<CreateGenerationInput | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const stream = useGenerationStream(generation?.eventsUrl ?? null, generation?.statusUrl ?? null);
  const error = submitError ?? stream.error ?? stream.state?.error ?? null;
  const result = stream.state?.result ?? null;

  async function submit(input: CreateGenerationInput) {
    setIsSubmitting(true);
    setSubmitError(null);
    setLastInput(input);

    try {
      setGeneration(await createGeneration(input));
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : "Could not start generation.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="hero" aria-labelledby="page-title">
        <div className="brand-mark" aria-hidden="true"><TerminalSquare /></div>
        <div>
          <p className="eyebrow">GitResume live console</p>
          <h1 id="page-title">Turn a repo into a resume signal deck.</h1>
          <p className="hero-copy">A retro developer cockpit for streaming repository analysis, generation progress, and copy-ready resume artifacts.</p>
        </div>
      </section>

      <div className="workspace-grid">
        <GenerationForm isSubmitting={isSubmitting || stream.isStreaming} onSubmit={submit} />
        <ProgressTimeline events={stream.events} isStreaming={stream.isStreaming} failedMessage={error} />
      </div>

      {error ? (
        <section className="error-panel" role="alert">
          <AlertTriangle aria-hidden="true" />
          <div>
            <h2>Generation needs attention</h2>
            <p>{error}</p>
          </div>
          <button type="button" onClick={() => lastInput ? void submit(lastInput) : undefined} disabled={!lastInput || isSubmitting}>
            <RotateCcw size={16} aria-hidden="true" /> Retry
          </button>
        </section>
      ) : null}

      {result ? <ResultPanel result={result} /> : null}
    </main>
  );
}
