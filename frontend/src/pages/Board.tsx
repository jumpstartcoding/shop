import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ErrorNote, LinkButton, Loading, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { money, sentence, time } from "../lib/format";
import { WO_STATUSES, type WorkOrderCard, type WorkOrderStatus } from "../lib/types";

type BoardData = { columns: { status: WorkOrderStatus; work_orders: WorkOrderCard[] }[] };

export function Board() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["board"],
    queryFn: () => api.get<BoardData>("/work-orders/board"),
    refetchInterval: 60_000,
  });
  const move = useMutation({
    mutationFn: ({ id, status }: { id: number; status: WorkOrderStatus }) => api.post(`/work-orders/${id}/status`, { status }),
  });

  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorNote error={error} />;

  const flow = WO_STATUSES.filter((s) => s !== "cancelled");
  const total = data.columns.reduce((n, c) => n + c.work_orders.length, 0);

  return (
    <>
      <PageHeader title="Board" sub={`${total} job${total === 1 ? "" : "s"} open or finished this week`}
        actions={<LinkButton to="/admin/work-orders/new" variant="primary">New work order</LinkButton>} />
      <ErrorNote error={move.error} />
      {/* Phones: stacked lanes. Wide screens: columns that scroll sideways. */}
      <div className="space-y-4 lg:-mx-4 lg:flex lg:gap-3 lg:space-y-0 lg:overflow-x-auto lg:px-4 lg:pb-4">
        {data.columns.map((col) => (
          <section key={col.status} aria-label={sentence(col.status)} className="lg:w-72 lg:shrink-0">
            <h2 className="mb-2 flex items-baseline justify-between border-b-2 border-steel pb-1 font-display text-xl font-semibold">
              {sentence(col.status)}
              <span className="num text-steel-2">{col.work_orders.length}</span>
            </h2>
            {col.work_orders.length === 0 ? (
              <p className="hidden py-3 text-[15px] text-steel-3 lg:block">Empty</p>
            ) : (
              <ul className="space-y-2">
                {col.work_orders.map((w) => {
                  const next = flow[flow.indexOf(w.status as (typeof flow)[number]) + 1];
                  return (
                    <li key={w.id} className={`rounded-md border bg-sheet ${w.status === "ready_for_pickup" ? "border-safety-deep border-l-[6px]" : "border-line"}`}>
                      <Link to={`/admin/work-orders/${w.id}`} className="block px-3 pt-2 pb-1">
                        <p className="font-semibold">{w.vehicle_name}</p>
                        <p className="text-[15px] text-steel-2">{w.customer_name}, {w.number}</p>
                        {w.concern && <p className="mt-1 line-clamp-2 text-[15px]">{w.concern}</p>}
                        <p className="num mt-1 text-lg">
                          {money(w.total_cents)}
                          {w.promised_at && <span className="ml-2 font-sans text-[15px] text-steel-2">promised {time(w.promised_at)}</span>}
                        </p>
                      </Link>
                      {next === "completed" ? (
                        <Link to={`/admin/work-orders/${w.id}`}
                          className="block min-h-12 content-center border-t border-line px-3 text-[15px] font-medium hover:bg-concrete">
                          Close out with checklist
                        </Link>
                      ) : next && (
                        <button
                          className="min-h-12 w-full border-t border-line px-3 text-left text-[15px] font-medium hover:bg-concrete disabled:opacity-50"
                          disabled={move.isPending}
                          onClick={() => move.mutate({ id: w.id, status: next })}
                        >
                          Move to {sentence(next).toLowerCase()}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        ))}
      </div>
    </>
  );
}
