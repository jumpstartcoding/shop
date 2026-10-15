import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/admin", label: "Today", end: true },
  { to: "/admin/board", label: "Board" },
  { to: "/admin/calendar", label: "Calendar" },
  { to: "/admin/customers", label: "Customers" },
  { to: "/admin/invoices", label: "Invoices" },
  { to: "/admin/estimates", label: "Estimates" },
  { to: "/admin/settings", label: "Settings" },
];

// The five that fit a phone's bottom bar; the rest live in the "More" sheet.
const PHONE_NAV = NAV.slice(0, 4);

type SearchResults = {
  customers: { id: number; name: string; phone: string | null; archived: boolean }[];
  vehicles: { id: number; customer_id: number; name: string; vin: string | null; license_plate: string | null; owner: string }[];
  documents: { kind: string; id: number; number: string; status: string; customer_name: string; total_cents: number }[];
};

const DOC_PATH: Record<string, string> = {
  work_order: "work-orders",
  estimate: "estimates",
  invoice: "invoices",
};

function SearchBox({ autoFocus, onDone }: { autoFocus?: boolean; onDone?: () => void }) {
  const id = useId();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 200);
    return () => clearTimeout(t);
  }, [q]);
  const { data, isFetching } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.get<SearchResults>("/search", { q: debounced }),
    enabled: debounced.length >= 2,
  });
  const empty =
    data && !data.customers.length && !data.vehicles.length && !data.documents.length;

  return (
    <div className="relative">
      <label htmlFor={id} className="sr-only">
        Search customers, vehicles, VINs, plates, or document numbers
      </label>
      <input
        id={id}
        type="search"
        autoFocus={autoFocus}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Name, phone, VIN, plate, or number"
        autoComplete="off"
        className="field"
      />
      {debounced.length >= 2 && (
        <div className="absolute inset-x-0 top-full z-40 mt-1 max-h-[70dvh] overflow-y-auto rounded-md border border-line bg-sheet shadow-lg">
          {isFetching && !data && <p className="px-4 py-3 text-steel-2">Searching…</p>}
          {empty && <p className="px-4 py-3 text-steel-2">Nothing matches “{debounced}”.</p>}
          {data && (
            <ul onClick={() => { setQ(""); onDone?.(); }}>
              {data.customers.map((c) => (
                <ResultRow key={`c${c.id}`} to={`/admin/customers/${c.id}`} title={c.name} sub={c.phone ?? "Customer"} />
              ))}
              {data.vehicles.map((v) => (
                <ResultRow
                  key={`v${v.id}`}
                  to={`/admin/vehicles/${v.id}`}
                  title={v.name}
                  sub={[v.owner, v.license_plate, v.vin].filter(Boolean).join(", ")}
                />
              ))}
              {data.documents.map((d) => (
                <ResultRow
                  key={`${d.kind}${d.id}`}
                  to={`/admin/${DOC_PATH[d.kind]}/${d.id}`}
                  title={d.number}
                  sub={`${d.customer_name}, ${money(d.total_cents)}`}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function ResultRow({ to, title, sub }: { to: string; title: string; sub: string }) {
  return (
    <li>
      <Link to={to} className="block min-h-12 border-b border-line px-4 py-2 last:border-0 hover:bg-concrete">
        <span className="block font-medium">{title}</span>
        <span className="block text-[15px] text-steel-2">{sub}</span>
      </Link>
    </li>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  const [sheet, setSheet] = useState<null | "search" | "more">(null);
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setSheet(null);
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [location.pathname]);

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-safety focus:p-3">
        Skip to content
      </a>

      {/* Desktop / tablet sidebar */}
      <aside className="hidden bg-steel text-white md:flex md:min-h-dvh md:flex-col">
        <Link to="/admin" className="block px-5 pt-6 pb-5">
          <ShopMark />
        </Link>
        <nav aria-label="Main" className="flex-1 px-2">
          {NAV.map((n) => (
            <NavItem key={n.to} {...n} />
          ))}
        </nav>
        <div className="border-t border-white/15 px-5 py-4 text-[15px]">
          <p className="text-white/70">{user?.name}</p>
          <button onClick={logout} className="mt-1 min-h-10 underline underline-offset-4">
            Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 border-b border-line bg-concrete/95 backdrop-blur">
          <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2">
            <Link to="/admin" className="md:hidden" aria-label="Today">
              <ShopMark compact />
            </Link>
            <div className="hidden flex-1 md:block">
              <SearchBox />
            </div>
            <div className="flex-1 md:hidden" />
            <button
              className="flex min-h-12 min-w-12 items-center justify-center rounded-md border border-line bg-sheet md:hidden"
              onClick={() => setSheet("search")}
              aria-label="Search"
            >
              <SearchIcon />
            </button>
            <NewMenu />
          </div>
        </header>

        <main id="main" ref={mainRef} tabIndex={-1} className="mx-auto max-w-5xl px-4 pt-5 pb-28 outline-none md:pb-10">
          <Outlet />
        </main>
      </div>

      {/* Phone bottom bar: thumb reach while the other hand is busy */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-white/10 bg-steel pb-[env(safe-area-inset-bottom)] text-white md:hidden"
      >
        {PHONE_NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              `flex min-h-16 flex-col items-center justify-center text-[15px] ${isActive ? "bg-white/10 font-semibold text-safety" : "text-white/85"}`
            }
          >
            {n.label}
          </NavLink>
        ))}
        <button className="min-h-16 text-[15px] text-white/85" onClick={() => setSheet("more")}>
          More
        </button>
      </nav>

      {sheet === "search" && (
        <Overlay onClose={() => setSheet(null)} label="Search">
          <SearchBox autoFocus onDone={() => setSheet(null)} />
        </Overlay>
      )}
      {sheet === "more" && (
        <Overlay onClose={() => setSheet(null)} label="More">
          <ul className="divide-y divide-line rounded-md border border-line bg-sheet">
            {NAV.slice(4).map((n) => (
              <li key={n.to}>
                <Link to={n.to} className="block min-h-14 px-4 py-4 font-medium">
                  {n.label}
                </Link>
              </li>
            ))}
            <li>
              <button onClick={logout} className="block min-h-14 w-full px-4 py-4 text-left font-medium">
                Sign out {user ? `(${user.name})` : ""}
              </button>
            </li>
          </ul>
        </Overlay>
      )}
    </div>
  );
}

function NavItem({ to, label, end }: { to: string; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `mb-1 flex min-h-12 items-center rounded-md border-l-4 px-3 ${isActive ? "border-safety bg-white/10 font-semibold" : "border-transparent text-white/85 hover:bg-white/5"}`
      }
    >
      {label}
    </NavLink>
  );
}

function NewMenu() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const items: [string, string][] = [
    ["Customer", "/admin/customers/new"],
    ["Work order", "/admin/work-orders/new"],
    ["Estimate", "/admin/estimates/new"],
    ["Invoice", "/admin/invoices/new"],
    ["Appointment", "/admin/calendar?new=1"],
  ];
  return (
    <div className="relative">
      <button
        className="inline-flex min-h-12 items-center rounded-md border border-safety-deep bg-safety px-4 font-semibold"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((o) => !o)}
      >
        New
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <ul role="menu" className="absolute right-0 z-50 mt-1 w-56 rounded-md border border-line bg-sheet py-1 shadow-lg">
            {items.map(([label, to]) => (
              <li key={to} role="none">
                <button
                  role="menuitem"
                  className="block min-h-12 w-full px-4 text-left hover:bg-concrete"
                  onClick={() => {
                    setOpen(false);
                    navigate(to);
                  }}
                >
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Overlay({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 bg-concrete p-4 md:hidden" role="dialog" aria-modal="true" aria-label={label}>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold">{label}</h2>
        <button onClick={onClose} className="min-h-12 px-3 font-medium">
          Close
        </button>
      </div>
      {children}
    </div>
  );
}

function ShopMark({ compact }: { compact?: boolean }) {
  const { data } = useQuery({
    queryKey: ["public-business"],
    queryFn: () => api.get<{ name: string }>("/public/business"),
    staleTime: 5 * 60_000,
  });
  return (
    <span className="flex items-center gap-2">
      <img src="/favicon.svg" alt="" className="h-8 w-8" />
      {!compact && <span className="font-display text-xl leading-tight font-bold">{data?.name ?? "Shop"}</span>}
    </span>
  );
}

function SearchIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.5 15.5 21 21" strokeLinecap="round" />
    </svg>
  );
}
