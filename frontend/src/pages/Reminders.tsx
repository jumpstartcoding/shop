import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Empty, ErrorNote, Field, Loading, Modal, PageHeader, Sheet } from "../components/ui";
import { api } from "../lib/api";
import { date, dateTime, localDateInput, phoneHref } from "../lib/format";
import type { Reminder, ReminderPreset } from "../lib/types";

type Scope = "due" | "open" | "closed";

export function RemindersPage() {
  const [scope, setScope] = useState<Scope>("due");
  const { data, error, isLoading } = useQuery({
    queryKey: ["reminders", scope],
    queryFn: () => api.get<Reminder[]>("/reminders", { scope }),
  });
  return (
    <div className="space-y-4">
      <PageHeader title="Service reminders" sub="Customers due for maintenance. Set reminders from a vehicle or a finished work order." />
      <div role="tablist" className="flex flex-wrap gap-2">
        {([["due", "Due now"], ["open", "All upcoming"], ["closed", "Done"]] as [Scope, string][]).map(([s, label]) => (
          <button key={s} role="tab" aria-selected={scope === s} onClick={() => setScope(s)}
            className={`min-h-12 rounded-md border px-4 font-semibold ${scope === s ? "border-steel bg-steel text-white" : "border-line bg-sheet"}`}>
            {label}
          </button>
        ))}
      </div>
      <Sheet>
        {isLoading ? <Loading /> : error ? <ErrorNote error={error} /> : !data?.length ? (
          <Empty>{scope === "due" ? "Nobody is due right now." : "No reminders here."}</Empty>
        ) : (
          <ul>{data.map((r) => <ReminderRow key={r.id} r={r} showVehicle />)}</ul>
        )}
      </Sheet>
      <p className="text-[15px] text-steel-2">
        Automatic reminder emails can be turned on in <Link className="underline" to="/admin/settings">Settings</Link>. Each reminder is emailed once; you can always send one by hand.
      </p>
    </div>
  );
}

