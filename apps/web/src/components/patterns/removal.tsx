import { type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";

/**
 * The inline two-step a row is removed by — a Platform, an Account or an
 * Instrument alike, and the same one a Connection is removed by. The button
 * is never disabled by a guess about what the row holds: the server is the
 * one authority on whether removal is allowed, and its refusal is kept here
 * to be shown at the row. `invalidates` is the list the row disappears from.
 */
export function useRemoval(remove: () => Promise<void>, invalidates: QueryKey) {
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: remove,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: invalidates }),
  });

  return {
    confirming,
    pending: mutation.isPending,
    refusal: mutation.error?.message,
    ask: () => setConfirming(true),
    keep: () => setConfirming(false),
    confirm: () => mutation.mutate(),
    forget: mutation.reset,
  };
}

export type Removal = ReturnType<typeof useRemoval>;

/** Remove → "Remove for good" / "Keep". `name` tells one row's buttons from the next. */
export function RemoveButtons({
  removal,
  name,
  className = "",
}: {
  removal: Removal;
  name: string;
  className?: string;
}) {
  if (removal.confirming) {
    return (
      <>
        <Button
          variant="ghost"
          size="sm"
          className={`text-alarm ${className}`}
          disabled={removal.pending}
          aria-label={`Remove ${name} for good`}
          onClick={removal.confirm}
        >
          {removal.pending ? "Removing…" : "Remove for good"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className={className}
          aria-label={`Keep ${name}`}
          onClick={removal.keep}
        >
          Keep
        </Button>
      </>
    );
  }
  return (
    <Button
      variant="ghost"
      size="sm"
      className={`text-muted-foreground ${className}`}
      aria-label={`Remove ${name}`}
      onClick={removal.ask}
    >
      <Trash2 aria-hidden />
      Remove
    </Button>
  );
}
