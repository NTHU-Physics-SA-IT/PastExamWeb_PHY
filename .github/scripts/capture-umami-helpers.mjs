export const UMAMI_SCREENSHOT_DATE = "90day";

const DAY_MS = 24 * 60 * 60 * 1000;
// Umami presets use inclusive local-calendar boundaries. The production
// 90day request spans 91 UTC days, while DST can shift a boundary by an hour.
// This narrow window accepts those calendar effects and rejects hourly ranges.
const MIN_90DAY_SPAN_DAYS = 89;
const MAX_90DAY_SPAN_DAYS = 92;
const SAFE_DATE_ENUM =
  /^(?:\d+(?:hour|day|week|month|year)|0(?:day|week|month|year)|all|custom)$/;
const SAFE_UNITS = new Set([
  "minute",
  "hour",
  "day",
  "week",
  "month",
  "year",
]);

function round(value, places = 3) {
  if (!Number.isFinite(value)) return "unavailable";
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
}

function safeDateEnum(value) {
  if (value == null || value === "") return "missing";
  return SAFE_DATE_ENUM.test(value) ? value : "other-redacted";
}

function safeUnit(value) {
  if (!value) return "unavailable";
  return SAFE_UNITS.has(value) ? value : "other-redacted";
}

function parseTimestamp(value) {
  if (!/^\d+(?:\.\d+)?$/.test(value ?? "")) return null;
  let numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  if (numeric > 1e9 && numeric < 1e11) numeric *= 1000;
  const date = new Date(numeric);
  return Number.isFinite(+date) ? date : null;
}

export function normalizeRedirectedDateUrl(requestedUrl, redirectedUrl) {
  const requested = new URL(requestedUrl);
  const redirected = new URL(redirectedUrl);

  if (redirected.origin !== requested.origin) {
    throw new Error("Umami share redirect changed origin.");
  }

  const previousDate = safeDateEnum(redirected.searchParams.get("date"));
  if (previousDate === UMAMI_SCREENSHOT_DATE) {
    return { needsNavigation: false, previousDate, url: redirected };
  }

  redirected.searchParams.set("date", UMAMI_SCREENSHOT_DATE);
  return { needsNavigation: true, previousDate, url: redirected };
}

export function evaluatePageviewsRange(
  requestUrl,
  responseStatus,
  expectedOrigin,
) {
  let parsed;
  try {
    parsed = new URL(requestUrl);
  } catch {
    return {
      relevant: false,
      valid: false,
      reason: "request-url-invalid",
      spanDays: "unavailable",
      status: "unavailable",
      unit: "unavailable",
    };
  }

  if (
    (expectedOrigin && parsed.origin !== expectedOrigin) ||
    !/(?:^|\/)pageviews?(?:\/|$)/i.test(parsed.pathname)
  ) {
    return {
      relevant: false,
      valid: false,
      reason:
        expectedOrigin && parsed.origin !== expectedOrigin
          ? "origin-mismatch"
          : "not-pageviews",
      spanDays: "unavailable",
      status: responseStatus,
      unit: "unavailable",
    };
  }

  const startAt = parseTimestamp(parsed.searchParams.get("startAt"));
  const endAt = parseTimestamp(parsed.searchParams.get("endAt"));
  const unit = safeUnit(parsed.searchParams.get("unit"));
  const spanDays =
    startAt && endAt ? (+endAt - +startAt) / DAY_MS : Number.NaN;
  const roundedSpanDays = round(spanDays);
  const successful =
    Number.isInteger(responseStatus) &&
    responseStatus >= 200 &&
    responseStatus < 300;

  let reason = "ok";
  if (!successful) reason = "response-unsuccessful";
  else if (!startAt || !endAt || !(spanDays > 0))
    reason = "timestamps-invalid";
  else if (unit !== "day") reason = "unit-mismatch";
  else if (
    spanDays < MIN_90DAY_SPAN_DAYS ||
    spanDays > MAX_90DAY_SPAN_DAYS
  )
    reason = "span-mismatch";

  return {
    relevant: true,
    valid: reason === "ok",
    reason,
    spanDays: roundedSpanDays,
    status: Number.isInteger(responseStatus)
      ? responseStatus
      : "unavailable",
    unit,
  };
}
