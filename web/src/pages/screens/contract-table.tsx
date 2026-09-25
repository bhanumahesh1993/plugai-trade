import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";
import { Field, Panel, MarketChip } from "@/components/ui";
import { Badge, Callout, DataTable, Select, type Column } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { DatedNote } from "@/components/derivatives/common";

interface Row extends Record<string, unknown> {
  Symbol: string; Market: "IN" | "US"; Exchange: string; Asset: string; Currency: string; "Lot / multiplier": string | number | null;
  Expiry: string; Settlement: string; "Exposure required": boolean; "Effective from": string; Source: string; "As of": string; Pending: boolean;
}
interface Table { as_of: string; rows: Row[]; sessions: Record<string, string>[]; fees: Record<string, string>[] }

const ASSETS = ["All", "Index / ETF", "Commodity", "Currency"];

export default function ContractTable() {
  const [market] = useMarket();
  const { data, error } = useQuery({ queryKey: ["contract-table"], queryFn: () => get<Table>("/api/derivatives/contract-table") });
  const [mkt, setMkt] = useState<string | null>(null);
  const [cur, setCur] = useState("All");
  const [asset, setAsset] = useState("All");
  const m = mkt ?? market;
  const rows = (data?.rows ?? []).filter((r) => (m === "All" || r.Market === m) && (cur === "All" || r.Currency === cur) && (asset === "All" || r.Asset === asset));
  const lot = (r: Row) => (r["Lot / multiplier"] == null ? "—" : typeof r["Lot / multiplier"] === "number" ? r["Lot / multiplier"].toLocaleString() : String(r["Lot / multiplier"]));
  const cols: Column<Row>[] = [
    { key: "Symbol", header: "Symbol", render: (r) => <span className="font-medium">{r.Symbol}</span> },
    { key: "Market", header: "Market", render: (r) => <MarketChip m={r.Market} /> },
    { key: "Exchange", header: "Exchange" },
    { key: "Asset", header: "Asset" },
    { key: "Currency", header: "Currency" },
    { key: "Lot / multiplier", header: "Lot / multiplier", align: "right", render: lot },
    { key: "Expiry", header: "Expiry", render: (r) => <span className="text-[13px]">{r.Expiry || "—"}</span> },
    { key: "Settlement", header: "Settlement", render: (r) => <span className="capitalize">{r.Settlement || "—"}</span> },
    { key: "Exposure required", header: "Exposure", render: (r) => (r["Exposure required"] ? <Badge tone="warn" className="whitespace-nowrap">Exposure required</Badge> : null) },
    { key: "Effective from", header: "Effective from", render: (r) => <span className="num whitespace-nowrap">{r["Effective from"] || "—"}</span> },
    { key: "Source", header: "Source", render: (r) => <span className={r.Pending ? "text-[13px] text-saffron" : "text-[13px] text-muted"}>{r.Source || "—"}</span> },
    { key: "As of", header: "As of", render: (r) => <span className="num whitespace-nowrap">{r["As of"]}</span> },
  ];
  const plain = (keys: string[]): Column<Record<string, string>>[] => keys.map((k) => ({ key: k, header: k, render: k === "Market" ? (r) => <MarketChip m={r.Market as "IN" | "US"} /> : undefined }));
  const exposure = rows.some((r) => r["Exposure required"]);
  const pending = rows.some((r) => r.Pending);
  const nifty = data?.rows.find((r) => r.Symbol === "NIFTY");
  const mes = data?.rows.find((r) => r.Symbol === "MES");

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          <FactTile big label="As of" value={data?.as_of ?? "…"} sub="dated rows from the reference tables" />
          <FactTile label="Rows shown" value={data ? `${rows.length} of ${data.rows.length}` : "…"} />
          <FactTile label="NIFTY lot" value={nifty ? lot(nifty) : "…"} sub={nifty ? `effective ${nifty["Effective from"]}` : undefined} />
          <FactTile label="MES multiplier" value={mes ? `$${lot(mes)}` : "…"} sub="per index point" />
        </div>
        <Panel title="Contracts" action={<span className="text-[13px] text-muted">Run <code className="text-ink">plugai-trade update</code> to fetch the latest published table</span>}>
          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3 lg:max-w-[720px]">
            <Field label="Market">
              <Select value={m} onChange={(e) => setMkt(e.target.value)}>
                <option value="All">All</option><option value="IN">IN</option><option value="US">US</option>
              </Select>
            </Field>
            <Field label="Currency">
              <Select value={cur} onChange={(e) => setCur(e.target.value)}>
                {["All", "INR", "USD"].map((c) => <option key={c}>{c}</option>)}
              </Select>
            </Field>
            <Field label="Asset">
              <Select value={asset} onChange={(e) => setAsset(e.target.value)}>
                {ASSETS.map((a) => <option key={a}>{a}</option>)}
              </Select>
            </Field>
          </div>
          {error && <Callout tone="danger" title="Could not read the reference tables">{(error as Error).message}. Run plugai-trade update, then reload.</Callout>}
          <DataTable rows={rows} columns={cols} rowKey={(r) => `${r.Market}-${r.Symbol}`}
            empty="No contracts match these filters. Set Market, Currency or Asset back to All." />
          <div className="mt-4 flex flex-col gap-2">
            {exposure && <Callout tone="warn" title="Exposure required">USDINR positions beyond small limits need genuine underlying currency exposure (Chapter 26).</Callout>}
            {pending && <p className="text-[13px] text-muted">† pending reference row: the book's printed value, not yet in the dated reference tables. Confirm with the exchange before relying on it.</p>}
          </div>
        </Panel>
        <div className="grid gap-5 xl:grid-cols-2">
          <Panel title="Sessions">
            <DataTable rows={data?.sessions ?? []} columns={plain(["Market", "Session", "Hours", "Time zone", "Settlement"])} rowKey={(r) => `${r.Market}-${r.Session}`} />
          </Panel>
          <Panel title="Fees and taxes on the trade">
            <DataTable rows={data?.fees ?? []} columns={plain(["Market", "Fee", "Value"])} rowKey={(r) => r.Fee} />
          </Panel>
        </div>
        <DatedNote asOf={data?.as_of}>Lot sizes, multipliers, sessions and fees change; this table is dated.</DatedNote>
      </div>
    </FactsProvider>
  );
}
