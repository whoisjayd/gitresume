import { AlertTriangle, RotateCcw, TerminalSquare } from "lucide-react";
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  createGeneration,
  deleteProviderKey,
  getDashboardSettings,
  getSession,
  listModels,
  logoutSession,
  saveProviderKey,
  setDefaultModel,
  type CreateGenerationInput,
  type CreateGenerationResponse,
  type DashboardSettings,
  type ModelEntry,
  type SessionInfo,
} from "./api/generations";
import { GenerationForm } from "./components/GenerationForm";
import { ProgressTimeline } from "./components/ProgressTimeline";
import { ResultPanel } from "./components/ResultPanel";
import { useGenerationStream } from "./hooks/useGenerationStream";

const REPO_URL = "https://github.com/WhoIsJayD/gitresume";
const THEME_KEY = "gitresume.theme";

type Theme = "light" | "dark";
type RetryGenerationInput = Omit<CreateGenerationInput, "githubToken" | "providerApiKey">;

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => readInitialTheme());
  const [generation, setGeneration] = useState<CreateGenerationResponse | null>(null);
  const [lastInput, setLastInput] = useState<RetryGenerationInput | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [dashboardSettings, setDashboardSettings] = useState<DashboardSettings | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const stream = useGenerationStream(generation?.eventsUrl ?? null, generation?.statusUrl ?? null);
  const error = submitError ?? stream.error ?? stream.state?.error ?? null;
  const result = stream.state?.result ?? null;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    writeThemePreference(theme);
  }, [theme]);

  useEffect(() => {
    let active = true;
    void Promise.all([getSession(), listModels(), getDashboardSettings()])
      .then(([sessionInfo, modelEntries, settings]) => {
        if (!active) return;
        setSession(sessionInfo);
        setModels(modelEntries);
        setDashboardSettings(settings);
        const fallback = modelEntries.find((model) => model.isAvailable)?.id ?? "";
        setSelectedModel(settings.defaultModel || fallback);
      })
      .catch((reason) => {
        if (!active) return;
        setSettingsError(reason instanceof Error ? reason.message : "Could not load dashboard settings.");
      });
    return () => { active = false; };
  }, []);

  const availableModelCount = useMemo(() => models.filter((model) => model.isAvailable).length, [models]);

  async function submit(input: CreateGenerationInput) {
    setIsSubmitting(true);
    setSubmitError(null);
    setLastInput(safeRetryInput(input));

    try {
      setGeneration(await createGeneration(input));
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : "Could not start generation.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function refreshSettings() {
    setDashboardSettings(await getDashboardSettings());
  }

  async function logout() {
    setSession(await logoutSession());
    await refreshSettings();
  }

  async function updateDefaultModel(model: string | null) {
    setSelectedModel(model ?? "");
    setDashboardSettings(await setDefaultModel(model));
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="wordmark" href="#generate" aria-label="GitResume home">
          <TerminalSquare aria-hidden="true" /> GitResume
        </a>
        <nav aria-label="Primary navigation">
          <a href="#generate">Generate</a>
          <a href="#dashboard">Dashboard</a>
          <a href="#models">Models</a>
          <a href="#settings">Settings</a>
          <a href="/docs">Docs</a>
          <a href={REPO_URL}>GitHub repo</a>
        </nav>
        <button type="button" className="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        </button>
      </header>

      <section className="hero" aria-labelledby="page-title" id="dashboard">
        <div className="brand-mark" aria-hidden="true"><TerminalSquare /></div>
        <div>
          <p className="eyebrow">GitResume dashboard</p>
          <h1 id="page-title">Turn a repo into a resume signal deck.</h1>
          <p className="hero-copy">A self-hostable cockpit for repository analysis, model selection, GitHub access, and BYOK configuration.</p>
          <SessionPanel session={session} onLogout={logout} />
        </div>
      </section>

      {settingsError ? <section className="error-panel" role="alert"><AlertTriangle /> <p>{settingsError}</p></section> : null}

      <section className="metric-grid" aria-label="Dashboard summary">
        <article><span>{models.length}</span><p>Total text models</p></article>
        <article><span>{availableModelCount}</span><p>Selectable models</p></article>
        <article><span>{dashboardSettings?.providerKeys.length ?? 0}</span><p>Saved BYOK keys</p></article>
        <article><span>{session?.appMode ?? "..."}</span><p>App mode</p></article>
      </section>

      <div className="workspace-grid" id="generate">
        <GenerationForm
          isSubmitting={isSubmitting || stream.isStreaming}
          models={models}
          selectedModel={selectedModel}
          providerKeys={dashboardSettings?.providerKeys ?? []}
          onSelectedModelChange={setSelectedModel}
          onSubmit={submit}
        />
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

      <ModelBrowser models={models} />
      <SettingsPanel
        settings={dashboardSettings}
        models={models}
        session={session}
        selectedModel={selectedModel}
        onDefaultModelChange={updateDefaultModel}
        onRefresh={refreshSettings}
      />

      <footer className="site-footer">
        <a href="/docs">Docs</a>
        <a href={REPO_URL}>GitHub repo</a>
      </footer>
    </main>
  );
}

