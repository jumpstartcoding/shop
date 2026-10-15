import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { Button, ErrorNote, Field } from "../components/ui";
import { api, fieldError } from "../lib/api";
import { money, phoneHref } from "../lib/format";
import type { Service } from "../lib/types";
import { Location } from "./Home";
import { addressLines, useServices, useShop } from "./shop";

function PageTitle({ children, sub }: { children: string; sub?: string }) {
  return (
    <div className="mx-auto max-w-6xl px-4 pt-10 pb-6">
      <h1 className="font-display text-5xl font-bold">{children}</h1>
      {sub && <p className="mt-2 max-w-2xl text-lg text-steel-2">{sub}</p>}
    </div>
  );
}

export function ServicesPage() {
  const { data: services } = useServices();
  const groups = new Map<string, Service[]>();
  for (const s of services ?? []) {
    const k = s.category ?? "Other";
    groups.set(k, [...(groups.get(k) ?? []), s]);
  }
  return (
    <>
      <PageTitle sub="Prices shown are starting points. Every job gets a written estimate before work begins.">Services</PageTitle>
      <div className="mx-auto max-w-6xl space-y-10 px-4 pb-16">
        {[...groups.entries()].map(([cat, items]) => (
          <section key={cat}>
            <h2 className="border-b-2 border-steel pb-1 font-display text-3xl font-semibold">{cat}</h2>
            <ul>
              {items.map((s) => (
                <li key={s.id} className="grid gap-2 border-b border-line py-4 sm:grid-cols-[1fr_auto] sm:items-center">
                  <div>
                    <h3 className="text-xl font-semibold">{s.name}</h3>
                    {s.description && <p className="text-steel-2">{s.description}</p>}
                  </div>
                  <div className="flex items-center gap-4">
                    {s.starting_price_cents !== null && <span className="num text-lg">from {money(s.starting_price_cents)}</span>}
                    <Link to={`/book?service=${encodeURIComponent(s.name)}`} className="inline-flex min-h-12 items-center rounded-md border border-steel px-4 font-semibold">
                      Book this
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  );
}

export function AboutPage() {
  const { data: shop } = useShop();
  if (!shop) return null;
  return (
    <>
      <PageTitle>{`About ${shop.name}`}</PageTitle>
      <div className="mx-auto grid max-w-6xl gap-10 px-4 pb-16 md:grid-cols-[2fr_1fr]">
        <div className="max-w-[68ch] space-y-4 text-lg leading-relaxed whitespace-pre-wrap">{shop.about_text}</div>
        <aside className="space-y-6">
          {shop.certifications && (
            <div>
              <h2 className="font-display text-2xl font-semibold">Experience and certifications</h2>
              <p className="mt-1 whitespace-pre-wrap">{shop.certifications}</p>
            </div>
          )}
          {shop.service_area && (
            <div>
              <h2 className="font-display text-2xl font-semibold">Service area</h2>
              <p className="mt-1">{shop.service_area}</p>
            </div>
          )}
        </aside>
      </div>
    </>
  );
}

export function ContactPage() {
  const { data: shop } = useShop();
  const [form, setForm] = useState({ name: "", phone: "", email: "", message: "", website: "" });
  const send = useMutation({ mutationFn: () => api.post("/public/contact", form) });
  if (!shop) return null;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <>
      <PageTitle sub="Calling is fastest during shop hours. Messages are answered as soon as the mechanic is out from under a car.">Contact</PageTitle>
      <div className="mx-auto grid max-w-6xl gap-10 px-4 pb-6 md:grid-cols-2">
        <div className="space-y-4 text-lg">
          {shop.phone && <p><a className="font-display text-4xl font-bold" href={phoneHref(shop.phone)}>{shop.phone}</a></p>}
          {shop.email && <p><a className="underline underline-offset-4" href={`mailto:${shop.email}`}>{shop.email}</a></p>}
          <address className="not-italic">{addressLines(shop).map((l) => <span key={l} className="block">{l}</span>)}</address>
        </div>
        {send.isSuccess ? (
          <div role="status" className="rounded-lg border-l-[6px] border-go bg-go-wash p-5">
            <p className="font-display text-2xl font-semibold">Message sent</p>
            <p>Thanks, {form.name.split(" ")[0]}. The shop will get back to you by {form.phone ? "phone" : "email"}.</p>
          </div>
        ) : (
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); send.mutate(); }} className="space-y-4">
            <ErrorNote error={send.error} />
            <Field label="Your name" error={fieldError(send.error, "name")}>{(p) => <input {...p} className="field" required autoComplete="name" value={form.name} onChange={set("name")} />}</Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Phone">{(p) => <input {...p} className="field" type="tel" autoComplete="tel" value={form.phone} onChange={set("phone")} />}</Field>
              <Field label="Email" error={fieldError(send.error, "email")}>{(p) => <input {...p} className="field" type="email" autoComplete="email" value={form.email} onChange={set("email")} />}</Field>
            </div>
            <Field label="Message">{(p) => <textarea {...p} className="field min-h-32" required value={form.message} onChange={set("message")} />}</Field>
            <Honeypot value={form.website} onChange={set("website")} />
            <Button type="submit" variant="primary" busy={send.isPending}>Send message</Button>
          </form>
        )}
      </div>
      <Location shop={shop} />
    </>
  );
}

/** Hidden from people and screen readers; bots that fill every field get filtered out. */
export function Honeypot({ value, onChange }: { value: string; onChange: (e: { target: { value: string } }) => void }) {
  return (
    <div aria-hidden="true" className="absolute -left-[9999px] h-px w-px overflow-hidden">
      <label>
        Website
        <input tabIndex={-1} autoComplete="off" value={value} onChange={onChange} />
      </label>
    </div>
  );
}
