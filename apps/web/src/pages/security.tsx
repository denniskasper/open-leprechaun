import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldOff } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import {
  changePassword,
  fetchSessionCount,
  logOutEverywhere,
  MINIMUM_PASSWORD_LENGTH,
} from "@/api/auth";
import { fetchMeta } from "@/api/meta";
import { EmptyState } from "@/components/patterns/empty-state";
import { ErrorState } from "@/components/patterns/error-state";
import { PasswordField } from "@/components/patterns/password-field";
import { SettingsGroup, SettingsPanel } from "@/components/patterns/settings-panel";
import { useSignOut } from "@/components/shell/sign-out";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/format";

/** "1 session open", "3 sessions open" — the words beside the figure. */
export function describeSessionCount(active: number): string {
  return active === 1 ? "session open" : "sessions open";
}

/**
 * What the other Sessions are, said in words: the count includes this
 * browser, so "everywhere" only has work to do above one.
 */
export function describeOtherSessions(active: number, locale?: string): string {
  if (active <= 1) {
    return "This browser holds the only one.";
  }
  const others = active - 1;
  return others === 1
    ? "This browser holds one of them; 1 other is open elsewhere."
    : `This browser holds one of them; ${formatNumber(others, locale)} others are open elsewhere.`;
}

export function SecurityPage() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: fetchMeta, staleTime: Infinity });

  return (
    <SettingsPanel
      title="Security"
      description="The Admin's password and the Sessions it has opened. Changing the one or ending the others takes effect at once."
    >
      {meta.data?.environment === "development" ? (
        <div className="py-8">
          <EmptyState
            icon={ShieldOff}
            title="Nothing to secure in development"
            description="A development instance authenticates nobody: there is no Session to end and no login for a password to protect. These controls appear on a production instance."
          />
        </div>
      ) : (
        // Once the instance has said what it is — or failed to, in which
        // case the groups show their own unreachable states.
        !meta.isPending && [<SessionsGroup key="sessions" />, <PasswordGroup key="password" />]
      )}
    </SettingsPanel>
  );
}

function SessionsGroup() {
  const { data: active, error, refetch } = useQuery({
    queryKey: ["auth", "sessions"],
    queryFn: fetchSessionCount,
  });
  const signOutEverywhere = useSignOut(logOutEverywhere);

  return (
    <SettingsGroup
      title="Sessions"
      description="Each browser or client that logged in holds its own Session. A Session records no device or address, so they are counted rather than listed."
    >
      {error ? (
        <ErrorState
          title="The Session count could not be loaded"
          detail="The API did not answer with the number of open Sessions."
          onRetry={() => void refetch()}
        />
      ) : (
        active !== undefined && (
          <div>
            <p className="flex items-baseline gap-3">
              <span
                data-testid="session-count"
                className="font-mono text-2xl font-semibold tabular-nums"
              >
                {formatNumber(active)}
              </span>
              <span className="microlabel text-muted-foreground">
                {describeSessionCount(active)}
              </span>
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">{describeOtherSessions(active)}</p>
          </div>
        )
      )}
      <div className="space-y-2">
        <Button
          variant="outline"
          disabled={signOutEverywhere.isPending}
          onClick={() => signOutEverywhere.mutate()}
        >
          {signOutEverywhere.isPending ? "Signing out…" : "Sign out everywhere"}
        </Button>
        <p className="text-sm text-pretty text-muted-foreground">
          Ends every Session, this one included. You will be asked to log in again here.
        </p>
        {signOutEverywhere.isError && (
          <p role="alert" className="text-sm text-alarm">
            {signOutEverywhere.error.message}
          </p>
        )}
      </div>
    </SettingsGroup>
  );
}

function PasswordGroup() {
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const currentId = useId();
  const nextId = useId();
  const confirmationId = useId();

  const change = useMutation({
    mutationFn: () => changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setConfirmation("");
      // The other Sessions are gone; the count above should say so.
      return queryClient.invalidateQueries({ queryKey: ["auth", "sessions"] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const differs = next !== confirmation;
    setMismatch(differs);
    if (differs) {
      change.reset();
    } else {
      change.mutate();
    }
  }

  return (
    <SettingsGroup
      title="Password"
      description="Changing it ends every other Session and keeps this one, so a password that may have leaked stops working everywhere but here."
    >
      <form onSubmit={submit} className="space-y-5">
        <PasswordField
          id={currentId}
          label="Current password"
          value={current}
          onChange={setCurrent}
          autoComplete="current-password"
        />
        <PasswordField
          id={nextId}
          label="New password"
          hint={`At least ${MINIMUM_PASSWORD_LENGTH} characters.`}
          minLength={MINIMUM_PASSWORD_LENGTH}
          value={next}
          onChange={setNext}
          autoComplete="new-password"
        />
        <PasswordField
          id={confirmationId}
          label="Confirm new password"
          minLength={MINIMUM_PASSWORD_LENGTH}
          value={confirmation}
          onChange={setConfirmation}
          autoComplete="new-password"
          error={mismatch ? "The two entries differ." : undefined}
        />
        {change.isError && (
          <ErrorState title="The password was not changed" detail={change.error.message} />
        )}
        {change.isSuccess && (
          <p role="status" className="text-sm text-signal">
            Password changed. Every other Session was signed out.
          </p>
        )}
        <Button type="submit" disabled={change.isPending}>
          {change.isPending ? "Changing…" : "Change password"}
        </Button>
      </form>
    </SettingsGroup>
  );
}
