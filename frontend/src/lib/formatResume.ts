import type { ResumeResult } from "../api/generations";

const escapeLatex = (value: string) =>
  value.replaceAll("\\", "\\textbackslash{}")
    .replaceAll("&", "\\&")
    .replaceAll("%", "\\%")
    .replaceAll("$", "\\$")
    .replaceAll("#", "\\#")
    .replaceAll("_", "\\_")
    .replaceAll("{", "\\{")
    .replaceAll("}", "\\}");

export function formatResumePlainText(result: ResumeResult): string {
  const lines = [result.projectTitle ?? "Generated Resume"];

  if (result.techStack?.length) {
    lines.push("", `Tech stack: ${result.techStack.join(", ")}`);
  }

  if (result.bulletPoints?.length) {
    lines.push("", "Impact bullets:", ...result.bulletPoints.map((point) => `- ${point}`));
  }

  const details = [
    ["Additional notes", result.additionalNotes],
    ["Future plans", result.futurePlans],
    ["Potential advancements", result.potentialAdvancements],
  ];

  for (const [label, value] of details) {
    if (value) {
      lines.push("", `${label}: ${value}`);
    }
  }

  if (result.interviewQuestions?.length) {
    lines.push("", "Interview questions:");
    for (const item of result.interviewQuestions) {
      lines.push(`- ${item.question}`, `  ${item.answer}`);
    }
  }

  return lines.join("\n");
}

export function formatResumeLatex(result: ResumeResult): string {
  const title = escapeLatex(result.projectTitle ?? "Generated Resume");
  const lines = [`\\section*{${title}}`];

  if (result.techStack?.length) {
    lines.push(`\\textbf{Tech Stack:} ${escapeLatex(result.techStack.join(", "))}`);
  }

  if (result.bulletPoints?.length) {
    lines.push("\\begin{itemize}");
    lines.push(...result.bulletPoints.map((point) => `  \\item ${escapeLatex(point)}`));
    lines.push("\\end{itemize}");
  }

  const details = [
    ["Notes", result.additionalNotes],
    ["Future plans", result.futurePlans],
    ["Potential advancements", result.potentialAdvancements],
  ];

  for (const [label, value] of details) {
    if (value) {
      lines.push(`\\textbf{${label}:} ${escapeLatex(value)}`);
    }
  }

  if (result.interviewQuestions?.length) {
    lines.push("\\subsection*{Interview Questions}");
    for (const item of result.interviewQuestions) {
      lines.push(`\\textbf{${escapeLatex(item.question)}}\\\\`);
      lines.push(escapeLatex(item.answer));
    }
  }

  return lines.join("\n");
}
