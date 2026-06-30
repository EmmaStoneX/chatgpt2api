import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const TIME_ZONE_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const DATE_TIME_PATTERN = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/;

type BeijingTimeOptions = {
  seconds?: boolean;
  short?: boolean;
  sourceTimeZone?: "beijing" | "utc";
};

function parseDateTime(value: string | number | Date, options?: Pick<BeijingTimeOptions, "sourceTimeZone">) {
  if (value instanceof Date) {
    return new Date(value);
  }
  if (typeof value === "number") {
    return new Date(Math.abs(value) < 1_000_000_000_000 ? value * 1000 : value);
  }
  const raw = value.trim();
  if (!raw) {
    return null;
  }
  if (/^\d{10}(?:\.\d+)?$/.test(raw) || /^\d{13}$/.test(raw)) {
    return parseDateTime(Number(raw), options);
  }
  const normalized = DATE_TIME_PATTERN.test(raw) && !TIME_ZONE_PATTERN.test(raw)
    ? `${raw.replace(" ", "T")}${options?.sourceTimeZone === "utc" ? "Z" : "+08:00"}`
    : raw;
  return new Date(normalized);
}

export function normalizeImageAssetUrl(url: string) {
  const value = String(url || "").trim();
  if (!value || typeof window === "undefined") {
    return value;
  }
  try {
    const parsed = new URL(value, window.location.origin);
    const isLocalHost = ["127.0.0.1", "localhost", "0.0.0.0"].includes(parsed.hostname);
    const sameHost = parsed.hostname === window.location.hostname;
    const isImagePath = parsed.pathname.startsWith("/images/") || parsed.pathname.startsWith("/image-thumbnails/");
    if (isImagePath && (isLocalHost || sameHost)) {
      return `${window.location.origin}${parsed.pathname}${parsed.search}${parsed.hash}`;
    }
  } catch {
    return value;
  }
  return value;
}

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getBeijingTimestamp(value?: string | number | Date | null, options?: Pick<BeijingTimeOptions, "sourceTimeZone">) {
  if (value === undefined || value === null || value === "") {
    return 0;
  }
  const date = parseDateTime(value, options);
  return date && Number.isFinite(date.getTime()) ? date.getTime() : 0;
}

export function formatBeijingDateTime(value?: string | number | Date | null, options?: BeijingTimeOptions) {
  if (value === undefined || value === null || value === "") {
    return "—";
  }
  const date = parseDateTime(value, options);
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

export function formatBeijingTime(value?: string | number | Date | null, options?: Pick<BeijingTimeOptions, "sourceTimeZone">) {
  if (value === undefined || value === null || value === "") {
    return "—";
  }
  const date = parseDateTime(value, options);
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
