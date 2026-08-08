import { useQuery } from "@tanstack/react-query";
import { Heart } from "lucide-react";
import { fetchMeta, type Meta } from "@/api/meta";
import { cn } from "@/lib/utils";

/**
 * Which instance this is, fetched once per session — a running instance never
 * changes identity. Until the API answers, or if it never does, the shell
 * shows no badge and no version, which is also what production looks like:
 * absence must never read as "production", so the version line is the
 * confirmation that the answer arrived.
 */
function useInstance() {
  const { data } = useQuery({
    queryKey: ["meta"],
    queryFn: fetchMeta,
    staleTime: Infinity,
  });
  return data;
}

/** What the badge says: the environment outside production, nothing within it. */
export function badgeLabel(instance: Meta | undefined): string | null {
  if (!instance || instance.environment === "production") {
    return null;
  }
  return "dev";
}

/** The environment badge: shown outside production, absent within it. */
export function EnvironmentBadge() {
  const label = badgeLabel(useInstance());
  if (!label) {
    return null;
  }
  return (
    <span className="microlabel rounded-sm border border-caution/50 px-1.5 py-0.5 text-caution">
      {label}
    </span>
  );
}

/** The version line: a commit hash in development, a release version elsewhere. */
export function VersionLine({ className }: { className?: string }) {
  const instance = useInstance();
  if (!instance) {
    return null;
  }
  return (
    <div className={cn("flex items-end justify-between gap-3", className)}>
      <div className="space-y-1">
        <p className="microlabel text-muted-foreground">Version</p>
        <p className="font-mono text-xs tabular-nums text-muted-foreground">{instance.version}</p>
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        made with
        <Heart aria-hidden className="size-3 fill-alarm text-alarm" />
        <span className="sr-only">love</span>
      </p>
    </div>
  );
}
