import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useNavigate } from "react-router";
import { fetchSession, logOut } from "@/api/auth";
import { Button } from "@/components/ui/button";

/**
 * Leaving is one motion whichever way the Session ends: revoke it, drop
 * every cached answer so nothing read under the old Session survives into
 * the next one, and stand at the login screen.
 */
export function useSignOut(revoke: () => Promise<void>) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: revoke,
    onSuccess: () => {
      queryClient.getQueryCache().clear();
      navigate("/login", { replace: true });
    },
  });
}

/**
 * The header's way out, on every page and at every width. It appears only
 * where there is a Session to end — development authenticates nobody, so
 * there it offers nothing.
 */
export function SignOutButton() {
  // Reads what the auth gate already asked; never asks on its own account.
  const { data: session } = useQuery({
    queryKey: ["auth", "session"],
    queryFn: fetchSession,
    enabled: false,
  });
  const signOut = useSignOut(logOut);

  if (!session) {
    return null;
  }
  return (
    <>
      {signOut.isError && (
        <span role="alert" className="text-xs text-alarm">
          Sign-out failed
        </span>
      )}
      <Button
        variant="ghost"
        size="icon"
        aria-label="Sign out"
        title="Sign out"
        disabled={signOut.isPending}
        onClick={() => signOut.mutate()}
      >
        <LogOut aria-hidden />
      </Button>
    </>
  );
}
