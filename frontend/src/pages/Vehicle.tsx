import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PhotoStrip } from "../components/Photos";
import { Button, Dl, Empty, ErrorNote, Field, InternalNote, LinkButton, Loading, Modal, PageHeader, Sheet } from "../components/ui";
import { VehicleFields, emptyVehicle, vehiclePayload } from "../components/VehicleFields";
import { api } from "../lib/api";
import { date, money, toCents } from "../lib/format";
import type { CustomerDetail, History, InspectionListItem, Photo, ServiceHistory, ServiceRecord, Vehicle } from "../lib/types";
import { HistorySheets } from "./Customers";

export function VehiclePage() {
  const id = Number(useParams().id);
  const [editing, setEditing] = useState(false);
  const { data: v, error, isLoading } = useQuery({
    queryKey: ["vehicle", id],
    queryFn: () => api.get<Vehicle>(`/vehicles/${id}`),
  });
  const owner = useQuery({
    queryKey: ["customer", v?.customer_id],
    queryFn: () => api.get<CustomerDetail>(`/customers/${v!.customer_id}`),
    enabled: !!v,
  });
  const history = useQuery({
    queryKey: ["vehicle-history", id],
    queryFn: () => api.get<History>(`/vehicles/${id}/history`),
  });

  if (isLoading) return <Loading />;
  if (error || !v) return <ErrorNote error={error} />;

  return (
    <div className="space-y-5">
      <PageHeader
        title={v.display_name}
        sub={owner.data && <Link className="underline underline-offset-4" to={`/admin/customers/${owner.data.id}`}>{owner.data.full_name}</Link>}
        actions={
          <>
            <Button onClick={() => setEditing(true)}>Edit</Button>
            <LinkButton variant="primary" to={`/admin/work-orders/new?customer=${v.customer_id}&vehicle=${v.id}`}>New work order</LinkButton>
          </>
        }
      />
      <Sheet title="Vehicle">
        <Dl
          rows={[
            ["VIN", v.vin && <span className="num text-lg tracking-wider">{v.vin}</span>],
            ["Plate", [v.license_plate, v.license_state].filter(Boolean).join(" ")],
            ["Mileage", v.mileage !== null ? `${v.mileage.toLocaleString()} mi` : null],
            ["Engine", v.engine],
            ["Transmission", v.transmission],
            ["Color", v.color],
          ]}
        />
        {v.internal_notes && <div className="px-4 pb-4"><InternalNote>{v.internal_notes}</InternalNote></div>}
      </Sheet>
      <ServiceHistorySheet vehicle={v} />
      <InspectionsSheet vehicleId={v.id} />
      <VehiclePhotos vehicleId={v.id} />
      {history.data && <HistorySheets history={history.data} />}
      {editing && <EditVehicle vehicle={v} onClose={() => setEditing(false)} />}
    </div>
  );
}

function EditVehicle({ vehicle, onClose }: { vehicle: Vehicle; onClose: () => void }) {
  const [d, setD] = useState(emptyVehicle(vehicle));
  const save = useMutation({
    mutationFn: () => api.patch(`/vehicles/${vehicle.id}`, vehiclePayload(d)),
    onSuccess: onClose,
  });
  return (
    <Modal title="Edit vehicle" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error} />
        <VehicleFields v={d} set={setD} error={save.error} />
        <Button type="submit" variant="primary" busy={save.isPending} className="w-full">Save changes</Button>
      </form>
    </Modal>
  );
}

