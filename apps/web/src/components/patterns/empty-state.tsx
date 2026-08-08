import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/**
 * The empty-state pattern (docs/agents/design.md): a screen whose data does
 * not exist yet says so in words, names the next step, and offers it as an
 * action when one exists. Never a blank region, never a lone dash.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div
      role="status"
      className="flex flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed border-input px-8 py-16 text-center"
    >
      {Icon && <Icon aria-hidden className="mb-2 size-5 text-muted-foreground" />}
      <p className="text-base font-medium">{title}</p>
      <p className="max-w-sm text-sm text-pretty text-muted-foreground">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
