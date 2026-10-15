import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button, Dl, ErrorNote, InternalNote, LinkButton, Loading, Modal, PageHeader, Sheet } from "../components/ui";
import { VehicleFields, emptyVehicle, vehiclePayload } from "../components/VehicleFields";
import { api } from "../lib/api";
import type { CustomerDetail, History, Vehicle } from "../lib/types";
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
