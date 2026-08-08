import type { ReactNode } from "react";

/**
 * Every page opens with this: a microlabel naming the section, the page title
 * on the strict type scale, and room for one line of context. Actions that
 * apply to the whole page sit to the right of the title.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="rise border-b border-border pb-6">
      {eyebrow && <p className="microlabel mb-2 text-muted-foreground">{eyebrow}</p>}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {description && <p className="mt-2 max-w-xl text-sm text-muted-foreground">{description}</p>}
    </header>
  );
}
