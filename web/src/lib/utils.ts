import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const TIME_ZONE_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const DATE_TIME_PATTERN = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/;

function parseDateTime(value: string | number | Date) {
  if (value instanceof Date || typeof value === "number") {
    return new Date(value);
  }
  const raw = value.trim();
  if (!raw) {
    return null;
  }
  const normalized = DATE_TIME_PATTERN.test(raw) && !TIME_ZONE_PATTERN.test(raw)
    ? `${raw.replace(" ", "T")}Z`
    : raw;
  return new Date(normalized);
}

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatBeijingDateTime(value?: string | number | Date | null, options?: { seconds?: boolean; short?: boolean }) {
  if (value === undefined || value === null || value === "") {
    return "—";
  }
  const date = parseDateTime(value);
  if (!date || Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    year: options?.short ? undefined : "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: options?.seconds ? "2-digit" : undefined,
    hour12: false,
  }).format(date);
}

export function formatBeijingTime(value?: string | number | Date | null) {
  if (value === undefined || value === null || value === "") {
    return "—";
  }
  const date = parseDateTime(value);
  if (!date || Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}
