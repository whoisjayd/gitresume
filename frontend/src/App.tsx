import { AlertTriangle, RotateCcw, TerminalSquare } from "lucide-react";
import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import {
  createGeneration,
  deleteProviderKey,
  disconnectOAuthProvider,
  disconnectOAuthProviderAccount,
  getOAuthProviderLoginJob,
  getDashboardSettings,
  getSession,
  listModels,
  listOAuthProviders,
  logoutSession,
  saveProviderKey,
  setDefaultModel,
  startOAuthProviderLogin,
  type CreateGenerationInput,
  type CreateGenerationResponse,
  type DashboardSettings,
  type ModelEntry,
  type OAuthLoginJob,
  type OAuthProviderStatus,
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
  const [oauthProviders, setOauthProviders] = useState<OAuthProviderStatus[]>([]);
  const [dashboardSettings, setDashboardSettings] = useState<DashboardSettings | null>(null);
  const [selectedProvider, setSelectedProvider] = useState("openai");
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
    void Promise.all([getSession(), listModels(), getDashboardSettings(), listOAuthProviders()])
      .then(([sessionInfo, modelEntries, settings, providerStatuses]) => {
        if (!active) return;
        setSession(sessionInfo);
        setModels(modelEntries);
        setOauthProviders(providerStatuses);
        setDashboardSettings(settings);
        const fallback = modelEntries.find((model) => model.isAvailable)?.id ?? "";
        const initialModel = settings.defaultModel || fallback;
        setSelectedModel(initialModel);
        setSelectedProvider(modelEntries.find((model) => model.id === initialModel)?.provider ?? "openai");
      })
      .catch((reason) => {
        if (!active) return;
        setSettingsError(reason instanceof Error ? reason.message : "Could not load dashboard settings.");
      });
    return () => { active = false; };
  }, []);

  async function submit(input: CreateGenerationInput): Promise<boolean> {
    setIsSubmitting(true);
    setSubmitError(null);
    setLastInput(safeRetryInput(input));

    try {
      setGeneration(await createGeneration(input));
      return true;
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : "Could not start generation.");
      return false;
    } finally {
      setIsSubmitting(false);
    }
  }

  async function refreshModelsAndOauthProviders() {
    const [modelEntries, providerStatuses] = await Promise.all([listModels(), listOAuthProviders()]);
    setModels(modelEntries);
    setOauthProviders(providerStatuses);
    const fallback = modelEntries.find((model) => model.isAvailable)?.id ?? "";
    if (!modelEntries.some((model) => model.id === selectedModel && model.isAvailable)) {
      setSelectedModel(fallback);
      setSelectedProvider(modelEntries.find((model) => model.id === fallback)?.provider ?? "openai");
    }
  }

  function updateSelectedProvider(provider: string) {
    setSelectedProvider(provider);
    const firstProviderModel = models.find((model) => model.provider === provider && model.isAvailable);
    if (firstProviderModel) {
      setSelectedModel(firstProviderModel.id);
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
    try {
      setSettingsError(null);
      setDashboardSettings(await setDefaultModel(model));
    } catch (reason) {
      setSettingsError(reason instanceof Error ? reason.message : "Could not update default model.");
    }
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
          <p className="hero-copy">Paste a GitHub repo, pick a provider and model, then generate resume-ready bullets and interview notes.</p>
          <SessionPanel session={session} onLogout={logout} />
        </div>
      </section>

      {settingsError ? <section className="error-panel" role="alert"><AlertTriangle /> <p>{settingsError}</p></section> : null}

      <div className="workspace-grid" id="generate">
        <GenerationForm
          isSubmitting={isSubmitting || stream.isStreaming}
          models={models}
          selectedProvider={selectedProvider}
          selectedModel={selectedModel}
          providerKeys={dashboardSettings?.providerKeys ?? []}
          guidedAnalysisEnabled={dashboardSettings?.guidedAnalysisEnabled ?? false}
          contributionAnalysisEnabled={dashboardSettings?.contributionAnalysisEnabled ?? false}
          contributionAnalysisDefaultDays={dashboardSettings?.contributionAnalysisDefaultDays ?? 300}
          onSelectedProviderChange={updateSelectedProvider}
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

      <OAuthProviderPanel providers={oauthProviders} onRefresh={refreshModelsAndOauthProviders} />
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

function OAuthProviderPanel({ providers, onRefresh }: {
  providers: OAuthProviderStatus[];
  onRefresh: () => Promise<void>;
}) {
  const [jobs, setJobs] = useState<Record<string, OAuthLoginJob>>({});
  const [busyProvider, setBusyProvider] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startLogin(provider: string) {
    setBusyProvider(provider);
    setError(null);
    try {
      const started = await startOAuthProviderLogin(provider);
      const job = await pollOAuthLoginJob(started.statusUrl, (latest) => {
        setJobs((current) => ({ ...current, [provider]: latest }));
      });
      setJobs((current) => ({ ...current, [provider]: job }));
      if (job.status === "succeeded") {
        await onRefresh();
        setJobs((current) => {
          const next = { ...current };
          delete next[provider];
          return next;
        });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start OAuth login.");
    } finally {
      setBusyProvider(null);
    }
  }

  async function disconnect(provider: string) {
    if (!window.confirm(`Disconnect ${provider}? Saved OAuth credentials for this provider will be removed.`)) {
      return;
    }
    setBusyProvider(provider);
    setError(null);
    try {
      await disconnectOAuthProvider(provider);
      await onRefresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not disconnect OAuth provider.");
    } finally {
      setBusyProvider(null);
    }
  }

  async function disconnectAccount(provider: string, accountId: string, busyKey: string) {
    const label = providerStatusAccountLabel(providers, provider, accountId) ?? accountId;
    if (!window.confirm(`Disconnect ${label}? This OAuth account credential will be removed.`)) {
      return;
    }
    setBusyProvider(busyKey);
    setError(null);
    try {
      await disconnectOAuthProviderAccount(provider, accountId);
      await onRefresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not disconnect OAuth account.");
    } finally {
      setBusyProvider(null);
    }
  }

  return (
    <section className="console-card settings-panel" aria-labelledby="oauth-providers-title">
      <div className="section-kicker">OAuth execution</div>
      <h2 id="oauth-providers-title">OAuth model providers</h2>
      <p className="notice">Connect ChatGPT or GitHub Copilot with device authorization. Tokens are stored encrypted server-side and never shown here.</p>
      {error ? <p className="notice" role="alert">{error}</p> : null}
      <div className="saved-key-list">
        {providers.map((provider) => (
          <article key={provider.provider} className="oauth-provider-card">
            <div className="oauth-provider-summary">
              <strong>{oauthProviderLabel(provider.provider)}</strong>
              <span>{provider.connected ? "Connected" : "Not connected"}{provider.accountLabel ? ` · ${provider.accountLabel}` : ""}</span>
              {provider.status ? <small>{provider.status}</small> : null}
            </div>
            {jobs[provider.provider] ? <OAuthLoginJobPanel job={jobs[provider.provider]} /> : null}
            {provider.connected ? (
              <div className="oauth-connected-panel">
                <div className="oauth-provider-actions">
                  <button type="button" onClick={() => void disconnect(provider.provider)} disabled={busyProvider === provider.provider}>
                    Disconnect {oauthProviderLabel(provider.provider)}
                  </button>
                  <button type="button" onClick={() => void startLogin(provider.provider)} disabled={busyProvider === provider.provider}>
                    {busyProvider === provider.provider ? "Waiting for device login..." : `Add another ${oauthProviderLabel(provider.provider)} account`}
                  </button>
                </div>
                {(provider.accounts ?? []).map((account) => {
                  const label = account.accountLabel || account.id;
                  const busyKey = `${provider.provider}:${account.id}`;
                  return (
                    <div key={account.id} className="oauth-account-card">
                      <div>
                        <strong>{label}</strong>
                        <span>{account.executable ? "Executable" : "Refresh required"}</span>
                        {account.status ? <small>{account.status}</small> : null}
                      </div>
                      <div className="oauth-provider-actions">
                        <button type="button" onClick={() => void disconnectAccount(provider.provider, account.id, busyKey)} disabled={busyProvider === busyKey}>
                          Disconnect {label}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="oauth-provider-actions">
                <button type="button" onClick={() => void startLogin(provider.provider)} disabled={busyProvider === provider.provider}>
                  {busyProvider === provider.provider ? "Waiting for device login..." : `Connect ${oauthProviderLabel(provider.provider)}`}
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function OAuthLoginJobPanel({ job }: { job: OAuthLoginJob }) {
  return (
    <div className="oauth-job-panel">
      <strong>{job.status.replaceAll("_", " ")}</strong>
      <span>{job.message}</span>
      {job.verificationUri ? <a href={job.verificationUri} target="_blank" rel="noreferrer">Open device login</a> : null}
      {job.userCode ? <code>{job.userCode}</code> : null}
    </div>
  );
}

async function pollOAuthLoginJob(
  statusUrl: string,
  onUpdate: (job: OAuthLoginJob) => void,
): Promise<OAuthLoginJob> {
  let latest = await getOAuthProviderLoginJob(statusUrl);
  onUpdate(latest);
  for (let attempt = 0; attempt < 15 * 60; attempt += 1) {
    if (["succeeded", "failed"].includes(latest.status)) {
      return latest;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    latest = await getOAuthProviderLoginJob(statusUrl);
    onUpdate(latest);
  }
  return latest;
}

function oauthProviderLabel(provider: string): string {
  return provider === "chatgpt" ? "ChatGPT" : "GitHub Copilot";
}

function providerStatusAccountLabel(providers: OAuthProviderStatus[], providerName: string, accountId: string): string | null {
  const provider = providers.find((item) => item.provider === providerName);
  const account = provider?.accounts?.find((item) => item.id === accountId);
  return account?.accountLabel || null;
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
  const [error, setError] = useState<string | null>(null);
  const providers = Array.from(new Set([...models.map((entry) => entry.provider), "openai", "gemini", "anthropic", "groq"])).sort();

  async function submitKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await saveProviderKey({ provider, label: label.trim(), secret, model: model || null });
      setLabel("");
      setSecret("");
      setModel("");
      await onRefresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save provider key.");
    } finally {
      setBusy(false);
    }
  }

  async function removeKey(keyId: string, keyLabel: string) {
    if (!window.confirm(`Delete ${keyLabel}? This saved provider key cannot be recovered.`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteProviderKey(keyId);
      await onRefresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete provider key.");
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
      {error ? <p className="notice" role="alert">{error}</p> : null}

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
            <button type="button" onClick={() => void removeKey(key.id, key.label)} disabled={busy} aria-label={`Delete ${key.label}`}>Delete</button>
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
  const retryInput: RetryGenerationInput = {
    repoUrl: input.repoUrl,
    jobDescription: input.jobDescription ?? null,
    model: input.model ?? null,
    providerKeyId: input.providerKeyId ?? null,
  };
  if (input.analysisAuthor) {
    retryInput.analysisAuthor = input.analysisAuthor;
    retryInput.analysisDays = input.analysisDays ?? null;
  }
  return retryInput;
}
