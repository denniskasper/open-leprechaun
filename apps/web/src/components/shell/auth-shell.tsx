import { Clover } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { EnvironmentBadge } from "@/components/shell/instance";
import { ThemeToggle } from "@/components/theme-toggle";
import { watchSystemTheme } from "@/lib/theme";

/**
 * The frame of the screens outside the application shell — setup and login:
 * a top bar with the wordmark and the theme toggle, and one narrow column
 * centred beneath it. Like the application shell, it answers to the window.
 */
export function AuthShell({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  useEffect(() => watchSystemTheme(), []);

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="flex h-16 items-center gap-2 border-b border-border px-4 sm:px-8">
        <span className="flex items-center gap-2.5">
          <Clover aria-hidden className="size-4 text-primary" />
          <span className="microlabel text-foreground">Open Leprechaun</span>
        </span>
        <EnvironmentBadge />
        <div className="flex-1" />
        <ThemeToggle />
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm">
          <p className="rise microlabel text-muted-foreground" style={{ animationDelay: "60ms" }}>
            {eyebrow}
          </p>
          <h1
            className="rise mt-3 text-display font-wide font-semibold uppercase"
            style={{ animationDelay: "120ms" }}
          >
            {title}
          </h1>
          <p
            className="rise mt-4 text-sm text-pretty text-muted-foreground"
            style={{ animationDelay: "180ms" }}
          >
            {description}
          </p>
          <div className="rise mt-8" style={{ animationDelay: "240ms" }}>
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}
