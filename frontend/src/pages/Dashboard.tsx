import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, Empty, ErrorNote, Loading, Modal, RowLink, Sheet, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { dateTime, dayLabel, money, time } from "../lib/format";
import type { WorkOrderCard } from "../lib/types";

type ApptRow = {
  id: number;
  status: string;
  starts_at: string | null;
  customer_name: string | null;
  vehicle_name: string | null;
  requested_service: string | null;
};
type InvRow = {
  id: number;
  number: string;
  status: string;
  customer_name: string;
  total_cents: number;
  balance_cents: number;
  due_date: string | null;
  paid_at: string | null;
};
type DashboardData = {
  as_of: string;
  notifications: { kind: string; count: number; message: string; entity_id?: number }[];
  appointments_today: ApptRow[];
  appointments_upcoming: ApptRow[];
  appointment_requests: ApptRow[];
  open_work_orders: WorkOrderCard[];
  vehicles_in_shop: WorkOrderCard[];
  pending_estimates: { id: number; number: string; status: string; customer_name: string; total_cents: number; sent_at: string | null }[];
  unpaid_invoices: InvRow[];
  recently_paid_invoices: InvRow[];
  revenue: { today_cents: number; week_cents: number; month_cents: number; year_cents: number };
  outstanding_cents: number;
  messages: { id: number; kind: string; name: string | null; message: string; entity_type: string | null; entity_id: number | null; created_at: string }[];
};

const NOTE_LINK: Record<string, string> = {
  appointment_requests: "/admin/calendar",
  ready_for_pickup: "/admin/board",
  estimates_awaiting: "/admin/estimates?status=sent",
  invoices_overdue: "/admin/invoices?unpaid=1",
  messages: "/admin#messages",
  online_payments: "/admin/invoices",
  reminders_due: "/admin/reminders",
  low_stock: "/admin/parts?low=1",
};

const ENTITY_PATH: Record<string, string> = { estimate: "estimates", invoice: "invoices", work_order: "work-orders", inspection: "inspections", history: "vehicles" };
const ENTITY_LABEL: Record<string, string> = { estimate: "estimate", invoice: "invoice", work_order: "work order", inspection: "inspection report", history: "vehicle's history" };

