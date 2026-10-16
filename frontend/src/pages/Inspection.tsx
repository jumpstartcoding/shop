import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PhotoStrip } from "../components/Photos";
import { AuthorizationBanner, DocumentTrail, SendButton } from "../components/Sending";
import { Button, ErrorNote, Field, InternalNote, Loading, Sheet, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { centsToInput, dateTime, money, toCents } from "../lib/format";
import type { Estimate, Inspection, InspectionItem, ItemStatus } from "../lib/types";

/** The four conditions, in the order a mechanic thinks about them. */
export const CONDITIONS: { value: ItemStatus; label: string; on: string; dot: string }[] = [
  { value: "good", label: "Good", on: "bg-go text-white border-go", dot: "bg-go" },
  { value: "monitor", label: "Monitor", on: "bg-safety text-steel border-safety-deep", dot: "bg-safety-deep" },
  { value: "attention", label: "Needs attention", on: "bg-signal text-white border-signal", dot: "bg-signal" },
  { value: "urgent", label: "Urgent", on: "bg-[#7a1d18] text-white border-[#7a1d18]", dot: "bg-[#7a1d18]" },
];

export function InspectionPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { data: insp, error, isLoading } = useQuery({
    queryKey: ["inspection", id],
    queryFn: () => api.get<Inspection>(`/inspections/${id}`),
  });
  const setStatus = useMutation({
    mutationFn: (status: "completed" | "in_progress") => api.patch<Inspection>(`/inspections/${id}`, { status }),
  });
  const restGood = useMutation({
    mutationFn: async (items: InspectionItem[]) => {
      for (const it of items) await api.patch(`/inspection-items/${it.id}`, { status: "good" });
    },
  });
  const makeEstimate = useMutation({
    mutationFn: () => api.post<Estimate>(`/inspections/${id}/estimate`),
    onSuccess: (e) => navigate(`/admin/estimates/${e.id}`),
  });

  if (isLoading) return <Loading />;
  if (error || !insp) return <ErrorNote error={error} />;

  const total = insp.items.length;
  const checked = total - insp.counts.unchecked;
  const unchecked = insp.items.filter((i) => !i.status);
  const done = insp.status === "completed";
  const red = insp.counts.attention + insp.counts.urgent;

  return (
    <div className="space-y-5">
      <section className="overflow-hidden rounded-lg border border-line bg-sheet md:flex">
        <div className="bg-steel px-4 py-3 text-white md:w-44 md:py-5">
          <p className="text-[15px] font-medium text-white/80">Inspection</p>
          <p className="num text-3xl font-bold leading-none md:text-4xl">{insp.number.split("-").slice(-1)[0]}</p>
          <p className="num text-[15px] text-white/80">{insp.number}</p>
        </div>
        <div className="flex-1 px-4 py-3 md:py-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h1 className="font-display text-[30px] leading-tight font-bold">
                <Link to={`/admin/vehicles/${insp.vehicle_id}`} className="underline-offset-4 hover:underline">{insp.vehicle_name}</Link>
              </h1>
              <p className="text-steel-2">
                {insp.customer_name}, <Link className="underline underline-offset-4" to={`/admin/work-orders/${insp.work_order_id}`}>{insp.work_order_number}</Link>
                {insp.mileage !== null && `, ${insp.mileage.toLocaleString()} mi`}
              </p>
            </div>
            <StatusBadge status={done ? "completed" : "in_progress"} />
          </div>
          <Progress checked={checked} total={total} red={red} yellow={insp.counts.monitor} green={insp.counts.good} />
        </div>
      </section>

      <Sheet title="Checklist">
        {done && <p className="border-b border-line bg-concrete/60 px-4 py-3 text-steel-2">Finished. This is what the customer sees; reopen it below to change anything.</p>}
        <ul>
          {insp.items.map((it) => (
            <ItemRow key={it.id} item={it} locked={done} />
          ))}
        </ul>
        {!done && <AddItem inspectionId={id} />}
      </Sheet>

      <SummarySheet insp={insp} />

      <Sheet title={done ? "Report" : "Finish"}>
        <div className="space-y-3 p-4">
          {!done ? (
            <>
              <p className="text-steel-2">
                {unchecked.length
                  ? `${unchecked.length} item${unchecked.length === 1 ? "" : "s"} still unchecked. Mark the ones you looked at, and remove any that don't apply.`
                  : "Everything is checked. Finish to share the report with the customer."}
              </p>
              <ErrorNote error={setStatus.error ?? restGood.error} />
              <div className="flex flex-wrap gap-2">
                {unchecked.length > 0 && (
                  <Button busy={restGood.isPending} onClick={() => restGood.mutate(unchecked)}>
                    Mark the other {unchecked.length} Good
                  </Button>
                )}
                <Button variant="primary" busy={setStatus.isPending} onClick={() => setStatus.mutate("completed")} disabled={unchecked.length > 0}>
                  Finish inspection
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="text-steel-2">Finished {dateTime(insp.completed_at)}. The customer's report shows red items first, with your photos and notes.</p>
              <AuthorizationBanner state={insp.authorization} approvedText="Acknowledged" />
              <ErrorNote error={makeEstimate.error ?? setStatus.error} />
              <div className="flex flex-wrap gap-2">
                <SendButton
                  path={`/inspections/${id}/send`}
                  label={insp.authorization?.status === "none" ? "Send report to customer" : "Send report again"}
                  noun="inspection report"
                  email={insp.customer_email}
                  phone={insp.customer_phone}
                  variant={insp.authorization?.status === "changed_since_signed" ? "primary" : "secondary"}
                />
                {insp.items.some((i) => i.status && i.status !== "good" && (i.recommendation || i.estimated_cost_cents)) && (
                  <Button variant="primary" busy={makeEstimate.isPending} onClick={() => makeEstimate.mutate()}>
                    Create estimate from findings
                  </Button>
                )}
                <a href={`/api/inspections/${id}/pdf`} target="_blank" rel="noopener" className="inline-flex min-h-12 items-center rounded-md px-4 font-medium hover:bg-black/5">
                  Print report
                </a>
                <Button variant="quiet" busy={setStatus.isPending} onClick={() => setStatus.mutate("in_progress")}>
                  Reopen to edit
                </Button>
              </div>
              {insp.estimate_ids.length > 0 && (
                <p className="text-steel-2">
                  Estimates from this inspection:{" "}
                  {insp.estimate_ids.map((eid, i) => (
                    <span key={eid}>{i > 0 && ", "}<Link className="underline" to={`/admin/estimates/${eid}`}>open #{eid}</Link></span>
                  ))}
                </p>
              )}
            </>
          )}
        </div>
      </Sheet>

      <DocumentTrail entityType="inspection" entityId={id} approvedWord="Acknowledged" />
    </div>
  );
}

