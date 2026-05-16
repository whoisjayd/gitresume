/// <reference types="node" />
import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import type { DashboardSettings, ModelEntry, OAuthProviderStatus, SessionInfo } from "./api/generations";
import { ProgressTimeline } from "./components/ProgressTimeline";
import { ResultPanel } from "./components/ResultPanel";

const stylesheet = readFileSync(join(process.cwd(), "src", "styles.css"), "utf-8");

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

const defaultSession: SessionInfo = {
  isAuthenticated: false,
  githubUser: null,
  githubUserId: null,
  appMode: "self_hosted",
  loginRequired: false,
};

const defaultModels: { models: ModelEntry[] } = {
  models: [
    {
      id: "openai/gpt-4o-mini",
      provider: "openai",
      mode: "chat",
      displayName: "GPT 4O Mini",
      authType: "api_key",
      supportsOauth: false,
      requiresApiKey: true,
      isAvailable: true,
      status: null,
      contextWindow: 128000,
    },
    {
      id: "github_copilot/gpt-4.1",
      provider: "github_copilot",
      mode: "chat",
      displayName: "GPT 4.1",
      authType: "oauth",
      supportsOauth: true,
      requiresApiKey: false,
      isAvailable: false,
      status: "OAuth connection is not implemented yet.",
    },
    {
      id: "gemini/gemini-1.5-flash",
      provider: "gemini",
      mode: "chat",
      displayName: "Gemini 1.5 Flash",
      authType: "api_key",
      supportsOauth: false,
      requiresApiKey: true,
      isAvailable: true,
      status: null,
    },
  ],
};

const defaultOauthProviders: { providers: OAuthProviderStatus[] } = {
  providers: [
    {
      provider: "github_copilot",
      connected: false,
      executable: false,
      supportsDeviceCode: false,
      connectionType: null,
      accountLabel: null,
      connectedAt: null,
      accounts: [],
      status: "Connect github_copilot with a manually configured server-stored OAuth token.",
    },
    {
      provider: "chatgpt",
      connected: false,
      executable: false,
      supportsDeviceCode: false,
      connectionType: null,
      accountLabel: null,
      connectedAt: null,
      accounts: [],
      status: "Connect chatgpt with a manually configured server-stored OAuth token.",
    },
  ],
};

const connectedOauthModels: { models: ModelEntry[] } = {
  models: defaultModels.models.map((model) =>
    model.provider === "github_copilot"
      ? { ...model, isAvailable: true, status: null }
      : model,
  ),
};

const defaultSettings: DashboardSettings = {
  appMode: "self_hosted",
  allowSavedByok: true,
  savedKeysEnabled: true,
  loginRequired: false,
  defaultModel: "openai/gpt-4o-mini",
  providerKeys: [
    {
      id: "key-123",
      provider: "openai",
      label: "Work OpenAI",
      model: "openai/gpt-4o-mini",
      createdAt: "2026-05-15T00:00:00Z",
      lastUsedAt: null,
      isActive: true,
    },
    {
      id: "key-gemini",
      provider: "gemini",
      label: "Gemini scoped",
      model: "gemini/gemini-1.5-flash",
      createdAt: "2026-05-15T00:01:00Z",
      lastUsedAt: null,
      isActive: true,
    },
  ],
};

function githubAccount(id: string, accountLabel: string) {
  return {
    id,
    provider: "github_copilot",
    connectionType: "manual_token" as const,
    accountLabel,
    connectedAt: "2026-05-15T00:00:00Z",
    expiresAt: null,
    lastRefreshedAt: null,
    lastUsedAt: null,
    isActive: true,
    executable: true,
    status: null,
  };
}

