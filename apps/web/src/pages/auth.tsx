import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";
import { fetchSetupStatus, logIn, MINIMUM_PASSWORD_LENGTH, runSetup } from "@/api/auth";
import { CodeField } from "@/components/patterns/code-field";
import { ErrorState } from "@/components/patterns/error-state";
import { PasswordField } from "@/components/patterns/password-field";
import { AuthShell } from "@/components/shell/auth-shell";
import { Button } from "@/components/ui/button";

/**
 * The two screens that exist before the shell does: first-run setup and
 * login. Both stand outside the app shell — no navigation is offered to
 * someone who has not authenticated — but inside the same instrument look.
 */
export function SetupPage() {
  const { data: status } = useQuery({ queryKey: ["auth", "setup"], queryFn: fetchSetupStatus });
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const enter = useEnter({ setUpFirst: true });
  const passwordId = useId();
  const confirmationId = useId();

  // Setup runs once; an instance that has its admin only ever offers login.
  // Not while this page's own submission is the reason the admin now exists,
  // though — that path is mid-flight to "/" and must not be diverted.
  if (status && !status.required && enter.isIdle) {
    return <Navigate to="/login" replace />;
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const differs = password !== confirmation;
    setMismatch(differs);
    if (!differs) {
      enter.mutate({ password });
    }
  }

  return (
    <AuthShell
      eyebrow="First run"
      title="Set the password"
      description="A fresh instance serves nothing until its Admin has a password. It is set once, here, and this screen never returns."
    >
      <form onSubmit={submit} className="space-y-5">
        <PasswordField
          id={passwordId}
          label="Password"
          hint={`At least ${MINIMUM_PASSWORD_LENGTH} characters.`}
          minLength={MINIMUM_PASSWORD_LENGTH}
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          autoFocus
        />
        <PasswordField
          id={confirmationId}
          label="Confirm password"
          minLength={MINIMUM_PASSWORD_LENGTH}
          value={confirmation}
          onChange={setConfirmation}
          autoComplete="new-password"
          error={mismatch ? "The two entries differ." : undefined}
        />
        {enter.isError && (
          <ErrorState title="Setup failed" detail={enter.error.message} />
        )}
        <Button type="submit" className="w-full" disabled={enter.isPending}>
          {enter.isPending ? "Setting up…" : "Set password and enter"}
        </Button>
      </form>
    </AuthShell>
  );
}

export function LoginPage() {
  const { data: status } = useQuery({ queryKey: ["auth", "setup"], queryFn: fetchSetupStatus });
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const enter = useEnter();
  const passwordId = useId();
  const codeId = useId();
  // The API said the password was right and a code is owed. The password
  // stays in memory for the second request — login is one endpoint, and it
  // judges both factors together.
  const [codeOwed, setCodeOwed] = useState(false);

  // No admin yet means there is nothing to log in to; setup comes first.
  if (status?.required) {
    return <Navigate to="/setup" replace />;
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    enter.mutate(codeOwed ? { password, code } : { password }, {
      onSuccess: (outcome) => {
        if (outcome === "code_required") {
          setCodeOwed(true);
        }
      },
    });
  }

  function startOver() {
    setCodeOwed(false);
    setCode("");
    setPassword("");
    enter.reset();
  }

  if (codeOwed) {
    return (
      <AuthShell
        eyebrow="Two-factor is on"
        title="Enter the code"
        description="The password was right. This instance also asks for the current code from your authenticator app."
      >
        <form onSubmit={submit} className="space-y-5">
          <CodeField
            id={codeId}
            hint="Lost the authenticator? There are no recovery codes — two-factor is turned off on the server, as docs/runbook.md describes."
            value={code}
            onChange={setCode}
            autoFocus
          />
          {enter.isError && <ErrorState title="Login failed" detail={enter.error.message} />}
          <Button type="submit" className="w-full" disabled={enter.isPending}>
            {enter.isPending ? "Checking…" : "Verify and log in"}
          </Button>
          <Button type="button" variant="ghost" className="w-full" onClick={startOver}>
            Start over
          </Button>
        </form>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow="This instance is protected"
      title="Log in"
      description="The session lives in an httpOnly cookie and renews itself with use; an idle month logs you out."
    >
      <form onSubmit={submit} className="space-y-5">
        <PasswordField
          id={passwordId}
          label="Password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          autoFocus
        />
        {enter.isError && (
          <ErrorState title="Login failed" detail={enter.error.message} />
        )}
        <Button type="submit" className="w-full" disabled={enter.isPending}>
          {enter.isPending ? "Checking…" : "Log in"}
        </Button>
      </form>
    </AuthShell>
  );
}

/**
 * Entering the app is one motion from either screen: setup logs in with the
 * password it just set, so login stays the single endpoint that mints
 * sessions.
 */
function useEnter({ setUpFirst = false }: { setUpFirst?: boolean } = {}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ password, code }: { password: string; code?: string }) => {
      if (setUpFirst) {
        await runSetup(password);
      }
      return logIn(password, code);
    },
    onSuccess: async (outcome) => {
      if (outcome === "code_required") {
        // Not in yet: the login screen asks for the code and comes back.
        return;
      }
      // Setup state and session both changed; let every reader see it fresh.
      await queryClient.invalidateQueries();
      // A fresh instance opens on the walk to its first report (ticket 58).
      navigate(setUpFirst ? "/first-run" : "/", { replace: true });
    },
  });
}
