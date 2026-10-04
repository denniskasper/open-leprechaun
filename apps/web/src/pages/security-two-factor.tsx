import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import {
  activateTwoFactor,
  beginEnrollment,
  disableTwoFactor,
  TWO_FACTOR_QUERY,
  type Enrollment,
} from "@/api/two-factor";
import { CodeField } from "@/components/patterns/code-field";
import { ErrorState } from "@/components/patterns/error-state";
import { Lamp, TONE, type Tone } from "@/components/patterns/lamp";
import { PasswordField } from "@/components/patterns/password-field";
import { QrCode } from "@/components/patterns/qr-code";
import { SettingsGroup } from "@/components/patterns/settings-panel";
import { Button } from "@/components/ui/button";

/** The command the enrollment copy promises; `docs/runbook.md` documents it. */
export const SERVER_SIDE_DISABLE = "pnpm auth:disable-two-factor";

/**
 * A base32 secret in groups of four, the way it is read aloud or typed into
 * an authenticator by hand. Display only — the copy button hands over the
 * unbroken secret.
 */
export function groupSecret(secret: string): string {
  return secret.match(/.{1,4}/g)?.join(" ") ?? secret;
}

/**
 * The second factor: off, being set up, or on. Setting it up is the one
 * place the secret is ever shown, and the place the Admin is told — before
 * anything activates — that there are no recovery codes.
 */
export function TwoFactorGroup() {
  const queryClient = useQueryClient();
  const { data: enabled, error, refetch } = useQuery(TWO_FACTOR_QUERY);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const begin = useMutation({
    mutationFn: beginEnrollment,
    onSuccess: (issued) => {
      setNotice(null);
      setEnrollment(issued);
    },
  });

  async function settled(message: string) {
    // The reminder in the shell and the Session count both follow from this.
    // Awaited before the panel moves on, so the reading and the notice never
    // disagree about whether two-factor is on.
    await queryClient.invalidateQueries({ queryKey: ["auth"] });
    setEnrollment(null);
    setNotice(message);
  }

  return (
    <SettingsGroup
      title="Two-factor"
      description="A code from an authenticator app, asked for at login on top of the password. There are no recovery codes: a lost authenticator is answered by turning two-factor off on the server."
    >
      {error ? (
        <ErrorState
          title="The two-factor state could not be loaded"
          detail="The API did not say whether two-factor is on."
          onRetry={() => void refetch()}
        />
      ) : (
        enabled !== undefined && (
          <>
            {enrollment ? (
              <Reading tone="caution" state="Setting up" caption="not enforced until a code proves it" />
            ) : enabled ? (
              <Reading tone="signal" state="On" caption="login asks for a code" />
            ) : (
              <Reading tone="caution" state="Off" caption="the password alone opens a Session" />
            )}
            {notice && (
              <p role="status" className="text-sm text-signal">
                {notice}
              </p>
            )}
            {enrollment ? (
              <EnrollmentSteps
                enrollment={enrollment}
                onCancel={() => setEnrollment(null)}
                onActivated={() =>
                  settled("Two-factor is on. Every other Session was signed out.")
                }
              />
            ) : enabled ? (
              <DisableForm
                onDisabled={() => settled("Two-factor is off. The password alone opens a Session.")}
              />
            ) : (
              <div className="space-y-2">
                <Button disabled={begin.isPending} onClick={() => begin.mutate()}>
                  {begin.isPending ? "Preparing…" : "Set up two-factor"}
                </Button>
                {begin.isError && (
                  <p role="alert" className="text-sm text-alarm">
                    {begin.error.message}
                  </p>
                )}
              </div>
            )}
          </>
        )
      )}
    </SettingsGroup>
  );
}

/** The state as an instrument reading: lamp, value, and what it means. */
function Reading({ tone, state, caption }: { tone: Tone; state: string; caption: string }) {
  return (
    <p className="flex items-center gap-3">
      <Lamp tone={tone} pulsing={false} />
      <span
        data-testid="two-factor-state"
        className={`font-mono text-2xl font-semibold uppercase ${TONE[tone].text}`}
      >
        {state}
      </span>
      <span className="microlabel text-muted-foreground">{caption}</span>
    </p>
  );
}

