import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders LLM/chatbot output as formatted text.
 *
 * The model replies in Markdown (**bold**, bullet lists, tables), which was
 * previously dumped into the DOM verbatim -- so patients saw literal asterisks
 * around drug names instead of emphasis, which reads as broken and, worse,
 * makes the emphasised safety words harder to notice.
 *
 * Raw HTML is deliberately NOT enabled: this text originates from a language
 * model, so treating it as markup-only keeps it inert. Links are forced to
 * open in a new tab with noreferrer.
 */
export default function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
          table: ({ ...props }) => (
            <div className="table-scroll">
              <table {...props} />
            </div>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
