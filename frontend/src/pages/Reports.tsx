import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Dl, ErrorNote, Field, Loading, PageHeader, Sheet } from "../components/ui";
import { api } from "../lib/api";
import { date, localDateInput, money, sentence } from "../lib/format";
import type { ReportSummary } from "../lib/types";

type Preset = "today" | "this_week" | "this_month" | "last_month" | "this_year" | "last_year" | "custom";
const PRESETS: [Preset, string][] = [
  ["today", "Today"],
  ["this_week", "This week"],
  ["this_month", "This month"],
  ["last_month", "Last month"],
  ["this_year", "This year"],
  ["last_year", "Last year"],
  ["custom", "Custom"],
];

function presetRange(p: Preset): [string, string] {
  const now = new Date();
  const d = (y: number, m: number, day: number) => localDateInput(new Date(y, m, day));
  const y = now.getFullYear();
  const m = now.getMonth();
  switch (p) {
    case "today":
      return [localDateInput(now), localDateInput(now)];
    case "this_week": {
      const monday = new Date(now);
      monday.setDate(now.getDate() - ((now.getDay() + 6) % 7));
      return [localDateInput(monday), localDateInput(now)];
    }
    case "last_month":
      return [d(y, m - 1, 1), d(y, m, 0)];
    case "this_year":
      return [d(y, 0, 1), localDateInput(now)];
    case "last_year":
      return [d(y - 1, 0, 1), d(y - 1, 11, 31)];
    default:
      return [d(y, m, 1), localDateInput(now)];
  }
}

export function useRange(initial: Preset) {
  const [preset, setPreset] = useState<Preset>(initial);
  const [custom, setCustom] = useState(() => presetRange(initial));
  const [start, end] = preset === "custom" ? custom : presetRange(preset);
  return { preset, setPreset, start, end, custom, setCustom };
}

export function DateRange({ range }: { range: ReturnType<typeof useRange> }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Date range">
        {PRESETS.map(([p, label]) => (
          <button key={p} type="button" aria-pressed={range.preset === p}
            onClick={() => { if (p === "custom") range.setCustom([range.start, range.end]); range.setPreset(p); }}
            className={`min-h-12 rounded-md border px-3 font-medium ${range.preset === p ? "border-steel bg-steel text-white" : "border-line bg-sheet"}`}>
            {label}
          </button>
        ))}
      </div>
      {range.preset === "custom" && (
        <div className="grid max-w-md grid-cols-2 gap-3">
          <Field label="From">{(p) => <input {...p} type="date" className="field" value={range.custom[0]} onChange={(e) => range.setCustom([e.target.value, range.custom[1]])} />}</Field>
          <Field label="To">{(p) => <input {...p} type="date" className="field" value={range.custom[1]} onChange={(e) => range.setCustom([range.custom[0], e.target.value])} />}</Field>
        </div>
      )}
    </div>
  );
}

const EXPORTS: [string, string][] = [
  ["customers", "Customers"],
  ["vehicles", "Vehicles"],
  ["work_orders", "Work orders"],
  ["invoices", "Invoices"],
  ["payments", "Payments"],
  ["expenses", "Expenses"],
  ["parts", "Parts"],
  ["service_history", "Service history"],
];

