import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api } from "../lib/api";
import { centsToInput, money, toCents } from "../lib/format";
import type { LineItem, LineItemIn, LineKind, Part, Totals } from "../lib/types";
import { Button, ErrorNote, Field, Modal, Sheet } from "./ui";

const KIND_LABEL: Record<LineKind, string> = {
  labor: "Labor",
  part: "Part",
  fee: "Fee",
  discount: "Discount",
};

function toInput(li: LineItem): LineItemIn {
  return {
    kind: li.kind,
    description: li.description,
    quantity: li.quantity,
    unit_price_cents: li.unit_price_cents,
    unit_cost_cents: li.unit_cost_cents,
    markup_pct: li.markup_pct,
    taxable: li.taxable,
    part_number: li.part_number,
    vendor_name: li.vendor_name,
    warranty_months: li.warranty_months,
    warranty_miles: li.warranty_miles,
    warranty_notes: li.warranty_notes,
    part_id: li.part_id,
  };
}

function qtyLabel(li: LineItem) {
  const q = Number(li.quantity);
  if (li.kind === "labor") return `${q} h × ${money(li.unit_price_cents)}`;
  if (q !== 1) return `${q} × ${money(li.unit_price_cents)}`;
  return null;
}

/**
 * Lines and totals for a work order, estimate, or invoice. `basePath` is the document's API
 * path, e.g. "/work-orders/12"; lines are added with POST, removed with DELETE, and edited by
 * replacing the full list with PUT so totals are always recomputed server-side.
 */
