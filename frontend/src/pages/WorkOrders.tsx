import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { LineItems } from "../components/LineItems";
import { PhotoStrip } from "../components/Photos";
import { ReminderModal } from "./Reminders";
import { CustomerVehiclePicker } from "../components/Picker";
import { AuthorizationBanner, DocumentTrail, SendButton } from "../components/Sending";
import { Button, ErrorNote, Field, InternalNote, LinkButton, Loading, Modal, PageHeader, Sheet, StatusBadge } from "../components/ui";
import { ApiError, api } from "../lib/api";
import { dateTime, phoneHref, sentence } from "../lib/format";
import { WO_STATUSES, type Estimate, type Inspection, type Invoice, type WorkOrder, type WorkOrderStatus } from "../lib/types";

export const CHECKLIST: [string, string][] = [
  ["repair_completed", "Repair completed"],
  ["vehicle_inspected", "Vehicle inspected"],
  ["test_drive_completed", "Test drive completed"],
  ["tools_removed", "Tools and covers removed"],
  ["old_parts_handled", "Old parts returned or disposed"],
  ["customer_notified", "Customer notified"],
  ["invoice_generated", "Invoice created"],
  ["payment_confirmed", "Payment confirmed"],
];

export function NewWorkOrder() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [customerId, setCustomerId] = useState<number | null>(Number(params.get("customer")) || null);
  const [vehicleId, setVehicleId] = useState<number | null>(Number(params.get("vehicle")) || null);
  const [concern, setConcern] = useState("");
  const [mileage, setMileage] = useState("");
  const appointmentId = Number(params.get("appointment")) || null;

  const onPick = useCallback((c: number | null, v: number | null) => {
    setCustomerId(c);
    setVehicleId(v);
  }, []);

  const create = useMutation({
    mutationFn: () =>
      api.post<WorkOrder>("/work-orders", {
        customer_id: customerId,
        vehicle_id: vehicleId,
        concern,
        mileage_in: mileage ? Number(mileage.replace(/\D/g, "")) : null,
        appointment_id: appointmentId,
      }),
    onSuccess: (wo) => navigate(`/admin/work-orders/${wo.id}`, { replace: true }),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <PageHeader title="New work order" />
      <ErrorNote error={create.error} />
      <Sheet>
        <div className="p-4">
          <CustomerVehiclePicker customerId={customerId} vehicleId={vehicleId} onChange={onPick} />
        </div>
      </Sheet>
      {vehicleId && (
        <Sheet>
          <div className="space-y-4 p-4">
            <Field label="Customer concern" hint="In the customer's words, e.g. “Shakes when braking from highway speed.”">
              {(p) => <textarea {...p} className="field min-h-24" value={concern} onChange={(e) => setConcern(e.target.value)} />}
            </Field>
            <Field label="Mileage in">
              {(p) => <input {...p} className="field num text-lg" inputMode="numeric" value={mileage} onChange={(e) => setMileage(e.target.value)} />}
            </Field>
          </div>
        </Sheet>
      )}
      <Button type="submit" variant="primary" disabled={!vehicleId} busy={create.isPending} className="w-full sm:w-auto">
        Open work order
      </Button>
    </form>
  );
}