export function ReportsPage() {
  const range = useRange("this_month");
  const { data, error, isLoading } = useQuery({
    queryKey: ["report", range.start, range.end],
    queryFn: () => api.get<ReportSummary>("/reports/summary", { start: range.start, end: range.end }),
    enabled: !!range.start && !!range.end,
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Reports" />
      <DateRange range={range} />
      {isLoading ? <Loading /> : error || !data ? <ErrorNote error={error} /> : (
        <>
          <p className="text-steel-2">{date(data.start)} to {date(data.end)}</p>
          <section aria-label="Money" className="grid grid-cols-2 overflow-hidden rounded-lg bg-steel text-white sm:grid-cols-4">
            <Stat label="Collected" value={money(data.collected.total_cents)} sub={`${data.collected.payments} payment${data.collected.payments === 1 ? "" : "s"}`} accent />
            <Stat label="Invoiced" value={money(data.invoiced.total_cents)} sub={`${data.invoiced.count} invoice${data.invoiced.count === 1 ? "" : "s"}`} />
            <Stat label="Average repair order" value={money(data.invoiced.average_cents)} />
            <Stat label="Owed to you now" value={money(data.outstanding_cents)} sub="all unpaid invoices" />
          </section>

          <div className="grid gap-5 lg:grid-cols-2">
            <Sheet title="Invoiced in this range">
              <Dl rows={[
                ["Labor", <span className="num">{money(data.invoiced.labor_cents)}</span>],
                ["Parts", <span className="num">{money(data.invoiced.parts_cents)}</span>],
                ["Fees", <span className="num">{money(data.invoiced.fees_cents)}</span>],
                ["Discounts", <span className="num">−{money(data.invoiced.discount_cents)}</span>],
                ["Tax charged", <span className="num">{money(data.invoiced.tax_cents)}</span>],
                ["Paid in full", `${data.invoiced.paid_count}`],
                ["Not yet paid", `${data.invoiced.unpaid_count}`],
              ]} />
            </Sheet>
            <Sheet title="Money in and out">
              <Dl rows={[
                ...Object.entries(data.collected.by_method).map(([m, c]): [string, React.ReactNode] => [`Collected: ${sentence(m)}`, <span className="num">{money(c)}</span>]),
                ["Expenses", <span className="num">−{money(data.expenses.total_cents)}</span>],
                ["Collected minus expenses", <span className="num font-semibold">{money(data.collected_less_expenses_cents)}</span>],
              ]} />
              {Object.keys(data.expenses.by_category).length > 0 && (
                <p className="border-t border-line px-4 py-3 text-[15px] text-steel-2">
                  Expenses: {Object.entries(data.expenses.by_category).map(([c, v]) => `${sentence(c)} ${money(v)}`).join(", ")}
                </p>
              )}
            </Sheet>
          </div>

          {data.collected.by_period.length > 0 && (
            <Sheet title={data.collected.period === "month" ? "Collected by month" : "Collected by day"}>
              <table className="w-full">
                <thead className="sr-only"><tr><th>Period</th><th>Collected</th></tr></thead>
                <tbody>
                  {data.collected.by_period.map((p) => (
                    <tr key={p.period} className="border-b border-line last:border-0">
                      <td className="px-4 py-2">{data.collected.period === "month" ? new Date(`${p.period}-01T12:00:00`).toLocaleDateString(undefined, { month: "long", year: "numeric" }) : date(p.period)}</td>
                      <td className="num px-4 py-2 text-right">{money(p.cents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Sheet>
          )}
          <p className="text-[15px] text-steel-2">{data.notice} “Collected” counts payments by the day they came in, after refunds. “Invoiced” counts invoices by their date, except voided ones.</p>
        </>
      )}

      <Sheet title="Export your data">
        <div className="space-y-3 p-4">
          <p className="text-steel-2">Spreadsheet files (CSV) of everything in the app, for your accountant or your own records. They open in Excel, Numbers, or Google Sheets.</p>
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {EXPORTS.map(([ds, label]) => (
              <li key={ds}>
                <a href={`/api/export/${ds}.csv`} download className="flex min-h-12 items-center justify-center rounded-md border border-line bg-sheet px-3 text-center font-medium hover:border-steel">
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </Sheet>
    </div>
  );
}

function Stat({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="border-b border-r border-white/10 px-4 py-3">
      <p className="text-[15px] text-white/75">{label}</p>
      <p className={`num text-2xl font-semibold ${accent ? "text-safety" : ""}`}>{value}</p>
      {sub && <p className="text-[14px] text-white/65">{sub}</p>}
    </div>
  );
}
