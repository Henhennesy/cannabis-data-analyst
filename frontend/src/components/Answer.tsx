import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders the model's answer as markdown.
 *
 * The model reaches for tables whenever it reports more than one figure --
 * which is most of the time -- and a raw `| Year | Dollar sales |` is exactly
 * the illegibility this tool is supposed to eliminate. remark-gfm is what
 * turns those into real tables.
 *
 * react-markdown does not render raw HTML by default, so model output cannot
 * inject markup into the page.
 */
export function Answer({ text }: { text: string }) {
  return (
    <div className="answer">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Figures belong in tabular figures, same as everywhere else.
          table: (props) => (
            <div className="answer__table-wrap">
              <table className="answer__table" {...props} />
            </div>
          ),
          code: ({ children, ...props }) => (
            <code className="answer__code" {...props}>
              {children}
            </code>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
