import { Clipboard, FileCode2 } from "lucide-react";
import type { ResumeResult } from "../api/generations";
import { formatResumeLatex, formatResumePlainText } from "../lib/formatResume";

type Props = {
  result: ResumeResult;
};

async function copyText(value: string) {
  await globalThis.navigator.clipboard.writeText(value);
}

export function ResultPanel({ result }: Props) {
  return (
    <section className="console-card result-panel" aria-label="Generated resume">
      <div className="result-header">
        <div>
          <div className="section-kicker">Generated artifact</div>
          <h2>{result.projectTitle ?? "Generated Resume"}</h2>
        </div>
        <div className="result-actions">
          <button type="button" onClick={() => void copyText(formatResumePlainText(result))}>
            <Clipboard size={16} aria-hidden="true" /> Copy plain text
          </button>
          <button type="button" onClick={() => void copyText(formatResumeLatex(result))}>
            <FileCode2 size={16} aria-hidden="true" /> Copy LaTeX
          </button>
        </div>
      </div>

      {result.techStack?.length ? (
        <div className="chip-row" aria-label="Tech stack">
          {result.techStack.map((tech) => <span className="chip" key={tech}>{tech}</span>)}
        </div>
      ) : null}

      {result.bulletPoints?.length ? (
        <ul className="bullet-list">
          {result.bulletPoints.map((point) => <li key={point}>{point}</li>)}
        </ul>
      ) : null}

      <div className="detail-grid">
        {result.additionalNotes ? <Detail title="Additional notes" value={result.additionalNotes} /> : null}
        {result.futurePlans ? <Detail title="Future plans" value={result.futurePlans} /> : null}
        {result.potentialAdvancements ? <Detail title="Potential advancements" value={result.potentialAdvancements} /> : null}
      </div>

      {result.interviewQuestions?.length ? (
        <div className="questions">
          <h3>Interview questions</h3>
          {result.interviewQuestions.map((item) => (
            <article key={`${item.category ?? "question"}-${item.question}`}>
              <span>{item.category ?? "Interview"}</span>
              <h4>{item.question}</h4>
              <p>{item.answer}</p>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function Detail({ title, value }: { title: string; value: string }) {
  return (
    <article>
      <h3>{title}</h3>
      <p>{value}</p>
    </article>
  );
}