export function WorkOrderPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [modal, setModal] = useState<null | "notes" | "checklist" | "reminder">(null);
  const { data: wo, error, isLoading } = useQuery({
    queryKey: ["work-order", id],
    queryFn: () => api.get<WorkOrder>(`/work-orders/${id}`),
  });

  const setStatus = useMutation({
    mutationFn: (body: { status: WorkOrderStatus; override_checklist?: boolean }) =>
      api.post<WorkOrder>(`/work-orders/${id}/status`, body),
    onError: (e) => {
      if (e instanceof ApiError && e.code === "checklist_incomplete") setModal("checklist");
    },
  });
  const makeEstimate = useMutation({
    mutationFn: () =>
      api.post<Estimate>("/estimates", { customer_id: wo!.customer_id, vehicle_id: wo!.vehicle_id, work_order_id: id }),
    onSuccess: (e) => navigate(`/admin/estimates/${e.id}`),
  });
  const notifyReady = useMutation({
    mutationFn: () => api.post<WorkOrder>(`/work-orders/${id}/status`, { status: "ready_for_pickup", notify_customer: true }),
  });
  const makeInvoice = useMutation({
    mutationFn: () => api.post<Invoice>(`/work-orders/${id}/invoice`),
    onSuccess: (inv) => navigate(`/admin/invoices/${inv.id}`),
  });

  if (isLoading) return <Loading />;
  if (error || !wo) return <ErrorNote error={error} />;

  const closed = wo.status === "completed" || wo.status === "cancelled";
  const activeInvoice = wo.invoice_ids.at(-1);

  return (
    <div className="space-y-5">
      {/* The repair tag: what's hanging on the mirror of the car in the bay. */}
      <section className="overflow-hidden rounded-lg border border-line bg-sheet md:flex">
        <div className="bg-safety px-4 py-3 md:w-44 md:py-5">
          <p className="text-[15px] font-medium">Work order</p>
          <p className="num text-3xl font-bold leading-none md:text-4xl">{wo.number.split("-").slice(-1)[0]}</p>
          <p className="num text-[15px]">{wo.number}</p>
        </div>
        <div className="flex-1 px-4 py-3 md:py-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h1 className="font-display text-[30px] leading-tight font-bold">
                <Link to={`/admin/vehicles/${wo.vehicle_id}`} className="underline-offset-4 hover:underline">{wo.party.vehicle_name}</Link>
              </h1>
              <p className="text-steel-2">
                <Link to={`/admin/customers/${wo.customer_id}`} className="font-medium text-steel underline-offset-4 hover:underline">
                  {wo.party.customer_name}
                </Link>
                {wo.party.license_plate && `, ${wo.party.license_plate}`}
                {wo.mileage_in !== null && `, ${wo.mileage_in.toLocaleString()} mi in`}
              </p>
            </div>
            <StatusBadge status={wo.status} />
          </div>
          {wo.concern && <p className="mt-3 text-lg">“{wo.concern}”</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {wo.party.customer_phone && (
              <a href={phoneHref(wo.party.customer_phone)} className="inline-flex min-h-12 items-center rounded-md border border-line px-4 font-medium">
                Call customer
              </a>
            )}
            <Button onClick={() => setModal("notes")}>Notes and mileage</Button>
          </div>
        </div>
      </section>

      <StatusStepper current={wo.status} busy={setStatus.isPending} onPick={(s) => setStatus.mutate({ status: s })} />
      <ErrorNote error={setStatus.error instanceof ApiError && setStatus.error.code === "checklist_incomplete" ? null : setStatus.error} />

      <InspectionSheet wo={wo} closed={closed} />

      <LineItems
        basePath={`/work-orders/${id}`}
        items={wo.items}
        totals={wo}
        readOnly={closed}
        lockedReason={closed ? `This work order is ${sentence(wo.status).toLowerCase()}. Move it back to In repair to change lines.` : undefined}
      />

      <Sheet title="Next step">
        <div className="flex flex-wrap gap-2 p-4">
          <Button onClick={() => makeEstimate.mutate()} busy={makeEstimate.isPending} disabled={closed || wo.items.length === 0}>
            Create estimate from these lines
          </Button>
          {activeInvoice ? (
            <Link to={`/admin/invoices/${activeInvoice}`} className="inline-flex min-h-12 items-center rounded-md border border-safety-deep bg-safety px-4 font-semibold">
              Open invoice
            </Link>
          ) : (
            <Button variant="primary" onClick={() => makeInvoice.mutate()} busy={makeInvoice.isPending} disabled={wo.items.length === 0 || wo.status === "cancelled"}>
              Create invoice
            </Button>
          )}
          {!closed && (
            <LinkButton to={`/admin/estimates/new?customer=${wo.customer_id}&vehicle=${wo.vehicle_id}&work_order=${wo.id}&supplement=1`}>
              Ask approval for extra work
            </LinkButton>
          )}
          <Button onClick={() => setModal("checklist")}>Completion checklist</Button>
          {wo.status === "completed" && <Button onClick={() => setModal("reminder")}>Remind about next service</Button>}
          {wo.status === "ready_for_pickup" && wo.party.customer_email && (
            <Button onClick={() => notifyReady.mutate()} busy={notifyReady.isPending}>
              Email customer it's ready
            </Button>
          )}
          <a href={`/api/work-orders/${id}/pdf`} target="_blank" rel="noopener" className="inline-flex min-h-12 items-center rounded-md px-4 font-medium hover:bg-black/5">
            Print work order
          </a>
        </div>
        {notifyReady.data?.email && (
          <p role="status" className="px-4 pb-3 text-steel-2">{notifyReady.data.email.message}</p>
        )}
        <div className="px-4 pb-4"><ErrorNote error={makeEstimate.error ?? makeInvoice.error ?? notifyReady.error} /></div>
        {wo.estimate_ids.length > 0 && (
          <p className="border-t border-line px-4 py-3 text-steel-2">
            Estimates:{" "}
            {wo.estimate_ids.map((eid, i) => (
              <span key={eid}>{i > 0 && ", "}<Link className="underline" to={`/admin/estimates/${eid}`}>#{eid}</Link></span>
            ))}
          </p>
        )}
      </Sheet>

      <Sheet title="Customer authorization">
        <div className="space-y-3 p-4">
          <p className="text-steel-2">
            Have the customer sign off on the work as written, from their phone. If you change the work afterwards, you'll see it here and can ask again.
          </p>
          <AuthorizationBanner state={wo.authorization} />
          {!closed && (
            <SendButton
              path={`/work-orders/${id}/send-authorization`}
              label={wo.authorization?.status === "approved" ? "Send again for signature" : "Send for signature"}
              noun="repair authorization"
              email={wo.party.customer_email}
              phone={wo.party.customer_phone}
              variant={wo.authorization?.status === "changed_since_signed" ? "primary" : "secondary"}
              disabled={wo.items.length === 0 && !wo.concern}
            />
          )}
        </div>
      </Sheet>

      <DocumentTrail entityType="work_order" entityId={id} />

      {(wo.customer_notes || wo.internal_notes) && (
        <Sheet title="Notes">
          <div className="space-y-3 p-4">
            {wo.customer_notes && (
              <div className="border-l-4 border-go px-3 py-1">
                <p className="text-[14px] font-semibold text-go">Customer-facing note (prints on documents)</p>
                <p className="whitespace-pre-wrap">{wo.customer_notes}</p>
              </div>
            )}
            <InternalNote>{wo.internal_notes}</InternalNote>
          </div>
        </Sheet>
      )}

      <Sheet title="Photos">
        <div className="p-4">
          <p className="mb-3 text-steel-2">Before and after shots, the VIN plate, a scan tool screen. Photos marked for the customer print on the work order.</p>
          <PhotoStrip entityType="work_order" entityId={wo.id} />
        </div>
      </Sheet>

      <p className="text-[15px] text-steel-2">
        Opened {dateTime(wo.created_at)}{wo.completed_at && `. Completed ${dateTime(wo.completed_at)}`}.
      </p>

      {modal === "notes" && <NotesModal wo={wo} onClose={() => setModal(null)} />}
      {modal === "reminder" && (
        <ReminderModal vehicleId={wo.vehicle_id} mileage={wo.mileage_out ?? wo.mileage_in} workOrderId={wo.id} onClose={() => setModal(null)} />
      )}
      {modal === "checklist" && (
        <ChecklistModal
          wo={wo}
          onClose={() => setModal(null)}
          onComplete={(override) => {
            setStatus.mutate({ status: "completed", override_checklist: override }, { onSuccess: () => setModal(null) });
          }}
          completing={setStatus.isPending}
        />
      )}
    </div>
  );
}

