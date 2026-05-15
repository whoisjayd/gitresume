import { useEffect, useState } from "react";
import type { GenerationEvent, GenerationState, GenerationStatus, ResumeResult } from "../api/generations";
import { getGeneration } from "../api/generations";

const eventNames: GenerationStatus[] = [
  "queued",
  "validating",
  "cloning",
  "analyzing",
  "generating",
  "succeeded",
  "completed",
  "failed",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function invalidPayload(source: EventSource) {
  setTimeout(() => source.close(), 0);
}

function eventResult(event: GenerationEvent): ResumeResult | undefined {
  if (!isRecord(event.data)) {
    return undefined;
  }

  if ("result" in event.data && isRecord(event.data.result)) {
    return event.data.result as ResumeResult;
  }

  if ("projectTitle" in event.data || "bulletPoints" in event.data) {
    return event.data as ResumeResult;
  }

  return undefined;
}

export function useGenerationStream(eventsUrl: string | null, statusUrl: string | null) {
  const [events, setEvents] = useState<GenerationEvent[]>([]);
  const [state, setState] = useState<GenerationState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  useEffect(() => {
    if (!eventsUrl || !statusUrl) {
      return undefined;
    }

    const source = new EventSource(eventsUrl);
    let active = true;
    setIsStreaming(true);
    setError(null);
    setEvents([]);
    setState(null);

    const handleEvent = (event: MessageEvent<string>) => {
      let parsed: GenerationEvent;

      try {
        parsed = JSON.parse(event.data) as GenerationEvent;
      } catch {
        setError("The progress stream sent an unreadable update. You can retry the generation.");
        setIsStreaming(false);
        invalidPayload(source);
        return;
      }

      if (!isRecord(parsed) || typeof parsed.eventType !== "string" || typeof parsed.message !== "string") {
        setError("The progress stream sent an unreadable update. You can retry the generation.");
        setIsStreaming(false);
        invalidPayload(source);
        return;
      }

      setEvents((current) => [...current.filter((item) => item.sequence !== parsed.sequence), parsed].sort((a, b) => a.sequence - b.sequence));

      if (parsed.eventType === "failed") {
        setError(parsed.message || "Generation failed. Please try again.");
        setIsStreaming(false);
        source.close();
        return;
      }

      if (parsed.eventType === "completed" || parsed.eventType === "succeeded") {
        const result = eventResult(parsed);
        if (result) {
          setState((current) => ({
            generationId: parsed.generationId,
            status: "succeeded",
            repositoryUrl: current?.repositoryUrl ?? "",
            jobDescription: current?.jobDescription,
            result,
            createdAt: current?.createdAt ?? parsed.createdAt,
            updatedAt: parsed.createdAt,
          }));
          setIsStreaming(false);
          source.close();
          return;
        }

        void getGeneration(statusUrl)
          .then((nextState) => {
            if (active) {
              setState(nextState);
            }
          })
          .catch((reason: unknown) => {
            if (active) {
              setError(reason instanceof Error ? reason.message : "Could not load generated resume.");
            }
          })
          .finally(() => {
            if (active) {
              setIsStreaming(false);
              source.close();
            }
          });
      }
    };

    for (const eventName of eventNames) {
      source.addEventListener(eventName, handleEvent);
    }

    source.onerror = () => {
      void getGeneration(statusUrl)
        .then((nextState) => {
          if (!active) {
            return;
          }
          setState(nextState);
          if (nextState.status === "succeeded" && nextState.result) {
            setError(null);
          } else {
            setError(nextState.error ?? "The progress stream disconnected. You can retry the generation.");
          }
        })
        .catch((reason: unknown) => {
          if (active) {
            setError(reason instanceof Error ? reason.message : "The progress stream disconnected. You can retry the generation.");
          }
        })
        .finally(() => {
          if (active) {
            setIsStreaming(false);
            source.close();
          }
        });
    };

    return () => {
      active = false;
      source.close();
    };
  }, [eventsUrl, statusUrl]);

  return { events, state, error, isStreaming };
}
