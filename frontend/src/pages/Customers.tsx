import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Button,
  Dl,
  Empty,
  ErrorNote,
  Field,
  InternalNote,
  LinkButton,
  Loading,
  Modal,
  PageHeader,
  RowLink,
  Sheet,
  StatusBadge,
} from "../components/ui";
import { PhotoStrip } from "../components/Photos";
import { CustomerVehiclePicker } from "../components/Picker";
import { VehicleFields, type VehicleDraft, emptyVehicle, vehiclePayload } from "../components/VehicleFields";
import { api, fieldError } from "../lib/api";
import { date, money, phoneHref } from "../lib/format";
import type { Appointment, Customer, CustomerDetail, CustomerListItem, History, Page } from "../lib/types";

export function CustomerList() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const archived = params.get("archived") === "1";
  const [text, setText] = useState(q);
  useEffect(() => {
    const t = setTimeout(() => {
      if (text !== q) setParams(text ? { q: text } : {}, { replace: true });
    }, 250);
    return () => clearTimeout(t);
  }, [text, q, setParams]);

  const { data, error, isLoading } = useQuery({
    queryKey: ["customers", q, archived],
    queryFn: () => api.get<Page<CustomerListItem>>("/customers", { q, include_archived: archived, page_size: 100 }),
  });

  return (
    <>
      <PageHeader title="Customers" actions={<LinkButton to="/admin/customers/new" variant="primary">New customer</LinkButton>} />
      <div className="mb-3">
        <label htmlFor="cust-q" className="sr-only">Find a customer</label>
        <input id="cust-q" type="search" className="field" placeholder="Name, phone, email, VIN, or plate" autoFocus={params.get("find") === "1"}
          value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <Sheet>
        {isLoading ? (
          <Loading />
        ) : error ? (
          <div className="p-4"><ErrorNote error={error} /></div>
        ) : data!.items.length === 0 ? (
          <Empty>
            {q ? `No customers match “${q}”.` : "No customers yet."}{" "}
            <Link className="underline" to="/admin/customers/new">Add a customer</Link>
          </Empty>
        ) : (
          <ul>
            {data!.items.map((c) => (
              <RowLink key={c.id} to={`/admin/customers/${c.id}`}>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">
                    {c.full_name} {c.archived_at && <span className="font-normal text-steel-2">(archived)</span>}
                  </p>
                  <p className="truncate text-[15px] text-steel-2">
                    {[c.phone, c.email].filter(Boolean).join(", ")}
                    {c.vehicle_count ? `, ${c.vehicle_count} vehicle${c.vehicle_count > 1 ? "s" : ""}` : ""}
                  </p>
                </div>
                {c.balance_cents > 0 && (
                  <span className="num text-lg text-signal">{money(c.balance_cents)} owed</span>
                )}
              </RowLink>
            ))}
          </ul>
        )}
      </Sheet>
      <label className="mt-4 flex min-h-12 items-center gap-3">
        <input type="checkbox" className="h-6 w-6" checked={archived}
          onChange={(e) => setParams(e.target.checked ? { archived: "1", ...(q ? { q } : {}) } : q ? { q } : {})} />
        Include archived customers
      </label>
    </>
  );
}

type CustomerDraft = {
  first_name: string;
  last_name: string;
  phone: string;
  email: string;
  address_line1: string;
  city: string;
  state: string;
  postal_code: string;
  preferred_contact: string;
  internal_notes: string;
};

function draftFrom(c?: Customer): CustomerDraft {
  return {
    first_name: c?.first_name ?? "",
    last_name: c?.last_name ?? "",
    phone: c?.phone ?? "",
    email: c?.email ?? "",
    address_line1: c?.address_line1 ?? "",
    city: c?.city ?? "",
    state: c?.state ?? "",
    postal_code: c?.postal_code ?? "",
    preferred_contact: c?.preferred_contact ?? "",
    internal_notes: c?.internal_notes ?? "",
  };
}