function InspectionSheet({ wo, closed }: { wo: WorkOrder; closed: boolean }) {
  const navigate = useNavigate();
  const insp = useQuery({
    queryKey: ["inspection", wo.inspection_id],
    queryFn: () => api.get<Inspection>(`/inspections/${wo.inspection_id}`),
    enabled: !!wo.inspection_id,
  });
  const start = useMutation({
    mutationFn: () => api.post<Inspection>(`/work-orders/${wo.id}/inspection`),
    onSuccess: (i) => navigate(`/admin/inspections/${i.id}`),
  });
  if (!wo.inspection_id) {
    if (closed) return null;
    return (
      <Sheet title="Inspection">
        <div className="flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="text-steel-2">Walk around the car with a 14-point checklist, take photos, and send the customer a color-coded report.</p>
          <Button variant="primary" busy={start.isPending} onClick={() => start.mutate()}>Start inspection</Button>
          <div className="w-full"><ErrorNote error={start.error} /></div>
        </div>
      </Sheet>
    );
  }
  const d = insp.data;
  return (
    <Sheet title="Inspection" action={<LinkButton to={`/admin/inspections/${wo.inspection_id}`} variant={d?.status === "completed" ? "secondary" : "primary"}>{d?.status === "completed" ? "Open" : "Continue"}</LinkButton>}>
      {d ? (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-4 py-3">
          <span className="font-semibold">{d.number}{d.status === "completed" ? ", finished" : `, ${d.items.length - d.counts.unchecked} of ${d.items.length} checked`}</span>
          <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="h-3 w-3 rounded-full bg-signal" />{d.counts.attention + d.counts.urgent} need attention</span>
          <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="h-3 w-3 rounded-full bg-safety-deep" />{d.counts.monitor} monitor</span>
          <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="h-3 w-3 rounded-full bg-go" />{d.counts.good} good</span>
        </div>
      ) : (
        <Loading />
      )}
    </Sheet>
  );
}