export function Dashboard() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardData>("/dashboard"),
    refetchInterval: 60_000,
  });
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorNote error={error} />;

  const greeting = dayLabel(data.as_of.slice(0, 10));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h1 className="font-display text-[34px] font-bold leading-tight">{greeting}</h1>
        <p className="text-steel-2">
          {data.vehicles_in_shop.length} in the shop, {data.appointments_today.length} booked today
        </p>
      </div>

      {data.notifications.length > 0 && (
        <ul className="space-y-2" aria-label="Needs attention">
          {data.notifications.map((n) => (
            <li key={n.kind}>
              <Link
                to={n.kind === "needs_refund" ? `/admin/invoices/${n.entity_id}` : NOTE_LINK[n.kind] ?? "/admin"}
                className={`flex min-h-12 items-center border-l-[6px] bg-sheet px-4 py-2 font-medium ${n.kind === "needs_refund" ? "border-signal text-signal" : "border-safety"}`}
              >
                {n.message}
              </Link>
            </li>
          ))}
        </ul>
      )}

      <QuickActions unpaid={data.unpaid_invoices} />

      <Money data={data} />

      {data.messages.length > 0 && <Messages messages={data.messages} />}

      <div className="grid gap-5 lg:grid-cols-2">
        <Sheet title="In the shop" action={<Link className="min-h-12 content-center underline underline-offset-4" to="/admin/board">Board</Link>}>
          {data.vehicles_in_shop.length === 0 ? (
            <Empty>
              No vehicles checked in. <Link className="underline" to="/admin/work-orders/new">Start a work order</Link>
            </Empty>
          ) : (
            <ul>
              {data.vehicles_in_shop.map((w) => (
                <RowLink key={w.id} to={`/admin/work-orders/${w.id}`}>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{w.vehicle_name}</p>
                    <p className="truncate text-[15px] text-steel-2">{w.customer_name}, {w.number}</p>
                  </div>
                  <StatusBadge status={w.status} />
                </RowLink>
              ))}
            </ul>
          )}
        </Sheet>

        <Sheet title="Today" action={<Link className="min-h-12 content-center underline underline-offset-4" to="/admin/calendar">Calendar</Link>}>
          {data.appointments_today.length === 0 ? (
            <Empty>Nothing booked today.</Empty>
          ) : (
            <ul>
              {data.appointments_today.map((a) => (
                <ApptLink key={a.id} a={a} showTime />
              ))}
            </ul>
          )}
          {data.appointments_upcoming.length > 0 && (
            <>
              <h3 className="border-t border-line px-4 pt-3 pb-1 font-display text-lg font-semibold">Next 7 days</h3>
              <ul>
                {data.appointments_upcoming.map((a) => (
                  <ApptLink key={a.id} a={a} showDay />
                ))}
              </ul>
            </>
          )}
        </Sheet>

        {data.appointment_requests.length > 0 && (
          <Sheet title="Requests to review">
            <ul>
              {data.appointment_requests.map((a) => (
                <ApptLink key={a.id} a={a} />
              ))}
            </ul>
          </Sheet>
        )}

        <Sheet title="Waiting on the customer">
          {data.pending_estimates.length === 0 ? (
            <Empty>No estimates out for approval.</Empty>
          ) : (
            <ul>
              {data.pending_estimates.map((e) => (
                <RowLink key={e.id} to={`/admin/estimates/${e.id}`}>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{e.customer_name}</p>
                    <p className="text-[15px] text-steel-2">{e.number}</p>
                  </div>
                  <span className="num text-lg">{money(e.total_cents)}</span>
                </RowLink>
              ))}
            </ul>
          )}
        </Sheet>

        <Sheet title="Unpaid invoices">
          {data.unpaid_invoices.length === 0 ? (
            <Empty>Everything is paid up.</Empty>
          ) : (
            <ul>
              {data.unpaid_invoices.map((i) => (
                <RowLink key={i.id} to={`/admin/invoices/${i.id}`}>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{i.customer_name}</p>
                    <p className="text-[15px] text-steel-2">{i.number}</p>
                  </div>
                  <div className="text-right">
                    <p className="num text-lg">{money(i.balance_cents)}</p>
                    <StatusBadge status={i.status} />
                  </div>
                </RowLink>
              ))}
            </ul>
          )}
        </Sheet>

        {data.recently_paid_invoices.length > 0 && (
          <Sheet title="Recently paid">
            <ul>
              {data.recently_paid_invoices.map((i) => (
                <RowLink key={i.id} to={`/admin/invoices/${i.id}`}>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{i.customer_name}</p>
                    <p className="text-[15px] text-steel-2">{i.number}</p>
                  </div>
                  <span className="num text-lg">{money(i.total_cents)}</span>
                </RowLink>
              ))}
            </ul>
          </Sheet>
        )}
      </div>
    </div>
  );
}

const QUICK: [string, string][] = [
  ["New customer", "/admin/customers/new"],
  ["New vehicle", "/admin/vehicles/new"],
  ["New appointment", "/admin/calendar?new=1"],
  ["New work order", "/admin/work-orders/new"],
  ["New estimate", "/admin/estimates/new"],
  ["New invoice", "/admin/invoices/new"],
];