function CustomerFields({ d, set, error }: { d: CustomerDraft; set: (d: CustomerDraft) => void; error: unknown }) {
  const f = (k: keyof CustomerDraft) => ({
    value: d[k],
    onChange: (e: { target: { value: string } }) => set({ ...d, [k]: e.target.value }),
  });
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Field label="First name" error={fieldError(error, "first_name")}>
          {(p) => <input {...p} className="field" required autoComplete="off" {...f("first_name")} />}
        </Field>
        <Field label="Last name">
          {(p) => <input {...p} className="field" autoComplete="off" {...f("last_name")} />}
        </Field>
      </div>
      <Field label="Phone" error={fieldError(error, "phone")}>
        {(p) => <input {...p} className="field" type="tel" inputMode="tel" {...f("phone")} />}
      </Field>
      <Field label="Email" error={fieldError(error, "email")}>
        {(p) => <input {...p} className="field" type="email" inputMode="email" {...f("email")} />}
      </Field>
      <Field label="Prefers">
        {(p) => (
          <select {...p} className="field" {...f("preferred_contact")}>
            <option value="">No preference</option>
            <option value="phone">Phone call</option>
            <option value="text">Text</option>
            <option value="email">Email</option>
          </select>
        )}
      </Field>
      <details className="rounded-md border border-line px-3 py-2">
        <summary className="min-h-10 cursor-pointer content-center font-medium">Address</summary>
        <div className="space-y-3 pt-2 pb-1">
          <Field label="Street">{(p) => <input {...p} className="field" {...f("address_line1")} />}</Field>
          <div className="grid grid-cols-[2fr_1fr_1fr] gap-2">
            <Field label="City">{(p) => <input {...p} className="field" {...f("city")} />}</Field>
            <Field label="State">{(p) => <input {...p} className="field" {...f("state")} />}</Field>
            <Field label="ZIP">{(p) => <input {...p} className="field" inputMode="numeric" {...f("postal_code")} />}</Field>
          </div>
        </div>
      </details>
      <Field label="Internal note" hint="Only you see this. Never shown on estimates or invoices.">
        {(p) => <textarea {...p} className="field min-h-20" {...f("internal_notes")} />}
      </Field>
    </div>
  );
}

function customerPayload(d: CustomerDraft) {
  return { ...d, preferred_contact: d.preferred_contact || null };
}

