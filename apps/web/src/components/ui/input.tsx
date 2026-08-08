import type * as React from "react";
import { cn } from "@/lib/utils";

// Focus is deliberately absent here: the global :focus-visible outline in
// index.css is the one focus treatment for the whole app.
function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      data-slot="input"
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm transition-colors placeholder:text-muted-foreground aria-invalid:border-alarm disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
