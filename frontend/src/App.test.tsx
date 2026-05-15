import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { ProgressTimeline } from "./components/ProgressTimeline";
import { ResultPanel } from "./components/ResultPanel";

type Listener = (event: MessageEvent<string>) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];

  readonly url: string;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(eventName: string, listener: Listener) {
    const listeners = this.listeners.get(eventName) ?? [];
    listeners.push(listener);
    this.listeners.set(eventName, listeners);
  }

  emit(eventName: string, data: unknown) {
    const event = new MessageEvent(eventName, { data: JSON.stringify(data) });
    for (const listener of this.listeners.get(eventName) ?? []) {
      listener(event);
    }
  }

  emitRaw(eventName: string, data: string) {
    const event = new MessageEvent(eventName, { data });
    for (const listener of this.listeners.get(eventName) ?? []) {
      listener(event);
    }
  }
}

const successState = {
  generationId: "gen-1",
  status: "succeeded",
  repositoryUrl: "https://github.com/acme/rocket",
  jobDescription: "Backend role",
  result: {
    projectTitle: "Rocket Console",
    techStack: ["React", "FastAPI", "Redis"],
    bulletPoints: [
      "Built a real-time repository analysis pipeline.",
      "Improved resume generation accuracy with structured prompts.",
    ],
    additionalNotes: "Uses SSE for live progress updates.",
    futurePlans: "Add export templates.",
    potentialAdvancements: "Queue-based orchestration for high throughput.",
    interviewQuestions: [
      {
        question: "How did you stream progress?",
        answer: "The client consumes named server-sent events.",
        category: "Frontend",
      },
    ],
  },
  createdAt: "2026-05-15T00:00:00Z",
  updatedAt: "2026-05-15T00:01:00Z",
};

function mockFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);

    if (url === "/api/generations" && init?.method === "POST") {
      return new Response(
        JSON.stringify({
          generationId: "gen-1",
          statusUrl: "/api/generations/gen-1",
          eventsUrl: "/api/generations/gen-1/events",
          redirectPath: "/generations/gen-1",
        }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      );
    }

    if (url === "/api/generations/gen-1") {
      return new Response(JSON.stringify(successState), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response("Not found", { status: 404 });
  });
}

