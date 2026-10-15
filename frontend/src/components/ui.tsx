import { type ButtonHTMLAttributes, type ReactNode, useId } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../lib/api";
import { sentence } from "../lib/format";

type Variant = "primary" | "secondary" | "quiet" | "danger";

const variants: Record<Variant, string> = {
  primary: "bg-safety text-steel border-safety-deep hover:bg-[#ffd21f] font-semibold",
  secondary: "bg-sheet text-steel border-line hover:border-steel font-medium",
  quiet: "bg-transparent text-steel border-transparent hover:bg-black/5 font-medium",
  danger: "bg-sheet text-signal border-signal/50 hover:bg-signal-wash font-medium",
};

export function Button({
  variant = "secondary",
  busy,
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
      className={`inline-flex min-h-12 items-center justify-center gap-2 rounded-md border px-4 text-base transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
    >
      {busy ? "Working…" : children}
    </button>
  );
}

export function LinkButton({
  to,
  variant = "secondary",
  className = "",
  children,
}: {
  to: string;
  variant?: Variant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      className={`inline-flex min-h-12 items-center justify-center gap-2 rounded-md border px-4 text-base ${variants[variant]} ${className}`}
    >
      {children}
    </Link>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (props: { id: string; "aria-invalid"?: boolean; "aria-describedby"?: string }) => ReactNode;
}) {
  const id = useId();
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-[15px] font-medium text-steel-2">
        {label}
      </label>
      {children({ id, "aria-invalid": error ? true : undefined, "aria-describedby": describedBy })}
      {error ? (
        <p id={`${id}-err`} className="text-[15px] text-signal">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-[15px] text-steel-2">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** A white working surface. Sections inside are separated by rules, not more boxes. */
export function Sheet({ title, action, children, className = "" }: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 rounded-lg border border-line bg-sheet ${className}`}>
      {(title || action) && (
        <header className="flex min-h-14 items-center justify-between gap-3 border-b border-line px-4">
          {title && <h2 className="font-display text-xl font-semibold">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

const tone: Record<string, string> = {
  go: "bg-go-wash text-go border-go/30",
  stop: "bg-signal-wash text-signal border-signal/30",
  hold: "bg-hold-wash text-hold border-hold/30",
  plain: "bg-concrete text-steel-2 border-line",
  ready: "bg-safety text-steel border-safety-deep",
};

const statusTone: Record<string, keyof typeof tone> = {
  paid: "go",
  approved: "go",
  completed: "go",
  confirmed: "go",
  succeeded: "go",
  ready_for_pickup: "ready",
  overdue: "stop",
  declined: "stop",
  cancelled: "stop",
  no_show: "stop",
  void: "plain",
  waiting_approval: "hold",
  sent: "hold",
  viewed: "hold",
  partially_paid: "hold",
  requested: "hold",
  quality_check: "hold",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded border px-2 py-0.5 text-[14px] font-semibold ${tone[statusTone[status] ?? "plain"]}`}
    >
      {sentence(status)}
    </span>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message =
    typeof error === "string"
      ? error
      : error instanceof ApiError
        ? error.message
        : "Something went wrong and nothing was saved. Try again.";
  return (
    <p role="alert" className="rounded-md border border-signal/40 bg-signal-wash px-4 py-3 text-signal">
      {message}
    </p>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="px-4 py-10 text-center text-steel-2" role="status">
      {label}…
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-8 text-center text-steel-2">{children}</div>;
}

export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="font-display text-[34px] leading-tight font-bold">{title}</h1>
        {sub && <div className="mt-0.5 text-steel-2">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

/** A tappable row in a list: whole row is the link target, min 56px tall. */
export function RowLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <li>
      <Link
        to={to}
        className="flex min-h-14 items-center gap-3 border-b border-line px-4 py-3 last:border-b-0 hover:bg-concrete/60"
      >
        {children}
      </Link>
    </li>
  );
}

export function Dl({ rows }: { rows: [string, ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-2 px-4 py-3">
      {shown.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-steel-2">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Internal notes are visually distinct everywhere so they're never mistaken for customer text. */
export function InternalNote({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <div className="border-l-4 border-steel bg-concrete px-3 py-2">
      <p className="text-[14px] font-semibold text-steel-2">Internal note (customers never see this)</p>
      <p className="whitespace-pre-wrap">{children}</p>
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-steel/50 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <div className="max-h-[92dvh] w-full overflow-y-auto rounded-t-xl bg-sheet sm:max-w-lg sm:rounded-xl">
        <header className="sticky top-0 flex min-h-14 items-center justify-between border-b border-line bg-sheet px-4">
          <h2 className="font-display text-xl font-semibold">{title}</h2>
          <Button variant="quiet" onClick={onClose} aria-label="Close">
            Close
          </Button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
