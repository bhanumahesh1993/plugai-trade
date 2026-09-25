import type { Market } from "./api";

export const currency = (m: Market) => (m === "IN" ? "₹" : "$");

/** Indian grouping for ₹ (1,21,726), Western for $ (121,726). */
export function money(x: number | null | undefined, m: Market, digits = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const locale = m === "IN" ? "en-IN" : "en-US";
  const s = Math.abs(x).toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${x < 0 ? "−" : ""}${currency(m)}${s}`;
}

export function num(x: number | null | undefined, m: Market = "US", digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toLocaleString(m === "IN" ? "en-IN" : "en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(x: number | null | undefined, digits = 2, signed = true): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  const v = (x * 100).toFixed(digits);
  return `${signed && x > 0 ? "+" : ""}${x < 0 ? "−" + v.slice(1) : v}%`;
}
