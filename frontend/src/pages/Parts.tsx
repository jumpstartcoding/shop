import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Empty, ErrorNote, Field, Loading, Modal, PageHeader, Sheet } from "../components/ui";
import { api, fieldError } from "../lib/api";
import { centsToInput, money, phoneHref, toCents } from "../lib/format";
import type { Part, Vendor } from "../lib/types";

/** Parts list and suppliers. Kept deliberately simple: one stock count per part. */
export function PartsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "vendors" ? "vendors" : "parts";
  return (
    <div className="space-y-4">
      <PageHeader title={tab === "parts" ? "Parts" : "Suppliers"} />
      <div role="tablist" className="flex gap-2">
        {(["parts", "vendors"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t}
            onClick={() => setParams(t === "parts" ? {} : { tab: t })}
            className={`min-h-12 rounded-md border px-4 font-semibold ${tab === t ? "border-steel bg-steel text-white" : "border-line bg-sheet"}`}>
            {t === "parts" ? "Parts" : "Suppliers"}
          </button>
        ))}
      </div>
      {tab === "parts" ? <PartsList /> : <VendorList />}
    </div>
  );
}

function PartsList() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const low = params.get("low") === "1";
  const [editing, setEditing] = useState<Part | "new" | null>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ["parts", q, low],
    queryFn: () => api.get<Part[]>("/parts", { q: q.trim() || undefined, low_stock: low || undefined }),
  });
  return (
    <>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1">
          <Field label="Search">{(p) => <input {...p} className="field" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, part number, category" />}</Field>
        </div>
        <label className="flex min-h-12 items-center gap-2">
          <input type="checkbox" className="h-6 w-6" checked={low} onChange={(e) => setParams(e.target.checked ? { low: "1" } : {})} />
          Low stock only
        </label>
        <Button variant="primary" onClick={() => setEditing("new")}>Add part</Button>
      </div>
      <Sheet>
        {isLoading ? <Loading /> : error ? <ErrorNote error={error} /> : !data?.length ? (
          <Empty>{q || low ? "No parts match." : "No parts yet. Add the ones you stock or order often; they can then be picked onto any job."}</Empty>
        ) : (
          <ul>
            {data.map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => setEditing(p)} className="flex min-h-14 w-full items-center gap-3 border-b border-line px-4 py-3 text-left last:border-0 hover:bg-concrete/60">
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold">{p.name}</span>
                    <span className="block text-[15px] text-steel-2">
                      {[p.part_number && `#${p.part_number}`, p.category, p.vendor_name].filter(Boolean).join(", ")}
                    </span>
                  </span>
                  <span className="text-right">
                    <span className="num block text-lg">{money(p.effective_price_cents)}</span>
                    <span className={`block text-[15px] ${p.low_stock ? "font-semibold text-signal" : "text-steel-2"}`}>
                      {p.quantity === null ? "Not tracked" : `${Number(p.quantity)} in stock${p.low_stock ? ", reorder" : ""}`}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Sheet>
      {editing && <PartModal part={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function PartModal({ part, onClose }: { part: Part | null; onClose: () => void }) {
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => api.get<Vendor[]>("/vendors") });
  const [d, setD] = useState({
    name: part?.name ?? "",
    part_number: part?.part_number ?? "",
    category: part?.category ?? "",
    vendor_id: part?.vendor_id ? String(part.vendor_id) : "",
    cost: centsToInput(part?.cost_cents),
    price: centsToInput(part?.price_cents),
    quantity: part?.quantity !== null && part?.quantity !== undefined ? String(Number(part.quantity)) : "",
    reorder_at: part?.reorder_at !== null && part?.reorder_at !== undefined ? String(Number(part.reorder_at)) : "",
    warranty_months: part?.warranty_months?.toString() ?? "",
    warranty_miles: part?.warranty_miles?.toString() ?? "",
    notes: part?.notes ?? "",
  });
  const [localError, setLocalError] = useState<string | null>(null);
  const [received, setReceived] = useState("");
  const set = (k: keyof typeof d) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value });
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => (part ? api.patch(`/parts/${part.id}`, body) : api.post("/parts", body)),
    onSuccess: onClose,
  });
  const stock = useMutation({
    mutationFn: (change: string) => api.post<Part>(`/parts/${part!.id}/stock`, { change, reason: "Received or counted" }),
    onSuccess: () => setReceived(""),
  });
  const archive = useMutation({ mutationFn: () => api.post(`/parts/${part!.id}/archive`), onSuccess: onClose });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    const cost = d.cost.trim() ? toCents(d.cost) : null;
    const price = d.price.trim() ? toCents(d.price) : null;
    if ((d.cost.trim() && cost === null) || (d.price.trim() && price === null)) return setLocalError("Enter amounts as dollars and cents, like 54.00.");
    if (cost === null && price === null) return setLocalError("Enter a cost, a customer price, or both.");
    save.mutate({
      name: d.name,
      part_number: d.part_number || null,
      category: d.category || null,
      vendor_id: d.vendor_id ? Number(d.vendor_id) : null,
      cost_cents: cost,
      price_cents: price,
      // Stock is changed with "Received / counted" once a part exists, so edits never overwrite a live count.
      ...(part ? {} : { quantity: d.quantity.trim() ? d.quantity : null }),
      reorder_at: d.reorder_at.trim() ? d.reorder_at : null,
      warranty_months: d.warranty_months ? Number(d.warranty_months) : null,
      warranty_miles: d.warranty_miles ? Number(d.warranty_miles) : null,
      notes: d.notes || null,
    });
  };

  return (
    <Modal title={part ? "Edit part" : "Add part"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <ErrorNote error={localError ?? save.error} />
        <Field label="Name" error={fieldError(save.error, "name")}>{(p) => <input {...p} required maxLength={200} className="field" value={d.name} onChange={set("name")} />}</Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Part number">{(p) => <input {...p} maxLength={80} className="field" value={d.part_number} onChange={set("part_number")} />}</Field>
          <Field label="Category">{(p) => <input {...p} maxLength={60} className="field" value={d.category} onChange={set("category")} placeholder="Brakes" />}</Field>
        </div>
        <Field label="Supplier">
          {(p) => (
            <select {...p} className="field" value={d.vendor_id} onChange={set("vendor_id")}>
              <option value="">None</option>
              {vendors.data?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Your cost">{(p) => <input {...p} inputMode="decimal" className="field num" value={d.cost} onChange={set("cost")} />}</Field>
          <Field label="Customer price" hint="Blank: your default markup on cost.">{(p) => <input {...p} inputMode="decimal" className="field num" value={d.price} onChange={set("price")} />}</Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {!part && (
            <Field label="In stock" hint="Blank: don't track stock.">{(p) => <input {...p} inputMode="decimal" className="field num" value={d.quantity} onChange={set("quantity")} />}</Field>
          )}
          <Field label="Reorder at" hint="Warn when stock gets this low.">{(p) => <input {...p} inputMode="decimal" className="field num" value={d.reorder_at} onChange={set("reorder_at")} />}</Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Warranty months">{(p) => <input {...p} inputMode="numeric" className="field num" value={d.warranty_months} onChange={set("warranty_months")} />}</Field>
          <Field label="Warranty miles">{(p) => <input {...p} inputMode="numeric" className="field num" value={d.warranty_miles} onChange={set("warranty_miles")} />}</Field>
        </div>
        <Field label="Notes">{(p) => <textarea {...p} maxLength={2000} className="field min-h-16" value={d.notes} onChange={set("notes")} />}</Field>
        <Button type="submit" variant="primary" className="w-full" busy={save.isPending}>{part ? "Save changes" : "Add part"}</Button>
      </form>
      {part && (
        <div className="mt-5 space-y-3 border-t border-line pt-4">
          <p className="font-semibold">
            Stock: {part.quantity === null ? "not tracked" : `${Number(stock.data?.quantity ?? part.quantity)} on hand`}
          </p>
          <form onSubmit={(e) => { e.preventDefault(); if (received.trim()) stock.mutate(received.trim()); }} className="flex flex-wrap items-end gap-2">
            <div className="w-36">
              <Field label="Received / counted" hint="+6 received, −1 damaged">
                {(p) => <input {...p} inputMode="decimal" className="field num" value={received} onChange={(e) => setReceived(e.target.value)} />}
              </Field>
            </div>
            <div className="pb-7"><Button type="submit" busy={stock.isPending}>Update stock</Button></div>
          </form>
          <ErrorNote error={stock.error ?? archive.error} />
          <p className="text-[15px] text-steel-2">Parts used on a job come out of stock when the work order is completed, and go back if it's reopened.</p>
          <Button variant="quiet" busy={archive.isPending} onClick={() => archive.mutate()}>Remove from parts list</Button>
        </div>
      )}
    </Modal>
  );
}

function VendorList() {
  const [editing, setEditing] = useState<Vendor | "new" | null>(null);
  const { data, error, isLoading } = useQuery({ queryKey: ["vendors"], queryFn: () => api.get<Vendor[]>("/vendors") });
  return (
    <>
      <div className="flex justify-end"><Button variant="primary" onClick={() => setEditing("new")}>Add supplier</Button></div>
      <Sheet>
        {isLoading ? <Loading /> : error ? <ErrorNote error={error} /> : !data?.length ? (
          <Empty>No suppliers yet. Add the parts stores and dealers you order from.</Empty>
        ) : (
          <ul>
            {data.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-0">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{v.name}</p>
                  <p className="text-[15px] text-steel-2">{[v.account_number && `Account ${v.account_number}`, v.email].filter(Boolean).join(", ")}</p>
                  {v.notes && <p className="text-[15px]">{v.notes}</p>}
                </div>
                {v.phone && <a href={phoneHref(v.phone)} className="inline-flex min-h-12 items-center rounded-md border border-line px-4 font-medium">Call</a>}
                {v.website && <a href={v.website.startsWith("http") ? v.website : `https://${v.website}`} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-12 items-center rounded-md border border-line px-4 font-medium">Website</a>}
                <Button variant="quiet" onClick={() => setEditing(v)}>Edit</Button>
              </li>
            ))}
          </ul>
        )}
      </Sheet>
      {editing && <VendorModal vendor={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function VendorModal({ vendor, onClose }: { vendor: Vendor | null; onClose: () => void }) {
  const [d, setD] = useState({
    name: vendor?.name ?? "", phone: vendor?.phone ?? "", email: vendor?.email ?? "",
    website: vendor?.website ?? "", account_number: vendor?.account_number ?? "", notes: vendor?.notes ?? "",
  });
  const set = (k: keyof typeof d) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value });
  const body = Object.fromEntries(Object.entries(d).map(([k, v]) => [k, v.trim() || null]));
  const save = useMutation({
    mutationFn: () => (vendor ? api.patch(`/vendors/${vendor.id}`, body) : api.post("/vendors", body)),
    onSuccess: onClose,
  });
  const archive = useMutation({ mutationFn: () => api.post(`/vendors/${vendor!.id}/archive`), onSuccess: onClose });
  return (
    <Modal title={vendor ? "Edit supplier" : "Add supplier"} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error ?? archive.error} />
        <Field label="Name">{(p) => <input {...p} required maxLength={120} className="field" value={d.name} onChange={set("name")} placeholder="NAPA, O'Reilly, the dealer…" />}</Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Phone">{(p) => <input {...p} type="tel" className="field" value={d.phone} onChange={set("phone")} />}</Field>
          <Field label="Account number">{(p) => <input {...p} maxLength={80} className="field" value={d.account_number} onChange={set("account_number")} />}</Field>
        </div>
        <Field label="Email" error={fieldError(save.error, "email")}>{(p) => <input {...p} type="email" className="field" value={d.email} onChange={set("email")} />}</Field>
        <Field label="Website">{(p) => <input {...p} className="field" value={d.website} onChange={set("website")} />}</Field>
        <Field label="Notes">{(p) => <textarea {...p} maxLength={2000} className="field min-h-16" value={d.notes} onChange={set("notes")} />}</Field>
        <Button type="submit" variant="primary" className="w-full" busy={save.isPending}>Save</Button>
        {vendor && <Button type="button" variant="quiet" busy={archive.isPending} onClick={() => archive.mutate()}>Remove supplier</Button>}
      </form>
    </Modal>
  );
}
