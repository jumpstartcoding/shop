import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useCallback, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { DocumentList } from "../components/DocumentList";
import { LineItems } from "../components/LineItems";
import { DocumentTrail, SendButton } from "../components/Sending";
import { CustomerVehiclePicker } from "../components/Picker";
import { Button, Dl, ErrorNote, Field, InternalNote, Loading, Modal, PageHeader, Sheet, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { centsToInput, date, dateTime, localDateInput, money, sentence, toCents } from "../lib/format";
import type { EmailResult, Invoice, Payment } from "../lib/types";

const FILTERS: [string, string[]][] = [
  ["All", []],
  ["Drafts", ["draft"]],
  ["Paid", ["paid"]],
  ["Void", ["void"]],
  ["Unpaid", []],
];

export function InvoiceList() {
  return (
    <DocumentList
      title="Invoices"
      path="invoices"
      filters={FILTERS}
      newLabel="New invoice"
      emptyText="No invoices yet. Most invoices are created from a work order."
      extraQuery={(i): Record<string, boolean> => (i === FILTERS.length - 1 ? { unpaid_only: true } : {})}
    />
  );
}

export function NewInvoice() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [customerId, setCustomerId] = useState<number | null>(Number(params.get("customer")) || null);
  const [vehicleId, setVehicleId] = useState<number | null>(Number(params.get("vehicle")) || null);
  const onPick = useCallback((c: number | null, v: number | null) => {
    setCustomerId(c);
    setVehicleId(v);
  }, []);
  const create = useMutation({
    mutationFn: () => api.post<Invoice>("/invoices", { customer_id: customerId, vehicle_id: vehicleId, items: [] }),
    onSuccess: (inv) => navigate(`/admin/invoices/${inv.id}`, { replace: true }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <PageHeader title="New invoice" sub="For quick counter jobs. For work done on a work order, open the work order and choose Create invoice." />
      <ErrorNote error={create.error} />
      <Sheet><div className="p-4"><CustomerVehiclePicker customerId={customerId} vehicleId={vehicleId} onChange={onPick} /></div></Sheet>
      <Button type="submit" variant="primary" disabled={!vehicleId} busy={create.isPending}>Start invoice</Button>
    </form>
  );
}

const METHOD_LABEL: Record<string, string> = { cash: "Cash", check: "Check", card: "Card", online: "Online", other: "Other" };

export function InvoicePage() {
  const id = Number(useParams().id);
  const [modal, setModal] = useState<null | "pay" | "void" | "edit" | { voidPayment: Payment }>(null);
  const { data: inv, error, isLoading } = useQuery({
    queryKey: ["invoice", id],
    queryFn: () => api.get<Invoice>(`/invoices/${id}`),
  });
  const markSent = useMutation({ mutationFn: () => api.post(`/invoices/${id}/mark-sent`) });

  if (isLoading) return <Loading />;
  if (error || !inv) return <ErrorNote error={error} />;

  const isVoid = inv.status === "void";
  const hasPayments = inv.amount_paid_cents > 0;
  const lockedReason = isVoid
    ? `Voided ${dateTime(inv.voided_at)}: ${inv.void_reason}`
    : hasPayments
      ? "Charges are locked because money has been received. Void the payments first to change them."
      : undefined;

  return (
    <div className="space-y-5">
      <PageHeader
        title={<>Invoice {inv.number}</>}
        sub={
          <>
            <Link className="font-medium text-steel underline-offset-4 hover:underline" to={`/admin/customers/${inv.customer_id}`}>{inv.party.customer_name}</Link>
            , <Link className="underline-offset-4 hover:underline" to={`/admin/vehicles/${inv.vehicle_id}`}>{inv.party.vehicle_name}</Link>
          </>
        }
        actions={<StatusBadge status={inv.status} />}
      />

      {/* Balance is the answer to "do they owe me anything", so it leads. */}
      <section className={`rounded-lg px-4 py-4 ${inv.balance_cents > 0 && !isVoid ? "bg-steel text-white" : "border border-line bg-sheet"}`}>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className={inv.balance_cents > 0 && !isVoid ? "text-white/75" : "text-steel-2"}>
              {isVoid ? "Void" : inv.balance_cents > 0 ? "Balance due" : "Paid in full"}
            </p>
            <p className={`num text-5xl font-bold ${inv.balance_cents > 0 && !isVoid ? "text-safety" : ""}`}>
              {money(isVoid || inv.balance_cents > 0 ? (isVoid ? 0 : inv.balance_cents) : inv.amount_paid_cents)}
            </p>
            <p className={inv.balance_cents > 0 && !isVoid ? "text-white/75" : "text-steel-2"}>
              {inv.balance_cents > 0 && !isVoid
                ? `of ${money(inv.total_cents)}${inv.due_date ? `, due ${date(inv.due_date)}` : ""}`
                : isVoid
                  ? `Was ${money(inv.total_cents)}`
                  : inv.paid_at ? `Paid ${date(inv.paid_at)}` : ""}
            </p>
          </div>
          {!isVoid && inv.balance_cents > 0 && (
            <Button variant="primary" className="min-w-44 text-lg" onClick={() => setModal("pay")}>
              Record payment
            </Button>
          )}
        </div>
      </section>

      <Sheet title="Details">
        <Dl
          rows={[
            ["Invoice date", date(inv.issue_date)],
            ["Due", date(inv.due_date)],
            ["Mileage", inv.mileage !== null ? `${inv.mileage.toLocaleString()} mi` : null],
            ["VIN", inv.party.vin],
            ["Given to customer", dateTime(inv.sent_at)],
            ["Work order", inv.work_order_id && <Link className="underline" to={`/admin/work-orders/${inv.work_order_id}`}>Open work order</Link>],
          ]}
        />
        <div className="flex flex-wrap gap-2 border-t border-line p-4">
          {!isVoid && (
            <SendButton
              path={`/invoices/${id}/send`}
              label={inv.sent_at ? "Send the invoice again" : "Send to customer"}
              noun="invoice"
              email={inv.party.customer_email}
              phone={inv.party.customer_phone}
              variant={inv.sent_at ? "secondary" : "primary"}
              disabled={!inv.items.length}
            />
          )}
          {!isVoid && !inv.sent_at && (
            <Button variant="quiet" onClick={() => markSent.mutate()} busy={markSent.isPending} disabled={!inv.items.length}>
              Mark as handed over
            </Button>
          )}
          <a href={`/api/invoices/${id}/pdf`} target="_blank" rel="noopener" className="inline-flex min-h-12 items-center rounded-md px-4 font-medium hover:bg-black/5">
            Print or download PDF
          </a>
          {!isVoid && <Button onClick={() => setModal("edit")}>Edit dates and notes</Button>}
          {!isVoid && !hasPayments && <Button variant="danger" onClick={() => setModal("void")}>Void invoice</Button>}
        </div>
        <div className="px-4 pb-2"><ErrorNote error={markSent.error} /></div>
        <p className="border-t border-line px-4 py-3 text-[15px] text-steel-2">
          Online card payments arrive in the next phase. Until then, record cash, check, and card-terminal payments here.
        </p>
      </Sheet>

      <LineItems basePath={`/invoices/${id}`} items={inv.items} totals={inv} readOnly={isVoid || hasPayments} lockedReason={lockedReason} />

      <Sheet title="Payments">
        {inv.payments.length === 0 ? (
          <p className="px-4 py-4 text-steel-2">No payments recorded.</p>
        ) : (
          <ul>
            {inv.payments.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-0">
                <div className="min-w-0 flex-1">
                  <p className={`font-semibold ${p.status === "void" ? "line-through text-steel-2" : ""}`}>
                    {METHOD_LABEL[p.method]} {p.reference && <span className="font-normal text-steel-2">({p.reference})</span>}
                  </p>
                  <p className="text-[15px] text-steel-2">
                    {dateTime(p.paid_at)}
                    {p.status === "void" && `. Voided: ${p.void_reason}`}
                  </p>
                </div>
                <p className={`num text-lg ${p.status === "void" ? "line-through text-steel-2" : ""}`}>{money(p.amount_cents)}</p>
                {p.status === "succeeded" && (
                  <div className="flex w-full flex-wrap gap-1 sm:w-auto">
                    <a href={`/api/payments/${p.id}/receipt`} target="_blank" rel="noopener" className="inline-flex min-h-12 items-center rounded-md px-3 font-medium hover:bg-black/5">
                      Receipt
                    </a>
                    {inv.party.customer_email && <EmailReceipt paymentId={p.id} />}
                    {!p.provider_ref && <Button variant="quiet" onClick={() => setModal({ voidPayment: p })}>Void</Button>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Sheet>

      <DocumentTrail entityType="invoice" entityId={id} />

      {(inv.customer_notes || inv.internal_notes) && (
        <Sheet title="Notes">
          <div className="space-y-3 p-4">
            {inv.customer_notes && (
              <div className="border-l-4 border-go px-3 py-1">
                <p className="text-[14px] font-semibold text-go">Customer-facing note (prints on the invoice)</p>
                <p className="whitespace-pre-wrap">{inv.customer_notes}</p>
              </div>
            )}
            <InternalNote>{inv.internal_notes}</InternalNote>
          </div>
        </Sheet>
      )}

      {modal === "pay" && <PaymentModal inv={inv} onClose={() => setModal(null)} />}
      {modal === "void" && (
        <ReasonModal title="Void invoice" action="Void invoice" path={`/invoices/${id}/void`} onClose={() => setModal(null)}
          help="The invoice keeps its number and stays in your records, marked void." />
      )}
      {modal === "edit" && <EditInvoice inv={inv} onClose={() => setModal(null)} />}
      {modal && typeof modal === "object" && (
        <ReasonModal title={`Void ${money(modal.voidPayment.amount_cents)} payment`} action="Void payment"
          path={`/payments/${modal.voidPayment.id}/void`} onClose={() => setModal(null)}
          help="Use this for a payment entered by mistake. The amount goes back onto the balance." />
      )}
    </div>
  );
}

function EmailReceipt({ paymentId }: { paymentId: number }) {
  const send = useMutation({ mutationFn: () => api.post<{ email: EmailResult }>(`/payments/${paymentId}/email-receipt`) });
  if (send.data) return <span role="status" className="min-h-12 content-center px-3 text-[15px] text-steel-2">{send.data.email.message}</span>;
  return <Button variant="quiet" busy={send.isPending} onClick={() => send.mutate()}>Email receipt</Button>;
}

function PaymentModal({ inv, onClose }: { inv: Invoice; onClose: () => void }) {
  const [amount, setAmount] = useState(centsToInput(inv.balance_cents));
  const [method, setMethod] = useState<"cash" | "check" | "card" | "other">("cash");
  const [reference, setReference] = useState("");
  const [when, setWhen] = useState(localDateInput(new Date()));
  const [localError, setLocalError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (cents: number) => {
      const today = localDateInput(new Date());
      return api.post(`/invoices/${inv.id}/payments`, {
        amount_cents: cents,
        method,
        reference: reference || null,
        // Today: let the server stamp the exact time. Backdated: noon local on that day.
        paid_at: when === today ? null : new Date(`${when}T12:00:00`).toISOString(),
      });
    },
    onSuccess: onClose,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const cents = toCents(amount);
    if (!cents) return setLocalError("Enter the amount received, like 125.00.");
    if (cents > inv.balance_cents) return setLocalError(`That's more than the ${money(inv.balance_cents)} balance.`);
    setLocalError(null);
    save.mutate(cents);
  };
  return (
    <Modal title="Record payment" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <ErrorNote error={localError ?? save.error} />
        <Field label="Amount received" hint={`Balance is ${money(inv.balance_cents)}. Enter less for a partial payment.`}>
          {(p) => <input {...p} className="field num text-3xl" inputMode="decimal" autoFocus value={amount} onChange={(e) => setAmount(e.target.value)} />}
        </Field>
        <fieldset>
          <legend className="mb-1 text-[15px] font-medium text-steel-2">Paid by</legend>
          <div className="grid grid-cols-4 gap-2">
            {(["cash", "check", "card", "other"] as const).map((m) => (
              <label key={m} className={`flex min-h-14 cursor-pointer items-center justify-center rounded-md border font-medium ${method === m ? "border-steel bg-steel text-white" : "border-line"}`}>
                <input type="radio" name="method" className="sr-only" checked={method === m} onChange={() => setMethod(m)} />
                {sentence(m)}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label={method === "check" ? "Check number" : method === "card" ? "Card reference" : "Reference"}>
          {(p) => <input {...p} className="field" value={reference} onChange={(e) => setReference(e.target.value)} />}
        </Field>
        <Field label="Date received">
          {(p) => <input {...p} type="date" className="field" value={when} max={localDateInput(new Date())} onChange={(e) => setWhen(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" className="w-full text-lg" busy={save.isPending}>
          Record {toCents(amount) ? money(toCents(amount)) : "payment"}
        </Button>
      </form>
    </Modal>
  );
}

function ReasonModal({ title, action, path, help, onClose }: { title: string; action: string; path: string; help: string; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const save = useMutation({ mutationFn: () => api.post(path, { reason }), onSuccess: onClose });
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <p>{help}</p>
        <ErrorNote error={save.error} />
        <Field label="Reason" hint="Kept in the record.">
          {(p) => <input {...p} className="field" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <Button type="submit" variant="danger" className="w-full" busy={save.isPending}>{action}</Button>
      </form>
    </Modal>
  );
}

function EditInvoice({ inv, onClose }: { inv: Invoice; onClose: () => void }) {
  const [due, setDue] = useState(inv.due_date ?? "");
  const [customerNotes, setCustomerNotes] = useState(inv.customer_notes ?? "");
  const [internal, setInternal] = useState(inv.internal_notes ?? "");
  const save = useMutation({
    mutationFn: () => api.patch(`/invoices/${inv.id}`, { due_date: due || null, customer_notes: customerNotes, internal_notes: internal }),
    onSuccess: onClose,
  });
  return (
    <Modal title="Edit invoice" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error} />
        <Field label="Due date">
          {(p) => <input {...p} type="date" className="field" min={inv.issue_date} value={due} onChange={(e) => setDue(e.target.value)} />}
        </Field>
        <Field label="Customer-facing note" hint="Prints on the invoice.">
          {(p) => <textarea {...p} className="field min-h-20" value={customerNotes} onChange={(e) => setCustomerNotes(e.target.value)} />}
        </Field>
        <Field label="Internal note" hint="Only you see this.">
          {(p) => <textarea {...p} className="field min-h-20" value={internal} onChange={(e) => setInternal(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" className="w-full" busy={save.isPending}>Save changes</Button>
      </form>
    </Modal>
  );
}