function ServiceHistorySheet({ vehicle }: { vehicle: Vehicle }) {
  const [adding, setAdding] = useState(false);
  const { data, error } = useQuery({
    queryKey: ["service-history", vehicle.id],
    queryFn: () => api.get<ServiceHistory>(`/vehicles/${vehicle.id}/service-history`),
  });
  const remove = useMutation({ mutationFn: (id: number) => api.del(`/service-records/${id}`) });
  if (error) return <ErrorNote error={error} />;
  if (!data) return null;
  return (
    <>
      <Sheet title="Service history" action={<Button variant="quiet" onClick={() => setAdding(true)}>Add past service</Button>}>
        {data.records.length === 0 ? (
          <Empty>Completed jobs appear here automatically. Add earlier work from the customer's records with “Add past service”.</Empty>
        ) : (
          <ol>
            {data.records.map((r) => (
              <RecordRow key={r.id} r={r} onRemove={() => confirm("Remove this past service record?") && remove.mutate(r.id)} />
            ))}
          </ol>
        )}
        <div className="px-4"><ErrorNote error={remove.error} /></div>
      </Sheet>
      {data.warranties.length > 0 && (
        <Sheet title="Warranties">
          <ul>
            {data.warranties.map((w, i) => (
              <li key={i} className="flex flex-wrap items-start gap-3 border-b border-line px-4 py-3 last:border-0">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{w.description}{w.part_number && <span className="ml-2 font-normal text-steel-2">#{w.part_number}</span>}</p>
                  <p className="text-[15px] text-steel-2">
                    {[
                      `Installed ${date(w.service_date)}`,
                      w.months && `${w.months} months`,
                      w.miles && `${w.miles.toLocaleString()} miles`,
                      w.expires_on && `until ${date(w.expires_on)}`,
                      w.expires_mileage && `or ${w.expires_mileage.toLocaleString()} mi`,
                    ].filter(Boolean).join(", ")}
                  </p>
                  {w.notes && <p className="text-[15px]">{w.notes}</p>}
                </div>
                <span className={`rounded border px-2 py-0.5 text-[14px] font-semibold ${w.state === "active" ? "border-go/30 bg-go-wash text-go" : w.state === "expired" ? "border-line bg-concrete text-steel-2" : "border-hold/30 bg-hold-wash text-hold"}`}>
                  {w.state === "active" ? "Active" : w.state === "expired" ? "Expired" : "See notes"}
                </span>
              </li>
            ))}
          </ul>
        </Sheet>
      )}
      {adding && <AddRecord vehicle={vehicle} onClose={() => setAdding(false)} />}
    </>
  );
}

function RecordRow({ r, onRemove }: { r: ServiceRecord; onRemove: () => void }) {
  return (
    <li className="border-b border-line px-4 py-3 last:border-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <p className="font-semibold">
          {date(r.service_date)}
          {r.mileage !== null && <span className="ml-2 font-normal text-steel-2">{r.mileage.toLocaleString()} mi</span>}
        </p>
        {r.total_cents !== null && <p className="num text-lg">{money(r.total_cents)}</p>}
      </div>
      <p>{r.summary}</p>
      <p className="text-[15px] text-steel-2">
        {r.source === "manual" ? (
          <>
            {r.performed_by ? `Done by ${r.performed_by}` : "Added by hand"}
            <button type="button" className="ml-3 min-h-11 underline underline-offset-4" onClick={onRemove}>Remove</button>
          </>
        ) : (
          <>
            {r.work_order && <Link className="underline" to={`/admin/work-orders/${r.work_order.id}`}>{r.work_order.number}</Link>}
            {r.invoice && <>{", "}<Link className="underline" to={`/admin/invoices/${r.invoice.id}`}>{r.invoice.number}</Link></>}
            {r.labor_cents + r.parts_cents > 0 && `, labor ${money(r.labor_cents)}, parts ${money(r.parts_cents)}`}
          </>
        )}
      </p>
      {r.notes && <p className="text-[15px] whitespace-pre-wrap">{r.notes}</p>}
    </li>
  );
}

function AddRecord({ vehicle, onClose }: { vehicle: Vehicle; onClose: () => void }) {
  const [d, setD] = useState({ service_date: "", summary: "", mileage: "", performed_by: "", total: "", notes: "" });
  const set = (k: keyof typeof d) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value });
  const save = useMutation({
    mutationFn: () =>
      api.post(`/vehicles/${vehicle.id}/service-records`, {
        service_date: d.service_date,
        summary: d.summary,
        mileage: d.mileage ? Number(d.mileage.replace(/\D/g, "")) : null,
        performed_by: d.performed_by || null,
        total_cents: d.total ? toCents(d.total) : null,
        notes: d.notes || null,
      }),
    onSuccess: onClose,
  });
  return (
    <Modal title="Add past service" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
        <ErrorNote error={save.error} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Date">{(p) => <input {...p} type="date" required className="field" value={d.service_date} onChange={set("service_date")} />}</Field>
          <Field label="Mileage">{(p) => <input {...p} inputMode="numeric" className="field num" value={d.mileage} onChange={set("mileage")} />}</Field>
        </div>
        <Field label="What was done">{(p) => <input {...p} required minLength={2} maxLength={500} className="field" value={d.summary} onChange={set("summary")} placeholder="Timing belt and water pump" />}</Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Done by" hint="Another shop, the dealer, the owner…">{(p) => <input {...p} maxLength={120} className="field" value={d.performed_by} onChange={set("performed_by")} />}</Field>
          <Field label="Cost (optional)">{(p) => <input {...p} inputMode="decimal" className="field num" value={d.total} onChange={set("total")} />}</Field>
        </div>
        <Field label="Notes">{(p) => <textarea {...p} maxLength={2000} className="field min-h-20" value={d.notes} onChange={set("notes")} />}</Field>
        <Button type="submit" variant="primary" className="w-full" busy={save.isPending}>Add to history</Button>
      </form>
    </Modal>
  );
}

