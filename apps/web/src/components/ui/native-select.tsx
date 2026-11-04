import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * The platform's own select, dressed to sit beside Input: for a handful of
 * fixed options the native control already carries keyboard and touch
 * behaviour no styled listbox would improve. Its options take the theme's
 * colours from the base layer in index.css, which keeps the platform popup
 * readable in both themes.
 */
export function NativeSelect({
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "flex h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm transition-colors",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
