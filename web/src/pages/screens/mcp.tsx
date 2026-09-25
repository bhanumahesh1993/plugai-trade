import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { get, post } from "@/lib/api";
import { Button, Panel } from "@/components/ui";
import { Badge, Callout, DataTable, Switch, useToast } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { CopyButton, ErrorLine } from "@/components/settings/common";

interface Tool { tool: string; tag: "READ" | "PAPER"; does: string; offered: boolean; [k: string]: unknown }
interface LogRow { time: string; tool: string; tag: string; args: string; result: unknown; [k: string]: unknown }
interface MCP { tools: Tool[]; paper_order: boolean; server: string; config: string; log: LogRow[]; offered: number }
const KEY = ["mcp"];

export default function McpServer() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: m, error, refetch, isFetching } = useQuery({ queryKey: KEY, queryFn: () => get<MCP>("/api/settings/mcp") });
  const [showCfg, setShowCfg] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const toggle = useMutation({
    mutationFn: (on: boolean) => post<MCP>("/api/settings/mcp/paper-order", { on }),
    onSuccess: (d) => { qc.setQueryData(KEY, d); toast(d.paper_order ? "Switched paper_order on. Restart Claude Desktop so the tool list refreshes." : "Switched paper_order off: a strictly read-only session. Restart Claude Desktop."); },
  });
  if (error) return <Callout tone="danger" title="MCP Server could not load">{(error as Error).message}</Callout>;
  if (!m) return <div className="min-h-[60vh]" aria-busy="true" />;
  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-5">
          <p className="text-[13px] text-muted">Use Claude Desktop as a front end to your journal, backtests and paper desk. Paper only: PlugAI-Trade never places real orders.</p>
          <Panel title="Tools">
            <DataTable rows={m.tools} rowKey={(r) => r.tool} columns={[
              { key: "tool", header: "Tool", render: (r) => <code className="text-[13px] font-medium">{r.tool}</code> },
              { key: "tag", header: "Tag", render: (r) => <Badge tone={r.tag === "READ" ? "neutral" : "indigo"}>{r.tag}</Badge> },
              { key: "does", header: "What it does" },
              { key: "offered", header: "Offered", render: (r) => (r.offered ? "Yes" : <span className="text-muted">Switched off</span>) },
            ]} />
            <p className="mt-3 text-[13px] text-muted">READ tools look at your data. PAPER creates a pending paper order that waits in Paper Trading › Paper Desk for your Accept or Reject. There is no third kind: the app has no order code, so a real order has nowhere to go.</p>
            <div className="mt-3 border-t border-line pt-2">
              <Switch checked={m.paper_order} onChange={(v) => toggle.mutate(v)} label={<code className="text-[14px]">paper_order</code>}
                hint="Switch off for a strictly read-only session. Restart Claude Desktop after changing it so the tool list refreshes." />
            </div>
            <ErrorLine error={toggle.error} />
          </Panel>

          <Panel title="Claude Desktop">
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-2">
                <CopyButton variant="primary" size="md" text={m.config} label="Copy config for Claude Desktop" done="Copied the config for Claude Desktop" />
                <Button variant="quiet" onClick={() => setShowCfg((x) => !x)}>{showCfg ? "Hide the config" : "Show the config"}</Button>
              </div>
              {showCfg && <pre className="scroll-thin overflow-auto rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[13px]">{m.config}</pre>}
              <p className="text-[13px] text-muted">In Claude Desktop open Settings, Developer, Edit Config; paste it beside any broker entry already there, save, and restart Claude Desktop. It starts the server with <code>plugai-trade mcp</code>, the same command you can run in a terminal.</p>
              <Callout tone="info">ChatGPT's developer-mode connectors need a public HTTPS address. That suits broker-hosted servers, not a program on your laptop: use Claude Desktop for this lab.</Callout>
            </div>
          </Panel>

          <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
            <div className="flex items-center gap-2 px-4 py-2.5">
              <button type="button" aria-expanded={logOpen} onClick={() => setLogOpen(!logOpen)} className="flex flex-1 items-center gap-2 text-left text-[14px] font-semibold">
                {logOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />} Tool-call log <span className="num font-normal text-muted">({m.log.length})</span>
              </button>
              {logOpen && <Button size="sm" variant="quiet" onClick={() => refetch()} disabled={isFetching}><RefreshCw size={13} /> Refresh</Button>}
            </div>
            {logOpen && (
              <div className="border-t border-line p-4">
                <DataTable rows={m.log} empty="Every button the assistant presses appears here with time, tool and arguments." columns={[
                  { key: "time", header: "Time", render: (r) => <span className="num whitespace-nowrap">{r.time}</span> },
                  { key: "tool", header: "Tool", render: (r) => <code className="text-[13px]">{r.tool}</code> },
                  { key: "tag", header: "Tag", render: (r) => <Badge tone={r.tag === "PAPER" ? "indigo" : "neutral"}>{r.tag}</Badge> },
                  { key: "args", header: "Arguments", render: (r) => <span className="break-all text-[12px]">{r.args}</span> },
                  { key: "result", header: "Result", render: (r) => <span className="text-[13px]">{typeof r.result === "string" ? r.result : JSON.stringify(r.result)}</span> },
                ]} />
              </div>
            )}
          </section>
        </div>
        <div className="flex flex-col gap-4">
          <FactTile big label="Tools offered" value={`${m.offered} of ${m.tools.length}`} sub={m.paper_order ? "five READ, one PAPER" : "READ only: paper_order is off"} />
          <div className="grid grid-cols-2 gap-2.5">
            <FactTile label="Real-order tools" value="0" sub="there is no order code" />
            <FactTile label="Calls logged" value={m.log.length} />
          </div>
        </div>
      </div>
    </FactsProvider>
  );
}
