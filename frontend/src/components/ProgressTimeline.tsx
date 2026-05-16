import { CheckCircle2, CircleDot, Loader2, XCircle } from "lucide-react";
import type { GenerationEvent, GenerationStatus } from "../api/generations";

const steps: { status: GenerationStatus; label: string; description: string }[] = [
  { status: "queued", label: "Queued", description: "Job accepted" },
  { status: "validating", label: "Validating", description: "Checking repository access" },
  { status: "cloning", label: "Cloning", description: "Pulling source code" },
  { status: "analyzing", label: "Analyzing", description: "Reading project signals" },
  { status: "generating", label: "Generating", description: "Writing resume content" },
  { status: "succeeded", label: "Succeeded", description: "Resume ready" },
];

type Props = {
  events: GenerationEvent[];
  isStreaming: boolean;
  failedMessage?: string | null;
};

export function ProgressTimeline({ events, isStreaming, failedMessage }: Props) {
  const latestByType = new Map<GenerationStatus, GenerationEvent>(
    events.map((event) => [event.eventType === "completed" ? "succeeded" : event.eventType, event]),
  );
  const latestEvent = events.at(-1);
  const liveMessage = failedMessage ?? latestEvent?.message ?? (isStreaming ? "Generation is starting." : "No generation is running.");

  return (
    <section className="console-card timeline-panel" aria-label="Generation progress">
      <div className="section-kicker">Live trace</div>
      <p className="sr-only" role="status" aria-live="polite" aria-label="Generation progress updates">
        {liveMessage}
      </p>
      <div className="timeline-grid">
        {steps.map((step) => {
          const event = latestByType.get(step.status);
          const active = events.at(-1)?.eventType === step.status && isStreaming;
          const complete = Boolean(event);

          return (
            <article className={`timeline-step ${active ? "active" : ""} ${complete ? "complete" : ""}`} key={step.status}>
              <div className="step-icon">
                {step.status === "succeeded" && complete ? <CheckCircle2 aria-hidden="true" /> : active ? <Loader2 aria-hidden="true" /> : <CircleDot aria-hidden="true" />}
              </div>
              <div>
                <h3>{step.label}</h3>
                <p>{event?.message ?? step.description}</p>
              </div>
            </article>
          );
        })}
        {failedMessage ? (
          <article className="timeline-step failed">
            <div className="step-icon"><XCircle aria-hidden="true" /></div>
            <div>
              <h3>Failed</h3>
              <p>{failedMessage}</p>
            </div>
          </article>
        ) : null}
      </div>
    </section>
  );
}
