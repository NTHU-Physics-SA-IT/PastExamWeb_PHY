import assert from "node:assert/strict";
import test from "node:test";

import {
  evaluatePageviewsRange,
  normalizeRedirectedDateUrl,
} from "./capture-umami-helpers.mjs";

const DAY_MS = 24 * 60 * 60 * 1000;

test("normalizes the redirected pathname without returning to the entry path", () => {
  const requestedUrl = new URL(
    "https://analytics.example/share/entry?date=90day",
  );
  const redirectedUrl = new URL(
    "https://analytics.example/share/dashboard?view=overview",
  );

  const result = normalizeRedirectedDateUrl(requestedUrl, redirectedUrl);

  assert.equal(result.needsNavigation, true);
  assert.equal(result.previousDate, "missing");
  assert.equal(result.url.origin, redirectedUrl.origin);
  assert.equal(result.url.pathname, "/share/dashboard");
  assert.equal(result.url.searchParams.get("view"), "overview");
  assert.equal(result.url.searchParams.get("date"), "90day");
});

test("does not navigate again when the redirected URL already has 90day", () => {
  const requestedUrl = new URL(
    "https://analytics.example/share/entry?date=90day",
  );
  const redirectedUrl = new URL(
    "https://analytics.example/share/dashboard?date=90day",
  );

  const result = normalizeRedirectedDateUrl(requestedUrl, redirectedUrl);

  assert.equal(result.needsNavigation, false);
  assert.equal(result.previousDate, "90day");
  assert.equal(result.url.toString(), redirectedUrl.toString());
});

test("rejects a redirected URL on another origin", () => {
  assert.throws(
    () =>
      normalizeRedirectedDateUrl(
        new URL("https://analytics.example/share/entry?date=90day"),
        new URL("https://other.example/share/dashboard"),
      ),
    /origin/i,
  );
});

function pageviewsUrl({ startAt, endAt, unit }) {
  const url = new URL("https://analytics.example/api/pageviews");
  url.searchParams.set("startAt", String(startAt));
  url.searchParams.set("endAt", String(endAt));
  url.searchParams.set("unit", unit);
  return url;
}

test("accepts a successful 91-day calendar-boundary pageviews range", () => {
  const startAt = Date.UTC(2026, 4, 23, 16);
  const result = evaluatePageviewsRange(
    pageviewsUrl({
      startAt,
      endAt: startAt + 91 * DAY_MS - 1,
      unit: "day",
    }),
    200,
  );

  assert.equal(result.relevant, true);
  assert.equal(result.valid, true);
  assert.equal(result.unit, "day");
  assert.equal(result.spanDays, 91);
});

test("ignores a pageviews-shaped request from another origin", () => {
  const startAt = Date.UTC(2026, 4, 23, 16);
  const result = evaluatePageviewsRange(
    pageviewsUrl({
      startAt,
      endAt: startAt + 91 * DAY_MS - 1,
      unit: "day",
    }),
    200,
    "https://dashboard.example",
  );

  assert.equal(result.relevant, false);
  assert.equal(result.valid, false);
  assert.equal(result.reason, "origin-mismatch");
});

test("rejects the observed 25-hour hourly fallback range", () => {
  const startAt = Date.UTC(2026, 7, 21, 5);
  const result = evaluatePageviewsRange(
    pageviewsUrl({
      startAt,
      endAt: startAt + 25 * 60 * 60 * 1000 - 1,
      unit: "hour",
    }),
    200,
  );

  assert.equal(result.relevant, true);
  assert.equal(result.valid, false);
  assert.equal(result.unit, "hour");
  assert.equal(result.spanDays, 1.042);
});

test("rejects wrong units, failed responses, and malformed or absurd timestamps", () => {
  const startAt = Date.UTC(2026, 4, 23, 16);
  const wrongUnit = evaluatePageviewsRange(
    pageviewsUrl({
      startAt,
      endAt: startAt + 91 * DAY_MS - 1,
      unit: "hour",
    }),
    200,
  );
  const failed = evaluatePageviewsRange(
    pageviewsUrl({
      startAt,
      endAt: startAt + 91 * DAY_MS - 1,
      unit: "day",
    }),
    500,
  );
  const malformed = evaluatePageviewsRange(
    pageviewsUrl({ startAt: "not-a-time", endAt: "also-bad", unit: "day" }),
    200,
  );
  const absurd = evaluatePageviewsRange(
    pageviewsUrl({
      startAt,
      endAt: startAt + 365 * DAY_MS,
      unit: "day",
    }),
    200,
  );

  assert.equal(wrongUnit.valid, false);
  assert.equal(failed.valid, false);
  assert.equal(malformed.valid, false);
  assert.equal(malformed.spanDays, "unavailable");
  assert.equal(absurd.valid, false);
  assert.equal(absurd.reason, "span-mismatch");
});
