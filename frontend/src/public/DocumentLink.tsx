import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { TotalsTable } from "../components/LineItems";
import { Button, ErrorNote, Field } from "../components/ui";
import { ApiError, api } from "../lib/api";
import { date, dateTime, money, phoneHref } from "../lib/format";
import { SignaturePad, type SignaturePadHandle } from "./SignaturePad";

type Item = {
  kind: string; kind_label: string; description: string; quantity: string; unit_price_cents: number;
  line_total_cents: number; part_number: string | null; warranty: string | null;
};
type Doc = {
  doc_type: "estimate" | "work_order" | "invoice";
  title: string; number: string; version: number | null; date: string; expires_on?: string; due_date?: string;
  business: { name: string; phone: string | null; email: string | null; address: string[] };
  customer: { name: string };
  vehicle: { description: string; vin: string | null; plate: string | null; mileage: number | null };
  concern: string | null; notes: string | null; items: Item[];
  totals: { tax_rate: string; labor_cents: number; parts_cents: number; fees_cents: number; discount_cents: number; taxable_cents: number; tax_cents: number; total_cents: number };
  authorization_statement?: string; terms?: string | null; footer?: string | null;
  amount_paid_cents?: number; balance_cents?: number;
  payments?: { date: string; method: string; amount_cents: number; reference: string | null }[];
};
type View = {
  purpose: "estimate" | "work_order" | "invoice";
  shop: { name: string; phone: string | null; email: string | null };
  document: Doc;
  state: {
    can_respond?: boolean; decision?: string | null; signed_at?: string | null; signer_name?: string | null;
    allow_typed_signature?: boolean; authorization_statement?: string; status?: string; balance_cents?: number;
  };
  receipts?: { id: number; amount_cents: number; paid_at: string }[];
};

