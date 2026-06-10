interface CodeListProps {
  /** Tokens rendered as inline <code> chips, joined by commas. */
  items: string[];
  /**
   * Optional trailing token (e.g. "…") rendered after the last item, with a
   * comma after the last code chip. Use for open-ended lists.
   */
  trailing?: string;
}

/**
 * Renders a comma-separated list of <code> chips that wraps cleanly: each
 * "chip," stays together (never splits a comma onto a new line) and the gap
 * between items is a real flex gap, so it survives line wrapping.
 */
export function CodeList({ items, trailing }: CodeListProps): React.ReactElement {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-1.5 align-middle">
      {items.map((item, i) => {
        const comma = trailing != null || i < items.length - 1;
        return (
          <span key={item} className="whitespace-nowrap">
            <code>{item}</code>
            {comma ? "," : ""}
          </span>
        );
      })}
      {trailing != null ? <span className="whitespace-nowrap">{trailing}</span> : null}
    </span>
  );
}
