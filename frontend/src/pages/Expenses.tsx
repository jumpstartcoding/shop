import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { PhotoStrip } from "../components/Photos";
import { Button, Empty, ErrorNote, Field, Loading, Modal, PageHeader, Sheet } from "../components/ui";
import { api } from "../lib/api";
import { centsToInput, date, localDateInput, money, sentence, toCents } from "../lib/format";
import { EXPENSE_CATEGORIES, type Expense, type ExpenseCategory, type ExpenseList, type Vendor } from "../lib/types";
import { DateRange, useRange } from "./Reports";

export function ExpensesPage() {
  const range = useRange("this_month");
  const [category, setCategory] = useState<ExpenseCategory | "">("");
  const [editing, setEditing] = useState<Expense | "new" | null>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ["expenses", range.start, range.end, category],
    queryFn: () => api.get<ExpenseList>("/expenses", { start: range.start, end: range.end, category: category || undefined }),
  });
  return (
    <div className="space-y-4">
      <PageHeader title="Expenses" actions={<Button variant="primary" onClick={() => setEditing("new")}>Add expense</Button>} />
      <DateRange range={range} />
      <Field label="Category">
        {(p) => (
          <select {...p} className="field sm:max-w-xs" value={category} onChange={(e) => setCategory(e.target.value as ExpenseCategory | "")}>
            <option value="">All categories</option>
            {EXPENSE_CATEGORIES.map((c) => <option key={c} value={c}>{sentence(c)}</option>)}
          </select>
        )}
      </Field>
      {isLoading ? <Loading /> : error || !data ? <ErrorNote error={error} /> : (
        <>
          <section aria-label="Totals" className="rounded-lg bg-steel px-4 py-3 text-white">
            <p className="text-white/75">Total, {date(data.start)} to {date(data.end)}</p>
            <p className="num text-3xl font-semibold">{money(data.total_cents)}</p>
            {Object.keys(data.by_category).length > 1 && (
              <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[15px] text-white/85">
                {Object.entries(data.by_category).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0)).map(([c, cents]) => (
                  <li key={c}>{sentence(c)} <span className="num font-semibold text-white">{money(cents)}</span></li>
                ))}
              </ul>
            )}
          </section>
          <Sheet>
            {data.items.length === 0 ? <Empty>No expenses in this range.</Empty> : (
              <ul>
                {data.items.map((e) => (
                  <li key={e.id}>
                    <button type="button" onClick={() => setEditing(e)} className="flex min-h-14 w-full items-center gap-3 border-b border-line px-4 py-3 text-left last:border-0 hover:bg-concrete/60">
                      <span className="min-w-0 flex-1">
                        <span className="block font-semibold">{e.description || e.vendor_name || sentence(e.category)}</span>
                        <span className="block text-[15px] text-steel-2">
                          {[date(e.expense_date), sentence(e.category), e.description ? e.vendor_name : null, e.receipts.length ? "receipt" : null].filter(Boolean).join(", ")}
                        </span>
                      </span>
                      <span className="num text-lg">{money(e.amount_cents)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Sheet>
        </>
      )}
      {editing && <ExpenseModal expense={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ExpenseModal({ expense, onClose }: { expense: Expense | null; onClose: () => void }) {
  const vendors = useQuery({ queryKey: ["vendors"], queryFn: () => api.get<Vendor[]>("/vendors") });
  const [d, setD] = useState({
    expense_date: expense?.expense_date ?? localDateInput(new Date()),
    category: expense?.category ?? ("parts" as ExpenseCategory),
    amount: centsToInput(expense?.amount_cents),
    vendor_id: expense?.vendor_id ? String(expense.vendor_id) : "",
    vendor_name: expense && !expense.vendor_id ? expense.vendor_name ?? "" : "",
    description: expense?.description ?? "",
  });
  const [created, setCreated] = useState<Expense | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = (k: keyof typeof d) => (e: { target: { value: string } }) => setD({ ...d, [k]: e.target.value });
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      expense ? api.patch<Expense>(`/expenses/${expense.id}`, body) : api.post<Expense>("/expenses", body),
    onSuccess: (e) => (expense ? onClose() : setCreated(e)),
  });
  const remove = useMutation({ mutationFn: () => api.del(`/expenses/${expense!.id}`), onSuccess: onClose });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    const cents = toCents(d.amount);
    if (!cents) return setLocalError("Enter the amount, like 129.99.");
    save.mutate({
      expense_date: d.expense_date,
      category: d.category,
      amount_cents: cents,
      vendor_id: d.vendor_id ? Number(d.vendor_id) : null,
      vendor_name: d.vendor_id ? null : d.vendor_name.trim() || null,
      description: d.description.trim() || null,
    });
  };

  const current = expense ?? created;
  return (
    <Modal title={expense ? "Edit expense" : created ? "Expense added" : "Add expense"} onClose={onClose}>
      {!created && (
        <form onSubmit={submit} className="space-y-4">
          <ErrorNote error={localError ?? save.error ?? remove.error} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Date">{(p) => <input {...p} type="date" required className="field" value={d.expense_date} onChange={set("expense_date")} />}</Field>
            <Field label="Amount">{(p) => <input {...p} required inputMode="decimal" className="field num text-lg" value={d.amount} onChange={set("amount")} />}</Field>
          </div>
          <Field label="Category">
            {(p) => (
              <select {...p} className="field" value={d.category} onChange={set("category")}>
                {EXPENSE_CATEGORIES.map((c) => <option key={c} value={c}>{sentence(c)}</option>)}
              </select>
            )}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Supplier">
              {(p) => (
                <select {...p} className="field" value={d.vendor_id} onChange={set("vendor_id")}>
                  <option value="">Other / none</option>
                  {vendors.data?.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
              )}
            </Field>
            {!d.vendor_id && <Field label="Paid to">{(p) => <input {...p} maxLength={120} className="field" value={d.vendor_name} onChange={set("vendor_name")} />}</Field>}
          </div>
          <Field label="What for">{(p) => <input {...p} maxLength={500} className="field" value={d.description} onChange={set("description")} />}</Field>
          <Button type="submit" variant="primary" className="w-full" busy={save.isPending}>{expense ? "Save changes" : "Add expense"}</Button>
        </form>
      )}
      {current && (
        <div className={`space-y-3 ${expense ? "mt-5 border-t border-line pt-4" : ""}`}>
          {created && <p role="status" className="rounded-md bg-go-wash px-3 py-2 text-go">Saved: {money(created.amount_cents)}, {sentence(created.category)}.</p>}
          <p className="font-semibold">Receipt</p>
          <p className="text-[15px] text-steel-2">Snap the paper receipt so you don't have to keep it.</p>
          <PhotoStrip entityType="expense" entityId={current.id} label="Add receipt" />
          {created && <Button variant="primary" className="w-full" onClick={onClose}>Done</Button>}
        </div>
      )}
      {expense && (
        <div className="mt-4">
          {confirmDelete ? (
            <div className="flex flex-wrap items-center gap-2">
              <span>Delete this expense?</span>
              <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>Delete</Button>
              <Button variant="quiet" onClick={() => setConfirmDelete(false)}>Keep</Button>
            </div>
          ) : (
            <Button variant="quiet" onClick={() => setConfirmDelete(true)}>Delete expense</Button>
          )}
        </div>
      )}
    </Modal>
  );
}
