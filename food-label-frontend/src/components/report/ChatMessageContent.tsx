import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface ChatMessageContentProps {
  content: string;
  isAssistant: boolean;
  pending?: boolean;
}

export function ChatMessageContent({
  content,
  isAssistant,
  pending = false,
}: ChatMessageContentProps) {
  if (!content) {
    return <div>{pending ? '正在生成回答...' : ''}</div>;
  }

  if (!isAssistant) {
    return <div className="whitespace-pre-wrap break-words">{content}</div>;
  }

  return (
    <div className="break-words text-sm leading-6 text-slate-700">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-2 mt-4 text-base font-semibold text-slate-900 first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-2 mt-4 text-base font-semibold text-slate-900 first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-2 mt-3 text-sm font-semibold text-slate-900 first:mt-0">{children}</h3>
          ),
          p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
          ul: ({ children }) => <ul className="mb-3 ml-5 list-disc space-y-1 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="mb-3 ml-5 list-decimal space-y-1 last:mb-0">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="mb-3 border-l-4 border-emerald-200 bg-emerald-50/60 px-3 py-2 text-slate-700 last:mb-0">
              {children}
            </blockquote>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-700 underline underline-offset-2"
            >
              {children}
            </a>
          ),
          code: ({ children, className }) => {
            if (className) {
              return (
                <code className="block overflow-x-auto rounded-xl bg-slate-900/95 px-3 py-2 text-xs text-slate-100">
                  {children}
                </code>
              );
            }
            return (
              <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[0.85em] text-slate-800">
                {children}
              </code>
            );
          },
          pre: ({ children }) => <pre className="mb-3 last:mb-0">{children}</pre>,
          table: ({ children }) => (
            <div className="mb-3 overflow-x-auto rounded-xl border border-slate-200 last:mb-0">
              <table className="min-w-full border-collapse text-left text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-slate-100 text-slate-700">{children}</thead>,
          th: ({ children }) => (
            <th className="border-b border-slate-200 px-3 py-2 font-semibold">{children}</th>
          ),
          td: ({ children }) => <td className="border-b border-slate-100 px-3 py-2 align-top">{children}</td>,
          hr: () => <hr className="my-3 border-slate-200" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
