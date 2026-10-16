import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { api } from "../lib/api";
import { dateTime } from "../lib/format";
import { shrinkPhoto } from "../lib/photos";
import type { Photo, PhotoEntity } from "../lib/types";
import { Button, ErrorNote, Field, Modal } from "./ui";

/**
 * Thumbnails plus an "Add photo" tile that opens the phone's camera (or photo library).
 * Pass `photos` when the parent already has them (inspection items); otherwise the strip
 * loads its own.
 */
export function PhotoStrip({
  entityType,
  entityId,
  photos,
  label = "Add photo",
  readOnly,
}: {
  entityType: PhotoEntity;
  entityId: number;
  photos?: Photo[];
  label?: string;
  readOnly?: boolean;
}) {
  const inputId = useId();
  const [open, setOpen] = useState<Photo | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const own = useQuery({
    queryKey: ["photos", entityType, entityId],
    queryFn: () => api.get<Photo[]>("/photos", { entity_type: entityType, entity_id: entityId }),
    enabled: photos === undefined,
  });
  const list = photos ?? own.data ?? [];

  const add = useMutation({
    mutationFn: async (files: File[]) => {
      for (let i = 0; i < files.length; i++) {
        setProgress(files.length > 1 ? `Uploading ${i + 1} of ${files.length}…` : "Uploading…");
        const blob = await shrinkPhoto(files[i]);
        await api.upload<Photo>("/photos", blob, { entity_type: entityType, entity_id: entityId });
      }
    },
    onSettled: () => setProgress(null),
  });

  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-2" aria-label="Photos">
        {list.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              onClick={() => setOpen(p)}
              className="relative block h-24 w-24 overflow-hidden rounded-md border border-line bg-concrete"
              aria-label={`Photo${p.caption ? `: ${p.caption}` : ""}. Open`}
            >
              <img src={p.thumb_url} alt="" loading="lazy" className="h-full w-full object-cover" />
              {!p.customer_visible && (
                <span className="absolute inset-x-0 bottom-0 bg-steel/85 px-1 text-[12px] font-semibold text-white">Shop only</span>
              )}
            </button>
          </li>
        ))}
        {!readOnly && (
          <li>
            <label
              htmlFor={inputId}
              className={`flex h-24 w-24 cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed border-steel-3 text-center text-[15px] font-semibold text-steel hover:border-steel hover:bg-concrete ${add.isPending ? "pointer-events-none opacity-60" : ""}`}
            >
              <CameraIcon />
              {add.isPending ? "Working" : label}
            </label>
            <input
              id={inputId}
              type="file"
              accept="image/*"
              capture="environment"
              multiple
              className="sr-only"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? []);
                e.target.value = "";
                if (files.length) add.mutate(files);
              }}
            />
          </li>
        )}
      </ul>
      {progress && <p role="status" className="text-[15px] text-steel-2">{progress}</p>}
      <ErrorNote error={add.error instanceof Error && !("status" in add.error) ? add.error.message : add.error} />
      {open && <PhotoModal photo={open} onClose={() => setOpen(null)} readOnly={readOnly} />}
    </div>
  );
}

function PhotoModal({ photo, onClose, readOnly }: { photo: Photo; onClose: () => void; readOnly?: boolean }) {
  const [caption, setCaption] = useState(photo.caption ?? "");
  const [visible, setVisible] = useState(photo.customer_visible);
  const [confirming, setConfirming] = useState(false);
  const save = useMutation({
    mutationFn: () => api.patch<Photo>(`/photos/${photo.id}`, { caption: caption.trim() || null, customer_visible: visible }),
    onSuccess: onClose,
  });
  const remove = useMutation({ mutationFn: () => api.del(`/photos/${photo.id}`), onSuccess: onClose });
  return (
    <Modal title="Photo" onClose={onClose}>
      <div className="space-y-4">
        <a href={photo.url} target="_blank" rel="noopener" className="block">
          <img src={photo.url} alt={photo.caption ?? "Photo"} className="max-h-[55dvh] w-full rounded-md bg-concrete object-contain" />
        </a>
        <p className="text-[15px] text-steel-2">Taken {dateTime(photo.created_at)}</p>
        {!readOnly && (
          <>
            <ErrorNote error={save.error ?? remove.error} />
            <Field label="Caption" hint="Shown under the photo on the customer's report.">
              {(p) => <input {...p} className="field" maxLength={300} value={caption} onChange={(e) => setCaption(e.target.value)} />}
            </Field>
            <label className="flex min-h-12 items-center gap-3">
              <input type="checkbox" className="h-6 w-6" checked={visible} onChange={(e) => setVisible(e.target.checked)} />
              Show this photo to the customer
            </label>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>Save</Button>
              {confirming ? (
                <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>Yes, remove it</Button>
              ) : (
                <Button variant="quiet" onClick={() => setConfirming(true)}>Remove photo</Button>
              )}
            </div>
            {confirming && (
              <p className="text-[15px] text-steel-2">
                It disappears from the app and from customer links. Copies already in a signed document stay in that document.
              </p>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

function CameraIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="mb-1 h-7 w-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
      <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  );
}
