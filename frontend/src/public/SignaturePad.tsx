import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";

export type SignaturePadHandle = { toDataUrl: () => string | null; clear: () => void };

/**
 * Finger or mouse signature. Draws with pointer events (touch, pen, mouse), scales for
 * high-density screens, and exports a PNG. `touch-action: none` keeps the page from
 * scrolling while signing on a phone.
 */
export const SignaturePad = forwardRef<SignaturePadHandle, { label: string; onChange?: (hasInk: boolean) => void }>(
  function SignaturePad({ label, onChange }, ref) {
    const canvas = useRef<HTMLCanvasElement>(null);
    const drawing = useRef(false);
    const last = useRef<{ x: number; y: number } | null>(null);
    const [ink, setInk] = useState(false);

    const setup = useCallback(() => {
      const c = canvas.current;
      if (!c) return;
      const ratio = Math.max(window.devicePixelRatio || 1, 1);
      const { width, height } = c.getBoundingClientRect();
      c.width = Math.round(width * ratio);
      c.height = Math.round(height * ratio);
      const ctx = c.getContext("2d")!;
      ctx.scale(ratio, ratio);
      ctx.lineWidth = 2.6;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#1f2a30";
      setInk(false);
      onChange?.(false);
    }, [onChange]);

    useEffect(() => {
      setup();
      // Rotating a phone changes the canvas size; start fresh rather than distort strokes.
      window.addEventListener("orientationchange", setup);
      return () => window.removeEventListener("orientationchange", setup);
    }, [setup]);

    useImperativeHandle(ref, () => ({
      clear: setup,
      toDataUrl: () => (ink && canvas.current ? canvas.current.toDataURL("image/png") : null),
    }));

    const point = (e: React.PointerEvent) => {
      const r = canvas.current!.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    return (
      <div>
        <div className="relative rounded-md border-2 border-steel bg-white">
          <canvas
            ref={canvas}
            role="img"
            aria-label={label}
            className="block h-44 w-full touch-none select-none"
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              drawing.current = true;
              last.current = point(e);
              const ctx = canvas.current!.getContext("2d")!;
              ctx.beginPath();
              ctx.arc(last.current.x, last.current.y, 1.2, 0, Math.PI * 2);
              ctx.fillStyle = "#1f2a30";
              ctx.fill();
            }}
            onPointerMove={(e) => {
              if (!drawing.current || !last.current) return;
              const p = point(e);
              const ctx = canvas.current!.getContext("2d")!;
              ctx.beginPath();
              ctx.moveTo(last.current.x, last.current.y);
              ctx.lineTo(p.x, p.y);
              ctx.stroke();
              last.current = p;
              if (!ink) {
                setInk(true);
                onChange?.(true);
              }
            }}
            onPointerUp={() => {
              drawing.current = false;
              last.current = null;
            }}
            onPointerCancel={() => {
              drawing.current = false;
              last.current = null;
            }}
          />
          <div aria-hidden="true" className="pointer-events-none absolute inset-x-4 bottom-8 border-b border-dashed border-steel-3" />
          {!ink && (
            <p aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-1/3 text-center text-steel-3">
              Sign here with your finger
            </p>
          )}
        </div>
        <button type="button" onClick={setup} className="mt-1 min-h-11 px-1 font-medium underline underline-offset-4">
          Clear signature
        </button>
      </div>
    );
  },
);