function EnrollmentSteps({
  enrollment,
  onCancel,
  onActivated,
}: {
  enrollment: Enrollment;
  onCancel: () => void;
  onActivated: () => Promise<void>;
}) {
  const [code, setCode] = useState("");
  const codeId = useId();
  const activate = useMutation({
    mutationFn: () => activateTwoFactor(code),
    onSuccess: onActivated,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    activate.mutate();
  }

  return (
    <ol className="space-y-8">
      <Step number="01" title="Add it to your authenticator">
        <p className="text-sm text-pretty text-muted-foreground">
          Scan the code, or paste the URI or the secret into an app or password store that
          generates one-time codes. This is the only time the secret is shown.
        </p>
        <QrCode text={enrollment.uri} label="QR code of the two-factor setup URI" />
        <Copyable label="Secret" value={enrollment.secret} shown={groupSecret(enrollment.secret)} />
        <Copyable label="URI" value={enrollment.uri} />
      </Step>

      <Step number="02" title="Know the way back in">
        <div className="space-y-2 border-l-2 border-caution pl-4 text-sm text-pretty">
          <p className="font-medium">There are no recovery codes.</p>
          <p className="text-muted-foreground">
            Keep the secret in a password store: with it, a replacement phone is set up in a
            minute. Without it and without the authenticator, the only way back in is to turn
            two-factor off on the server itself:
          </p>
          <p>
            <code className="font-mono text-xs break-all">{SERVER_SIDE_DISABLE}</code>
          </p>
          <p className="text-muted-foreground">
            That takes a shell on the host — nothing in this app can do it, and nobody without
            the host can. The steps are in <span className="font-mono text-xs">docs/runbook.md</span>.
          </p>
        </div>
      </Step>

      <Step number="03" title="Prove it works">
        <form onSubmit={submit} className="space-y-5">
          <CodeField
            id={codeId}
            hint="Two-factor turns on only once a code from the authenticator verifies. Turning it on signs out every other Session."
            value={code}
            onChange={setCode}
          />
          {activate.isError && (
            <ErrorState title="Two-factor was not turned on" detail={activate.error.message} />
          )}
          <div className="flex flex-wrap gap-3">
            <Button type="submit" disabled={activate.isPending}>
              {activate.isPending ? "Verifying…" : "Verify and turn on"}
            </Button>
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </form>
      </Step>
    </ol>
  );
}

function Step({ number, title, children }: { number: string; title: string; children: ReactNode }) {
  return (
    <li className="space-y-4">
      <h3 className="flex items-baseline gap-3 text-sm font-medium">
        <span aria-hidden className="microlabel text-muted-foreground">
          {number}
        </span>
        {title}
      </h3>
      {children}
    </li>
  );
}

/** A value to carry elsewhere: set in the data face, selectable, with a copy button. */
function Copyable({ label, value, shown = value }: { label: string; value: string; shown?: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      // No clipboard access; the value is on screen to be selected by hand.
      setCopied(false);
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="microlabel text-muted-foreground">{label}</span>
        <Button type="button" variant="ghost" size="sm" onClick={() => void copy()}>
          <span aria-live="polite">{copied ? "Copied" : `Copy ${label.toLowerCase()}`}</span>
        </Button>
      </div>
      <p
        data-testid={`two-factor-${label.toLowerCase()}`}
        className="rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs break-all select-all"
      >
        {shown}
      </p>
    </div>
  );
}

function DisableForm({ onDisabled }: { onDisabled: () => Promise<void> }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const passwordId = useId();
  const codeId = useId();
  const disable = useMutation({
    mutationFn: () => disableTwoFactor(password, code),
    onSuccess: onDisabled,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    disable.mutate();
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <p className="text-sm text-pretty text-muted-foreground">
        Turning it off takes both factors. Without the authenticator it is turned off on the
        server instead: <code className="font-mono text-xs">{SERVER_SIDE_DISABLE}</code>, described
        in <span className="font-mono text-xs">docs/runbook.md</span>.
      </p>
      <PasswordField
        id={passwordId}
        label="Current password"
        value={password}
        onChange={setPassword}
        autoComplete="current-password"
      />
      <CodeField id={codeId} value={code} onChange={setCode} />
      {disable.isError && (
        <ErrorState title="Two-factor was not turned off" detail={disable.error.message} />
      )}
      <Button type="submit" variant="outline" disabled={disable.isPending}>
        {disable.isPending ? "Turning off…" : "Turn off two-factor"}
      </Button>
    </form>
  );
}
