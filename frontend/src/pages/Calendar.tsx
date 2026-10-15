import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useCallback, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CustomerVehiclePicker } from "../components/Picker";
import { Button, Dl, ErrorNote, Field, InternalNote, LinkButton, Loading, Modal, PageHeader, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { date, dayLabel, localDateInput, localTimeInput, phoneHref, sentence, time, toIsoWithOffset } from "../lib/format";
import type { Appointment } from "../lib/types";

type View = "day" | "week" | "month";

function startOfDay(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function addDays(d: Date, n: number) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
function startOfWeek(d: Date) {
  const x = startOfDay(d);
  return addDays(x, -((x.getDay() + 6) % 7)); // Monday
}

function range(view: View, anchor: Date): [Date, Date] {
  if (view === "day") return [startOfDay(anchor), addDays(startOfDay(anchor), 1)];
  if (view === "week") return [startOfWeek(anchor), addDays(startOfWeek(anchor), 7)];
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const gridStart = startOfWeek(first);
  return [gridStart, addDays(gridStart, 42)];
}

export function Calendar() {
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<View>(() => (window.innerWidth < 768 ? "day" : "week"));
  const [anchor, setAnchor] = useState(() => startOfDay(new Date()));
  const [from, to] = range(view, anchor);
  const openId = Number(params.get("appointment")) || null;
  const creating = params.get("new") === "1";

  const { data, error, isLoading } = useQuery({
    queryKey: ["appointments", from.toISOString(), to.toISOString()],
    queryFn: () => api.get<Appointment[]>("/appointments", { from: from.toISOString(), to: to.toISOString() }),
  });

  const move = useMutation({
    mutationFn: ({ a, day }: { a: Appointment; day: Date }) => {
      const start = new Date(a.starts_at!);
      const length = a.ends_at ? new Date(a.ends_at).getTime() - start.getTime() : 0;
      const next = new Date(day);
      next.setHours(start.getHours(), start.getMinutes(), 0, 0);
      return api.patch(`/appointments/${a.id}`, {
        starts_at: next.toISOString(),
        ends_at: length ? new Date(next.getTime() + length).toISOString() : null,
      });
    },
  });

  const unscheduled = (data ?? []).filter((a) => !a.starts_at && !["cancelled", "no_show", "completed"].includes(a.status));
  const scheduled = (data ?? []).filter((a) => a.starts_at);
  const byDay = useMemo(() => {
    const m = new Map<string, Appointment[]>();
    for (const a of scheduled) {
      const k = localDateInput(new Date(a.starts_at!));
      m.set(k, [...(m.get(k) ?? []), a]);
    }
    return m;
  }, [scheduled]);

  const step = (dir: number) =>
    setAnchor((d) =>
      view === "day" ? addDays(d, dir) : view === "week" ? addDays(d, 7 * dir) : new Date(d.getFullYear(), d.getMonth() + dir, 1),
    );
  const open = (id: number) => setParams({ appointment: String(id) });
  const close = () => setParams({});

  const title =
    view === "month"
      ? anchor.toLocaleDateString("en-US", { month: "long", year: "numeric" })
      : view === "week"
        ? `Week of ${dayLabel(from)}`
        : dayLabel(anchor);

  return (
    <>
      <PageHeader title="Calendar" actions={<Button variant="primary" onClick={() => setParams({ new: "1" })}>New appointment</Button>} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-line bg-sheet" role="group" aria-label="View">
          {(["day", "week", "month"] as View[]).map((v) => (
            <button key={v} aria-pressed={view === v} onClick={() => setView(v)}
              className={`min-h-12 px-4 font-medium first:rounded-l-md last:rounded-r-md ${view === v ? "bg-steel text-white" : ""}`}>
              {sentence(v)}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <Button aria-label="Previous" onClick={() => step(-1)}>‹</Button>
          <Button onClick={() => setAnchor(startOfDay(new Date()))}>Today</Button>
          <Button aria-label="Next" onClick={() => step(1)}>›</Button>
        </div>
        <h2 className="font-display text-2xl font-semibold">{title}</h2>
      </div>
      <ErrorNote error={error ?? move.error} />

      {unscheduled.length > 0 && (
        <section className="mb-4 rounded-lg border-l-[6px] border-safety bg-sheet">
          <h3 className="px-4 pt-3 font-display text-xl font-semibold">Requests without a time</h3>
          <ul>
            {unscheduled.map((a) => (
              <li key={a.id}>
                <button onClick={() => open(a.id)} className="flex min-h-14 w-full items-center gap-3 border-b border-line px-4 py-2 text-left last:border-0">
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold">{a.customer_name ?? "New customer"}</span>
                    <span className="block truncate text-[15px] text-steel-2">
                      {[a.requested_service, a.preferred_date && `prefers ${date(a.preferred_date)}`, a.preferred_time].filter(Boolean).join(", ")}
                    </span>
                  </span>
                  <StatusBadge status={a.status} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {isLoading ? (
        <Loading />
      ) : view === "month" ? (
        <MonthGrid from={from} anchor={anchor} byDay={byDay} onPickDay={(d) => { setAnchor(d); setView("day"); }} />
      ) : (
        <div className={view === "week" ? "grid gap-3 lg:grid-cols-7" : ""}>
          {Array.from({ length: view === "week" ? 7 : 1 }, (_, i) => addDays(from, i)).map((d) => (
            <DayColumn key={d.toISOString()} day={d} items={byDay.get(localDateInput(d)) ?? []} onOpen={open}
              onDrop={(a) => move.mutate({ a, day: d })} compact={view === "week"} />
          ))}
        </div>
      )}
      <p className="mt-3 hidden text-[15px] text-steel-2 lg:block">Drag an appointment to another day to move it. Open it to change the time.</p>

      {openId && <AppointmentModal id={openId} onClose={close} />}
      {creating && <NewAppointmentModal onClose={close} defaultDay={anchor} />}
    </>
  );
}

let dragging: Appointment | null = null;

function DayColumn({ day, items, onOpen, onDrop, compact }: {
  day: Date;
  items: Appointment[];
  onOpen: (id: number) => void;
  onDrop: (a: Appointment) => void;
  compact: boolean;
}) {
  const [over, setOver] = useState(false);
  const isToday = localDateInput(day) === localDateInput(new Date());
  return (
    <section
      aria-label={dayLabel(day)}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (dragging && localDateInput(new Date(dragging.starts_at!)) !== localDateInput(day)) onDrop(dragging);
        dragging = null;
      }}
      className={`rounded-lg border bg-sheet ${over ? "border-steel ring-2 ring-safety" : "border-line"} ${compact ? "lg:min-h-64" : ""}`}
    >
      <h3 className={`flex min-h-11 items-center justify-between border-b px-3 font-display text-lg font-semibold ${isToday ? "border-safety-deep bg-safety" : "border-line"}`}>
        {dayLabel(day)}
        {items.length > 0 && <span className="num text-steel-2">{items.length}</span>}
      </h3>
      {items.length === 0 ? (
        <p className="px-3 py-3 text-[15px] text-steel-3">{compact ? "Open" : "Nothing booked."}</p>
      ) : (
        <ul>
          {items.map((a) => (
            <li key={a.id}>
              <button
                draggable
                onDragStart={() => { dragging = a; }}
                onClick={() => onOpen(a.id)}
                className={`block min-h-14 w-full border-b border-line px-3 py-2 text-left last:border-0 ${["cancelled", "no_show"].includes(a.status) ? "opacity-55" : ""}`}
              >
                <span className="num block text-lg">{time(a.starts_at)}{a.ends_at && !compact && `–${time(a.ends_at)}`}</span>
                <span className="block font-semibold">{a.customer_name ?? "New customer"}</span>
                <span className="block truncate text-[15px] text-steel-2">{[a.vehicle_name, a.requested_service].filter(Boolean).join(", ")}</span>
                {a.status !== "confirmed" && <span className="mt-1 block"><StatusBadge status={a.status} /></span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function MonthGrid({ from, anchor, byDay, onPickDay }: { from: Date; anchor: Date; byDay: Map<string, Appointment[]>; onPickDay: (d: Date) => void }) {
  const days = Array.from({ length: 42 }, (_, i) => addDays(from, i));
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-sheet">
      <div className="grid grid-cols-7 border-b border-line text-center text-[15px] text-steel-2">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="py-2">{d}</div>)}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const items = byDay.get(localDateInput(d)) ?? [];
          const inMonth = d.getMonth() === anchor.getMonth();
          const isToday = localDateInput(d) === localDateInput(new Date());
          return (
            <button key={d.toISOString()} onClick={() => onPickDay(d)}
              aria-label={`${dayLabel(d)}, ${items.length} appointment${items.length === 1 ? "" : "s"}`}
              className={`min-h-16 border-r border-b border-line p-1 text-left align-top sm:min-h-24 ${inMonth ? "" : "bg-concrete/60 text-steel-3"}`}>
              <span className={`num inline-block min-w-7 rounded px-1 text-center text-lg ${isToday ? "bg-safety" : ""}`}>{d.getDate()}</span>
              {items.length > 0 && (
                <span className="mt-1 block">
                  <span className="sm:hidden inline-block rounded bg-steel px-1.5 text-[14px] font-semibold text-white">{items.length}</span>
                  <span className="hidden space-y-0.5 sm:block">
                    {items.slice(0, 3).map((a) => (
                      <span key={a.id} className="block truncate text-[14px]">{time(a.starts_at)} {a.customer_name}</span>
                    ))}
                    {items.length > 3 && <span className="block text-[14px] text-steel-2">+{items.length - 3} more</span>}
                  </span>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function AppointmentModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: a, error, isLoading } = useQuery({
    queryKey: ["appointment", id],
    queryFn: () => api.get<Appointment>(`/appointments/${id}`),
  });
  const [day, setDay] = useState<string | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const [hours, setHours] = useState("1");
  const update = useMutation({ mutationFn: (body: Record<string, unknown>) => api.patch(`/appointments/${id}`, body) });

  if (isLoading) return <Modal title="Appointment" onClose={onClose}><Loading /></Modal>;
  if (error || !a) return <Modal title="Appointment" onClose={onClose}><ErrorNote error={error} /></Modal>;

  const startDate = a.starts_at ? new Date(a.starts_at) : null;
  const dayVal = day ?? (startDate ? localDateInput(startDate) : a.preferred_date ?? localDateInput(new Date()));
  const startVal = start ?? (startDate ? localTimeInput(startDate) : "09:00");

  const schedule = (e: FormEvent) => {
    e.preventDefault();
    const s = toIsoWithOffset(dayVal, startVal);
    const end = new Date(new Date(s).getTime() + Number(hours || 1) * 3600_000).toISOString();
    update.mutate({ starts_at: s, ends_at: end, ...(a.status === "requested" ? { status: "confirmed" } : {}) });
  };

  const done = ["completed", "cancelled", "no_show"].includes(a.status);

  return (
    <Modal title={a.customer_name ?? a.contact_name ?? "Appointment"} onClose={onClose}>
      <div className="space-y-4">
        <div className="flex items-center gap-2"><StatusBadge status={a.status} /><span className="text-steel-2">{a.source === "online" ? "Requested online" : "Booked by you"}</span></div>
        <ErrorNote error={update.error} />
        <Dl
          rows={[
            ["When", a.starts_at ? `${dayLabel(a.starts_at)}, ${time(a.starts_at)}${a.ends_at ? `–${time(a.ends_at)}` : ""}` : "Not scheduled"],
            ["Prefers", [a.preferred_date && date(a.preferred_date), a.preferred_time].filter(Boolean).join(", ")],
            ["Vehicle", a.vehicle_name],
            ["Mileage", a.reported_mileage?.toLocaleString()],
            ["Service", a.requested_service],
            ["Concern", a.concern],
            ["Phone", (a.contact_phone) && <a className="underline" href={phoneHref(a.contact_phone)}>{a.contact_phone}</a>],
            ["Email", a.contact_email],
            ["Customer note", a.customer_notes],
          ]}
        />
        <InternalNote>{a.internal_notes}</InternalNote>

        {a.customer_id === null && (
          <p className="rounded-md bg-hold-wash px-3 py-2 text-hold">
            This request isn't linked to a customer yet.{" "}
            <Link className="font-semibold underline" to={`/admin/customers/new?appointment=${a.id}`}>Create customer from request</Link>
          </p>
        )}

        {!done && (
          <form onSubmit={schedule} className="space-y-3 rounded-md border border-line p-3">
            <p className="font-display text-lg font-semibold">{a.starts_at ? "Reschedule" : "Schedule"}</p>
            <div className="grid grid-cols-[1fr_1fr_5rem] gap-2">
              <Field label="Day">{(p) => <input {...p} type="date" className="field" value={dayVal} onChange={(e) => setDay(e.target.value)} />}</Field>
              <Field label="Start">{(p) => <input {...p} type="time" step={900} className="field" value={startVal} onChange={(e) => setStart(e.target.value)} />}</Field>
              <Field label="Hours">{(p) => <input {...p} className="field" inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)} />}</Field>
            </div>
            <Button type="submit" variant="primary" className="w-full" busy={update.isPending}>
              {a.status === "requested" ? "Confirm this time" : "Save new time"}
            </Button>
          </form>
        )}

        <div className="flex flex-wrap gap-2">
          {a.customer_id && a.vehicle_id && !a.work_order_id && !done && (
            <LinkButton variant="primary" to={`/admin/work-orders/new?customer=${a.customer_id}&vehicle=${a.vehicle_id}&appointment=${a.id}`}>
              Check in and open work order
            </LinkButton>
          )}
          {a.work_order_id && <LinkButton to={`/admin/work-orders/${a.work_order_id}`}>Open work order</LinkButton>}
          {a.customer_id && <LinkButton to={`/admin/customers/${a.customer_id}`}>Customer</LinkButton>}
          {!done && (
            <>
              <Button onClick={() => update.mutate({ status: "no_show" })}>No-show</Button>
              <Button variant="danger" onClick={() => confirm("Cancel this appointment?") && update.mutate({ status: "cancelled" })}>Cancel appointment</Button>
            </>
          )}
          {done && <Button onClick={() => update.mutate({ status: a.starts_at ? "confirmed" : "requested" })}>Reopen</Button>}
        </div>
      </div>
    </Modal>
  );
}

function NewAppointmentModal({ onClose, defaultDay }: { onClose: () => void; defaultDay: Date }) {
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [vehicleId, setVehicleId] = useState<number | null>(null);
  const [day, setDay] = useState(localDateInput(defaultDay));
  const [start, setStart] = useState("09:00");
  const [hours, setHours] = useState("1");
  const [service, setService] = useState("");
  const [concern, setConcern] = useState("");
  const onPick = useCallback((c: number | null, v: number | null) => { setCustomerId(c); setVehicleId(v); }, []);
  const create = useMutation({
    mutationFn: () => {
      const s = toIsoWithOffset(day, start);
      return api.post("/appointments", {
        customer_id: customerId,
        vehicle_id: vehicleId,
        starts_at: s,
        ends_at: new Date(new Date(s).getTime() + Number(hours || 1) * 3600_000).toISOString(),
        requested_service: service,
        concern,
      });
    },
    onSuccess: onClose,
  });
  return (
    <Modal title="New appointment" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="space-y-4">
        <ErrorNote error={create.error} />
        <CustomerVehiclePicker customerId={customerId} vehicleId={vehicleId} onChange={onPick} />
        <div className="grid grid-cols-[1fr_1fr_5rem] gap-2">
          <Field label="Day">{(p) => <input {...p} type="date" className="field" required value={day} onChange={(e) => setDay(e.target.value)} />}</Field>
          <Field label="Start">{(p) => <input {...p} type="time" step={900} className="field" required value={start} onChange={(e) => setStart(e.target.value)} />}</Field>
          <Field label="Hours">{(p) => <input {...p} className="field" inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)} />}</Field>
        </div>
        <Field label="Service">{(p) => <input {...p} className="field" value={service} onChange={(e) => setService(e.target.value)} placeholder="Oil change, brakes, diagnosis…" />}</Field>
        <Field label="Concern">{(p) => <textarea {...p} className="field min-h-20" value={concern} onChange={(e) => setConcern(e.target.value)} />}</Field>
        <Button type="submit" variant="primary" className="w-full" disabled={!customerId} busy={create.isPending}>Book appointment</Button>
      </form>
    </Modal>
  );
}