/** The things a mechanic starts most often, one tap from the home screen (spec §44). */
function QuickActions({ unpaid }: { unpaid: InvRow[] }) {
  const [paying, setPaying] = useState(false);
  const tile = "flex min-h-14 items-center justify-center rounded-md border px-3 text-center font-semibold";
  return (
    <nav aria-label="Quick actions">
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <li>
          <Link to="/admin/customers?find=1" className={`${tile} border-steel bg-steel text-white`}>Find customer</Link>
        </li>
        <li>
          <button type="button" onClick={() => setPaying(true)} className={`${tile} w-full border-safety-deep bg-safety text-steel`}>Record payment</button>
        </li>
        {QUICK.map(([label, to]) => (
          <li key={to}>
            <Link to={to} className={`${tile} whitespace-nowrap border-line bg-sheet hover:border-steel`}>
              <span aria-hidden="true" className="mr-1.5 text-xl leading-none">+</span>
              <span className="sr-only">New </span>
              {label.replace("New ", "").replace(/^./, (c) => c.toUpperCase())}
            </Link>
          </li>
        ))}
      </ul>
      {paying && (
        <Modal title="Record a payment" onClose={() => setPaying(false)}>
          <p className="mb-3 text-steel-2">Which invoice is it for?</p>
          {unpaid.length === 0 ? (
            <Empty>No unpaid invoices that have been sent. Open a draft invoice to take payment on it.</Empty>
          ) : (
            <ul className="divide-y divide-line rounded-md border border-line">
              {unpaid.map((i) => (
                <li key={i.id}>
                  <Link to={`/admin/invoices/${i.id}?pay=1`} className="flex min-h-14 items-center gap-3 px-3 py-2 hover:bg-concrete">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">{i.customer_name}</span>
                      <span className="block text-[15px] text-steel-2">{i.number}</span>
                    </span>
                    <span className="num text-lg">{money(i.balance_cents)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Link to="/admin/invoices" className="mt-3 inline-flex min-h-12 items-center underline underline-offset-4">All invoices</Link>
        </Modal>
      )}
    </nav>
  );
}

function Money({ data }: { data: DashboardData }) {
  const cells: [string, number][] = [
    ["Today", data.revenue.today_cents],
    ["This week", data.revenue.week_cents],
    ["This month", data.revenue.month_cents],
    ["This year", data.revenue.year_cents],
  ];
  return (
    <section aria-label="Money" className="rounded-lg bg-steel text-white">
      <div className="grid grid-cols-2 sm:grid-cols-5">
        {cells.map(([label, cents]) => (
          <div key={label} className="border-b border-white/10 px-4 py-3 sm:border-r sm:border-b-0">
            <p className="text-[15px] text-white/70">{label}</p>
            <p className="num text-2xl font-semibold">{money(cents)}</p>
          </div>
        ))}
        <Link to="/admin/invoices?unpaid=1" className="col-span-2 px-4 py-3 sm:col-span-1">
          <p className="text-[15px] text-white/70">Owed to you</p>
          <p className="num text-2xl font-semibold text-safety">{money(data.outstanding_cents)}</p>
        </Link>
      </div>
    </section>
  );
}

function ApptLink({ a, showTime, showDay }: { a: ApptRow; showTime?: boolean; showDay?: boolean }) {
  return (
    <RowLink to={`/admin/calendar?appointment=${a.id}`}>
      {(showTime || showDay) && (
        <span className="num w-24 shrink-0 text-lg leading-tight">
          {showDay && a.starts_at && <span className="block text-[15px] text-steel-2">{dayLabel(a.starts_at).split(",")[0]}</span>}
          <span className="block whitespace-nowrap">{a.starts_at ? time(a.starts_at) : ""}</span>
        </span>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold">{a.customer_name ?? "New customer"}</p>
        <p className="truncate text-[15px] text-steel-2">
          {[a.vehicle_name, a.requested_service].filter(Boolean).join(", ")}
        </p>
      </div>
      <StatusBadge status={a.status} />
    </RowLink>
  );
}

function Messages({ messages }: { messages: DashboardData["messages"] }) {
  const done = useMutation({ mutationFn: (id: number) => api.post(`/inquiries/${id}/handled`) });
  return (
    <Sheet title={<span id="messages">Messages from customers</span>}>
      <ul>
        {messages.map((m) => (
          <li key={m.id} className="flex flex-wrap items-start gap-3 border-b border-line px-4 py-3 last:border-0">
            <div className="min-w-0 flex-1">
              <p className="font-semibold">
                {m.name ?? "Someone"}{" "}
                <span className="font-normal text-steel-2">
                  {m.kind === "question" ? "asked about " : "wrote through the website"}
                  {m.kind === "question" && m.entity_type && m.entity_id && (
                    <Link className="underline" to={`/admin/${ENTITY_PATH[m.entity_type]}/${m.entity_id}`}>
                      their {ENTITY_LABEL[m.entity_type] ?? m.entity_type.replace("_", " ")}
                    </Link>
                  )}
                  , {dateTime(m.created_at)}
                </span>
              </p>
              <p className="whitespace-pre-wrap">{m.message}</p>
            </div>
            <Button variant="quiet" busy={done.isPending} onClick={() => done.mutate(m.id)}>Mark answered</Button>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