export function NewCustomer() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const appointmentId = Number(params.get("appointment")) || null;
  const [d, setD] = useState(draftFrom());
  const [withVehicle, setWithVehicle] = useState(true);
  const [v, setV] = useState<VehicleDraft>(emptyVehicle());

  // Started from an online booking request: prefill from what the customer typed.
  const request = useQuery({
    queryKey: ["appointment", appointmentId],
    queryFn: () => api.get<Appointment>(`/appointments/${appointmentId}`),
    enabled: appointmentId !== null,
  });
  const [prefilled, setPrefilled] = useState(false);
  useEffect(() => {
    const a = request.data;
    if (!a || prefilled) return;
    const [first, ...rest] = (a.contact_name ?? "").trim().split(/\s+/);
    setD((cur) => ({ ...cur, first_name: first ?? "", last_name: rest.join(" "), phone: a.contact_phone ?? "", email: a.contact_email ?? "" }));
    const m = (a.vehicle_description ?? "").match(/^(\d{4})\s+(\S+)\s*(.*)$/);
    setV((cur) => ({
      ...cur,
      year: m?.[1] ?? "",
      make: m?.[2] ?? a.vehicle_description ?? "",
      model: m?.[3] ?? "",
      mileage: a.reported_mileage?.toString() ?? "",
    }));
    setPrefilled(true);
  }, [request.data, prefilled]);

  const create = useMutation({
    mutationFn: async () => {
      const c = await api.post<CustomerDetail>("/customers", {
        ...customerPayload(d),
        vehicle: withVehicle ? vehiclePayload(v) : null,
      });
      if (appointmentId) {
        await api.patch(`/appointments/${appointmentId}`, { customer_id: c.id, vehicle_id: c.vehicles[0]?.id ?? null });
      }
      return c;
    },
    onSuccess: (c) =>
      navigate(appointmentId ? `/admin/calendar?appointment=${appointmentId}` : `/admin/customers/${c.id}`, { replace: true }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <PageHeader title="New customer" sub={appointmentId ? "Filled in from the online request. Check it over before saving." : undefined} />
      <ErrorNote error={create.error} />
      <Sheet title="Customer">
        <div className="p-4"><CustomerFields d={d} set={setD} error={create.error} /></div>
      </Sheet>
      <Sheet
        title="Vehicle"
        action={
          <label className="flex min-h-12 items-center gap-2">
            <input type="checkbox" className="h-6 w-6" checked={withVehicle} onChange={(e) => setWithVehicle(e.target.checked)} />
            Add now
          </label>
        }
      >
        {withVehicle && <div className="p-4"><VehicleFields v={v} set={setV} error={create.error} prefix="vehicle." /></div>}
      </Sheet>
      <Button type="submit" variant="primary" busy={create.isPending} className="w-full sm:w-auto">
        Save customer
      </Button>
    </form>
  );
}

export function CustomerDetailPage() {
  const id = Number(useParams().id);
  const [editing, setEditing] = useState(false);
  const [params, setParams] = useSearchParams();
  // "New vehicle" from the dashboard picks the owner, then lands here with ?add_vehicle=1.
  const [addingVehicle, setAddingVehicle] = useState(() => params.get("add_vehicle") === "1");
  useEffect(() => {
    if (params.get("add_vehicle")) setParams({}, { replace: true });
  }, [params, setParams]);
  const { data: c, error, isLoading } = useQuery({
    queryKey: ["customer", id],
    queryFn: () => api.get<CustomerDetail>(`/customers/${id}`),
  });
  const { data: history } = useQuery({
    queryKey: ["customer-history", id],
    queryFn: () => api.get<History>(`/customers/${id}/history`),
  });
  const archive = useMutation({
    mutationFn: () => api.post(`/customers/${id}/${c?.archived_at ? "restore" : "archive"}`),
  });

  if (isLoading) return <Loading />;
  if (error || !c) return <ErrorNote error={error} />;

  const address = [c.address_line1, [c.city, c.state].filter(Boolean).join(", "), c.postal_code]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="space-y-5">
      <PageHeader
        title={c.full_name}
        sub={
          <>
            Customer since {date(c.customer_since)}
            {c.archived_at && <strong className="ml-2 text-signal">Archived</strong>}
          </>
        }
        actions={<Button onClick={() => setEditing(true)}>Edit</Button>}
      />

      <div className="flex flex-wrap gap-2">
        {c.phone && (
          <a href={phoneHref(c.phone)} className="inline-flex min-h-12 items-center rounded-md border border-line bg-sheet px-4 font-medium">
            Call {c.phone}
          </a>
        )}
        {c.phone && (
          <a href={phoneHref(c.phone)?.replace("tel:", "sms:")} className="inline-flex min-h-12 items-center rounded-md border border-line bg-sheet px-4 font-medium">
            Text
          </a>
        )}
        {c.email && (
          <a href={`mailto:${c.email}`} className="inline-flex min-h-12 items-center rounded-md border border-line bg-sheet px-4 font-medium">
            Email
          </a>
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Sheet title="Details">
          <Dl
            rows={[
              ["Phone", c.phone],
              ["Email", c.email],
              ["Prefers", c.preferred_contact],
              ["Address", address],
              ["Balance", c.balance_cents ? <span className="num text-lg text-signal">{money(c.balance_cents)}</span> : "Nothing owed"],
              ["Paid to date", <span className="num text-lg">{money(c.lifetime_paid_cents)}</span>],
            ]}
          />
          {c.internal_notes && <div className="px-4 pb-4"><InternalNote>{c.internal_notes}</InternalNote></div>}
        </Sheet>

        <Sheet title="Vehicles" action={<Button variant="quiet" onClick={() => setAddingVehicle(true)}>Add vehicle</Button>}>
          {c.vehicles.length === 0 ? (
            <Empty>No vehicles on file.</Empty>
          ) : (
            <ul>
              {c.vehicles.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-0">
                  <Link to={`/admin/vehicles/${v.id}`} className="min-h-12 min-w-0 flex-1">
                    <p className="font-semibold underline-offset-4 hover:underline">{v.display_name}</p>
                    <p className="text-[15px] text-steel-2">
                      {[v.license_plate, v.vin, v.mileage && `${v.mileage.toLocaleString()} mi`].filter(Boolean).join(", ")}
                    </p>
                  </Link>
                  <LinkButton to={`/admin/work-orders/new?customer=${c.id}&vehicle=${v.id}`}>New work order</LinkButton>
                </li>
              ))}
            </ul>
          )}
        </Sheet>
      </div>

      {history && <HistorySheets history={history} />}

      <Sheet title="Photos">
        <div className="p-4">
          <p className="mb-2 text-steel-2">A signed paper form, a note left with the keys: anything about the customer rather than one vehicle.</p>
          <PhotoStrip entityType="customer" entityId={c.id} />
        </div>
      </Sheet>

      <Button variant={c.archived_at ? "secondary" : "danger"} busy={archive.isPending} onClick={() => archive.mutate()}>
        {c.archived_at ? "Restore customer" : "Archive customer"}
      </Button>
      <ErrorNote error={archive.error} />

      {editing && <EditCustomer customer={c} onClose={() => setEditing(false)} />}
      {addingVehicle && <AddVehicle customerId={c.id} onClose={() => setAddingVehicle(false)} />}
    </div>
  );
}