describe("GitResume SPA", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
  });

  it("submits a generation request without exposing the GitHub token in stream URLs", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.click(screen.getByRole("button", { name: /add job description/i }));
    await user.type(screen.getByLabelText(/job description/i), "Backend role");
    await user.type(screen.getByLabelText(/github token/i), "ghp_secret_token");
    await user.click(screen.getByRole("button", { name: /generate resume/i }));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/generations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          repoUrl: "https://github.com/acme/rocket",
          jobDescription: "Backend role",
          githubToken: "ghp_secret_token",
        }),
      }),
    );
    expect(MockEventSource.instances[0].url).toBe("/api/generations/gen-1/events");
    expect(MockEventSource.instances[0].url).not.toContain("ghp_secret_token");
  });

  it("renders progress events and falls back to status fetch for completed results", async () => {
    mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.click(screen.getByRole("button", { name: /generate resume/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

    act(() => {
      MockEventSource.instances[0].emit("validating", {
        generationId: "gen-1",
        eventType: "validating",
        status: "validating",
        message: "Checking repository access",
        sequence: 2,
        createdAt: "2026-05-15T00:00:02Z",
      });
      MockEventSource.instances[0].emit("completed", {
        generationId: "gen-1",
        eventType: "completed",
        status: "completed",
        message: "Resume ready",
        sequence: 6,
        createdAt: "2026-05-15T00:00:06Z",
      });
    });

    expect(await screen.findByText(/checking repository access/i)).toBeTruthy();
    expect(await screen.findByRole("heading", { name: /rocket console/i })).toBeTruthy();
    expect(screen.getByText("React")).toBeTruthy();
    expect(screen.getByText(/built a real-time repository analysis pipeline/i)).toBeTruthy();
    expect(screen.getByText(/how did you stream progress/i)).toBeTruthy();
  });

  it("shows SSE errors with a retry action", async () => {
    mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.click(screen.getByRole("button", { name: /generate resume/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

    act(() => {
      MockEventSource.instances[0].emit("failed", {
        generationId: "gen-1",
        eventType: "failed",
        status: "failed",
        message: "Repository could not be cloned",
        sequence: 3,
        createdAt: "2026-05-15T00:00:03Z",
      });
    });

    expect((await screen.findByRole("alert")).textContent).toMatch(/repository could not be cloned/i);
    expect(screen.getByRole("button", { name: /retry/i }).hasAttribute("disabled")).toBe(false);
  });

  it("recovers final status when the progress stream disconnects after completion", async () => {
    mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.click(screen.getByRole("button", { name: /generate resume/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

    act(() => {
      MockEventSource.instances[0].onerror?.();
    });

    expect(await screen.findByRole("heading", { name: /rocket console/i })).toBeTruthy();
    expect(screen.queryByText(/progress stream disconnected/i)).toBeNull();
  });

  it("treats JSON-but-invalid stream payloads as recoverable errors", async () => {
    mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.click(screen.getByRole("button", { name: /generate resume/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

    act(() => {
      MockEventSource.instances[0].emitRaw("completed", JSON.stringify({ data: "not-an-object" }));
    });

    expect((await screen.findByRole("alert")).textContent).toMatch(/progress stream sent an unreadable update/i);
    expect(MockEventSource.instances[0].close).toHaveBeenCalled();
  });

  it("surfaces malformed stream payloads as recoverable errors", async () => {
    mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.click(screen.getByRole("button", { name: /generate resume/i }));
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

    act(() => {
      MockEventSource.instances[0].emitRaw("analyzing", "not-json");
    });

    expect((await screen.findByRole("alert")).textContent).toMatch(/progress stream sent an unreadable update/i);
    expect(MockEventSource.instances[0].close).toHaveBeenCalled();
  });

  it("copies plain text and LaTeX resume content", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    Object.defineProperty(Navigator.prototype, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    render(<ResultPanel result={successState.result} />);

    const result = await screen.findByRole("region", { name: /generated resume/i });
    fireEvent.click(within(result).getByRole("button", { name: /copy plain text/i }));
    fireEvent.click(within(result).getByRole("button", { name: /copy latex/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
    expect(writeText).toHaveBeenNthCalledWith(1, expect.stringContaining("Rocket Console"));
    expect(writeText).toHaveBeenNthCalledWith(2, expect.stringContaining("\\section*{Rocket Console}"));
    expect(writeText).toHaveBeenNthCalledWith(2, expect.stringContaining("Future plans"));
    expect(writeText).toHaveBeenNthCalledWith(2, expect.stringContaining("How did you stream progress?"));
  });

  it("renders all required generation progress phases", () => {
    render(
      <ProgressTimeline
        events={[
          event("queued", 1, "Job queued"),
          event("validating", 2, "Checking repository"),
          event("cloning", 3, "Cloning source"),
          event("analyzing", 4, "Analyzing files"),
          event("generating", 5, "Generating resume"),
          event("succeeded", 6, "Resume ready"),
        ]}
        isStreaming={false}
      />,
    );

    expect(screen.getByText("Job queued")).toBeTruthy();
    expect(screen.getByText("Checking repository")).toBeTruthy();
    expect(screen.getByText("Cloning source")).toBeTruthy();
    expect(screen.getByText("Analyzing files")).toBeTruthy();
    expect(screen.getByText("Generating resume")).toBeTruthy();
    expect(screen.getByText("Resume ready")).toBeTruthy();
  });

  it("maps completed SSE events onto the succeeded timeline phase", () => {
    render(
      <ProgressTimeline
        events={[event("completed", 6, "Resume ready")]}
        isStreaming={false}
      />,
    );

    expect(screen.getByText("Succeeded").closest("article")?.className).toContain("complete");
    expect(screen.getByText("Resume ready")).toBeTruthy();
  });
});

function event(eventType: "queued" | "validating" | "cloning" | "analyzing" | "generating" | "succeeded" | "completed", sequence: number, message: string) {
  return {
    generationId: "gen-1",
    eventType,
    status: eventType === "completed" ? "succeeded" : eventType,
    message,
    sequence,
    createdAt: `2026-05-15T00:00:0${sequence}Z`,
  };
}