function Progress({ checked, total, red, yellow, green }: { checked: number; total: number; red: number; yellow: number; green: number }) {
  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-semibold">{checked} of {total} checked</p>
        <p className="flex flex-wrap gap-3 text-[15px]">
          <Count dot="bg-signal" n={red} label="need attention" />
          <Count dot="bg-safety-deep" n={yellow} label="monitor" />
          <Count dot="bg-go" n={green} label="good" />
        </p>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-concrete" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={checked} aria-label="Items checked">
        <div className="h-full bg-steel transition-[width]" style={{ width: `${total ? (checked / total) * 100 : 0}%` }} />
      </div>
    </div>
  );
}

function Count({ dot, n, label }: { dot: string; n: number; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-3 w-3 rounded-full ${dot}`} aria-hidden="true" />
      <span className="num font-semibold">{n}</span> {label}
    </span>
  );
}

function ItemRow({ item, locked }: { item: InspectionItem; locked: boolean }) {
  const [pending, setPending] = useState<ItemStatus | null>(null);
  const [open, setOpen] = useState(false);
  const status = pending ?? item.status;
  const set = useMutation({
    mutationFn: (s: ItemStatus) => api.patch(`/inspection-items/${item.id}`, { status: s }),
    onMutate: (s) => {
      setPending(s);
      if (s !== "good" && !item.notes && !item.recommendation) setOpen(true);
    },
    onSettled: () => setPending(null),
  });
  const extras = [
    item.notes,
    item.recommendation && `Recommend: ${item.recommendation}`,
    item.estimated_cost_cents ? money(item.estimated_cost_cents) : null,
  ].filter(Boolean);

  return (
    <li className={`border-b border-line px-4 py-3 last:border-b-0 ${status && status !== "good" ? "bg-concrete/40" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-lg font-semibold">{item.name}</p>
          {!open && extras.length > 0 && <p className="text-[15px] text-steel-2">{extras.join(" · ")}</p>}
        </div>
        {item.photos.length > 0 && !open && <span className="shrink-0 text-[15px] text-steel-2">{item.photos.length} photo{item.photos.length === 1 ? "" : "s"}</span>}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4" role="group" aria-label={`${item.name}: condition`}>
        {CONDITIONS.map((c) => {
          const on = status === c.value;
          return (
            <button
              key={c.value}
              type="button"
              aria-pressed={on}
              disabled={locked}
              onClick={() => !on && set.mutate(c.value)}
              className={`flex min-h-12 items-center justify-center gap-2 rounded-md border-2 px-2 font-semibold disabled:cursor-default ${on ? c.on : `border-line bg-sheet text-steel ${locked ? "opacity-40" : "hover:border-steel"}`}`}
            >
              {!on && <span className={`inline-block h-3 w-3 rounded-full ${c.dot}`} aria-hidden="true" />}
              {c.label}
            </button>
          );
        })}
      </div>
      <ErrorNote error={set.error} />
      <button
        type="button"
        className="mt-1 min-h-11 font-medium text-steel-2 underline underline-offset-4"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "Hide notes and photos" : locked ? "Notes and photos" : "Notes, photos, recommendation"}
      </button>
      {open && (locked ? <ItemReadOnly item={item} /> : <ItemDetails item={item} />)}
    </li>
  );
}

