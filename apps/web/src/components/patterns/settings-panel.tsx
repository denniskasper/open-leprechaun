import { Children, useId, type ReactNode } from "react";
import { PageHeader } from "@/components/page-header";

/**
 * The settings-panel pattern (docs/agents/design.md): every screen under
 * Settings is one panel — a heading, one line saying what the panel governs,
 * then its controls in named groups ruled apart by hairlines. A panel never
 * invents its own frame.
 */
export function SettingsPanel({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div>
      <PageHeader eyebrow="Settings" title={title} description={description} />
      <div className="divide-y divide-border border-b border-border">
        {Children.map(children, (child, index) => (
          <div className="rise" style={{ animationDelay: `${60 + index * 60}ms` }}>
            {child}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * One group of controls inside a panel: what it is and what it does on the
 * left, the controls themselves on the right; stacked on a narrow screen.
 * The description is where a consequence is stated before the control that
 * causes it.
 */
export function SettingsGroup({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  const headingId = useId();

  return (
    <section
      aria-labelledby={headingId}
      className="grid gap-x-10 gap-y-5 py-8 md:grid-cols-[15rem_minmax(0,1fr)]"
    >
      <div>
        <h2 id={headingId} className="text-base font-medium">
          {title}
        </h2>
        <p className="mt-1.5 text-sm text-pretty text-muted-foreground">{description}</p>
      </div>
      <div className="min-w-0 max-w-md space-y-5">{children}</div>
    </section>
  );
}
