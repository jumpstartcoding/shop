import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button, ErrorNote, Field } from "../components/ui";
import { api, fieldError } from "../lib/api";
import { localDateInput, phoneHref } from "../lib/format";
import { Honeypot } from "./Pages";
import { useServices, useShop } from "./shop";

const TIMES: [string, string][] = [
  ["morning", "Morning"],
  ["midday", "Midday"],
  ["afternoon", "Afternoon"],
  ["any", "Any time"],
];

export function BookPage() {
  const [params] = useSearchParams();
  const estimate = params.get("estimate") === "1";
  const { data: shop } = useShop();
  const { data: services } = useServices();
  const [f, setF] = useState({
    name: "", phone: "", email: "", vehicle_year: "", vehicle_make: "", vehicle_model: "", mileage: "",
    requested_service: params.get("service") ?? (estimate ? "Estimate" : ""),
    preferred_date: "", preferred_time: "any", concern: "", notes: "", website: "",
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const book = useMutation({
    mutationFn: () =>
      api.post("/public/appointments", {
        ...f,
        vehicle_year: f.vehicle_year ? Number(f.vehicle_year) : null,
        mileage: f.mileage ? Number(f.mileage.replace(/\D/g, "")) : null,
        preferred_date: f.preferred_date || null,
      }),
  });

  if (book.isSuccess) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16">
        <div role="status" className="rounded-lg border-l-[6px] border-go bg-go-wash p-6">
          <h1 className="font-display text-4xl font-bold">Request received</h1>
          <p className="mt-2 text-lg">
            Thanks, {f.name.split(" ")[0]}. This is a request, not a confirmed time yet. The shop will
            {f.phone ? " call or text you" : " email you"} to confirm.
          </p>
          {shop?.phone && <p className="mt-3">Need it sooner? Call <a className="font-semibold underline" href={phoneHref(shop.phone)}>{shop.phone}</a>.</p>}
        </div>
        <Link to="/" className="mt-6 inline-block min-h-12 content-center underline underline-offset-4">Back to the home page</Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 pt-10 pb-16">
      <h1 className="font-display text-5xl font-bold">{estimate ? "Request an estimate" : "Book an appointment"}</h1>
      <p className="mt-2 text-lg text-steel-2">
        Tell us about the car and what's going on. You'll hear back to confirm a time
        {estimate ? ", and get a written estimate before any work is done." : "."}
      </p>

      <form onSubmit={(e: FormEvent) => { e.preventDefault(); book.mutate(); }} className="mt-8 space-y-8" noValidate>
        <ErrorNote error={book.error} />

        <fieldset className="space-y-4">
          <legend className="mb-2 font-display text-2xl font-semibold">You</legend>
          <Field label="Name" error={fieldError(book.error, "name")}>
            {(p) => <input {...p} className="field" autoComplete="name" required value={f.name} onChange={set("name")} />}
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Phone" hint="Best for confirming quickly" error={fieldError(book.error, "phone")}>
              {(p) => <input {...p} className="field" type="tel" autoComplete="tel" value={f.phone} onChange={set("phone")} />}
            </Field>
            <Field label="Email" error={fieldError(book.error, "email")}>
              {(p) => <input {...p} className="field" type="email" autoComplete="email" value={f.email} onChange={set("email")} />}
            </Field>
          </div>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="mb-2 font-display text-2xl font-semibold">Vehicle</legend>
          <div className="grid grid-cols-[6rem_1fr_1fr] gap-2">
            <Field label="Year" error={fieldError(book.error, "vehicle_year")}>
              {(p) => <input {...p} className="field" inputMode="numeric" maxLength={4} value={f.vehicle_year} onChange={set("vehicle_year")} />}
            </Field>
            <Field label="Make">{(p) => <input {...p} className="field" placeholder="Honda" value={f.vehicle_make} onChange={set("vehicle_make")} />}</Field>
            <Field label="Model">{(p) => <input {...p} className="field" placeholder="Accord" value={f.vehicle_model} onChange={set("vehicle_model")} />}</Field>
          </div>
          <Field label="Approximate mileage">
            {(p) => <input {...p} className="field sm:w-48" inputMode="numeric" value={f.mileage} onChange={set("mileage")} />}
          </Field>
        </fieldset>

        <fieldset className="space-y-4">
          <legend className="mb-2 font-display text-2xl font-semibold">The visit</legend>
          <Field label="Service">
            {(p) => (
              <select {...p} className="field" value={f.requested_service} onChange={set("requested_service")}>
                <option value="">Not sure, something's wrong</option>
                {estimate && <option value="Estimate">Estimate</option>}
                {services?.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
              </select>
            )}
          </Field>
          <Field label="What's going on?" hint="Noises, warning lights, when it happens. Anything helps.">
            {(p) => <textarea {...p} className="field min-h-28" value={f.concern} onChange={set("concern")} />}
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Preferred day" error={fieldError(book.error, "preferred_date")}>
              {(p) => <input {...p} className="field" type="date" min={localDateInput(new Date())} value={f.preferred_date} onChange={set("preferred_date")} />}
            </Field>
            <fieldset>
              <legend className="mb-1 text-[15px] font-medium text-steel-2">Preferred time</legend>
              <div className="grid grid-cols-2 gap-2">
                {TIMES.map(([v, label]) => (
                  <label key={v} className={`flex min-h-12 cursor-pointer items-center justify-center rounded-md border font-medium ${f.preferred_time === v ? "border-steel bg-steel text-white" : "border-line"}`}>
                    <input type="radio" name="time" className="sr-only" checked={f.preferred_time === v} onChange={() => setF({ ...f, preferred_time: v })} />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
          <Field label="Anything else?">
            {(p) => <textarea {...p} className="field min-h-20" value={f.notes} onChange={set("notes")} />}
          </Field>
        </fieldset>
        <Honeypot value={f.website} onChange={set("website")} />
        <Button type="submit" variant="primary" busy={book.isPending} className="w-full text-lg sm:w-auto">
          {estimate ? "Request estimate" : "Request appointment"}
        </Button>
      </form>
    </div>
  );
}
