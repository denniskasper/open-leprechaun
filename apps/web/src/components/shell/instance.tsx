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

/**
 * What the version line says. Development runs the working copy, so it shows
 * the bare commit hash; everywhere else runs a release, and a release is named
 * `v` and its semantic version.
 */
export function versionLabel(instance: Meta | undefined): string | null {
  if (!instance) {
    return null;
  }
  if (instance.environment === "development") {
    return instance.version;
  }
  return instance.version.startsWith("v") ? instance.version : `v${instance.version}`;
}

/** The version line: a commit hash in development, a release version elsewhere. */
export function VersionLine({ className }: { className?: string }) {
  const instance = useInstance();
  const version = versionLabel(instance);
  if (!version) {
    return null;
  }
  return (
    // One mono row: which build this is, and who it came from. The version
    // needs no caption — a hash or a v-number says what it is on sight.
    <div
      className={cn(
        "flex items-center justify-between gap-3 font-mono text-2xs text-muted-foreground",
        className,
      )}
    >
      <span className="tabular-nums">{version}</span>
      <span className="flex items-center gap-1.5">
        made with
        <Heart aria-hidden className="size-3 fill-alarm text-alarm" />
        <span className="sr-only">love</span>
      </span>
    </div>
  );
}