export function ReminderRow({ r, showVehicle }: { r: Reminder; showVehicle?: boolean }) {
  const update = useMutation({ mutationFn: (status: string) => api.patch(`/reminders/${r.id}`, { status }) });
  const send = useMutation({ mutationFn: () => api.post<{ email: { status: string; message: string } }>(`/reminders/${r.id}/send`) });
  const due = [r.due_date && `${r.overdue ? "was due" : "due"} ${date(r.due_date)}`, r.due_mileage && `at ${r.due_mileage.toLocaleString()} mi`].filter(Boolean).join(" or ");
  return (
    <li className={`border-b border-line px-4 py-3 last:border-0 ${r.status !== "open" ? "opacity-70" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold">
            {r.title}
            {r.due && r.status === "open" && <span className={`ml-2 rounded px-1.5 py-0.5 text-[14px] ${r.overdue ? "bg-signal text-white" : "bg-safety text-steel"}`}>{r.overdue ? "Overdue" : "Due"}</span>}
          </p>
          <p className="text-[15px] text-steel-2">{due}{r.vehicle_mileage !== null && r.due_mileage ? ` (now ${r.vehicle_mileage.toLocaleString()} mi)` : ""}</p>
          {showVehicle && (
            <p>
              <Link className="underline underline-offset-4" to={`/admin/customers/${r.customer_id}`}>{r.customer_name}</Link>,{" "}
              <Link className="underline underline-offset-4" to={`/admin/vehicles/${r.vehicle_id}`}>{r.vehicle_name}</Link>
            </p>
          )}
          {r.notes && <p className="text-[15px]">{r.notes}</p>}
          {r.emailed_at && <p className="text-[15px] text-steel-2">Emailed {dateTime(r.emailed_at)}</p>}
          {r.status !== "open" && <p className="text-[15px] text-steel-2">{r.status === "done" ? "Done" : "Dismissed"}</p>}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {r.status === "open" ? (
          <>
            {r.customer_phone && <a href={phoneHref(r.customer_phone)} className="inline-flex min-h-12 items-center rounded-md border border-line px-4 font-medium">Call</a>}
            {r.customer_phone && (
              <a href={`${phoneHref(r.customer_phone)?.replace("tel:", "sms:")}?&body=${encodeURIComponent(`Hi ${r.customer_name.split(" ")[0]}, your ${r.vehicle_name} is due for ${r.title.toLowerCase()}. Want to book a time?`)}`}
                className="inline-flex min-h-12 items-center rounded-md border border-line px-4 font-medium">Text</a>
            )}
            {r.customer_email && <Button busy={send.isPending} onClick={() => send.mutate()}>{r.emailed_at ? "Email again" : "Email reminder"}</Button>}
            <Button variant="quiet" busy={update.isPending} onClick={() => update.mutate("done")}>Mark done</Button>
            <Button variant="quiet" busy={update.isPending} onClick={() => update.mutate("dismissed")}>Dismiss</Button>
          </>
        ) : (
          <Button variant="quiet" busy={update.isPending} onClick={() => update.mutate("open")}>Reopen</Button>
        )}
      </div>
      {send.data && <p role="status" className="mt-1 text-[15px] text-steel-2">{send.data.email.message}</p>}
      <ErrorNote error={update.error ?? send.error} />
    </li>
  );
}

/** Set a reminder for a vehicle. Presets suggest a typical interval from today and from the
 * vehicle's current mileage; every value can be changed. */
export function ReminderModal({
  vehicleId,
  mileage,
  workOrderId,
  onClose,
}: {
  vehicleId: number;
  mileage: number | null;
  workOrderId?: number;
  onClose: () => void;
}) {
  const presets = useQuery({ queryKey: ["reminder-presets"], queryFn: () => api.get<ReminderPreset[]>("/reminders/presets") });
  const [kind, setKind] = useState("oil_change");
  const [title, setTitle] = useState("Oil change");
  const [dueDate, setDueDate] = useState(() => addMonths(6));
  const [dueMiles, setDueMiles] = useState(mileage !== null ? String(mileage + 5000) : "");
  const [notes, setNotes] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      api.post(`/vehicles/${vehicleId}/reminders`, {
        kind,
        title: title.trim() || null,
        due_date: dueDate || null,
        due_mileage: dueMiles ? Number(dueMiles.replace(/\D/g, "")) : null,
        notes: notes.trim() || null,
        work_order_id: workOrderId ?? null,
      }),
    onSuccess: onClose,
  });
  const pick = (p: ReminderPreset) => {
    setKind(p.kind);
    setTitle(p.kind === "custom" ? "" : p.title);
    setDueDate(p.months ? addMonths(p.months) : "");
    setDueMiles(p.miles && mileage !== null ? String(mileage + p.miles) : "");
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (!dueDate && !dueMiles) return setLocalError("Give a due date, a due mileage, or both.");
    if (kind === "custom" && !title.trim()) return setLocalError("Name the service.");
    save.mutate();
  };
  return (
    <Modal title="Service reminder" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <ErrorNote error={localError ?? save.error} />
        <div className="flex flex-wrap gap-2" role="group" aria-label="Type of service">
          {presets.data?.map((p) => (
            <button key={p.kind} type="button" aria-pressed={kind === p.kind} onClick={() => pick(p)}
              className={`min-h-11 rounded-md border px-3 font-medium ${kind === p.kind ? "border-steel bg-steel text-white" : "border-line bg-sheet"}`}>
              {p.kind === "custom" ? "Other" : p.title}
            </button>
          ))}
        </div>
        <Field label="Service">{(p) => <input {...p} maxLength={120} className="field" value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Due date">{(p) => <input {...p} type="date" className="field" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />}</Field>
          <Field label="Or at mileage" hint={mileage !== null ? `Now ${mileage.toLocaleString()}` : undefined}>
            {(p) => <input {...p} inputMode="numeric" className="field num" value={dueMiles} onChange={(e) => setDueMiles(e.target.value)} />}
          </Field>
        </div>
        <Field label="Note (optional)">{(p) => <input {...p} maxLength={2000} className="field" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Uses 0W-20 full synthetic" />}</Field>
        <Button type="submit" variant="primary" className="w-full" busy={save.isPending}>Set reminder</Button>
      </form>
    </Modal>
  );
}

function addMonths(n: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() + n);
  return localDateInput(d);
}