function SessionPanel({ session, onLogout }: { session: SessionInfo | null; onLogout: () => Promise<void> }) {
  if (!session) return <div className="console-card session-panel">Loading session...</div>;
  return (
    <div className="console-card session-panel">
      <div>
        <strong>{session.isAuthenticated ? session.githubUser : "Anonymous"}</strong>
        <span>{session.appMode} mode</span>
      </div>
      {session.loginRequired ? <p>Hosted dashboards require GitHub login before saved BYOK keys can be managed.</p> : null}
      {session.isAuthenticated ? (
        <button type="button" onClick={() => void onLogout()}>Logout</button>
      ) : (
        <a className="button-link" href="/api/session/login?next=/dashboard">Login with GitHub</a>
      )}
    </div>
  );
}

function ModelBrowser({ models }: { models: ModelEntry[] }) {
  return (
    <section className="console-card model-browser" id="models" aria-labelledby="models-title">
      <div className="section-kicker">Model browser</div>
      <h2 id="models-title">LiteLLM text model catalog</h2>
      <div className="model-grid">
        {models.map((model) => (
          <article key={model.id} className={model.isAvailable ? "" : "muted-card"}>
            <h3>{model.displayName}</h3>
            <p>{model.id}</p>
            <div className="chip-row">
              <span className="chip">{model.provider}</span>
              <span className="chip">{model.mode}</span>
              <span className="chip">{model.authType}</span>
              <span className="chip">{model.isAvailable ? "Selectable" : "Unavailable"}</span>
            </div>
            {model.status ? <small>{model.status}</small> : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function SettingsPanel({ settings, models, session, selectedModel, onDefaultModelChange, onRefresh }: {
  settings: DashboardSettings | null;
  models: ModelEntry[];
  session: SessionInfo | null;
  selectedModel: string;
  onDefaultModelChange: (model: string | null) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const [provider, setProvider] = useState("openai");
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const providers = Array.from(new Set([...models.map((entry) => entry.provider), "openai", "gemini", "anthropic", "groq"])).sort();

  async function submitKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await saveProviderKey({ provider, label: label.trim(), secret, model: model || null });
      setLabel("");
      setSecret("");
      setModel("");
      await onRefresh();
    } finally {
      setBusy(false);
    }
  }

  async function removeKey(keyId: string) {
    setBusy(true);
    try {
      await deleteProviderKey(keyId);
      await onRefresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="console-card settings-panel" id="settings" aria-labelledby="settings-title">
      <div className="section-kicker">Settings</div>
      <h2 id="settings-title">{session?.appMode === "hosted" ? "Hosted BYOK settings" : "Self-hosted global settings"}</h2>
      {settings?.loginRequired ? <p className="notice">Hosted saved keys require GitHub login. Ephemeral keys remain available in the Generate form.</p> : null}
      {settings?.disabledReason ? <p className="notice">{settings.disabledReason}</p> : null}

      <label className="field">
        <span>Default model</span>
        <select aria-label="Default model" value={settings?.defaultModel ?? selectedModel} onChange={(event) => void onDefaultModelChange(event.target.value || null)} disabled={!settings?.savedKeysEnabled}>
          <option value="">Server default</option>
          {models.filter((entry) => entry.isAvailable).map((entry) => <option key={entry.id} value={entry.id}>{entry.displayName}</option>)}
        </select>
      </label>

      <div className="saved-key-list">
        {(settings?.providerKeys ?? []).map((key) => (
          <article key={key.id}>
            <div><strong>{key.label}</strong><span>{key.provider}{key.model ? ` · ${key.model}` : ""}</span></div>
            <button type="button" onClick={() => void removeKey(key.id)} disabled={busy} aria-label={`Delete ${key.label}`}>Delete</button>
          </article>
        ))}
      </div>

      <form className="settings-form" onSubmit={submitKey}>
        <label className="field"><span>Key label</span><input value={label} onChange={(event) => setLabel(event.target.value)} required disabled={!settings?.savedKeysEnabled} /></label>
        <label className="field"><span>Key provider</span><select value={provider} onChange={(event) => setProvider(event.target.value)} disabled={!settings?.savedKeysEnabled}>{providers.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="field"><span>API key secret</span><input type="password" value={secret} onChange={(event) => setSecret(event.target.value)} required autoComplete="off" disabled={!settings?.savedKeysEnabled} /></label>
        <label className="field"><span>Restrict to model</span><select value={model} onChange={(event) => setModel(event.target.value)} disabled={!settings?.savedKeysEnabled}><option value="">Any compatible model</option>{models.filter((entry) => entry.isAvailable).map((entry) => <option key={entry.id} value={entry.id}>{entry.displayName}</option>)}</select></label>
        <button className="primary-action" type="submit" disabled={busy || !settings?.savedKeysEnabled}>Save provider key</button>
      </form>
    </section>
  );
}

function readInitialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" ? stored : "dark";
  } catch {
    return "dark";
  }
}

function writeThemePreference(theme: Theme) {
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    // Storage can be unavailable in private or locked-down browser contexts.
  }
}

function safeRetryInput(input: CreateGenerationInput): RetryGenerationInput {
  return {
    repoUrl: input.repoUrl,
    jobDescription: input.jobDescription ?? null,
    model: input.model ?? null,
    providerKeyId: input.providerKeyId ?? null,
  };
}
