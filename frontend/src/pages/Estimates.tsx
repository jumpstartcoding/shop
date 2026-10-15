import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useCallback, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { DocumentList } from "../components/DocumentList";
import { LineItems } from "../components/LineItems";
import { AuthorizationBanner, DocumentTrail, SendButton } from "../components/Sending";
import { CustomerVehiclePicker } from "../components/Picker";
import { Button, Dl, ErrorNote, Field, InternalNote, Loading, Modal, PageHeader, Sheet, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { date, dateTime, sentence } from "../lib/format";
import type { Estimate, WorkOrder } from "../lib/types";

const FILTERS: [string, string[]][] = [
  ["All", []],
  ["Drafts", ["draft"]],
  ["Waiting on customer", ["sent", "viewed"]],
  ["Approved", ["approved"]],
  ["Declined", ["declined"]],
];

export function EstimateList() {
  return (
    <DocumentList
      title="Estimates"
      path="estimates"
      filters={FILTERS}
      newLabel="New estimate"
      emptyText="No estimates yet. Build one from a work order, or start a new one."
    />
  );
}

export function NewEstimate() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [customerId, setCustomerId] = useState<number | null>(Number(params.get("customer")) || null);
  const [vehicleId, setVehicleId] = useState<number | null>(Number(params.get("vehicle")) || null);
  const [concern, setConcern] = useState("");
  const workOrderId = Number(params.get("work_order")) || null;
  const supplement = params.get("supplement") === "1" && workOrderId !== null;
  const onPick = useCallback((c: number | null, v: number | null) => {
    setCustomerId(c);
    setVehicleId(v);
  }, []);
  const create = useMutation({
    mutationFn: () =>
      api.post<Estimate>("/estimates", {
        customer_id: customerId, vehicle_id: vehicleId, concern, items: [],
        work_order_id: workOrderId, is_supplement: supplement,
      }),
    onSuccess: (e) => navigate(`/admin/estimates/${e.id}`, { replace: true }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <PageHeader
        title={supplement ? "Approval for additional work" : "New estimate"}
        sub={supplement
          ? "Add only the extra work you found. When the customer approves, it's added to the work order."
          : "For a job that's already in the shop, open its work order and create the estimate from there."}
      />
      <ErrorNote error={create.error} />
      <Sheet><div className="p-4"><CustomerVehiclePicker customerId={customerId} vehicleId={vehicleId} onChange={onPick} /></div></Sheet>
      {vehicleId && (
        <Sheet>
          <div className="p-4">
            <Field label={supplement ? "What you found" : "What the customer asked about"}>
              {(p) => <textarea {...p} className="field min-h-20" value={concern} onChange={(e) => setConcern(e.target.value)} />}
            </Field>
          </div>
        </Sheet>
      )}
      <Button type="submit" variant="primary" disabled={!vehicleId} busy={create.isPending}>{supplement ? "Start approval request" : "Start estimate"}</Button>
    </form>
  );
}

export function EstimatePage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [modal, setModal] = useState<null | "decision" | "notes">(null);
  const { data: est, error, isLoading } = useQuery({
    queryKey: ["estimate", id],
    queryFn: () => api.get<Estimate>(`/estimates/${id}`),
  });
  const action = useMutation({
    mutationFn: (path: string) => api.post(`/estimates/${id}/${path}`),
  });
  const convert = useMutation({
    mutationFn: () => api.post<WorkOrder>(`/estimates/${id}/convert`),
    onSuccess: (wo) => navigate(`/admin/work-orders/${wo.id}`),
  });

  if (isLoading) return <Loading />;
  if (error || !est) return <ErrorNote error={error} />;

  const editable = est.status === "draft";
  const lockedReason = !editable
    ? est.converted_at
      ? "This estimate has been turned into work and can't change."
      : `This estimate was ${est.status}. To change it, create a new version; the customer will need to approve again.`
    : undefined;

  return (
    <div className="space-y-5">
      <PageHeader
        title={<>{est.is_supplement ? "Additional work" : "Estimate"} {est.number}{est.version > 1 && <span className="ml-2 text-steel-2">v{est.version}</span>}</>}
        sub={
          <>
            <Link className="font-medium text-steel underline-offset-4 hover:underline" to={`/admin/customers/${est.customer_id}`}>{est.party.customer_name}</Link>
            , <Link className="underline-offset-4 hover:underline" to={`/admin/vehicles/${est.vehicle_id}`}>{est.party.vehicle_name}</Link>
          </>
        }
        actions={<StatusBadge status={est.status} />}
      />

      <Sheet title="Where it stands">
        <Dl
          rows={[
            ["Created", date(est.created_at)],
            ["Valid until", date(est.expires_on)],
            ["Given to customer", dateTime(est.sent_at)],
            ["Approved", est.approved_at && `${dateTime(est.approved_at)}, ${methodLabel(est.decision_method)}`],
            ["Declined", est.declined_at && `${dateTime(est.declined_at)}, ${methodLabel(est.decision_method)}`],
            ["Note", est.decision_note],
            ["Work order", est.work_order_id && <Link className="underline" to={`/admin/work-orders/${est.work_order_id}`}>Open work order</Link>],
          ]}
        />
        <div className="px-4 pb-3"><AuthorizationBanner state={est.authorization} /></div>
        <div className="flex flex-wrap gap-2 border-t border-line p-4">
          {["draft", "sent", "viewed"].includes(est.status) && (
            <SendButton
              path={`/estimates/${id}/send`}
              label={est.status === "draft" ? "Send to customer for approval" : "Send the link again"}
              noun={est.is_supplement ? "approval request" : "estimate"}
              email={est.party.customer_email}
              phone={est.party.customer_phone}
              disabled={!est.items.length}
            />
          )}
          {["draft", "sent", "viewed"].includes(est.status) && (
            <Button onClick={() => setModal("decision")} disabled={!est.items.length}>
              Record answer from phone or in person
            </Button>
          )}
          {est.status === "draft" && (
            <Button variant="quiet" onClick={() => action.mutate("mark-sent")} busy={action.isPending} disabled={!est.items.length}>
              Mark as printed or handed over
            </Button>
          )}
          {est.status === "approved" && !est.converted_at && (
            <Button variant="primary" onClick={() => convert.mutate()} busy={convert.isPending}>
              {est.is_supplement ? "Add to work order" : est.work_order_id ? "Apply to work order" : "Turn into work order"}
            </Button>
          )}
          {est.status !== "draft" && !est.converted_at && (
            <Button onClick={() => confirm("Create a new version? Any approval on this version will no longer apply, and the customer's current link stops working.") && action.mutate("revise")}
              busy={action.isPending}>
              Create new version
            </Button>
          )}
          <a href={`/api/estimates/${id}/pdf`} target="_blank" rel="noopener" className="inline-flex min-h-12 items-center rounded-md px-4 font-medium hover:bg-black/5">
            Preview PDF
          </a>
          <Button variant="quiet" onClick={() => setModal("notes")}>Notes</Button>
        </div>
        <div className="px-4 pb-2"><ErrorNote error={action.error ?? convert.error} /></div>
      </Sheet>

      {est.concern && <p className="text-lg">“{est.concern}”</p>}

      <LineItems basePath={`/estimates/${id}`} items={est.items} totals={est} readOnly={!editable} lockedReason={lockedReason} />

      {(est.customer_notes || est.internal_notes) && (
        <Sheet title="Notes">
          <div className="space-y-3 p-4">
            {est.customer_notes && (
              <div className="border-l-4 border-go px-3 py-1">
                <p className="text-[14px] font-semibold text-go">Customer-facing note (prints on the estimate)</p>
                <p className="whitespace-pre-wrap">{est.customer_notes}</p>
              </div>
            )}
            <InternalNote>{est.internal_notes}</InternalNote>
          </div>
        </Sheet>
      )}

      <DocumentTrail entityType="estimate" entityId={id} />

      {modal === "decision" && <DecisionModal id={id} onClose={() => setModal(null)} />}
      {modal === "notes" && <EstimateNotes est={est} onClose={() => setModal(null)} />}
    </div>
  );
}

function methodLabel(m: string | null): string {
  return m === "link" ? "through the customer's link" : m === "in_person" ? "in person" : m ? `by ${m}` : "";
}

function DecisionModal({ id, onClose }: { id: number; onClose: () => void }) {
  const [decision, setDecision] = useState<"approved" | "declined">("approved");
  const [method, setMethod] = useState("phone");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => api.post(`/estimates/${id}/decision`, { decision, method, note }),
    onSuccess: onClose,
  });
  return (
    <Modal title="Customer's answer" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error} />
        <fieldset className="grid grid-cols-2 gap-2">
          <legend className="mb-1 text-[15px] font-medium text-steel-2">Answer</legend>
          {(["approved", "declined"] as const).map((d) => (
            <label key={d} className={`flex min-h-14 cursor-pointer items-center gap-2 rounded-md border px-3 ${decision === d ? "border-steel bg-safety/25" : "border-line"}`}>
              <input type="radio" name="decision" className="h-5 w-5" checked={decision === d} onChange={() => setDecision(d)} />
              <span className="text-lg font-medium">{sentence(d)}</span>
            </label>
          ))}
        </fieldset>
        <Field label="How they told you">
          {(p) => (
            <select {...p} className="field" value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="phone">Phone call</option>
              <option value="in_person">In person</option>
              <option value="text">Text message</option>
              <option value="email">Email</option>
            </select>
          )}
        </Field>
        <Field label="Note" hint="e.g. “Approved front brakes only, will wait on rear.”">
          {(p) => <textarea {...p} className="field min-h-20" value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" className="w-full" busy={save.isPending}>
          Record {decision === "approved" ? "approval" : "decline"}
        </Button>
      </form>
    </Modal>
  );
}

function EstimateNotes({ est, onClose }: { est: Estimate; onClose: () => void }) {
  const editable = est.status === "draft";
  const [customerNotes, setCustomerNotes] = useState(est.customer_notes ?? "");
  const [internal, setInternal] = useState(est.internal_notes ?? "");
  const save = useMutation({
    mutationFn: () => api.patch(`/estimates/${est.id}`, editable ? { customer_notes: customerNotes, internal_notes: internal } : { internal_notes: internal }),
    onSuccess: onClose,
  });
  return (
    <Modal title="Estimate notes" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error} />
        <Field label="Customer-facing note" hint={editable ? "Prints on the estimate." : "Locked once the estimate was given to the customer."}>
          {(p) => <textarea {...p} className="field min-h-24" disabled={!editable} value={customerNotes} onChange={(e) => setCustomerNotes(e.target.value)} />}
        </Field>
        <Field label="Internal note" hint="Only you see this.">
          {(p) => <textarea {...p} className="field min-h-20" value={internal} onChange={(e) => setInternal(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" className="w-full" busy={save.isPending}>Save notes</Button>
      </form>
    </Modal>
  );
}