function mockFetch(options: { session?: typeof defaultSession; models?: typeof defaultModels; settings?: typeof defaultSettings; oauthProviders?: typeof defaultOauthProviders } = {}) {
  const session = options.session ?? defaultSession;
  let models = options.models ?? defaultModels;
  let oauthProviders = options.oauthProviders ?? defaultOauthProviders;
  let settings = options.settings ?? defaultSettings;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);

    if (url === "/api/session" && (!init?.method || init.method === "GET")) {
      return new Response(JSON.stringify(session), { status: 200, headers: { "Content-Type": "application/json" } });
    }

    if (url === "/api/session/logout" && init?.method === "POST") {
      return new Response(JSON.stringify({ ...session, isAuthenticated: false, githubUser: null, githubUserId: null }), { status: 200, headers: { "Content-Type": "application/json" } });
    }

    if (url === "/api/models") {
      return new Response(JSON.stringify(models), { status: 200, headers: { "Content-Type": "application/json" } });
    }

    if (url === "/api/oauth-providers" && (!init?.method || init.method === "GET")) {
      return new Response(JSON.stringify(oauthProviders), { status: 200, headers: { "Content-Type": "application/json" } });
    }

    if (url === "/api/oauth-providers/github_copilot/connect" && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      const accounts = oauthProviders.providers.find((provider) => provider.provider === "github_copilot")?.accounts ?? [];
      const account = githubAccount(`acct-${accounts.length + 1}`, body.accountLabel || `Account ${accounts.length + 1}`);
      oauthProviders = {
        providers: oauthProviders.providers.map((provider) => provider.provider === "github_copilot" ? { ...provider, connected: true, executable: true, connectionType: "manual_token", accountLabel: account.accountLabel, accounts: [...accounts, account], status: "Connected with server-stored manual OAuth token account(s)." } : provider),
      };
      models = connectedOauthModels;
      return new Response(JSON.stringify(oauthProviders.providers[0]), { status: 200, headers: { "Content-Type": "application/json" } });
    }

    if (url.startsWith("/api/oauth-providers/github_copilot/accounts/") && init?.method === "PUT") {
      const accountId = url.split("/").at(-1);
      oauthProviders = {
        providers: oauthProviders.providers.map((provider) => provider.provider === "github_copilot" ? { ...provider, accounts: (provider.accounts ?? []).map((account) => account.id === accountId ? { ...account, lastRefreshedAt: "2026-05-15T00:03:00Z" } : account) } : provider),
      };
      return new Response(JSON.stringify(oauthProviders.providers[0]), { status: 200, headers: { "Content-Type": "application/json" } });
    }

    if (url.startsWith("/api/oauth-providers/github_copilot/accounts/") && init?.method === "DELETE") {
      const accountId = url.split("/").at(-1);
      oauthProviders = {
        providers: oauthProviders.providers.map((provider) => provider.provider === "github_copilot" ? { ...provider, accounts: (provider.accounts ?? []).filter((account) => account.id !== accountId) } : provider),
      };
      return new Response(null, { status: 204 });
    }

    if (url === "/api/oauth-providers/github_copilot" && init?.method === "DELETE") {
      oauthProviders = defaultOauthProviders;
      models = defaultModels;
      return new Response(null, { status: 204 });
    }

    if (url === "/api/settings" && (!init?.method || init.method === "GET")) {
      return new Response(JSON.stringify(settings), { status: 200, headers: { "Content-Type": "application/json" } });
    }

    if (url === "/api/settings/provider-keys" && init?.method === "POST") {
      settings = {
        ...settings,
        providerKeys: [
          ...settings.providerKeys,
          {
            id: "key-new",
            provider: "gemini",
            label: "Gemini Personal",
            model: null,
            createdAt: "2026-05-15T00:02:00Z",
            lastUsedAt: null,
            isActive: true,
          },
        ],
      };
      return new Response(JSON.stringify(settings.providerKeys.at(-1)), { status: 201, headers: { "Content-Type": "application/json" } });
    }

    if (url === "/api/settings/provider-keys/key-123" && init?.method === "DELETE") {
      settings = { ...settings, providerKeys: [] };
      return new Response(null, { status: 204 });
    }

    if (url === "/api/settings/default-model" && init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      settings = { ...settings, defaultModel: body.model };
      return new Response(JSON.stringify(settings), { status: 200, headers: { "Content-Type": "application/json" } });
    }

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
    vi.restoreAllMocks();
    try {
      window.localStorage.clear();
    } catch {
      // Tests intentionally exercise storage failures.
    }
  });

  it("renders dashboard navigation, GitHub session controls, and persists theme preference", async () => {
    mockFetch({ session: { ...defaultSession, isAuthenticated: true, githubUser: "octocat", githubUserId: "123", appMode: "hosted", loginRequired: false } });
    const user = userEvent.setup();

    render(<App />);

    expect((await screen.findByRole("link", { name: /generate/i })).getAttribute("href")).toBe("#generate");
    expect(screen.getByRole("link", { name: /dashboard/i }).getAttribute("href")).toBe("#dashboard");
    expect(screen.getByRole("link", { name: /models/i }).getAttribute("href")).toBe("#models");
    expect(screen.getByRole("link", { name: /settings/i }).getAttribute("href")).toBe("#settings");
    expect(screen.getAllByRole("link", { name: /docs/i })[0].getAttribute("href")).toBe("/docs");
    expect(screen.getAllByRole("link", { name: /github repo/i })[0].getAttribute("href")).toBe("https://github.com/WhoIsJayD/gitresume");
    expect(screen.getByText(/octocat/i)).toBeTruthy();
    expect(screen.getAllByText(/hosted/i).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /switch to light theme/i }));

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("gitresume.theme")).toBe("light");
  });

  it("renders and toggles when localStorage throws", async () => {
    mockFetch();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("link", { name: /generate/i })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /switch to light theme/i }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("uses theme variables for page and surface backgrounds instead of hard-coded dark values", () => {
    const bodyRule = stylesheet.match(/body \{[\s\S]*?\n\}/)?.[0] ?? "";
    expect(stylesheet).toContain("--body-background:");
    expect(stylesheet).toContain("--button-bg:");
    expect(stylesheet).toContain("--brand-bg:");
    expect(stylesheet).toContain("--timeline-step-bg:");
    expect(stylesheet).toContain("--input-bg:");
    expect(stylesheet).toContain("background: var(--body-background);");
    expect(stylesheet).toContain("background: var(--button-bg);");
    expect(stylesheet).toContain("background: var(--brand-bg);");
    expect(stylesheet).toContain("background: var(--timeline-step-bg);");
    expect(bodyRule).not.toMatch(/#[0-9a-f]{6}/i);
    expect(stylesheet).not.toContain("background: #191b16;");
    expect(stylesheet).not.toContain("background: #151711;");
  });

  it("shows hosted login-required messaging and links login to the dashboard", async () => {
    mockFetch({ session: { ...defaultSession, appMode: "hosted", loginRequired: true } });

    render(<App />);

    expect(await screen.findByText(/hosted dashboards require github login/i)).toBeTruthy();
    expect(screen.getByRole("link", { name: /login with github/i }).getAttribute("href")).toBe("/api/session/login?next=/dashboard");
  });

  it("connects and disconnects OAuth providers without leaking manual tokens", async () => {
    const fetchMock = mockFetch();
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("heading", { name: /oauth model providers/i })).toBeTruthy();
    expect(screen.getAllByText(/github_copilot/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/not connected/i).length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText(/github_copilot manual token/i), "ghu-ui-secret-token");
    await user.type(screen.getByLabelText(/github_copilot account label/i), "Work Copilot");
    await user.click(screen.getByRole("button", { name: /^connect github_copilot$/i }));

    await screen.findByRole("button", { name: /disconnect github_copilot/i });
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === "/api/models")).toHaveLength(2));
    expect(screen.queryByDisplayValue("ghu-ui-secret-token")).toBeNull();
    expect(document.body.textContent).not.toContain("ghu-ui-secret-token");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/oauth-providers/github_copilot/connect",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ accessToken: "ghu-ui-secret-token", refreshToken: null, expiresAt: null, accountLabel: "Work Copilot" }),
      }),
    );

    await user.click(screen.getByRole("button", { name: /disconnect github_copilot/i }));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === "/api/models")).toHaveLength(3));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/oauth-providers/github_copilot",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("lists multiple OAuth accounts and refreshes or deletes one account", async () => {
    const fetchMock = mockFetch({
      oauthProviders: {
        providers: [
          {
            ...defaultOauthProviders.providers[0],
            connected: true,
            executable: true,
            connectionType: "manual_token",
            accountLabel: "Work Copilot",
            accounts: [githubAccount("acct-1", "Work Copilot"), githubAccount("acct-2", "Personal Copilot")],
          },
          defaultOauthProviders.providers[1],
        ],
      },
    });
    const user = userEvent.setup();

    render(<App />);

    expect((await screen.findAllByText(/Work Copilot/i)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Personal Copilot/i).length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText(/github_copilot manual token/i), "ghu-third-secret");
    await user.type(screen.getByLabelText(/github_copilot refresh token/i), "refresh-third-secret");
    await user.type(screen.getByLabelText(/github_copilot token expiry/i), "2026-06-01T12:30");
    await user.type(screen.getByLabelText(/github_copilot account label/i), "Side Copilot");
    await user.click(screen.getByRole("button", { name: /^connect github_copilot$/i }));

    await waitFor(() => expect(screen.getAllByText(/Side Copilot/i).length).toBeGreaterThan(0));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/oauth-providers/github_copilot/connect",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ accessToken: "ghu-third-secret", refreshToken: "refresh-third-secret", expiresAt: "2026-06-01T12:30", accountLabel: "Side Copilot" }),
      }),
    );
    expect(document.body.textContent).not.toContain("ghu-third-secret");
    expect(document.body.textContent).not.toContain("refresh-third-secret");

    await user.type(screen.getByLabelText(/replacement token for Work Copilot/i), "ghu-refresh-secret");
    await user.type(screen.getByLabelText(/replacement refresh token for Work Copilot/i), "refresh-replacement-secret");
    await user.type(screen.getByLabelText(/replacement expiry for Work Copilot/i), "2026-07-01T08:45");
    await user.click(screen.getByRole("button", { name: /refresh Work Copilot/i }));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === "/api/models")).toHaveLength(3));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/oauth-providers/github_copilot/accounts/acct-1",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ accessToken: "ghu-refresh-secret", refreshToken: "refresh-replacement-secret", expiresAt: "2026-07-01T08:45" }),
      }),
    );
    expect(document.body.textContent).not.toContain("ghu-refresh-secret");
    expect(document.body.textContent).not.toContain("refresh-replacement-secret");

    await user.click(screen.getByRole("button", { name: /disconnect Personal Copilot/i }));

    await waitFor(() => expect(screen.queryByText(/Personal Copilot/i)).toBeNull());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/oauth-providers/github_copilot/accounts/acct-2",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("renders model browser, disables unavailable models, and includes selected model and BYOK fields in generation body", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    const modelSelect = await screen.findByLabelText(/generation model/i);
    expect(within(modelSelect).getByRole("option", { name: /GPT 4.1 unavailable/i }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/OAuth connection is not implemented yet/i)).toBeTruthy();

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.type(screen.getByLabelText(/provider api key/i), "sk-provider-secret");
    await user.selectOptions(screen.getByLabelText(/saved provider key/i), "key-123");
    await user.click(screen.getByRole("button", { name: /generate resume/i }));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/generations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          repoUrl: "https://github.com/acme/rocket",
          jobDescription: null,
          githubToken: null,
          model: "openai/gpt-4o-mini",
          providerKeyId: "key-123",
          providerApiKey: "sk-provider-secret",
        }),
      }),
    );
    expect(MockEventSource.instances[0].url).not.toContain("sk-provider-secret");
  });

  it("clears an incompatible saved provider key when the selected model changes", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.selectOptions(await screen.findByLabelText(/generation model/i), "gemini/gemini-1.5-flash");
    await user.selectOptions(screen.getByLabelText(/saved provider key/i), "key-gemini");
    await user.selectOptions(screen.getByLabelText(/generation model/i), "openai/gpt-4o-mini");
    await user.click(screen.getByRole("button", { name: /generate resume/i }));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/generations",
      expect.objectContaining({
        body: JSON.stringify({
          repoUrl: "https://github.com/acme/rocket",
          jobDescription: null,
          githubToken: null,
          model: "openai/gpt-4o-mini",
          providerKeyId: null,
          providerApiKey: null,
        }),
      }),
    );
  });

  it("manages saved BYOK keys and default model without exposing secrets", async () => {
    const fetchMock = mockFetch();
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByText("Work OpenAI")).toBeTruthy();
    expect(screen.queryByText(/sk-existing-secret/i)).toBeNull();

    await user.type(screen.getByLabelText(/key label/i), "Gemini Personal");
    await user.selectOptions(screen.getByLabelText(/key provider/i), "gemini");
    await user.type(screen.getByLabelText(/^api key secret/i), "gemini-secret");
    await user.click(screen.getByRole("button", { name: /save provider key/i }));

    expect(await screen.findByText("Gemini Personal")).toBeTruthy();
    expect(screen.queryByText(/gemini-secret/i)).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/provider-keys",
      expect.objectContaining({ body: JSON.stringify({ provider: "gemini", label: "Gemini Personal", secret: "gemini-secret", model: null }) }),
    );

    await user.selectOptions(screen.getByLabelText(/default model/i), "openai/gpt-4o-mini");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/default-model",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ model: "openai/gpt-4o-mini" }) }),
    );

    await user.click(screen.getByRole("button", { name: /delete Work OpenAI/i }));
    expect(fetchMock).toHaveBeenCalledWith("/api/settings/provider-keys/key-123", expect.objectContaining({ method: "DELETE" }));
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
          model: "openai/gpt-4o-mini",
          providerKeyId: null,
          providerApiKey: null,
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

  it("does not resend GitHub or provider secrets when retrying a failed generation", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("EventSource", MockEventSource);
    const user = userEvent.setup();

    render(<App />);

    await user.type(screen.getByLabelText(/repository url/i), "https://github.com/acme/rocket");
    await user.type(screen.getByLabelText(/github token/i), "ghp_secret_token");
    await user.type(screen.getByLabelText(/provider api key/i), "sk-provider-secret");
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

    await user.click(await screen.findByRole("button", { name: /retry/i }));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === "/api/generations")).toHaveLength(2));
    const retryCall = fetchMock.mock.calls.filter(([url]) => url === "/api/generations")[1];
    expect(retryCall[1]).toEqual(expect.objectContaining({
      body: JSON.stringify({
        repoUrl: "https://github.com/acme/rocket",
        jobDescription: null,
        model: "openai/gpt-4o-mini",
        providerKeyId: null,
      }),
    }));
    expect(String(retryCall[1]?.body)).not.toContain("ghp_secret_token");
    expect(String(retryCall[1]?.body)).not.toContain("sk-provider-secret");
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
