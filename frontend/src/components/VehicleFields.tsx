import { useMutation } from "@tanstack/react-query";
import { ApiError, api, fieldError } from "../lib/api";
import type { Vehicle, VinDecode } from "../lib/types";
import { Button, Field } from "./ui";

/** Fill in year, make, model, and more from the VIN (NHTSA's free service). Only empty
 * fields are filled, so nothing typed by hand is overwritten. */
function useVinLookup(v: VehicleDraft, set: (v: VehicleDraft) => void) {
  const clean = v.vin.replace(/\s/g, "").toUpperCase();
  const look = useMutation({
    mutationFn: () => api.get<VinDecode>(`/vin/${clean}`),
    onSuccess: (d) => {
      const fill = (cur: string, val: string | number | null) => cur || (val === null ? "" : String(val));
      set({
        ...v,
        vin: d.vin,
        year: fill(v.year, d.year),
        make: fill(v.make, d.make),
        model: fill(v.model, d.model),
        trim: fill(v.trim, d.trim),
        engine: fill(v.engine, d.engine),
        transmission: fill(v.transmission, d.transmission),
      });
    },
  });
  const message = look.error
    ? look.error instanceof ApiError ? look.error.message : "VIN lookup didn't work. Enter the details by hand."
    : look.data
      ? look.data.warning ? `Filled in what was found. NHTSA notes: ${look.data.warning}` : "Filled in from the VIN. Check it matches the vehicle."
      : null;
  return { ready: clean.length === 17, look, message };
}

export type VehicleDraft = {
  year: string;
  make: string;
  model: string;
  trim: string;
  vin: string;
  license_plate: string;
  license_state: string;
  mileage: string;
  engine: string;
  transmission: string;
  color: string;
  internal_notes: string;
};

export function emptyVehicle(v?: Vehicle): VehicleDraft {
  return {
    year: v?.year?.toString() ?? "",
    make: v?.make ?? "",
    model: v?.model ?? "",
    trim: v?.trim ?? "",
    vin: v?.vin ?? "",
    license_plate: v?.license_plate ?? "",
    license_state: v?.license_state ?? "",
    mileage: v?.mileage?.toString() ?? "",
    engine: v?.engine ?? "",
    transmission: v?.transmission ?? "",
    color: v?.color ?? "",
    internal_notes: v?.internal_notes ?? "",
  };
}

export function vehiclePayload(v: VehicleDraft) {
  return {
    ...v,
    year: v.year ? Number(v.year) : null,
    mileage: v.mileage ? Number(v.mileage.replace(/\D/g, "")) : null,
  };
}

export function VehicleFields({
  v,
  set,
  error,
  prefix = "",
}: {
  v: VehicleDraft;
  set: (v: VehicleDraft) => void;
  error: unknown;
  prefix?: string;
}) {
  const f = (k: keyof VehicleDraft) => ({
    value: v[k],
    onChange: (e: { target: { value: string } }) => set({ ...v, [k]: e.target.value }),
  });
  const err = (k: string) => fieldError(error, prefix + k);
  const vin = useVinLookup(v, set);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-[5.5rem_1fr_1fr] gap-2">
        <Field label="Year" error={err("year")}>
          {(p) => <input {...p} className="field" inputMode="numeric" maxLength={4} {...f("year")} />}
        </Field>
        <Field label="Make">{(p) => <input {...p} className="field" {...f("make")} />}</Field>
        <Field label="Model">{(p) => <input {...p} className="field" {...f("model")} />}</Field>
      </div>
      <div className="flex items-end gap-2">
        <div className="min-w-0 flex-1">
          <Field label="VIN" error={err("vin")} hint="Usually on the driver-side dash or door jamb.">
            {(p) => (
              <input {...p} className="field num text-lg tracking-wider uppercase" autoCapitalize="characters"
                autoComplete="off" spellCheck={false} maxLength={20} {...f("vin")} />
            )}
          </Field>
        </div>
        <div className="pb-7">
          <Button type="button" onClick={() => vin.look.mutate()} busy={vin.look.isPending} disabled={!vin.ready}>
            Look up
          </Button>
        </div>
      </div>
      {vin.message && (
        <p role="status" className={`-mt-2 text-[15px] ${vin.look.error ? "text-signal" : "text-go"}`}>{vin.message}</p>
      )}
      <div className="grid grid-cols-[1fr_5rem_1fr] gap-2">
        <Field label="Plate" error={err("license_plate")}>
          {(p) => <input {...p} className="field uppercase" autoCapitalize="characters" {...f("license_plate")} />}
        </Field>
        <Field label="State">{(p) => <input {...p} className="field uppercase" maxLength={10} {...f("license_state")} />}</Field>
        <Field label="Mileage" error={err("mileage")}>
          {(p) => <input {...p} className="field num text-lg" inputMode="numeric" {...f("mileage")} />}
        </Field>
      </div>
      <details className="rounded-md border border-line px-3 py-2">
        <summary className="min-h-10 cursor-pointer content-center font-medium">More details</summary>
        <div className="grid grid-cols-2 gap-2 pt-2 pb-1">
          <Field label="Trim">{(p) => <input {...p} className="field" {...f("trim")} />}</Field>
          <Field label="Color">{(p) => <input {...p} className="field" {...f("color")} />}</Field>
          <Field label="Engine">{(p) => <input {...p} className="field" {...f("engine")} />}</Field>
          <Field label="Transmission">{(p) => <input {...p} className="field" {...f("transmission")} />}</Field>
        </div>
        <div className="pb-2">
          <Field label="Internal note" hint="Only you see this.">
            {(p) => <textarea {...p} className="field min-h-20" {...f("internal_notes")} />}
          </Field>
        </div>
      </details>
    </div>
  );
}
