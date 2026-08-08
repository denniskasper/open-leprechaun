import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * The platform's own select, dressed to sit beside Input: for a handful of
 * fixed options the native control already carries keyboard and touch
 * behaviour no styled listbox would improve. Options need their own
 * background so the platform popup stays readable in both themes.
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
