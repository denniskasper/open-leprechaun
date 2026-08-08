import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
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

const container = document.getElementById("root");
if (!container) {
  throw new Error("index.html is missing its #root element.");
}

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
