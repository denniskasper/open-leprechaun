/**
 * Theme selection: light, dark, or follow the OS.
 *
 * The chosen preference lives in localStorage under "theme"; "system" is the
 * absence of a stored value. index.html applies the class before first paint
 * with the same rules, so the page never flashes the wrong theme.
 */

export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "theme";
const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)");

export function getThemePreference(): ThemePreference {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" ? stored : "system";
}

export function setThemePreference(preference: ThemePreference): void {
  if (preference === "system") {
    localStorage.removeItem(STORAGE_KEY);
  } else {
    localStorage.setItem(STORAGE_KEY, preference);
  }
  syncThemeClass();
}

function syncThemeClass(): void {
  const preference = getThemePreference();
  const dark = preference === "dark" || (preference === "system" && systemDark().matches);
  document.documentElement.classList.toggle("dark", dark);
}

/** Keep a "system" preference tracking the OS while the app is open. */
export function watchSystemTheme(): () => void {
  const media = systemDark();
  media.addEventListener("change", syncThemeClass);
  return () => media.removeEventListener("change", syncThemeClass);
}