/** The page a customer opens from a text or email: review, then approve or pay. */
export function DocumentLink() {
  const { token } = useParams();
  const { data, error, isLoading } = useQuery({
    queryKey: ["link", token],
    queryFn: () => api.get<View>(`/public/links/${token}`),
    retry: false,
  });

  if (isLoading) return <p className="p-10 text-center text-steel-2">Loading your document…</p>;
  if (error || !data) {
    const gone = error instanceof ApiError && (error.status === 410 || error.status === 404);
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <h1 className="font-display text-4xl font-bold">{gone ? "This link no longer works" : "Couldn't open this document"}</h1>
        <p className="mt-3 text-lg">{error instanceof ApiError ? error.message : "Check your connection and try again."}</p>
      </div>
    );
  }

  const d = data.document;
  const pdf = `/api/public/links/${token}/pdf`;
  return (
    <div className="min-h-dvh bg-concrete pb-16">
      <header className="bg-steel text-white">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-2 px-4 py-4">
          <p className="font-display text-2xl font-bold">{data.shop.name}</p>
          {data.shop.phone && (
            <a href={phoneHref(data.shop.phone)} className="min-h-12 content-center font-semibold text-safety">
              Call {data.shop.phone}
            </a>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-3xl space-y-4 px-4 pt-5">
        <div>
          <p className="text-steel-2">For {d.customer.name}</p>
          <h1 className="font-display text-4xl leading-tight font-bold">{d.title}</h1>
          <p className="num text-lg">
            {d.number}{d.version && d.version > 1 ? ` (version ${d.version})` : ""}
            <span className="ml-2 font-sans text-base text-steel-2">
              {d.doc_type === "invoice" ? `dated ${date(d.date)}` : d.expires_on ? `valid until ${date(d.expires_on)}` : date(d.date)}
            </span>
          </p>
        </div>

        {data.purpose === "invoice" ? <InvoiceSummary data={data} token={token!} /> : <DecisionStatus data={data} pdf={pdf} />}

        <section className="rounded-lg border border-line bg-sheet">
          <div className="border-b border-line px-4 py-3">
            <p className="text-[15px] text-steel-2">Vehicle</p>
            <p className="text-lg font-semibold">{d.vehicle.description}</p>
            <p className="text-[15px] text-steel-2">
              {[d.vehicle.plate, d.vehicle.vin && `VIN ${d.vehicle.vin}`, d.vehicle.mileage !== null && `${d.vehicle.mileage.toLocaleString()} mi`].filter(Boolean).join(", ")}
            </p>
          </div>
          {d.concern && <p className="border-b border-line px-4 py-3">You told us: “{d.concern}”</p>}
          <ul>
            {d.items.map((li, i) => (
              <li key={i} className="flex items-start gap-3 border-b border-line px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p><span className="mr-2 text-[14px] font-semibold text-steel-2">{li.kind_label}</span>{li.description}</p>
                  <p className="text-[15px] text-steel-2">
                    {[
                      li.kind === "labor" ? `${Number(li.quantity)} h at ${money(li.unit_price_cents)}/h` : Number(li.quantity) !== 1 ? `${Number(li.quantity)} × ${money(li.unit_price_cents)}` : null,
                      li.warranty && `Warranty ${li.warranty}`,
                    ].filter(Boolean).join(", ")}
                  </p>
                </div>
                <p className="num text-lg">{li.kind === "discount" ? "−" : ""}{money(li.line_total_cents)}</p>
              </li>
            ))}
          </ul>
          <TotalsTable totals={d.totals} />
        </section>

        {d.notes && (
          <section className="rounded-lg border border-line bg-sheet px-4 py-3">
            <p className="text-[15px] text-steel-2">Notes from the shop</p>
            <p className="whitespace-pre-wrap">{d.notes}</p>
          </section>
        )}

        {data.purpose !== "invoice" && data.state.can_respond && <Respond data={data} token={token!} />}
        {data.purpose !== "invoice" && <Question token={token!} />}

        <a href={pdf} target="_blank" rel="noopener" className="inline-flex min-h-12 items-center rounded-md border border-steel bg-sheet px-5 font-semibold">
          Download PDF
        </a>
        {d.terms && <p className="text-[15px] whitespace-pre-wrap text-steel-2">{d.terms}</p>}
      </div>
    </div>
  );
}

function DecisionStatus({ data, pdf }: { data: View; pdf: string }) {
  const s = data.state;
  if (s.decision === "approved") {
    return (
      <div role="status" className="rounded-lg border-l-[6px] border-go bg-go-wash px-4 py-3">
        <p className="font-display text-2xl font-semibold text-go">Approved</p>
        <p>Signed by {s.signer_name} on {dateTime(s.signed_at)}. Thank you.</p>
        <a href={pdf} target="_blank" rel="noopener" className="mt-1 inline-block min-h-11 content-center font-semibold underline underline-offset-4">Your signed copy</a>
      </div>
    );
  }
  if (s.decision === "declined") {
    return (
      <div role="status" className="rounded-lg border-l-[6px] border-steel bg-sheet px-4 py-3">
        <p className="font-display text-2xl font-semibold">Declined</p>
        <p>You declined this on {dateTime(s.signed_at)}. Call the shop if you change your mind.</p>
      </div>
    );
  }
  if (!s.can_respond) {
    return (
      <div className="rounded-lg border-l-[6px] border-hold bg-hold-wash px-4 py-3">
        This document has changed or is closed. Contact the shop for the latest version.
      </div>
    );
  }
  return (
    <div className="rounded-lg bg-steel px-4 py-4 text-white">
      <p className="text-white/80">Estimated total</p>
      <p className="num text-5xl font-bold text-safety">{money(data.document.totals.total_cents)}</p>
      <p className="mt-1 text-white/80">Review the work below, then approve or decline at the bottom.</p>
    </div>
  );
}

function InvoiceSummary({ data, token }: { data: View; token: string }) {
  const bal = data.state.balance_cents ?? 0;
  return (
    <div className={`rounded-lg px-4 py-4 ${bal > 0 ? "bg-steel text-white" : "border-l-[6px] border-go bg-go-wash"}`}>
      <p className={bal > 0 ? "text-white/80" : "text-go"}>{bal > 0 ? "Balance due" : "Paid in full"}</p>
      <p className={`num text-5xl font-bold ${bal > 0 ? "text-safety" : "text-go"}`}>{money(bal > 0 ? bal : data.document.totals.total_cents)}</p>
      {bal > 0 && data.document.due_date && <p className="text-white/80">Due {date(data.document.due_date)}</p>}
      {bal > 0 && data.shop.phone && (
        <p className="mt-2 text-white/90">
          To pay, call <a className="font-semibold underline" href={phoneHref(data.shop.phone)}>{data.shop.phone}</a> or pay at the shop.
        </p>
      )}
      {(data.receipts?.length ?? 0) > 0 && (
        <ul className="mt-3 space-y-1">
          {data.receipts!.map((r) => (
            <li key={r.id}>
              <a href={`/api/public/links/${token}/receipts/${r.id}`} target="_blank" rel="noopener"
                className={`inline-block min-h-10 content-center underline underline-offset-4 ${bal > 0 ? "text-white" : ""}`}>
                Receipt: {money(r.amount_cents)} on {date(r.paid_at)}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Respond({ data, token }: { data: View; token: string }) {
  const qc = useQueryClient();
  const pad = useRef<SignaturePadHandle>(null);
  const [name, setName] = useState(data.document.customer.name);
  const [agree, setAgree] = useState(false);
  const [typed, setTyped] = useState(false);
  const [typedName, setTypedName] = useState("");
  const [declining, setDeclining] = useState(false);
  const [note, setNote] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const allowTyped = data.state.allow_typed_signature;

  const send = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/public/links/${token}/respond`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["link", token] }),
  });

  const approve = (e: FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (!agree) return setLocalError("Check the box to confirm you authorize the work.");
    const image = typed ? null : pad.current?.toDataUrl();
    if (!typed && !image) return setLocalError("Sign in the box with your finger or mouse.");
    if (typed && typedName.trim().length < 2) return setLocalError("Type your full name to sign.");
    send.mutate({ decision: "approved", signer_name: name, agree, signature_image: image, typed_signature: typed ? typedName : null });
  };

  if (declining) {
    return (
      <form onSubmit={(e) => { e.preventDefault(); send.mutate({ decision: "declined", signer_name: name, note }); }}
        className="space-y-4 rounded-lg border border-line bg-sheet p-4">
        <h2 className="font-display text-2xl font-semibold">Decline this {data.purpose === "estimate" ? "estimate" : "work"}</h2>
        <ErrorNote error={send.error} />
        <Field label="Your name">{(p) => <input {...p} className="field" required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Reason (optional)" hint="Helps the shop suggest another option.">
          {(p) => <textarea {...p} className="field min-h-20" value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="danger" busy={send.isPending}>Decline</Button>
          <Button type="button" variant="quiet" onClick={() => setDeclining(false)}>Go back</Button>
        </div>
      </form>
    );
  }

  return (
    <form onSubmit={approve} className="space-y-4 rounded-lg border-2 border-steel bg-sheet p-4">
      <h2 className="font-display text-3xl font-bold">Approve and sign</h2>
      <ErrorNote error={localError ?? send.error} />
      <label className="flex items-start gap-3 rounded-md bg-concrete p-3">
        <input type="checkbox" className="mt-1 h-6 w-6 shrink-0" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span className="text-lg">{data.state.authorization_statement}</span>
      </label>
      <Field label="Your full name">
        {(p) => <input {...p} className="field" required autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />}
      </Field>
      {typed ? (
        <Field label="Type your name to sign">
          {(p) => <input {...p} className="field font-display text-2xl" value={typedName} onChange={(e) => setTypedName(e.target.value)} />}
        </Field>
      ) : (
        <SignaturePad ref={pad} label="Signature pad. Draw your signature here." />
      )}
      {allowTyped && (
        <button type="button" className="min-h-11 font-medium underline underline-offset-4" onClick={() => setTyped((t) => !t)}>
          {typed ? "Draw my signature instead" : "Type my name instead"}
        </button>
      )}
      <p className="text-[15px] text-steel-2">
        Your signature, name, the date and time, and this device's IP address are saved with this exact version of the document.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" className="flex-1 text-lg" busy={send.isPending}>
          Approve {money(data.document.totals.total_cents)}
        </Button>
        <Button type="button" variant="quiet" onClick={() => setDeclining(true)}>Decline</Button>
      </div>
    </form>
  );
}

function Question({ token }: { token: string }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const ask = useMutation({ mutationFn: () => api.post(`/public/links/${token}/question`, { message }) });
  if (ask.isSuccess) return <p role="status" className="rounded-lg bg-go-wash px-4 py-3 text-go">Question sent. The shop will get back to you.</p>;
  if (!open) {
    return <Button variant="secondary" onClick={() => setOpen(true)}>Ask the shop a question</Button>;
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); ask.mutate(); }} className="space-y-3 rounded-lg border border-line bg-sheet p-4">
      <ErrorNote error={ask.error} />
      <Field label="Your question">{(p) => <textarea {...p} className="field min-h-24" required autoFocus value={message} onChange={(e) => setMessage(e.target.value)} />}</Field>
      <Button type="submit" busy={ask.isPending}>Send question</Button>
    </form>
  );
}
