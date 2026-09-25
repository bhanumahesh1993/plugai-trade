import { StrictMode, lazy, Suspense, type ComponentType } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes, useParams } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./styles.css";
import { ThemeProvider } from "@/components/theme";
import { AppShell } from "@/components/shell";
import { ToastProvider } from "@/components/kit";
import { Panel } from "@/components/ui";
import { SCREENS } from "@/screens";

const Home = lazy(() => import("@/pages/Home"));

// One file per screen: pages/screens/<slug>.tsx (slug from screens.ts). Found automatically.
const modules = import.meta.glob<{ default: ComponentType }>("./pages/screens/*.tsx");
const screenPages = Object.fromEntries(
  Object.entries(modules).map(([path, load]) => [path.split("/").pop()!.replace(".tsx", ""), lazy(load)]),
);


const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } } });

function NotYet() {
  const { slug } = useParams();
  const s = SCREENS.find((x) => x.slug === slug);
  return (
    <Panel title={s?.title ?? "Screen"} className="max-w-[640px]">
      <p>This screen is being moved to the new design. Until then it works in the classic view.</p>
      <p className="mt-2 text-[13px] text-muted">Run <code>plugai-trade start --classic</code> to open it.</p>
    </Panel>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <ToastProvider>
        <BrowserRouter>
          <Suspense fallback={null}>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<Home />} />
                {Object.entries(screenPages).map(([slug, Page]) => (
                  <Route key={slug} path={slug} element={<Page />} />
                ))}
                <Route path=":slug" element={<NotYet />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
