import { HealthPanel } from "./components/HealthPanel";

export function App() {
  return (
    <div className="instrument-field min-h-dvh">
      <div className="relative mx-auto flex min-h-dvh w-full max-w-2xl flex-col px-6 sm:px-10">
        <header className="rise flex items-baseline justify-between gap-4 border-b border-hairline py-5 font-mono text-[0.6rem] tracking-[0.2em] uppercase">
          <span className="text-bone">Open Leprechaun</span>
          <span className="text-bone-faint">Walking skeleton</span>
        </header>

        <main className="flex flex-1 items-center py-20">
          <HealthPanel />
        </main>

        <footer
          className="rise border-t border-hairline py-5 font-mono text-[0.6rem] tracking-[0.2em] text-bone-faint uppercase"
          style={{ animationDelay: "480ms" }}
        >
          Nothing beyond this check is wired yet
        </footer>
      </div>
    </div>
  );
}