export function LineItems({
  basePath,
  items,
  totals,
  readOnly,
  lockedReason,
  showCost = true,
}: {
  basePath: string;
  items: LineItem[];
  totals: Totals;
  readOnly?: boolean;
  lockedReason?: string;
  showCost?: boolean;
}) {
  const [editing, setEditing] = useState<{ index: number | null; kind: LineKind } | null>(null);
  const [picking, setPicking] = useState(false);

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`${basePath}/items/${id}`),
  });

  return (
    <Sheet title="Parts and labor">
      {items.length === 0 ? (
        <p className="px-4 py-6 text-steel-2">
          {readOnly ? "No lines." : "Nothing added yet. Add the labor and parts for this job."}
        </p>
      ) : (
        <ul>
          {items.map((li, i) => (
            <li key={li.id} className="flex items-start gap-3 border-b border-line px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  <span className="mr-2 text-[14px] font-semibold text-steel-2">{KIND_LABEL[li.kind]}</span>
                  {li.description}
                </p>
                <p className="text-[15px] text-steel-2">
                  {[
                    qtyLabel(li),
                    li.part_number && `#${li.part_number}`,
                    li.vendor_name,
                    showCost && li.unit_cost_cents !== null && `cost ${money(li.unit_cost_cents)}`,
                    li.warranty_months && `${li.warranty_months} mo warranty`,
                    li.taxable ? "taxed" : null,
                  ]
                    .filter(Boolean)
                    .join(", ")}
                </p>
              </div>
              <p className={`num text-lg ${li.kind === "discount" ? "text-go" : ""}`}>
                {li.kind === "discount" ? "−" : ""}
                {money(li.line_total_cents)}
              </p>
              {!readOnly && (
                <Button variant="quiet" className="-my-2 px-3" onClick={() => setEditing({ index: i, kind: li.kind })}>
                  Edit
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {!readOnly && (
        <div className="grid grid-cols-2 gap-2 border-b border-line p-3 sm:grid-cols-5">
          <Button className="col-span-2 sm:col-span-1" onClick={() => setPicking(true)}>From parts list</Button>
          {(["labor", "part", "fee", "discount"] as LineKind[]).map((k) => (
            <Button key={k} onClick={() => setEditing({ index: null, kind: k })}>
              Add {KIND_LABEL[k].toLowerCase()}
            </Button>
          ))}
        </div>
      )}
      {readOnly && lockedReason && <p className="border-b border-line bg-concrete px-4 py-2 text-[15px] text-steel-2">{lockedReason}</p>}
      <ErrorNote error={remove.error} />

      <TotalsTable totals={totals} />

      {picking && <PartPicker basePath={basePath} onClose={() => setPicking(false)} />}
      {editing && (
        <LineEditor
          basePath={basePath}
          items={items}
          index={editing.index}
          kind={editing.kind}
          onClose={() => setEditing(null)}
          onDelete={
            editing.index !== null
              ? async () => {
                  await remove.mutateAsync(items[editing.index!].id);
                  setEditing(null);
                }
              : undefined
          }
        />
      )}
    </Sheet>
  );
}

/** Pick a part from the parts list: fills the line with its price, number, vendor, and
 * warranty, and links it so stock comes out when the work order is completed. */
function PartPicker({ basePath, onClose }: { basePath: string; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [chosen, setChosen] = useState<Part | null>(null);
  const [qty, setQty] = useState("1");
  const parts = useQuery({
    queryKey: ["parts", q],
    queryFn: () => api.get<Part[]>("/parts", { q: q.trim() || undefined, limit: 50 }),
  });
  const add = useMutation({
    mutationFn: (p: Part) =>
      api.post(`${basePath}/items`, {
        kind: "part",
        description: p.name,
        quantity: String(Number(qty) || 1),
        // No set price: send the cost so the shop's markup applies, as on the parts list.
        unit_price_cents: p.price_from_markup ? null : p.price_cents,
        unit_cost_cents: p.cost_cents,
        part_number: p.part_number,
        vendor_name: p.vendor_name,
        warranty_months: p.warranty_months,
        warranty_miles: p.warranty_miles,
        warranty_notes: p.warranty_notes,
        part_id: p.id,
      } satisfies LineItemIn),
    onSuccess: onClose,
  });
  return (
    <Modal title="Add from parts list" onClose={onClose}>
      {chosen ? (
        <form onSubmit={(e) => { e.preventDefault(); add.mutate(chosen); }} className="space-y-4">
          <p className="text-lg font-semibold">{chosen.name}</p>
          <p className="text-steel-2">
            {[chosen.part_number && `#${chosen.part_number}`, money(chosen.effective_price_cents) + " each", chosen.quantity !== null && `${Number(chosen.quantity)} in stock`].filter(Boolean).join(", ")}
          </p>
          <Field label="Quantity">{(p) => <input {...p} className="field num" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} />}</Field>
          {chosen.quantity !== null && (
            <p className="text-[15px] text-steel-2">Comes out of stock when this work order is completed (not for estimates or invoices).</p>
          )}
          <ErrorNote error={add.error} />
          <div className="flex gap-2">
            <Button type="submit" variant="primary" busy={add.isPending}>Add to this job</Button>
            <Button type="button" variant="quiet" onClick={() => setChosen(null)}>Pick another</Button>
          </div>
        </form>
      ) : (
        <div className="space-y-3">
          <Field label="Search parts">
            {(p) => <input {...p} className="field" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, part number, or category" />}
          </Field>
          <ErrorNote error={parts.error} />
          <ul className="max-h-[50dvh] overflow-y-auto">
            {(parts.data ?? []).map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => setChosen(p)}
                  className="flex min-h-14 w-full items-center gap-3 border-b border-line px-1 py-2 text-left hover:bg-concrete/60">
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{p.name}</span>
                    <span className="block text-[15px] text-steel-2">{[p.part_number && `#${p.part_number}`, p.vendor_name].filter(Boolean).join(", ")}</span>
                  </span>
                  <span className="text-right">
                    <span className="num block">{money(p.effective_price_cents)}</span>
                    {p.quantity !== null && <span className={`block text-[14px] ${p.low_stock ? "font-semibold text-signal" : "text-steel-2"}`}>{Number(p.quantity)} in stock</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {parts.data?.length === 0 && <p className="text-steel-2">No parts match. Add parts on the Parts page, or use “Add part” to type one in.</p>}
        </div>
      )}
    </Modal>
  );
}

export function TotalsTable({ totals }: { totals: Totals }) {
  const rows: [string, number, boolean?][] = [
    ["Labor", totals.labor_cents],
    ["Parts", totals.parts_cents],
  ];
  if (totals.fees_cents) rows.push(["Fees", totals.fees_cents]);
  if (totals.discount_cents) rows.push(["Discounts", -totals.discount_cents]);
  rows.push([`Tax (${Number(totals.tax_rate)}% on ${money(totals.taxable_cents)})`, totals.tax_cents]);
  return (
    <table className="w-full">
      <tbody>
        {rows.map(([label, cents]) => (
          <tr key={label}>
            <th scope="row" className="px-4 py-1 text-left font-normal text-steel-2">{label}</th>
            <td className="num px-4 py-1 text-right text-lg">{money(cents)}</td>
          </tr>
        ))}
        <tr className="border-t-2 border-steel">
          <th scope="row" className="px-4 py-3 text-left font-display text-xl font-bold">Total</th>
          <td className="num px-4 py-3 text-right text-2xl font-bold">{money(totals.total_cents)}</td>
        </tr>
      </tbody>
    </table>
  );
}

function LineEditor({
  basePath,
  items,
  index,
  kind: initialKind,
  onClose,
  onDelete,
}: {
  basePath: string;
  items: LineItem[];
  index: number | null;
  kind: LineKind;
  onClose: () => void;
  onDelete?: () => Promise<void>;
}) {
  const existing = index !== null ? items[index] : null;
  const [kind] = useState<LineKind>(existing?.kind ?? initialKind);
  const [description, setDescription] = useState(existing?.description ?? "");
  const [quantity, setQuantity] = useState(existing ? String(Number(existing.quantity)) : "1");
  const [price, setPrice] = useState(existing ? centsToInput(existing.unit_price_cents) : "");
  const [cost, setCost] = useState(centsToInput(existing?.unit_cost_cents));
  const [markup, setMarkup] = useState(existing?.markup_pct ? String(Number(existing.markup_pct)) : "");
  const [taxable, setTaxable] = useState<"default" | "yes" | "no">(
    existing ? (existing.taxable ? "yes" : "no") : "default",
  );
  const [partNumber, setPartNumber] = useState(existing?.part_number ?? "");
  const [vendor, setVendor] = useState(existing?.vendor_name ?? "");
  const [warrantyMonths, setWarrantyMonths] = useState(existing?.warranty_months?.toString() ?? "");
  const [warrantyMiles, setWarrantyMiles] = useState(existing?.warranty_miles?.toString() ?? "");
  const [localError, setLocalError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (line: LineItemIn) => {
      if (index === null) return api.post(`${basePath}/items`, line);
      const all = items.map(toInput);
      all[index] = line;
      return api.put(`${basePath}/items`, all);
    },
    onSuccess: onClose,
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    const priceCents = toCents(price);
    const costCents = toCents(cost);
    if (price && priceCents === null) return setLocalError("Enter the price as dollars and cents, like 89.99.");
    if (cost && costCents === null) return setLocalError("Enter the cost as dollars and cents, like 54.00.");
    if ((kind === "fee" || kind === "discount") && priceCents === null)
      return setLocalError("Enter an amount.");
    if (kind === "part" && priceCents === null && costCents === null)
      return setLocalError("Enter a price, or a cost so the markup can be applied.");
    const qty = Number(quantity);
    if (!(qty > 0)) return setLocalError(kind === "labor" ? "Enter the hours, like 1.5." : "Enter a quantity above zero.");

    save.mutate({
      kind,
      description: description.trim(),
      quantity: String(qty),
      unit_price_cents: priceCents,
      unit_cost_cents: kind === "part" ? costCents : null,
      markup_pct: kind === "part" && markup ? markup : null,
      taxable: taxable === "default" ? null : taxable === "yes",
      part_number: kind === "part" ? partNumber || null : null,
      vendor_name: kind === "part" ? vendor || null : null,
      warranty_months: warrantyMonths ? Number(warrantyMonths) : null,
      warranty_miles: warrantyMiles ? Number(warrantyMiles) : null,
    });
  };

  const title = `${existing ? "Edit" : "Add"} ${KIND_LABEL[kind].toLowerCase()}`;
  const amountLabel =
    kind === "labor" ? "Rate per hour" : kind === "part" ? "Price to customer (each)" : "Amount";

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <ErrorNote error={localError ?? save.error} />
        <Field label="Description">
          {(p) => (
            <input {...p} className="field" required autoFocus value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={kind === "labor" ? "Replace front brake pads" : kind === "part" ? "Brake pad set" : ""} />
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          {(kind === "labor" || kind === "part") && (
            <Field label={kind === "labor" ? "Hours" : "Quantity"}>
              {(p) => (
                <input {...p} className="field num text-lg" inputMode="decimal" value={quantity}
                  onChange={(e) => setQuantity(e.target.value)} />
              )}
            </Field>
          )}
          <Field label={amountLabel} hint={kind === "labor" && !price ? "Blank uses your shop rate" : undefined}>
            {(p) => (
              <input {...p} className="field num text-lg" inputMode="decimal" value={price} placeholder="0.00"
                onChange={(e) => setPrice(e.target.value)} />
            )}
          </Field>
        </div>
        {kind === "part" && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Your cost (each)" hint="Never shown to customers">
                {(p) => (
                  <input {...p} className="field num text-lg" inputMode="decimal" value={cost} placeholder="0.00"
                    onChange={(e) => setCost(e.target.value)} />
                )}
              </Field>
              <Field label="Markup %" hint={!price ? "Used when price is blank" : undefined}>
                {(p) => (
                  <input {...p} className="field num text-lg" inputMode="decimal" value={markup}
                    placeholder="Shop default" onChange={(e) => setMarkup(e.target.value)} />
                )}
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Part number">
                {(p) => <input {...p} className="field" value={partNumber} onChange={(e) => setPartNumber(e.target.value)} />}
              </Field>
              <Field label="Vendor">
                {(p) => <input {...p} className="field" value={vendor} onChange={(e) => setVendor(e.target.value)} />}
              </Field>
            </div>
          </>
        )}
        {(kind === "part" || kind === "labor") && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Warranty months">
              {(p) => (
                <input {...p} className="field" inputMode="numeric" value={warrantyMonths}
                  onChange={(e) => setWarrantyMonths(e.target.value.replace(/\D/g, ""))} />
              )}
            </Field>
            <Field label="Warranty miles">
              {(p) => (
                <input {...p} className="field" inputMode="numeric" value={warrantyMiles}
                  onChange={(e) => setWarrantyMiles(e.target.value.replace(/\D/g, ""))} />
              )}
            </Field>
          </div>
        )}
        <Field label="Sales tax">
          {(p) => (
            <select {...p} className="field" value={taxable} onChange={(e) => setTaxable(e.target.value as typeof taxable)}>
              <option value="default">Use shop setting</option>
              <option value="yes">Taxable</option>
              <option value="no">Not taxable</option>
            </select>
          )}
        </Field>
        <div className="flex flex-wrap gap-2 pt-2">
          <Button type="submit" variant="primary" busy={save.isPending} className="flex-1">
            {existing ? "Save line" : title}
          </Button>
          {onDelete && (
            <Button type="button" variant="danger" onClick={() => void onDelete()}>
              Remove
            </Button>
          )}
        </div>
      </form>
    </Modal>
  );
}
