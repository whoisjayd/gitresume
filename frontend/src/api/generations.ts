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
