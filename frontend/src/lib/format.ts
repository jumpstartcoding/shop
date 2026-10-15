const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export function money(cents: number | null | undefined): string {
  return usd.format((cents ?? 0) / 100);
}

/** "12.5" or "$1,234.50" -> cents. Returns null for blank or invalid input. */
export function toCents(input: string): number | null {
  const cleaned = input.replace(/[$,\s]/g, "");
  if (cleaned === "") return null;
  if (!/^\d+(\.\d{0,2})?$/.test(cleaned)) return null;
  const [whole, frac = ""] = cleaned.split(".");
  return Number(whole) * 100 + Number((frac + "00").slice(0, 2));
}

export function centsToInput(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  return (cents / 100).toFixed(2);
}

const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
const shortDate = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });
const timeFmt = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });

/** Date-only strings ("2026-10-14") are calendar dates; don't shift them through UTC. */
function parse(value: string): Date {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value);
}

export function date(value: string | null | undefined): string {
  return value ? dateFmt.format(parse(value)) : "";
}
export function dayLabel(value: string | Date): string {
  return shortDate.format(typeof value === "string" ? parse(value) : value);
}
export function time(value: string | null | undefined): string {
  return value ? timeFmt.format(new Date(value)) : "";
}
export function dateTime(value: string | null | undefined): string {
  return value ? `${date(value)}, ${time(value)}` : "";
}

export function phoneHref(phone: string | null | undefined): string | undefined {
  const digits = phone?.replace(/\D/g, "");
  return digits ? `tel:${digits}` : undefined;
}

export function sentence(s: string): string {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** Local date + time inputs -> ISO string with the browser's offset. */
export function toIsoWithOffset(localDate: string, localTime: string): string {
  const d = new Date(`${localDate}T${localTime}`);
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return `${localDate}T${localTime}:00${sign}${pad(off / 60)}:${pad(off % 60)}`;
}

export function localDateInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
export function localTimeInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