export function HistorySheets({ history }: { history: History }) {
  const groups: [string, string, History["work_orders"]][] = [
    ["Work orders", "work-orders", history.work_orders],
    ["Estimates", "estimates", history.estimates],
    ["Invoices", "invoices", history.invoices],
  ];
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      {groups.map(([title, path, rows]) => (
        <Sheet key={path} title={title}>
          {rows.length === 0 ? (
            <Empty>None yet.</Empty>
          ) : (
            <ul>
              {rows.map((r) => (
                <RowLink key={r.id} to={`/admin/${path}/${r.id}`}>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">{r.number}</p>
                    <p className="truncate text-[15px] text-steel-2">{date(r.date)}, {r.vehicle_name}</p>
                  </div>
                  <div className="text-right">
                    <p className="num text-lg">{money(r.total_cents)}</p>
                    <StatusBadge status={r.status} />
                  </div>
                </RowLink>
              ))}
            </ul>
          )}
        </Sheet>
      ))}
    </div>
  );
}

function EditCustomer({ customer, onClose }: { customer: Customer; onClose: () => void }) {
  const [d, setD] = useState(draftFrom(customer));
  const save = useMutation({
    mutationFn: () => api.patch(`/customers/${customer.id}`, customerPayload(d)),
    onSuccess: onClose,
  });
  return (
    <Modal title="Edit customer" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error} />
        <CustomerFields d={d} set={setD} error={save.error} />
        <Button type="submit" variant="primary" busy={save.isPending} className="w-full">Save changes</Button>
      </form>
    </Modal>
  );
}

function AddVehicle({ customerId, onClose }: { customerId: number; onClose: () => void }) {
  const [v, setV] = useState<VehicleDraft>(emptyVehicle());
  const save = useMutation({
    mutationFn: () => api.post("/vehicles", { customer_id: customerId, ...vehiclePayload(v) }),
    onSuccess: onClose,
  });
  return (
    <Modal title="Add vehicle" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error} />
        <VehicleFields v={v} set={setV} error={save.error} />
        <Button type="submit" variant="primary" busy={save.isPending} className="w-full">Add vehicle</Button>
      </form>
    </Modal>
  );
}

/** "New vehicle" without a customer in hand: pick the owner first. */
export function NewVehicle() {
  const navigate = useNavigate();
  return (
    <div className="space-y-4">
      <PageHeader title="New vehicle" sub="Whose vehicle is it? New customers get their vehicle on the new-customer form." />
      <Sheet>
        <div className="p-4">
          <CustomerVehiclePicker customerId={null} vehicleId={null}
            onChange={(c) => c && navigate(`/admin/customers/${c}?add_vehicle=1`, { replace: true })} />
        </div>
      </Sheet>
      <LinkButton to="/admin/customers/new">New customer with a vehicle</LinkButton>
    </div>
  );
}
