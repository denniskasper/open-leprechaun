import { Clover, Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { EnvironmentBadge, VersionLine } from "@/components/shell/instance";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { watchSystemTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { NAV_SECTIONS } from "@/navigation";

/**
 * The application shell: sidebar navigation on desktop, a sheet behind a menu
 * button on mobile, and a content region every page renders into. The first
 * element in tab order is a skip link straight to that region.
 */
export function AppShell() {
  useEffect(() => watchSystemTheme(), []);

  return (
    <div className="min-h-dvh bg-canvas">
      <a
        href="#content"
        className="sr-only z-50 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-4 focus:left-4"
      >
        Skip to content
      </a>

      {/* The content sheet: a clean surface on the canvas, edged by hairlines. */}
      <div className="relative mx-auto flex min-h-dvh w-full max-w-6xl border-x border-border bg-background">
        <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border md:flex">
          <Wordmark className="flex h-16 items-center px-6" />
          <NavSections className="flex-1 space-y-8 overflow-y-auto px-3 py-6" />
          <VersionLine className="border-t border-border px-6 py-4" />
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-40 flex h-16 items-center gap-2 border-b border-border bg-background/85 px-4 backdrop-blur-sm sm:px-8">
            <MobileNav />
            <Wordmark className="md:hidden" />
            <EnvironmentBadge />
            <div className="flex-1" />
            <ThemeToggle />
          </header>

          <main id="content" tabIndex={-1} className="flex-1 px-4 py-8 outline-none sm:px-8 sm:py-10">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}

function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <Clover aria-hidden className="size-4 text-primary" />
      <span className="microlabel text-foreground">Open Leprechaun</span>
    </span>
  );
}

function NavSections({ className }: { className?: string }) {
  return (
    <nav aria-label="Primary" className={className}>
      {NAV_SECTIONS.map((section) => (
        <div key={section.label}>
          <p className="microlabel px-3 pb-2 text-muted-foreground">{section.label}</p>
          <ul className="space-y-1">
            {section.items.map((item) => (
              <li key={item.to}>
                {/* NavLink sets aria-current="page" on the active route. */}
                <NavLink
                  to={item.to}
                  end
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )
                  }
                >
                  <item.icon aria-hidden className="size-4 shrink-0" />
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function MobileNav() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  // Following a link should close the sheet, not leave it over the new page.
  useEffect(() => setOpen(false), [location]);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Open navigation" className="md:hidden">
          <Menu aria-hidden />
        </Button>
      </SheetTrigger>
      <SheetContent side="left">
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <SheetDescription className="sr-only">Pages of this application</SheetDescription>
        <Wordmark className="flex h-16 items-center px-6" />
        <NavSections className="flex-1 space-y-8 overflow-y-auto px-3 py-6" />
        <VersionLine className="border-t border-border px-6 py-4" />
      </SheetContent>
    </Sheet>
  );
}
