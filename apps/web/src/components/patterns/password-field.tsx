import { Input } from "@/components/ui/input";

/**
 * A labelled password input with room for a hint or, in its place, an error.
 * Shared by every form that takes a password — setup, login, the Security
 * panel — so they state their rules and their refusals the same way.
 */
export function PasswordField({
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
