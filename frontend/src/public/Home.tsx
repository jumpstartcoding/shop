import { Link } from "react-router-dom";
import { money, phoneHref } from "../lib/format";
import type { PublicBusiness, Service } from "../lib/types";
import { addressLines, hhmm12, mapsQuery, openStatus, shopDayKey, useServices, useShop } from "./shop";

const PROMISES: [string, string][] = [
  ["A written estimate first", "You see the parts, labor, and total before any work starts, and nothing extra happens without your OK."],
  ["You talk to the mechanic", "The person on the phone is the person working on your car. No service-writer relay."],
  ["See what we found", "Worn parts get explained, and kept for you if you want to look at them."],
  ["Records that follow the car", "Every visit is kept on file by vehicle, so the next repair starts with the history."],
];

export function Home() {
  const { data: shop } = useShop();
  const { data: services } = useServices();
  if (!shop) return <div className="min-h-[60vh]" />;
  return (
    <>
      <Hero shop={shop} />
      {services && services.length > 0 && <ServiceList services={services} />}
      <section className="border-t border-line">
        <div className="mx-auto max-w-6xl px-4 py-12">
          <h2 className="font-display text-4xl font-bold">How the work gets done here</h2>
          <div className="mt-6 grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
            {PROMISES.map(([title, text]) => (
              <div key={title} className="border-t-4 border-steel pt-3">
                <h3 className="font-display text-2xl font-semibold">{title}</h3>
                <p className="mt-1 text-steel-2">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
      <Reviews shop={shop} />
      {(shop.offers_towing || shop.financing_info) && (
        <section className="bg-concrete">
          <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 md:grid-cols-2">
            {shop.offers_towing && (
              <div>
                <h2 className="font-display text-3xl font-bold">Broken down?</h2>
                <p className="mt-2 whitespace-pre-wrap">{shop.towing_info || "Call us and we'll help you get the car to the shop."}</p>
                {shop.phone && <a href={phoneHref(shop.phone)} className="mt-3 inline-block font-semibold underline underline-offset-4">Call {shop.phone}</a>}
              </div>
            )}
            {shop.financing_info && (
              <div>
                <h2 className="font-display text-3xl font-bold">Paying for repairs</h2>
                <p className="mt-2 whitespace-pre-wrap">{shop.financing_info}</p>
              </div>
            )}
          </div>
        </section>
      )}
      <Location shop={shop} />
    </>
  );
}

function Hero({ shop }: { shop: PublicBusiness }) {
  const status = openStatus(shop);
  const lines = addressLines(shop);
  const maps = mapsQuery(shop);
  return (
    <section className="mx-auto grid max-w-6xl gap-8 px-4 pt-10 pb-12 md:grid-cols-[1.4fr_1fr] md:items-center md:pt-16">
      <div>
        {shop.service_area && <p className="text-lg text-steel-2">{shop.service_area}</p>}
        <h1 className="mt-2 font-display text-[56px] leading-[0.95] font-bold sm:text-[76px]">{shop.name}</h1>
        <p className="mt-4 max-w-xl text-xl">
          Repairs, maintenance, and diagnostics, done by the mechanic you talk to.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/book" className="inline-flex min-h-14 items-center rounded-md border border-safety-deep bg-safety px-6 text-lg font-semibold">
            Book an appointment
          </Link>
          <Link to="/book?estimate=1" className="inline-flex min-h-14 items-center rounded-md border border-steel px-6 text-lg font-semibold">
            Request an estimate
          </Link>
        </div>
      </div>

      {/* The sign on the shop door: are they open, and where. */}
      <aside aria-label="Hours and location" className="rounded-lg bg-steel p-5 text-white">
        {status && (
          <p className="flex items-center gap-3 font-display text-3xl font-bold">
            <span aria-hidden="true" className={`inline-block h-4 w-4 rounded-full ${status.open ? "bg-[#3fbf6f]" : "bg-[#d0473f]"}`} />
            {status.open ? "Open now" : "Closed now"}
          </p>
        )}
        {status?.line && <p className="mt-1 text-white/85">{status.line}</p>}
        {shop.phone && (
          <a href={phoneHref(shop.phone)} className="mt-4 block font-display text-4xl font-bold text-safety">
            {shop.phone}
          </a>
        )}
        <div className="mt-4 border-t border-white/15 pt-4 text-white/85">
          {lines.map((l) => <p key={l}>{l}</p>)}
          {maps && (
            <a href={`https://www.google.com/maps/dir/?api=1&destination=${maps}`} rel="noopener noreferrer"
              className="mt-2 inline-block min-h-10 content-center font-semibold text-white underline underline-offset-4">
              Get directions
            </a>
          )}
        </div>
        <WeekStrip shop={shop} />
      </aside>
    </section>
  );
}

function WeekStrip({ shop }: { shop: PublicBusiness }) {
  const order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  if (!Object.values(shop.hours).some(Boolean)) return null;
  const todayKey = shopDayKey(shop.timezone);
  return (
    <table className="mt-4 w-full border-t border-white/15 pt-2 text-[15px]">
      <caption className="sr-only">Weekly hours</caption>
      <tbody>
        {order.map((d) => {
          const h = shop.hours[d];
          return (
            <tr key={d} className={d === todayKey ? "font-semibold text-white" : "text-white/75"}>
              <th scope="row" className="py-0.5 pr-3 text-left font-[inherit] capitalize">{d}</th>
              <td className="text-right">{h ? `${hhmm12(h.open)} to ${hhmm12(h.close)}` : "Closed"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ServiceList({ services }: { services: Service[] }) {
  return (
    <section className="bg-concrete">
      <div className="mx-auto max-w-6xl px-4 py-12">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="font-display text-4xl font-bold">What we work on</h2>
          <Link to="/services" className="min-h-12 content-center font-semibold underline underline-offset-4">All services</Link>
        </div>
        <ul className="mt-6 grid gap-x-8 sm:grid-cols-2 lg:grid-cols-3">
          {services.map((s) => (
            <li key={s.id} className="flex items-baseline justify-between gap-3 border-b border-line py-3">
              <Link to={`/book?service=${encodeURIComponent(s.name)}`} className="text-lg font-medium underline-offset-4 hover:underline">
                {s.name}
              </Link>
              {s.starting_price_cents !== null && <span className="num text-steel-2">from {money(s.starting_price_cents)}</span>}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Reviews({ shop }: { shop: PublicBusiness }) {
  if (!shop.testimonials.length && !shop.reviews_url) return null;
  return (
    <section className="border-t border-line">
      <div className="mx-auto max-w-6xl px-4 py-12">
        <h2 className="font-display text-4xl font-bold">What customers say</h2>
        {shop.testimonials.length > 0 && (
          <div className="mt-6 grid gap-8 md:grid-cols-3">
            {shop.testimonials.map((t, i) => (
              <figure key={i}>
                <blockquote className="text-lg">“{t.text}”</blockquote>
                <figcaption className="mt-2 font-semibold">{t.name}</figcaption>
              </figure>
            ))}
          </div>
        )}
        {shop.reviews_url && (
          <a href={shop.reviews_url} rel="noopener noreferrer" className="mt-6 inline-block min-h-12 content-center font-semibold underline underline-offset-4">
            Read more reviews
          </a>
        )}
      </div>
    </section>
  );
}

export function Location({ shop }: { shop: PublicBusiness }) {
  const q = mapsQuery(shop);
  if (!q) return null;
  return (
    <section className="border-t border-line">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-12 md:grid-cols-[1fr_2fr]">
        <div>
          <h2 className="font-display text-4xl font-bold">Find the shop</h2>
          <address className="mt-3 text-lg not-italic">
            {addressLines(shop).map((l) => <span key={l} className="block">{l}</span>)}
          </address>
          <a href={`https://www.google.com/maps/dir/?api=1&destination=${q}`} rel="noopener noreferrer"
            className="mt-3 inline-flex min-h-12 items-center rounded-md border border-steel px-5 font-semibold">
            Get directions
          </a>
        </div>
        <iframe
          title={`Map showing ${shop.name}`}
          src={`https://www.google.com/maps?q=${q}&output=embed`}
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          className="h-80 w-full rounded-lg border border-line"
        />
      </div>
    </section>
  );
}
