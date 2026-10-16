/**
 * Shrink a photo on the phone before it's uploaded: a 12-megapixel camera shot (3-5 MB)
 * becomes a ~1600 px JPEG of a few hundred KB. Faster on a weak bay signal, cheaper to
 * store, and still sharp enough to show a scored rotor. The server re-encodes it again and
 * strips location data; this step is about speed, not trust.
 */
const MAX_SIDE = 1600;

export async function shrinkPhoto(file: File): Promise<Blob> {
  let source: ImageBitmap | HTMLImageElement;
  try {
    // Applies the camera's rotation, so portrait shots stay portrait.
    source = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    source = await loadImage(file);
  }
  const scale = Math.min(1, MAX_SIDE / Math.max(source.width, source.height));
  const w = Math.round(source.width * scale);
  const h = Math.round(source.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser can't prepare photos.");
  ctx.drawImage(source, 0, 0, w, h);
  if ("close" in source) source.close();
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.82));
  if (!blob) throw new Error("This photo couldn't be prepared. Try taking it again.");
  return blob;
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("This browser can't open that photo format. Take the photo with the camera button instead."));
    };
    img.src = url;
  });
}
