import { KeyRound, Link2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import type { CreateGenerationInput, ModelEntry, ProviderKeyMetadata } from "../api/generations";

type Props = {
  isSubmitting: boolean;
  models: ModelEntry[];
  selectedModel: string;
  providerKeys: ProviderKeyMetadata[];
  onSubmit: (input: CreateGenerationInput) => Promise<void>;
  onSelectedModelChange: (model: string) => void;
};

export function GenerationForm({ isSubmitting, models, selectedModel, providerKeys, onSubmit, onSelectedModelChange }: Props) {
  const [repoUrl, setRepoUrl] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [providerApiKey, setProviderApiKey] = useState("");
  const [providerKeyId, setProviderKeyId] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [showJobDescription, setShowJobDescription] = useState(false);
  const availableModels = models.filter((model) => model.isAvailable);
  const compatibleKeys = providerKeys.filter((key) => !selectedModel || !key.model || key.model === selectedModel);

  useEffect(() => {
    if (providerKeyId && !compatibleKeys.some((key) => key.id === providerKeyId)) {
      setProviderKeyId("");
    }
  }, [compatibleKeys, providerKeyId]);

  return (
    <form
      className="console-card form-panel"
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmit({
          repoUrl: repoUrl.trim(),
          jobDescription: showJobDescription && jobDescription.trim() ? jobDescription.trim() : null,
          githubToken: githubToken.trim() ? githubToken.trim() : null,
          model: selectedModel || availableModels[0]?.id || null,
          providerKeyId: providerKeyId || null,
          providerApiKey: providerApiKey.trim() ? providerApiKey.trim() : null,
        });
      }}
    >
      <div className="section-kicker">Input channel</div>
      <label className="field">
        <span><Link2 size={16} aria-hidden="true" /> Repository URL</span>
        <input
          required
          type="url"
          value={repoUrl}
          onChange={(event) => setRepoUrl(event.target.value)}
          placeholder="https://github.com/owner/repo"
        />
      </label>

      <label className="field">
        <span>Generation model</span>
        <select
          value={selectedModel}
          onChange={(event) => onSelectedModelChange(event.target.value)}
          aria-label="Generation model"
        >
          {models.map((model) => (
            <option key={model.id} value={model.id} disabled={!model.isAvailable}>
              {model.displayName}{model.isAvailable ? "" : " unavailable"}
            </option>
          ))}
        </select>
        <small>OAuth and Responses API models remain visible in the browser, but unavailable models cannot be selected.</small>
      </label>

      <button className="text-button" type="button" onClick={() => setShowJobDescription((value) => !value)}>
        {showJobDescription ? "Remove job description" : "Add job description"}
      </button>

      {showJobDescription ? (
        <label className="field">
          <span>Job description</span>
          <textarea
            value={jobDescription}
            onChange={(event) => setJobDescription(event.target.value)}
            placeholder="Paste a target role to tailor the resume bullets."
            rows={5}
          />
        </label>
      ) : null}

      <label className="field">
        <span><KeyRound size={16} aria-hidden="true" /> GitHub token</span>
        <input
          type="password"
          value={githubToken}
          onChange={(event) => setGithubToken(event.target.value)}
          placeholder="Optional for private repositories"
          autoComplete="off"
        />
        <small>Sent only in the POST body. It is never added to the page URL or SSE URL.</small>
      </label>

      <label className="field">
        <span><KeyRound size={16} aria-hidden="true" /> Provider API key</span>
        <input
          type="password"
          value={providerApiKey}
          onChange={(event) => setProviderApiKey(event.target.value)}
          placeholder="Optional ephemeral BYOK for this generation"
          autoComplete="off"
        />
        <small>Ephemeral BYOK is held in memory and sent only in the POST body.</small>
      </label>

      <label className="field">
        <span>Saved provider key</span>
        <select value={providerKeyId} onChange={(event) => setProviderKeyId(event.target.value)} aria-label="Saved provider key">
          <option value="">Use environment or ephemeral key</option>
          {compatibleKeys.map((key) => (
            <option key={key.id} value={key.id}>{key.label} ({key.provider})</option>
          ))}
        </select>
      </label>

      <button className="primary-action" type="submit" disabled={isSubmitting}>
        <Play size={18} aria-hidden="true" /> {isSubmitting ? "Generating..." : "Generate resume"}
      </button>
    </form>
  );
}
