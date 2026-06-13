"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "light" | "dark";

function current(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function setTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("tpo-theme", theme);
  } catch {
    /* private mode: ignore */
  }
}

/**
 * Floating dark-mode toggle. Light is the default; documents stay paper in both
 * themes (see globals.css). The real app will fold this into the avatar menu;
 * for now it's a fixed control so the theme is switchable everywhere.
 */
export function ThemeToggle() {
  const [theme, setLocal] = useState<Theme>("light");
  useEffect(() => setLocal(current()), []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setLocal(next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
      title="Toggle dark mode"
      className="fixed bottom-[18px] right-[18px] z-[200] grid h-[42px] w-[42px] place-items-center rounded-full border border-line bg-surface text-ink shadow-[var(--shadow-panel)] transition-transform hover:-translate-y-0.5"
    >
      {theme === "dark" ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}
    </button>
  );
}
