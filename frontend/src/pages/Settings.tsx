import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Button, ErrorNote, Field, Loading, Modal, PageHeader, Sheet } from "../components/ui";
import { api, fieldError } from "../lib/api";
import { centsToInput, money, toCents } from "../lib/format";
import type { Business, Service } from "../lib/types";

const DAYS: [string, string][] = [
  ["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"],
  ["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"],
];

export function SettingsPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Business>("/settings") });
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorNote error={error} />;
  return (
    <div className="space-y-5">
      <PageHeader title="Settings" />
      <BusinessForm business={data} />
      <Services />
      <Password />
    </div>
  );
}

type Draft = Record<string, string | boolean>;

function BusinessForm({ business }: { business: Business }) {
  const [d, setD] = useState<Draft>({});
  const [hours, setHours] = useState(business.hours);
  const [saved, setSaved] = useState(false);
  useEffect(() => setHours(business.hours), [business.hours]);

  const val = (k: keyof Business) => (k in d ? d[k] : (business[k] ?? "")) as string;
  const bool = (k: keyof Business) => (k in d ? d[k] : business[k]) as boolean;
  const text = (k: keyof Business) => ({
    value: val(k),
    onChange: (e: { target: { value: string } }) => { setSaved(false); setD({ ...d, [k]: e.target.value }); },
  });
  const check = (k: keyof Business) => ({
    checked: bool(k),
    onChange: (e: { target: { checked: boolean } }) => { setSaved(false); setD({ ...d, [k]: e.target.checked }); },
  });

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { ...d, hours };
      if ("default_labor_rate_cents" in d) body.default_labor_rate_cents = toCents(String(d.default_labor_rate_cents));
      return api.patch<Business>("/settings", body);
    },
    onSuccess: () => { setD({}); setSaved(true); },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const err = (k: string) => fieldError(save.error, k);

  return (
    <form onSubmit={submit} className="space-y-5">
      <Sheet title="Shop profile">
        <div className="grid gap-4 p-4 sm:grid-cols-2">
          <Field label="Shop name" error={err("name")}>{(p) => <input {...p} className="field" required {...text("name")} />}</Field>
          <Field label="Phone">{(p) => <input {...p} className="field" type="tel" {...text("phone")} />}</Field>
          <Field label="Email" error={err("email")}>{(p) => <input {...p} className="field" type="email" {...text("email")} />}</Field>
          <Field label="Website">{(p) => <input {...p} className="field" {...text("website")} />}</Field>
          <Field label="Street">{(p) => <input {...p} className="field" {...text("address_line1")} />}</Field>
          <div className="grid grid-cols-[2fr_1fr_1fr] gap-2">
            <Field label="City">{(p) => <input {...p} className="field" {...text("city")} />}</Field>
            <Field label="State">{(p) => <input {...p} className="field" {...text("state")} />}</Field>
            <Field label="ZIP">{(p) => <input {...p} className="field" {...text("postal_code")} />}</Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="Service area">{(p) => <textarea {...p} className="field min-h-16" {...text("service_area")} />}</Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="About the shop" hint="Shown on the website's About page.">{(p) => <textarea {...p} className="field min-h-28" {...text("about_text")} />}</Field>
          </div>
          <Field label="Certifications and experience">{(p) => <textarea {...p} className="field min-h-20" {...text("certifications")} />}</Field>
          <Field label="Financing or payment info">{(p) => <textarea {...p} className="field min-h-20" {...text("financing_info")} />}</Field>
          <label className="flex min-h-12 items-center gap-3 sm:col-span-2">
            <input type="checkbox" className="h-6 w-6" {...check("offers_towing")} /> Offer towing or emergency help
          </label>
          {bool("offers_towing") && (
            <div className="sm:col-span-2">
              <Field label="Towing details">{(p) => <textarea {...p} className="field min-h-16" {...text("towing_info")} />}</Field>
            </div>
          )}
        </div>
      </Sheet>

      <Sheet title="Hours">
        <ul>
          {DAYS.map(([key, label]) => {
            const h = hours[key] ?? null;
            return (
              <li key={key} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2 last:border-0">
                <label className="flex min-h-12 w-36 items-center gap-2">
                  <input type="checkbox" className="h-6 w-6" checked={!!h}
                    onChange={(e) => { setSaved(false); setHours({ ...hours, [key]: e.target.checked ? { open: "08:00", close: "17:00" } : null }); }} />
                  {label}
                </label>
                {h ? (
                  <div className="flex items-center gap-2">
                    <input aria-label={`${label} opens`} type="time" className="field w-32" value={h.open}
                      onChange={(e) => { setSaved(false); setHours({ ...hours, [key]: { ...h, open: e.target.value } }); }} />
                    <span>to</span>
                    <input aria-label={`${label} closes`} type="time" className="field w-32" value={h.close}
                      onChange={(e) => { setSaved(false); setHours({ ...hours, [key]: { ...h, close: e.target.value } }); }} />
                  </div>
                ) : (
                  <span className="text-steel-2">Closed</span>
                )}
              </li>
            );
          })}
        </ul>
      </Sheet>

      <Sheet title="Pricing and tax">
        <div className="grid gap-4 p-4 sm:grid-cols-2">
          <Field label="Labor rate per hour" error={err("default_labor_rate_cents")}>
            {(p) => (
              <input {...p} className="field num text-lg" inputMode="decimal"
                value={"default_labor_rate_cents" in d ? String(d.default_labor_rate_cents) : centsToInput(business.default_labor_rate_cents)}
                onChange={(e) => { setSaved(false); setD({ ...d, default_labor_rate_cents: e.target.value }); }} />
            )}
          </Field>
          <Field label="Default parts markup %" error={err("default_parts_markup_pct")}>
            {(p) => <input {...p} className="field num text-lg" inputMode="decimal" {...text("default_parts_markup_pct")} />}
          </Field>
          <Field label="Sales tax rate %" error={err("tax_rate")}>
            {(p) => <input {...p} className="field num text-lg" inputMode="decimal" {...text("tax_rate")} />}
          </Field>
          <fieldset className="space-y-1">
            <legend className="text-[15px] font-medium text-steel-2">Taxed by default</legend>
            <label className="flex min-h-11 items-center gap-3"><input type="checkbox" className="h-6 w-6" {...check("tax_parts")} /> Parts</label>
            <label className="flex min-h-11 items-center gap-3"><input type="checkbox" className="h-6 w-6" {...check("tax_labor")} /> Labor</label>
            <label className="flex min-h-11 items-center gap-3"><input type="checkbox" className="h-6 w-6" {...check("tax_fees")} /> Fees</label>
          </fieldset>
          <p className="rounded-md bg-concrete px-3 py-2 text-[15px] text-steel-2 sm:col-span-2">
            Tax is applied exactly as set here, and each line can be changed. This app doesn't know your state's rules and isn't tax or accounting advice; check with a tax professional.
          </p>
        </div>
      </Sheet>

      <Sheet title="Documents">
        <div className="grid gap-4 p-4 sm:grid-cols-3">
          <Field label="Invoice prefix" error={err("invoice_prefix")} hint={`Next looks like ${val("invoice_prefix") || "INV"}-${new Date().getFullYear()}-0001`}>
            {(p) => <input {...p} className="field uppercase" maxLength={10} {...text("invoice_prefix")} />}
          </Field>
          <Field label="Estimate prefix" error={err("estimate_prefix")}>{(p) => <input {...p} className="field uppercase" maxLength={10} {...text("estimate_prefix")} />}</Field>
          <Field label="Work order prefix" error={err("work_order_prefix")}>{(p) => <input {...p} className="field uppercase" maxLength={10} {...text("work_order_prefix")} />}</Field>
          <Field label="Invoices due after (days)" hint="0 means due on receipt.">{(p) => <input {...p} className="field" inputMode="numeric" {...text("invoice_due_days")} />}</Field>
          <Field label="Estimates valid for (days)">{(p) => <input {...p} className="field" inputMode="numeric" {...text("estimate_valid_days")} />}</Field>
          <div className="sm:col-span-3">
            <Field label="Authorization statement" hint="Shown above the customer's signature on estimates and approvals. You're responsible for wording that fits your state.">
              {(p) => <textarea {...p} className="field min-h-20" {...text("authorization_statement")} />}
            </Field>
          </div>
          <div className="sm:col-span-3">
            <Field label="Invoice footer" hint="Warranty terms, thank-you note.">{(p) => <textarea {...p} className="field min-h-16" {...text("invoice_footer")} />}</Field>
          </div>
        </div>
      </Sheet>

      <div className="sticky bottom-20 z-20 flex items-center gap-3 rounded-lg border border-line bg-sheet p-3 shadow md:bottom-4">
        <Button type="submit" variant="primary" busy={save.isPending}>Save settings</Button>
        {saved && <p role="status" className="text-go">Settings saved.</p>}
        <ErrorNote error={save.error} />
      </div>
    </form>
  );
}