function ItemReadOnly({ item }: { item: InspectionItem }) {
  return (
    <div className="mt-2 space-y-2 rounded-md border border-line bg-sheet p-3">
      {item.notes && <p className="whitespace-pre-wrap">{item.notes}</p>}
      {item.recommendation && <p><span className="text-steel-2">Recommended: </span>{item.recommendation}{item.estimated_cost_cents ? `, about ${money(item.estimated_cost_cents)}` : ""}</p>}
      {!item.notes && !item.recommendation && item.photos.length === 0 && <p className="text-steel-2">No notes or photos.</p>}
      {item.photos.length > 0 && <PhotoStrip entityType="inspection_item" entityId={item.id} photos={item.photos} readOnly />}
    </div>
  );
}

function ItemDetails({ item }: { item: InspectionItem }) {
  const [notes, setNotes] = useState(item.notes ?? "");
  const [rec, setRec] = useState(item.recommendation ?? "");
  const [cost, setCost] = useState(centsToInput(item.estimated_cost_cents));
  const [costError, setCostError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch(`/inspection-items/${item.id}`, body),
  });
  const remove = useMutation({ mutationFn: () => api.del(`/inspection-items/${item.id}`) });
  const dirty = notes !== (item.notes ?? "") || rec !== (item.recommendation ?? "") || cost !== centsToInput(item.estimated_cost_cents);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setCostError(null);
    const cents = cost.trim() ? toCents(cost) : null;
    if (cost.trim() && cents === null) return setCostError("Enter a dollar amount, like 425.00.");
    save.mutate({ notes: notes.trim() || null, recommendation: rec.trim() || null, estimated_cost_cents: cents });
  };

  return (
    <div className="mt-2 space-y-3 rounded-md border border-line bg-sheet p-3">
      <form onSubmit={submit} className="space-y-3">
        <ErrorNote error={save.error} />
        <Field label="What you found" hint="The customer sees this on the report.">
          {(p) => <textarea {...p} className="field min-h-20" maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Front pads at 2 mm, rotors scored." />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
          <Field label="Recommended repair">
            {(p) => <input {...p} className="field" maxLength={300} value={rec} onChange={(e) => setRec(e.target.value)} placeholder="Replace front pads and rotors" />}
          </Field>
          <Field label="Estimated cost" error={costError ?? undefined}>
            {(p) => <input {...p} className="field num" inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} placeholder="0.00" />}
          </Field>
        </div>
        {(dirty || save.isSuccess) && (
          <div className="flex items-center gap-3">
            <Button type="submit" variant={dirty ? "primary" : "secondary"} busy={save.isPending} disabled={!dirty}>
              {dirty ? "Save" : "Saved"}
            </Button>
          </div>
        )}
      </form>
      <div>
        <p className="mb-1 text-[15px] font-medium text-steel-2">Photos</p>
        <PhotoStrip entityType="inspection_item" entityId={item.id} photos={item.photos} />
      </div>
      <div className="border-t border-line pt-2">
        <ErrorNote error={remove.error} />
        {confirmRemove ? (
          <div className="flex flex-wrap items-center gap-2">
            <span>Remove “{item.name}” from this inspection?</span>
            <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>Remove</Button>
            <Button variant="quiet" onClick={() => setConfirmRemove(false)}>Keep it</Button>
          </div>
        ) : (
          <Button variant="quiet" onClick={() => setConfirmRemove(true)}>Doesn't apply to this vehicle</Button>
        )}
      </div>
    </div>
  );
}

