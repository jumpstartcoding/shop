import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { CustomerDetail, CustomerListItem, Page } from "../lib/types";
import { Button } from "./ui";

/**
 * Choose a customer, then one of their vehicles. Used at the top of every "new document"
 * form so starting a job takes two taps when you know who it's for.
 */
export function CustomerVehiclePicker({
  customerId,
  vehicleId,
  onChange,
}: {
  customerId: number | null;
  vehicleId: number | null;
  onChange: (customerId: number | null, vehicleId: number | null) => void;
}) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);

  const matches = useQuery({
    queryKey: ["customers", debounced, false],
    queryFn: () => api.get<Page<CustomerListItem>>("/customers", { q: debounced, page_size: 8 }),
    enabled: customerId === null,
  });
  const customer = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => api.get<CustomerDetail>(`/customers/${customerId}`),
    enabled: customerId !== null,
  });

  useEffect(() => {
    // One vehicle on file: pick it automatically.
    const vs = customer.data?.vehicles;
    if (vs && vs.length === 1 && vehicleId === null) onChange(customerId, vs[0].id);
  }, [customer.data, vehicleId, customerId, onChange]);

  if (customerId === null) {
    return (
      <div className="space-y-2">
        <label htmlFor="pick-customer" className="block text-[15px] font-medium text-steel-2">Customer</label>
        <input id="pick-customer" type="search" className="field" autoFocus placeholder="Search name, phone, plate, or VIN"
          value={q} onChange={(e) => setQ(e.target.value)} />
        <ul className="divide-y divide-line rounded-md border border-line">
          {matches.data?.items.map((c) => (
            <li key={c.id}>
              <button type="button" className="block min-h-12 w-full px-3 py-2 text-left hover:bg-concrete" onClick={() => onChange(c.id, null)}>
                <span className="font-semibold">{c.full_name}</span>
                <span className="block text-[15px] text-steel-2">{[c.phone, c.email].filter(Boolean).join(", ")}</span>
              </button>
            </li>
          ))}
          {matches.data?.items.length === 0 && (
            <li className="px-3 py-3 text-steel-2">
              No match. <Link className="underline" to="/admin/customers/new">Add a new customer</Link>
            </li>
          )}
        </ul>
      </div>
    );
  }

  const c = customer.data;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-[15px] font-medium text-steel-2">Customer</p>
          <p className="text-lg font-semibold">{c?.full_name ?? "…"}</p>
        </div>
        <Button type="button" variant="quiet" onClick={() => onChange(null, null)}>Change</Button>
      </div>
      <fieldset>
        <legend className="mb-1 text-[15px] font-medium text-steel-2">Vehicle</legend>
        {c && c.vehicles.length === 0 && (
          <p className="text-steel-2">
            No vehicles on file. <Link className="underline" to={`/admin/customers/${c.id}`}>Add one on the customer page</Link>
          </p>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {c?.vehicles.map((v) => (
            <label key={v.id}
              className={`flex min-h-14 cursor-pointer items-center gap-3 rounded-md border px-3 py-2 ${vehicleId === v.id ? "border-steel bg-safety/25" : "border-line bg-sheet"}`}>
              <input type="radio" name="vehicle" className="h-5 w-5" checked={vehicleId === v.id} onChange={() => onChange(customerId, v.id)} />
              <span>
                <span className="block font-semibold">{v.display_name}</span>
                <span className="block text-[15px] text-steel-2">{[v.license_plate, v.mileage && `${v.mileage.toLocaleString()} mi`].filter(Boolean).join(", ")}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
    </div>
  );
}
