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
  const [theme, setTheme] = useState<Theme>(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("plugai-theme", theme); } catch { /* ignore */ }
  }, [theme]);
  return <Ctx.Provider value={{ theme, setTheme }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
