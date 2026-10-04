import { Input } from "@/components/ui/input";

/**
 * A labelled field for the six digits an authenticator shows. Shared by the
 * login screen and the Security panel so a code is asked for the same way
 * wherever one is owed: numeric keypad on a phone, offered by a password
 * manager that holds the secret, set wide in the fixed-pitch face.
 */
export function CodeField({
  id,
  hint,
  value,
  onChange,
  autoFocus,
}: {
  id: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
}) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="microlabel block text-muted-foreground">
        Authenticator code
      </label>
      <Input
        id={id}
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        // Room for the space an authenticator shows mid-code.
        maxLength={7}
        placeholder="000 000"
        className="w-36 font-mono text-base tracking-widest tabular-nums placeholder:text-muted-foreground/50"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoFocus={autoFocus}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-sm text-pretty text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}
