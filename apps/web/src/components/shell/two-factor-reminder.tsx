import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { fetchMeta, type Meta } from "@/api/meta";
import { TWO_FACTOR_QUERY } from "@/api/two-factor";
import { Lamp } from "@/components/patterns/lamp";

/**
 * Whether the reminder shows: only on a production instance that has said
 * two-factor is off. Not knowing — the API has not answered, or failed to —
 * shows nothing, because a warning that may be false teaches the Admin to
 * read past it. Development authenticates nobody and has nothing to remind.
 */
export function remindsOfTwoFactor(
  instance: Meta | undefined,
  enabled: boolean | undefined,
): boolean {
  return instance?.environment === "production" && enabled === false;
}

/**
 * The persistent reminder (ADR-0005): on every page of a production instance
 * while two-factor is off. It cannot be dismissed — it goes when two-factor
 * is on, and not before.
 */
export function TwoFactorReminder() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: fetchMeta, staleTime: Infinity });
  const production = meta.data?.environment === "production";
  const twoFactor = useQuery({ ...TWO_FACTOR_QUERY, enabled: production });

  if (!remindsOfTwoFactor(meta.data, twoFactor.data)) {
    return null;
  }
  return (
    <aside
      aria-label="Two-factor reminder"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-caution/40 bg-caution/5 px-4 py-2.5 text-sm sm:px-8 xl:px-12"
    >
      <Lamp tone="caution" size="sm" />
      <p className="text-pretty">
        <span className="font-medium">Two-factor is off.</span>{" "}
        <span className="text-muted-foreground">
          A leaked password alone would open this ledger.
        </span>
      </p>
      <Link
        to="/settings/security"
        className="font-medium text-caution underline underline-offset-4 hover:text-foreground"
      >
        Set it up
      </Link>
    </aside>
  );
}