function AddItem({ inspectionId }: { inspectionId: number }) {
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/inspections/${inspectionId}/items`, { name }),
    onSuccess: () => setName(""),
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) add.mutate(); }} className="flex flex-wrap items-end gap-2 border-t border-line p-4">
      <div className="min-w-0 flex-1">
        <Field label="Add an item">
          {(p) => <input {...p} className="field" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="Wiper blades, exhaust, CV boots…" />}
        </Field>
      </div>
      <Button type="submit" busy={add.isPending} disabled={!name.trim()}>Add</Button>
      <div className="w-full"><ErrorNote error={add.error} /></div>
    </form>
  );
}

function SummarySheet({ insp }: { insp: Inspection }) {
  const [summary, setSummary] = useState(insp.summary ?? "");
  const [internal, setInternal] = useState(insp.internal_notes ?? "");
  const [editing, setEditing] = useState(false);
  const save = useMutation({
    mutationFn: () => api.patch(`/inspections/${insp.id}`, { summary: summary.trim() || null, internal_notes: internal.trim() || null }),
    onSuccess: () => setEditing(false),
  });
  if (!editing) {
    return (
      <Sheet title="Summary" action={<Button variant="quiet" onClick={() => setEditing(true)}>{insp.summary || insp.internal_notes ? "Edit" : "Add"}</Button>}>
        <div className="space-y-3 p-4">
          {insp.summary ? (
            <div className="border-l-4 border-go px-3 py-1">
              <p className="text-[14px] font-semibold text-go">For the customer (top of the report)</p>
              <p className="whitespace-pre-wrap">{insp.summary}</p>
            </div>
          ) : (
            <p className="text-steel-2">A sentence or two at the top of the customer's report, like “Front brakes need replacing now; everything else looks good.”</p>
          )}
          <InternalNote>{insp.internal_notes}</InternalNote>
        </div>
      </Sheet>
    );
  }
  return (
    <Sheet title="Summary">
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-3 p-4">
        <ErrorNote error={save.error} />
        <Field label="For the customer" hint="Shown at the top of the report.">
          {(p) => <textarea {...p} className="field min-h-24" maxLength={5000} value={summary} onChange={(e) => setSummary(e.target.value)} />}
        </Field>
        <Field label="Internal note" hint="Only you see this.">
          {(p) => <textarea {...p} className="field min-h-20" maxLength={5000} value={internal} onChange={(e) => setInternal(e.target.value)} />}
        </Field>
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={save.isPending}>Save</Button>
          <Button type="button" variant="quiet" onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      </form>
    </Sheet>
  );
}
