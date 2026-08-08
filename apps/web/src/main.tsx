import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { AppShell } from "@/components/shell/app-shell";
import { HealthPage } from "@/pages/health";
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
  {
    element: <AppShell />,
    children: [{ index: true, element: <HealthPage /> }],
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
