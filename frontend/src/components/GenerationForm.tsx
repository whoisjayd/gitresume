import { KeyRound, Link2, Play } from "lucide-react";
import { useState } from "react";
import type { CreateGenerationInput } from "../api/generations";

type Props = {
  isSubmitting: boolean;
  onSubmit: (input: CreateGenerationInput) => Promise<void>;
};

export function GenerationForm({ isSubmitting, onSubmit }: Props) {
  const [repoUrl, setRepoUrl] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [showJobDescription, setShowJobDescription] = useState(false);

  return (
    <form
      className="console-card form-panel"
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmit({
          repoUrl: repoUrl.trim(),
          jobDescription: showJobDescription && jobDescription.trim() ? jobDescription.trim() : null,
          githubToken: githubToken.trim() ? githubToken.trim() : null,
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

      <button className="primary-action" type="submit" disabled={isSubmitting}>
        <Play size={18} aria-hidden="true" /> {isSubmitting ? "Generating..." : "Generate resume"}
      </button>
    </form>
  );
}