function StatusStepper({ current, onPick, busy }: { current: WorkOrderStatus; onPick: (s: WorkOrderStatus) => void; busy: boolean }) {
  const steps = WO_STATUSES.filter((s) => s !== "cancelled");
  const idx = steps.indexOf(current as (typeof steps)[number]);
  const currentRef = useRef<HTMLButtonElement>(null);
  // On a phone the strip scrolls sideways; keep the current step in view.
  useEffect(() => {
    currentRef.current?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [current]);
  return (
    <nav aria-label="Work order status" className="-mx-4 overflow-x-auto px-4">
      <ol className="flex min-w-max gap-1">
        {steps.map((s, i) => {
          const done = idx >= 0 && i < idx;
          const here = s === current;
          return (
            <li key={s}>
              <button
                type="button"
                ref={here ? currentRef : undefined}
                disabled={busy || here}
                aria-current={here ? "step" : undefined}
                onClick={() => onPick(s)}
                className={`min-h-12 rounded-md border px-3 text-[15px] font-medium ${
                  here
                    ? "border-steel bg-steel text-white"
                    : done
                      ? "border-line bg-sheet text-steel-2 line-through decoration-steel-3"
                      : "border-line bg-sheet text-steel"
                }`}
              >
                {sentence(s)}
              </button>
            </li>
          );
        })}
        {current === "cancelled" ? (
          <li><span className="inline-flex min-h-12 items-center rounded-md border border-signal px-3 font-semibold text-signal">Cancelled</span></li>
        ) : (
          <li>
            <button type="button" disabled={busy} onClick={() => confirm("Cancel this work order?") && onPick("cancelled")}
              className="min-h-12 rounded-md border border-transparent px-3 text-[15px] text-signal underline underline-offset-4">
              Cancel job
            </button>
          </li>
        )}
      </ol>
    </nav>
  );
}

function NotesModal({ wo, onClose }: { wo: WorkOrder; onClose: () => void }) {
  const [concern, setConcern] = useState(wo.concern ?? "");
  const [customerNotes, setCustomerNotes] = useState(wo.customer_notes ?? "");
  const [internal, setInternal] = useState(wo.internal_notes ?? "");
  const [mileageIn, setMileageIn] = useState(wo.mileage_in?.toString() ?? "");
  const [mileageOut, setMileageOut] = useState(wo.mileage_out?.toString() ?? "");
  const closed = wo.status === "completed" || wo.status === "cancelled";
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/work-orders/${wo.id}`, {
        customer_notes: customerNotes,
        internal_notes: internal,
        ...(closed
          ? {}
          : {
              concern,
              mileage_in: mileageIn ? Number(mileageIn.replace(/\D/g, "")) : null,
              mileage_out: mileageOut ? Number(mileageOut.replace(/\D/g, "")) : null,
            }),
      }),
    onSuccess: onClose,
  });
  return (
    <Modal title="Notes and mileage" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error} />
        <Field label="Customer concern">
          {(p) => <textarea {...p} className="field min-h-20" disabled={closed} value={concern} onChange={(e) => setConcern(e.target.value)} />}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Mileage in">
            {(p) => <input {...p} className="field num text-lg" inputMode="numeric" disabled={closed} value={mileageIn} onChange={(e) => setMileageIn(e.target.value)} />}
          </Field>
          <Field label="Mileage out">
            {(p) => <input {...p} className="field num text-lg" inputMode="numeric" disabled={closed} value={mileageOut} onChange={(e) => setMileageOut(e.target.value)} />}
          </Field>
        </div>
        <Field label="Customer-facing note" hint="Prints on estimates and invoices.">
          {(p) => <textarea {...p} className="field min-h-20" value={customerNotes} onChange={(e) => setCustomerNotes(e.target.value)} />}
        </Field>
        <Field label="Internal note" hint="Only you see this.">
          {(p) => <textarea {...p} className="field min-h-20 border-l-4 border-l-steel" value={internal} onChange={(e) => setInternal(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" busy={save.isPending} className="w-full">Save notes</Button>
      </form>
    </Modal>
  );
}

function ChecklistModal({
  wo,
  onClose,
  onComplete,
  completing,
}: {
  wo: WorkOrder;
  onClose: () => void;
  onComplete: (override: boolean) => void;
  completing: boolean;
}) {
  // Ticks show immediately; the server copy catches up, and a failed save rolls the tick back.
  const [checks, setChecks] = useState<Record<string, boolean>>(wo.qc_checklist);
  useEffect(() => setChecks(wo.qc_checklist), [wo.qc_checklist]);
  const save = useMutation({
    mutationFn: (patch: Record<string, boolean>) => api.patch(`/work-orders/${wo.id}`, { qc_checklist: patch }),
    onError: () => setChecks(wo.qc_checklist),
  });
  const allDone = CHECKLIST.every(([k]) => checks[k]);
  return (
    <Modal title="Before you close it out" onClose={onClose}>
      <ErrorNote error={save.error} />
      <ul className="divide-y divide-line">
        {CHECKLIST.map(([key, label]) => (
          <li key={key}>
            <label className="flex min-h-14 items-center gap-3">
              <input type="checkbox" className="h-6 w-6 accent-[#276b43]" checked={!!checks[key]}
                onChange={(e) => {
                  setChecks((c) => ({ ...c, [key]: e.target.checked }));
                  save.mutate({ [key]: e.target.checked });
                }} />
              <span className="text-lg">{label}</span>
            </label>
          </li>
        ))}
      </ul>
      {wo.status !== "completed" && (
        <div className="mt-4 space-y-2">
          <Button variant="primary" className="w-full" disabled={!allDone} busy={completing} onClick={() => onComplete(false)}>
            Mark job completed
          </Button>
          {!allDone && (
            <Button variant="quiet" className="w-full" busy={completing}
              onClick={() => confirm("Complete without every item checked? This is recorded in the history.") && onComplete(true)}>
              Complete anyway
            </Button>
          )}
        </div>
      )}
    </Modal>
  );
}
