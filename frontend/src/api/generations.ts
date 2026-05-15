export type GenerationStatus =
  | "queued"
  | "validating"
  | "cloning"
  | "analyzing"
  | "generating"
  | "succeeded"
  | "completed"
  | "failed";

export type InterviewQuestion = {
  question: string;
  answer: string;
  category?: string;
};

export type ResumeResult = {
  projectTitle?: string;
  techStack?: string[];
  bulletPoints?: string[];
  additionalNotes?: string;
  futurePlans?: string;
  potentialAdvancements?: string;
  interviewQuestions?: InterviewQuestion[];
};

export type GenerationState = {
  generationId: string;
  status: GenerationStatus;
  repositoryUrl: string;
  jobDescription?: string | null;
  result?: ResumeResult | null;
  error?: string | null;
  taskId?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type GenerationEvent = {
  generationId: string;
  eventType: GenerationStatus;
  status?: GenerationStatus;
  message: string;
  sequence: number;
  data?: { result?: ResumeResult; error?: string } | ResumeResult | null;
  createdAt: string;
};

export type CreateGenerationResponse = {
  generationId: string;
  statusUrl: string;
  eventsUrl: string;
  redirectPath: string;
};

export type CreateGenerationInput = {
  repoUrl: string;
  jobDescription?: string | null;
  githubToken?: string | null;
  model?: string | null;
  providerKeyId?: string | null;
  providerApiKey?: string | null;
};

export type SessionInfo = {
  isAuthenticated: boolean;
  githubUser?: string | null;
  githubUserId?: string | null;
  appMode: "self_hosted" | "hosted";
  loginRequired: boolean;
};

export type ModelEntry = {
  id: string;
  provider: string;
  mode: string;
  displayName: string;
  authType: "api_key" | "oauth" | "none";
  supportsOauth: boolean;
  requiresApiKey: boolean;
  isAvailable: boolean;
  status?: string | null;
  contextWindow?: number | null;
};

export type ProviderKeyMetadata = {
  id: string;
  provider: string;
  label: string;
  model?: string | null;
  createdAt: string;
  lastUsedAt?: string | null;
  isActive: boolean;
};

export type DashboardSettings = {
  appMode: "self_hosted" | "hosted";
  allowSavedByok: boolean;
  savedKeysEnabled: boolean;
  loginRequired: boolean;
  defaultModel?: string | null;
  providerKeys: ProviderKeyMetadata[];
  disabledReason?: string | null;
};

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function createGeneration(input: CreateGenerationInput): Promise<CreateGenerationResponse> {
  const response = await fetch("/api/generations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  return readJson<CreateGenerationResponse>(response);
}

export async function getGeneration(statusUrl: string): Promise<GenerationState> {
  return readJson<GenerationState>(await fetch(statusUrl));
}

export async function getSession(): Promise<SessionInfo> {
  return readJson<SessionInfo>(await fetch("/api/session"));
}

export async function logoutSession(): Promise<SessionInfo> {
  return readJson<SessionInfo>(await fetch("/api/session/logout", { method: "POST" }));
}

export async function listModels(): Promise<ModelEntry[]> {
  const response = await readJson<{ models: ModelEntry[] }>(await fetch("/api/models"));
  return response.models;
}

export async function getDashboardSettings(): Promise<DashboardSettings> {
  return readJson<DashboardSettings>(await fetch("/api/settings"));
}

export async function saveProviderKey(input: { provider: string; label: string; secret: string; model?: string | null }): Promise<ProviderKeyMetadata> {
  return readJson<ProviderKeyMetadata>(await fetch("/api/settings/provider-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }));
}

export async function deleteProviderKey(keyId: string): Promise<void> {
  const response = await fetch(`/api/settings/provider-keys/${keyId}`, { method: "DELETE" });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }
}

export async function setDefaultModel(model: string | null): Promise<DashboardSettings> {
  return readJson<DashboardSettings>(await fetch("/api/settings/default-model", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  }));
}
