import { Clover, Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { EnvironmentBadge, VersionLine } from "@/components/shell/instance";
import { SignOutButton } from "@/components/shell/sign-out";
import { TwoFactorReminder } from "@/components/shell/two-factor-reminder";
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
 *
 * Desktop has no top bar — what it held sits in the sidebar: the environment
 * badge beside the wordmark, theme and sign-out in the footer beside the
 * version. A phone keeps the bar, because there the sidebar is put away.
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

      {/* The content sheet: a clean surface on the canvas. It fills the window
          until its cap, and only past that do its hairline edges show. */}
      <div className="relative mx-auto flex min-h-dvh w-full max-w-sheet border-border bg-background 2xl:border-x">
        <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border md:flex">
          <div className="flex h-14 shrink-0 items-center justify-between gap-3 px-6">
            <Wordmark stacked />
            <EnvironmentBadge />
          </div>
          <NavSections className="scrollbar-thin flex-1 space-y-6 overflow-y-auto px-3 py-4" />
          <div className="flex shrink-0 flex-wrap items-center border-t border-border py-1.5 pr-2 pl-6 [&>[role=alert]]:order-first [&>[role=alert]]:basis-full [&>[role=alert]]:py-1.5 [&>[role=alert]]:pr-4">
            <VersionLine className="min-w-0 flex-1 pr-2" />
            <ThemeToggle className="size-7" />
            <SignOutButton className="size-7" />
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b border-border bg-background/85 px-4 backdrop-blur-sm sm:px-8 md:hidden">
            <MobileNav />
            <Wordmark />
            <EnvironmentBadge />
            <div className="flex-1" />
            <ThemeToggle />
            <SignOutButton />
          </header>
          <TwoFactorReminder />

          <main
            id="content"
            tabIndex={-1}
            className="flex-1 px-4 py-8 outline-none sm:px-8 sm:py-10 xl:px-12"
          >
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}

/**
 * The wordmark. The sidebar sets it on two lines, which leaves the narrow
 * column room for the environment badge beside it.
 */
function Wordmark({ className, stacked = false }: { className?: string; stacked?: boolean }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <Clover aria-hidden className={cn("shrink-0 text-primary", stacked ? "size-5" : "size-4")} />
      <span className="microlabel whitespace-nowrap text-foreground">
        Open {stacked && <br />}
        Leprechaun
      </span>
    </span>
  );
}

function NavSections({ className }: { className?: string }) {
  return (
    <nav aria-label="Primary" className={className}>
      {NAV_SECTIONS.map((section) => (
        <div key={section.label}>
          <p className="microlabel px-3 pb-1.5 text-muted-foreground">{section.label}</p>
          <ul className="space-y-px">
            {section.items.map((item) => (
              <li key={item.to}>
                {/* NavLink sets aria-current="page" on the active route. */}
                <NavLink
                  to={item.to}
                  end
                  className={({ isActive }) =>
                    cn(
                      "flex h-8 items-center gap-2.5 rounded-md px-3 text-sm font-medium transition-colors",
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
        <Button variant="ghost" size="icon" aria-label="Open navigation">
          <Menu aria-hidden />
        </Button>
      </SheetTrigger>
      <SheetContent side="left">
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <SheetDescription className="sr-only">Pages of this application</SheetDescription>
        <Wordmark className="flex h-14 shrink-0 items-center px-6" />
        <NavSections className="scrollbar-thin flex-1 space-y-6 overflow-y-auto px-3 py-4" />
        <VersionLine className="border-t border-border px-6 py-4" />
      </SheetContent>
    </Sheet>
  );
}
