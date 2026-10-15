import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { PublicBusiness, Service } from "../lib/types";

export function useShop() {
  return useQuery({
    queryKey: ["public-business"],
    queryFn: () => api.get<PublicBusiness>("/public/business"),
    staleTime: 5 * 60_000,
  });
}

export function useServices() {
  return useQuery({
    queryKey: ["public-services"],
    queryFn: () => api.get<Service[]>("/public/services"),
    staleTime: 5 * 60_000,
  });
}

export const DAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;
export const DAY_NAMES: Record<string, string> = {
  mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday",
};

export function hhmm12(t: string): string {
  const [h, m] = t.split(":").map(Number);
  const suffix = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return m ? `${h12}:${String(m).padStart(2, "0")} ${suffix}` : `${h12} ${suffix}`;
}

/** Day and minutes-since-midnight in the shop's own time zone, wherever the visitor is. */
function shopClock(tz: string): { day: number; minutes: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const day = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(get("weekday"));
  return { day, minutes: Number(get("hour")) * 60 + Number(get("minute")) };
}

export function shopDayKey(tz: string): string {
  return DAY_KEYS[shopClock(tz).day];
}

const toMin = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
};

export function openStatus(shop: PublicBusiness): { open: boolean; line: string } | null {
  const hours = shop.hours ?? {};
  if (!Object.values(hours).some(Boolean)) return null;
  const { day, minutes } = shopClock(shop.timezone);
  const today = hours[DAY_KEYS[day]];
  if (today && minutes >= toMin(today.open) && minutes < toMin(today.close)) {
    return { open: true, line: `Until ${hhmm12(today.close)} today` };
  }
  for (let i = 0; i < 8; i++) {
    const d = (day + i) % 7;
    const h = hours[DAY_KEYS[d]];
    if (!h) continue;
    if (i === 0 && minutes >= toMin(h.open)) continue;
    const when = i === 0 ? "today" : i === 1 ? "tomorrow" : DAY_NAMES[DAY_KEYS[d]];
    return { open: false, line: `Opens ${when} at ${hhmm12(h.open)}` };
  }
  return { open: false, line: "" };
}

export function addressLines(shop: PublicBusiness): string[] {
  const city = [shop.city, shop.state].filter(Boolean).join(", ");
  return [shop.address_line1, shop.address_line2, [city, shop.postal_code].filter(Boolean).join(" ")].filter(
    (x): x is string => !!x,
  );
}

export function mapsQuery(shop: PublicBusiness): string | null {
  const lines = addressLines(shop);
  return lines.length ? encodeURIComponent(`${shop.name}, ${lines.join(", ")}`) : null;
}
