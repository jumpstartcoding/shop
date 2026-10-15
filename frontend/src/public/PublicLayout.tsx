import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { phoneHref } from "../lib/format";
import { DAY_NAMES, addressLines, hhmm12, useShop } from "./shop";

export function PublicLayout() {
  const { data: shop } = useShop();
  const [menu, setMenu] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => {
    setMenu(false);
    window.scrollTo(0, 0);
  }, [pathname]);
  useEffect(() => {
    if (shop) document.title = shop.name;
  }, [shop]);

  const nav = [
    ["/services", "Services"],
    ["/about", "About"],
    ["/contact", "Contact"],
  ] as const;

  return (
    <div className="min-h-dvh bg-sheet">
      <a href="#content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-safety focus:p-3">
        Skip to content
      </a>
      <header className="border-b border-line bg-sheet">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <Link to="/" className="flex min-h-12 items-center gap-3">
            {shop?.has_logo ? (
              <img src="/api/public/logo" alt="" className="h-10 w-auto" />
            ) : (
              <img src="/favicon.svg" alt="" className="h-9 w-9" />
            )}
            <span className="font-display text-2xl leading-none font-bold">{shop?.name ?? ""}</span>
          </Link>
          <nav aria-label="Main" className="ml-auto hidden items-center gap-1 md:flex">
            {nav.map(([to, label]) => (
              <NavLink key={to} to={to}
                className={({ isActive }) => `min-h-12 content-center px-3 font-medium ${isActive ? "underline decoration-safety decoration-4 underline-offset-8" : ""}`}>
                {label}
              </NavLink>
            ))}
            {shop?.phone && (
              <a href={phoneHref(shop.phone)} className="ml-2 min-h-12 content-center px-3 font-semibold">{shop.phone}</a>
            )}
            <Link to="/book" className="ml-2 inline-flex min-h-12 items-center rounded-md border border-safety-deep bg-safety px-5 font-semibold">
              Book an appointment
            </Link>
          </nav>
          <button className="ml-auto min-h-12 rounded-md border border-line px-4 font-medium md:hidden" aria-expanded={menu}
            onClick={() => setMenu((m) => !m)}>
            Menu
          </button>
        </div>
        {menu && (
          <nav aria-label="Main" className="border-t border-line md:hidden">
            {nav.map(([to, label]) => (
              <Link key={to} to={to} className="block min-h-14 border-b border-line px-4 py-4 text-lg font-medium">{label}</Link>
            ))}
            <Link to="/book" className="block min-h-14 bg-safety px-4 py-4 text-lg font-semibold">Book an appointment</Link>
          </nav>
        )}
      </header>

      <main id="content">
        <Outlet />
      </main>

      {/* Phones: call and book always one thumb away. */}
      {shop?.phone && (
        <div className="sticky bottom-0 z-30 grid grid-cols-2 border-t border-steel bg-steel pb-[env(safe-area-inset-bottom)] md:hidden">
          <a href={phoneHref(shop.phone)} className="flex min-h-14 items-center justify-center font-semibold text-white">Call the shop</a>
          <Link to="/book" className="flex min-h-14 items-center justify-center bg-safety font-semibold">Book</Link>
        </div>
      )}

      <footer className="bg-steel text-white">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 sm:grid-cols-3">
          <div>
            <p className="font-display text-2xl font-bold">{shop?.name}</p>
            {shop && addressLines(shop).map((l) => <p key={l} className="text-white/80">{l}</p>)}
            {shop?.phone && <a className="mt-2 block font-semibold text-safety" href={phoneHref(shop.phone)}>{shop.phone}</a>}
            {shop?.email && <a className="block text-white/80 underline-offset-4 hover:underline" href={`mailto:${shop.email}`}>{shop.email}</a>}
          </div>
          <div>
            <p className="mb-1 font-display text-xl font-semibold">Hours</p>
            <table className="text-white/85">
              <tbody>
                {shop && Object.keys(DAY_NAMES).map((d) => {
                  const h = shop.hours[d];
                  return (
                    <tr key={d}>
                      <th scope="row" className="pr-4 text-left font-normal">{DAY_NAMES[d]}</th>
                      <td>{h ? `${hhmm12(h.open)} to ${hhmm12(h.close)}` : "Closed"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="space-y-1">
            <Link className="block min-h-10 content-center underline-offset-4 hover:underline" to="/book">Book an appointment</Link>
            <Link className="block min-h-10 content-center underline-offset-4 hover:underline" to="/book?estimate=1">Request an estimate</Link>
            <Link className="block min-h-10 content-center underline-offset-4 hover:underline" to="/services">Services</Link>
            <Link className="block min-h-10 content-center underline-offset-4 hover:underline" to="/contact">Contact</Link>
            {Object.entries(shop?.social_links ?? {}).map(([k, v]) => (
              <a key={k} href={v} rel="noopener noreferrer" className="block min-h-10 content-center capitalize underline-offset-4 hover:underline">{k}</a>
            ))}
            <Link className="mt-4 block min-h-10 content-center text-[15px] text-white/60 underline-offset-4 hover:underline" to="/admin">Shop login</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
