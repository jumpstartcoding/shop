import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { dateTime, phoneHref, sentence } from "../lib/format";
import type { AuthorizationState, DocumentTrail as Trail, SendResult } from "../lib/types";
import { Button, ErrorNote, Modal, Sheet } from "./ui";

/**
 * Send a document to the customer: emails the link when there's an address on file, and
 * always shows the link so it can be texted or copied. Most shop customers answer texts.
 */
export function SendButton({
  path,
  label,
  noun,
  email,
  phone,
  shopName,
  variant = "primary",
  disabled,
}: {
  path: string;
  label: string;
  noun: string;
  email: string | null;
  phone: string | null;
  shopName?: string;
  variant?: "primary" | "secondary";
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [useEmail, setUseEmail] = useState(!!email);
  const [copied, setCopied] = useState(false);
  const send = useMutation({ mutationFn: () => api.post<SendResult>(path, { email: useEmail && !!email }) });
  const result = send.data;
  const smsBody = result ? encodeURIComponent(`${shopName ? shopName + ": " : ""}your ${noun} is ready to review: ${result.link}`) : "";

  return (
    <>
      <Button variant={variant} disabled={disabled} onClick={() => { send.reset(); setCopied(false); setOpen(true); }}>
        {label}
      </Button>
      {open && (
        <Modal title={label} onClose={() => setOpen(false)}>
          {!result ? (
            <div className="space-y-4">
              <p>The customer gets a private link to review the {noun}{noun === "invoice" ? "" : ", sign, and approve it"} on their phone. No account needed.</p>
              {email ? (
                <label className="flex min-h-12 items-center gap-3">
                  <input type="checkbox" className="h-6 w-6" checked={useEmail} onChange={(e) => setUseEmail(e.target.checked)} />
                  Email the link to {email}
                </label>
              ) : (
                <p className="rounded-md bg-concrete px-3 py-2 text-steel-2">No email on file. You'll get a link to text or copy.</p>
              )}
              <ErrorNote error={send.error} />
              <Button variant="primary" className="w-full" busy={send.isPending} onClick={() => send.mutate()}>
                Create link{useEmail && email ? " and email it" : ""}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              {result.email && (
                <p role="status" className={`rounded-md px-3 py-2 ${result.email.status === "sent" ? "bg-go-wash text-go" : result.email.status === "failed" ? "bg-signal-wash text-signal" : "bg-concrete text-steel-2"}`}>
                  {result.email.status === "failed"
                    ? `The ${noun} was sent and the link works, but the email couldn't be delivered. Text the link instead.`
                    : result.email.message}
                </p>
              )}
              <div>
                <p className="mb-1 text-[15px] font-medium text-steel-2">Customer link</p>
                <input readOnly className="field text-[15px]" value={result.link} onFocus={(e) => e.target.select()} aria-label="Customer link" />
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {phone && (
                  <a href={`${phoneHref(phone)?.replace("tel:", "sms:")}?&body=${smsBody}`}
                    className="inline-flex min-h-12 items-center justify-center rounded-md border border-safety-deep bg-safety px-4 font-semibold">
                    Text the link
                  </a>
                )}
                <Button onClick={async () => {
                  try { await navigator.clipboard.writeText(result.link); setCopied(true); } catch { setCopied(false); }
                }}>
                  {copied ? "Copied" : "Copy link"}
                </Button>
              </div>
              <Button variant="quiet" className="w-full" onClick={() => setOpen(false)}>Done</Button>
            </div>
          )}
        </Modal>
      )}
    </>
  );
}

const AUTH_TEXT: Record<AuthorizationState["status"], string> = {
  none: "Not sent for signature yet.",
  awaiting: "Link sent. Waiting for the customer.",
  approved: "Approved",
  declined: "Declined",
  changed_since_signed: "Changed since the customer signed. Send it again for a new signature.",
};

export function AuthorizationBanner({ state }: { state: AuthorizationState | null }) {
  if (!state) return null;
  const tone =
    state.status === "approved" ? "border-go bg-go-wash text-go"
      : state.status === "declined" || state.status === "changed_since_signed" ? "border-signal bg-signal-wash text-signal"
        : state.status === "awaiting" ? "border-hold bg-hold-wash text-hold" : "border-line bg-concrete text-steel-2";
  return (
    <p className={`rounded-md border-l-[6px] px-3 py-2 ${tone}`}>
      <strong>{AUTH_TEXT[state.status]}</strong>
      {state.signed_at && (state.status === "approved" || state.status === "declined") && (
        <> by {state.signer_name}, {dateTime(state.signed_at)} ({state.method === "drawn" ? "signed on their phone" : state.method === "typed" ? "typed signature" : state.method === "link" ? "through their link" : `by ${state.method?.replace("_", " ")}`})</>
      )}
    </p>
  );
}

/** Signed copies, links, and emails for one document: the paper trail. */
export function DocumentTrail({ entityType, entityId }: { entityType: string; entityId: number }) {
  const { data, error } = useQuery({
    queryKey: ["trail", entityType, entityId],
    queryFn: () => api.get<Trail>("/documents", { entity_type: entityType, entity_id: entityId }),
  });
  const revoke = useMutation({ mutationFn: (id: number) => api.post(`/links/${id}/revoke`) });
  if (error) return <ErrorNote error={error} />;
  if (!data || (!data.versions.length && !data.emails.length)) return null;
  return (
    <Sheet title="Sent and signed">
      <ul>
        {data.authorizations.map((a) => (
          <li key={`a${a.id}`} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className={`font-semibold ${a.status === "superseded" ? "text-steel-2 line-through" : ""}`}>
                {sentence(a.decision)} by {a.signer_name}
              </p>
              <p className="text-[15px] text-steel-2">
                {dateTime(a.signed_at)}, {a.recorded_by_shop ? `recorded by you (${a.method.replace("_", " ")})` : a.method === "link" ? "through their link" : `${a.method} signature`}
                {a.ip_address && !a.recorded_by_shop ? `, from ${a.ip_address}` : ""}
                {a.status === "superseded" && ". No longer applies; the document changed."}
              </p>
              {a.note && <p className="text-[15px]">“{a.note}”</p>}
            </div>
            {a.signed_version_id && (
              <a className="min-h-12 content-center font-medium underline underline-offset-4" target="_blank" rel="noopener"
                href={`/api/documents/${a.signed_version_id}/pdf`}>
                Signed PDF
              </a>
            )}
          </li>
        ))}
        {data.versions.filter((v) => v.kind === "issued").map((v) => (
          <li key={`v${v.id}`} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium">Version {v.version} as sent</p>
              <p className="text-[15px] text-steel-2">{dateTime(v.created_at)}</p>
            </div>
            <a className="min-h-12 content-center font-medium underline underline-offset-4" target="_blank" rel="noopener" href={`/api/documents/${v.id}/pdf`}>
              PDF
            </a>
          </li>
        ))}
        {data.links.map((l) => (
          <li key={`l${l.id}`} className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium">Link {l.active ? "active" : "closed"}</p>
              <p className="text-[15px] text-steel-2">
                Created {dateTime(l.created_at)}. {l.view_count ? `Opened ${l.view_count} time${l.view_count === 1 ? "" : "s"}, first ${dateTime(l.first_viewed_at)}.` : "Not opened yet."}
              </p>
            </div>
            {l.active && <Button variant="quiet" busy={revoke.isPending} onClick={() => revoke.mutate(l.id)}>Turn off</Button>}
          </li>
        ))}
        {data.emails.map((e) => (
          <li key={`e${e.id}`} className="border-b border-line px-4 py-3 last:border-0">
            <p className="font-medium">Email {e.status === "sent" ? "sent" : e.status === "failed" ? "failed" : "not sent"}{e.to ? ` to ${e.to}` : ""}</p>
            <p className="text-[15px]">“{e.subject}”</p>
            <p className="text-[15px] text-steel-2">{dateTime(e.created_at)}{e.error && e.status !== "sent" ? `. ${e.error}` : ""}</p>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
