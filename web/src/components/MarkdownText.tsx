import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";

const components: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0 whitespace-pre-wrap">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-ink-900">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  a: ({ href, children }) => (
    <a href={href} className="underline decoration-accent/50 underline-offset-2" target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-ink-50 px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
  ),
  h1: ({ children }) => <p className="mb-2 font-display text-lg font-semibold">{children}</p>,
  h2: ({ children }) => <p className="mb-2 font-display text-base font-semibold">{children}</p>,
  h3: ({ children }) => <p className="mb-1.5 text-sm font-semibold">{children}</p>,
};

export function MarkdownText({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`markdown-body ${className}`}>
      <ReactMarkdown components={components}>{text}</ReactMarkdown>
    </div>
  );
}