function InspectionsSheet({ vehicleId }: { vehicleId: number }) {
  const { data } = useQuery({
    queryKey: ["vehicle-inspections", vehicleId],
    queryFn: () => api.get<InspectionListItem[]>(`/vehicles/${vehicleId}/inspections`),
  });
  if (!data || data.length === 0) return null;
  return (
    <Sheet title="Inspections">
      <ul>
        {data.map((i) => (
          <li key={i.id}>
            <Link to={`/admin/inspections/${i.id}`} className="flex min-h-14 flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-3 last:border-0 hover:bg-concrete/60">
              <span className="font-semibold">{date(i.completed_at ?? i.created_at)}</span>
              <span className="num text-steel-2">{i.number}</span>
              {i.mileage !== null && <span className="text-steel-2">{i.mileage.toLocaleString()} mi</span>}
              <span className="ml-auto inline-flex gap-3 text-[15px]">
                <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="h-3 w-3 rounded-full bg-signal" />{i.counts.red}</span>
                <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="h-3 w-3 rounded-full bg-safety-deep" />{i.counts.yellow}</span>
                <span className="inline-flex items-center gap-1"><span aria-hidden="true" className="h-3 w-3 rounded-full bg-go" />{i.counts.green}</span>
                <span className="sr-only">{`${i.counts.red} need attention, ${i.counts.yellow} monitor, ${i.counts.green} good`}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}

function VehiclePhotos({ vehicleId }: { vehicleId: number }) {
  const { data } = useQuery({
    queryKey: ["vehicle-photos", vehicleId],
    queryFn: () => api.get<Photo[]>(`/vehicles/${vehicleId}/photos`),
  });
  const others = (data ?? []).filter((p) => p.entity_type !== "vehicle");
  return (
    <Sheet title="Photos">
      <div className="space-y-4 p-4">
        <div>
          <p className="mb-2 text-steel-2">Photos of the vehicle itself: VIN plate, existing damage at drop-off, odometer.</p>
          <PhotoStrip entityType="vehicle" entityId={vehicleId} />
        </div>
        {others.length > 0 && (
          <div>
            <p className="mb-2 font-medium">From inspections, work orders, and estimates</p>
            <ul className="flex flex-wrap gap-2">
              {others.map((p) => (
                <li key={p.id}>
                  <a href={p.url} target="_blank" rel="noopener" className="block h-24 w-24 overflow-hidden rounded-md border border-line bg-concrete">
                    <img src={p.thumb_url} alt={p.caption ?? ""} loading="lazy" className="h-full w-full object-cover" />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Sheet>
  );
}
