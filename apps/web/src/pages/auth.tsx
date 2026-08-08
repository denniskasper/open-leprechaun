import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clover } from "lucide-react";
import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { Navigate, useNavigate } from "react-router";
import { fetchSetupStatus, logIn, runSetup } from "@/api/auth";
import { ErrorState } from "@/components/patterns/error-state";
import { EnvironmentBadge } from "@/components/shell/instance";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { watchSystemTheme } from "@/lib/theme";

/** The floor the API enforces; stated here so the form can say it up front. */
const MINIMUM_PASSWORD_LENGTH = 12;

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
      enter.mutate(password);
    }
  }

  return (
    <AuthScreen
      eyebrow="First run"
      title="Set the password"
      description="A fresh instance serves nothing until its Admin has a password. It is set once, here, and this screen never returns."
    >
      <form onSubmit={submit} className="space-y-5">
        <Field
          id={passwordId}
          label="Password"
          hint={`At least ${MINIMUM_PASSWORD_LENGTH} characters.`}
          minLength={MINIMUM_PASSWORD_LENGTH}
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          autoFocus
        />
        <Field
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
    </AuthScreen>
  );
}

export function LoginPage() {
  const { data: status } = useQuery({ queryKey: ["auth", "setup"], queryFn: fetchSetupStatus });
  const [password, setPassword] = useState("");
  const enter = useEnter();
  const passwordId = useId();

  // No admin yet means there is nothing to log in to; setup comes first.
  if (status?.required) {
    return <Navigate to="/setup" replace />;
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    enter.mutate(password);
  }

  return (
    <AuthScreen
      eyebrow="This instance is protected"
      title="Log in"
      description="The session lives in an httpOnly cookie and renews itself with use; an idle month logs you out."
    >
      <form onSubmit={submit} className="space-y-5">
        <Field
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
    </AuthScreen>
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
    mutationFn: async (password: string) => {
      if (setUpFirst) {
        await runSetup(password);
      }
      await logIn(password);
    },
    onSuccess: async () => {
      // Setup state and session both changed; let every reader see it fresh.
      await queryClient.invalidateQueries();
      navigate("/", { replace: true });
    },
  });
}

function Field({
  id,
  label,
  hint,
  error,
  minLength,
  value,
  onChange,
  autoComplete,
  autoFocus,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  minLength?: number;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  autoFocus?: boolean;
}) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="microlabel block text-muted-foreground">
        {label}
      </label>
      <Input
        id={id}
        type="password"
        required
        minLength={minLength}
        className="font-mono"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
      />
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-sm text-alarm">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="text-sm text-muted-foreground">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

function AuthScreen({
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
