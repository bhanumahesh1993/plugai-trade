import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "book" | "desk";
const Ctx = createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({ theme: "book", setTheme: () => {} });

function initial(): Theme {
  try {
    const saved = localStorage.getItem("plugai-theme");
    if (saved === "book" || saved === "desk") return saved;
  } catch { /* private mode: fall through */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "desk" : "book";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const t = initial();
    document.documentElement.dataset.theme = t; // before first paint, so charts read the right tokens
    return t;
  });
  const setTheme = (t: Theme) => {
    document.documentElement.dataset.theme = t; // synchronously: charts re-read CSS vars on this render
    setThemeState(t);
  };
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("plugai-theme", theme); } catch { /* ignore */ }
  }, [theme]);
  return <Ctx.Provider value={{ theme, setTheme }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
