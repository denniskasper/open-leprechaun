import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { AppShell } from "@/components/shell/app-shell";
import { AuthGate } from "@/components/shell/auth-gate";
import { LoginPage, SetupPage } from "@/pages/auth";
import { HealthPage } from "@/pages/health";
import { InstrumentsPage } from "@/pages/instruments";
import { PlatformsPage } from "@/pages/platforms";
import { TransactionsPage } from "@/pages/transactions";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A health probe that retries for a minute reports "loading" when the
      // honest answer is "unreachable".
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

const router = createBrowserRouter([
  // Setup and login stand outside the shell: no navigation is offered to
  // someone who has not authenticated.
  { path: "/setup", element: <SetupPage /> },
  { path: "/login", element: <LoginPage /> },
  {
    element: <AuthGate />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <HealthPage /> },
          { path: "transactions", element: <TransactionsPage /> },
          { path: "instruments", element: <InstrumentsPage /> },
          { path: "settings/platforms", element: <PlatformsPage /> },
        ],
      },
    ],
  },
]);

const container = document.getElementById("root");
if (!container) {
  throw new Error("index.html is missing its #root element.");
}

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
