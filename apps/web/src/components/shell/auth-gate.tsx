import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet } from "react-router";
import { fetchSession, fetchSetupStatus } from "@/api/auth";
import { fetchMeta } from "@/api/meta";

/**
 * The turnstile in front of every shell route. Outside development, an
 * instance with no admin sends every path to the setup screen, and an
 * instance with an admin but no session sends every path to login.
 * Development waves straight through — no setup, no login.
 *
 * When the API cannot be reached at all, the gate opens rather than locks:
 * the pages behind it show their own unreachable states, which say more than
 * a login screen that cannot log anyone in.
 */
export function AuthGate() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: fetchMeta, staleTime: Infinity });
  const production = meta.data?.environment === "production";
  const setup = useQuery({
    queryKey: ["auth", "setup"],
    queryFn: fetchSetupStatus,
    enabled: production,
  });
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: fetchSession,
    enabled: production && setup.data?.required === false,
  });

  if (meta.isError || setup.isError || session.isError) {
    return <Outlet />;
  }
  if (meta.isPending) {
    return null;
  }
  if (!production) {
    return <Outlet />;
  }
  if (setup.isPending) {
    return null;
  }
  if (setup.data.required) {
    return <Navigate to="/setup" replace />;
  }
  if (session.isPending) {
    return null;
  }
  if (!session.data) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
