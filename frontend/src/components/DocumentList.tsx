import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { date, money } from "../lib/format";
import type { DocumentListItem, Page } from "../lib/types";
import { Button, Empty, ErrorNote, LinkButton, Loading, PageHeader, RowLink, Sheet, StatusBadge } from "./ui";

/** Shared list screen for estimates and invoices: filter chips, search, paged rows. */
export function DocumentList({
  title,
  path,
  filters,
  newLabel,
  emptyText,
  extraQuery,
}: {
  title: string;
  path: "estimates" | "invoices";
  filters: [string, string[]][];
  newLabel: string;
  emptyText: string;
  extraQuery?: (filterIndex: number) => Record<string, string | boolean>;
}) {
  const [params, setParams] = useSearchParams();
  const initial = Math.max(
    0,
    filters.findIndex(([, s]) => s.join(",") === (params.get("status") ?? "")),
  );
  const [filter, setFilter] = useState(params.get("unpaid") ? filters.length - 1 : initial);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(1), [filter, debounced]);

  const { data, error, isLoading } = useQuery({
    queryKey: [path, filter, debounced, page],
    queryFn: () =>
      api.get<Page<DocumentListItem>>(`/${path}`, {
        status: filters[filter][1],
        q: debounced,
        page,
        page_size: 30,
        ...(extraQuery?.(filter) ?? {}),
      }),
  });

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <PageHeader title={title} actions={<LinkButton to={`/admin/${path}/new`} variant="primary">{newLabel}</LinkButton>} />
      <div className="-mx-4 mb-3 overflow-x-auto px-4">
        <div className="flex min-w-max gap-2" role="group" aria-label="Filter">
          {filters.map(([label], i) => (
            <button
              key={label}
              aria-pressed={i === filter}
              onClick={() => {
                setFilter(i);
                setParams({}, { replace: true });
              }}
              className={`min-h-12 rounded-md border px-4 font-medium ${i === filter ? "border-steel bg-steel text-white" : "border-line bg-sheet"}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <label htmlFor={`${path}-q`} className="sr-only">Search {title.toLowerCase()}</label>
      <input id={`${path}-q`} type="search" className="field mb-3" placeholder="Number or customer name" value={q} onChange={(e) => setQ(e.target.value)} />
      <Sheet>
        {isLoading ? (
          <Loading />
        ) : error ? (
          <div className="p-4"><ErrorNote error={error} /></div>
        ) : data!.items.length === 0 ? (
          <Empty>{debounced || filter ? "Nothing matches." : emptyText}</Empty>
        ) : (
          <ul>
            {data!.items.map((d) => (
              <RowLink key={d.id} to={`/admin/${path}/${d.id}`}>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{d.customer_name}</p>
                  <p className="truncate text-[15px] text-steel-2">{d.number}, {date(d.date)}, {d.vehicle_name}</p>
                </div>
                <div className="text-right">
                  <p className="num text-lg">
                    {d.balance_cents !== null && d.balance_cents > 0 && d.balance_cents !== d.total_cents
                      ? `${money(d.balance_cents)} due`
                      : money(d.total_cents)}
                  </p>
                  <StatusBadge status={d.status} />
                </div>
              </RowLink>
            ))}
          </ul>
        )}
      </Sheet>
      {pages > 1 && (
        <div className="mt-3 flex items-center justify-between">
          <Button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Newer</Button>
          <span className="text-steel-2">Page {page} of {pages}</span>
          <Button disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Older</Button>
        </div>
      )}
      <p className="mt-4 text-[15px] text-steel-2">
        Looking for a specific customer's documents? Open them from <Link className="underline" to="/admin/customers">Customers</Link>.
      </p>
    </>
  );
}
