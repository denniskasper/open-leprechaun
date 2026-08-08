import { TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

/**
 * The error-state pattern (docs/agents/design.md): something failed, so the
 * region says what failed, what that means, and how to try again. The rest of
 * the screen stays usable; an error never blanks the page.
 */
export function ErrorState({
  title,
  detail,
  onRetry,
  children,
}: {
  title: string;
  detail: string;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  return (
    <div role="alert" className="rounded-xl border border-alarm/40 bg-alarm/5 px-6 py-5">
      <div className="flex items-center gap-2.5 text-alarm">
        <TriangleAlert aria-hidden className="size-4 shrink-0" />
        <p className="font-medium">{title}</p>
      </div>
      <p className="mt-1.5 text-sm text-pretty text-muted-foreground">{detail}</p>
      {children}
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
