/**
 * Theme selection: light, dark, or follow the OS.
 *
 * The chosen preference lives in localStorage under "theme"; "system" is the
 * absence of a stored value. index.html applies the class before first paint
 * with the same rules, so the page never flashes the wrong theme. The
 * theme-color meta follows the class, its two colours stated on the meta
 * itself.
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
  syncTheme();
}

function syncTheme(): void {
  const preference = getThemePreference();
  const dark = preference === "dark" || (preference === "system" && systemDark().matches);
  document.documentElement.classList.toggle("dark", dark);

  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  const color = themeColor?.dataset[dark ? "dark" : "light"];
  if (themeColor && color) themeColor.content = color;
}

/** Keep a "system" preference tracking the OS while the app is open. */
export function watchSystemTheme(): () => void {
  const media = systemDark();
  media.addEventListener("change", syncTheme);
  return () => media.removeEventListener("change", syncTheme);
}