function Services() {
  const { data } = useQuery({ queryKey: ["services"], queryFn: () => api.get<Service[]>("/services") });
  const [editing, setEditing] = useState<Service | "new" | null>(null);
  return (
    <Sheet title="Services on your website" action={<Button variant="quiet" onClick={() => setEditing("new")}>Add service</Button>}>
      <ul>
        {data?.map((s) => (
          <li key={s.id} className="flex items-center gap-3 border-b border-line px-4 py-2 last:border-0">
            <div className="min-w-0 flex-1">
              <p className="font-semibold">{s.name} {!s.is_published && <span className="font-normal text-steel-2">(hidden)</span>}</p>
              <p className="truncate text-[15px] text-steel-2">{[s.category, s.starting_price_cents && `from ${money(s.starting_price_cents)}`].filter(Boolean).join(", ")}</p>
            </div>
            <Button variant="quiet" onClick={() => setEditing(s)}>Edit</Button>
          </li>
        ))}
      </ul>
      {editing && <ServiceModal service={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Sheet>
  );
}

function ServiceModal({ service, onClose }: { service: Service | null; onClose: () => void }) {
  const [name, setName] = useState(service?.name ?? "");
  const [category, setCategory] = useState(service?.category ?? "");
  const [description, setDescription] = useState(service?.description ?? "");
  const [price, setPrice] = useState(centsToInput(service?.starting_price_cents));
  const [published, setPublished] = useState(service?.is_published ?? true);
  const body = () => ({ name, category, description, starting_price_cents: toCents(price), is_published: published });
  const save = useMutation({
    mutationFn: () => (service ? api.patch(`/services/${service.id}`, body()) : api.post("/services", body())),
    onSuccess: onClose,
  });
  const archive = useMutation({ mutationFn: () => api.post(`/services/${service!.id}/archive`), onSuccess: onClose });
  return (
    <Modal title={service ? "Edit service" : "Add service"} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error ?? archive.error} />
        <Field label="Name">{(p) => <input {...p} className="field" required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Category">{(p) => <input {...p} className="field" value={category} onChange={(e) => setCategory(e.target.value)} />}</Field>
        <Field label="Description">{(p) => <textarea {...p} className="field min-h-20" value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
        <Field label="Starting price" hint="Leave blank to show no price.">{(p) => <input {...p} className="field num text-lg" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />}</Field>
        <label className="flex min-h-12 items-center gap-3"><input type="checkbox" className="h-6 w-6" checked={published} onChange={(e) => setPublished(e.target.checked)} /> Show on website</label>
        <div className="flex gap-2">
          <Button type="submit" variant="primary" className="flex-1" busy={save.isPending}>Save service</Button>
          {service && <Button type="button" variant="danger" busy={archive.isPending} onClick={() => archive.mutate()}>Remove</Button>}
        </div>
      </form>
    </Modal>
  );
}

function Password() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState(false);
  const save = useMutation({
    mutationFn: () => api.post("/auth/change-password", { current_password: current, new_password: next }),
    onSuccess: () => { setCurrent(""); setNext(""); setDone(true); },
  });
  return (
    <Sheet title="Password">
      <form onSubmit={(e) => { e.preventDefault(); setDone(false); save.mutate(); }} className="grid gap-4 p-4 sm:grid-cols-2">
        <Field label="Current password">{(p) => <input {...p} className="field" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />}</Field>
        <Field label="New password" hint="At least 12 characters." error={fieldError(save.error, "new_password")}>
          {(p) => <input {...p} className="field" type="password" autoComplete="new-password" required minLength={12} value={next} onChange={(e) => setNext(e.target.value)} />}
        </Field>
        <div className="flex items-center gap-3 sm:col-span-2">
          <Button type="submit" busy={save.isPending}>Change password</Button>
          {done && <p role="status" className="text-go">Password changed. Other devices were signed out.</p>}
        </div>
        <div className="sm:col-span-2"><ErrorNote error={save.error && !fieldError(save.error, "new_password") ? save.error : null} /></div>
      </form>
    </Sheet>
  );
}
