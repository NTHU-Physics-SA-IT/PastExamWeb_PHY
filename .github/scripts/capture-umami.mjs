import { chromium } from "@playwright/test";
import sharp from "sharp";
import { mkdir, readFile, stat } from "node:fs/promises";

import {
  classifyDateFilterLabel,
  evaluatePageviewsRange,
  pageviewsEndpointFingerprint,
  safeDateEnum,
  UMAMI_SCREENSHOT_DATE,
} from "./capture-umami-helpers.mjs";

const shareUrl = process.env.UMAMI_SHARE_URL?.trim();
if (!shareUrl)
  throw new Error("UMAMI_SHARE_URL was not provided after preflight.");

let targetUrl;
try {
  targetUrl = new URL(shareUrl);
} catch {
  throw new Error("UMAMI_SHARE_URL is not a valid URL.");
}
if (
  targetUrl.protocol !== "https:" ||
  !targetUrl.hostname ||
  targetUrl.username ||
  targetUrl.password ||
  targetUrl.pathname === "/"
) {
  throw new Error(
    "UMAMI_SHARE_URL must be an HTTPS public share-page URL without embedded credentials.",
  );
}
targetUrl.searchParams.set("date", UMAMI_SCREENSHOT_DATE);

const outputDirectory = "dist/umami-assets";
const deviceScaleFactor = 2;

await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch();

async function verifyPng(path) {
  const file = await stat(path);
  const signature = (await readFile(path)).subarray(0, 8).toString("hex");
  if (file.size < 10_000 || signature !== "89504e470d0a1a0a") {
    throw new Error(`Screenshot validation failed for ${path}.`);
  }
  return file.size;
}

async function findKpiBox(page, chartBox) {
  const upstreamGrid = page
    .locator('div[style*="grid-template-columns"][style*="minmax"]')
    .first();

  if ((await upstreamGrid.count()) > 0 && (await upstreamGrid.isVisible())) {
    const box = await upstreamGrid.boundingBox();
    if (box) return box;
  }

  return page.evaluate(({ chartY }) => {
    const root = document.querySelector("main") ?? document.body;
    const candidates = [...root.querySelectorAll("div")]
      .map((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return {
          bottomGap: chartY - rect.bottom,
          childCount: element.children.length,
          height: rect.height,
          isVisible:
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            Number(style.opacity) !== 0,
          width: rect.width,
          x: rect.x,
          y: rect.y,
        };
      })
      .filter(
        (box) =>
          box.isVisible &&
          box.childCount >= 3 &&
          box.width >= 700 &&
          box.height >= 60 &&
          box.height <= 320 &&
          box.x >= 0 &&
          box.y >= 0 &&
          box.bottomGap >= -8 &&
          box.bottomGap <= 500,
      )
      .sort((a, b) => a.bottomGap - b.bottomGap || b.width - a.width);

    const best = candidates[0];
    if (!best) return null;
    return {
      x: best.x,
      y: best.y,
      width: best.width,
      height: best.height,
    };
  }, chartBox);
}

async function navigateSafely(page, url, phase) {
  let response;
  try {
    response = await page.goto(url.toString(), {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
  } catch {
    throw new Error(`Umami ${phase} navigation failed.`);
  }

  if (!response) {
    throw new Error(`Umami ${phase} navigation returned no response.`);
  }
  if (response.status() >= 400) {
    throw new Error(
      `Umami ${phase} navigation returned HTTP ${response.status()}.`,
    );
  }
  return response;
}

async function assertPublicSharePage(page) {
  let finalUrl;
  try {
    finalUrl = new URL(page.url());
  } catch {
    throw new Error("Umami share page returned an invalid final URL.");
  }

  const loginForm = page.locator('input[type="password"]:visible');
  if (
    finalUrl.origin !== targetUrl.origin ||
    finalUrl.pathname.toLowerCase().includes("login") ||
    (await loginForm.count()) > 0
  ) {
    throw new Error(
      "Umami share page redirected away from the configured public dashboard.",
    );
  }
  return finalUrl;
}

async function findDateFilterControl(page, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const candidates = page.locator(
      'button:visible,[role="combobox"]:visible',
    );
    const count = Math.min(await candidates.count(), 120);
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      const date = classifyDateFilterLabel(
        await candidate.innerText().catch(() => ""),
      );
      if (date) return { date, locator: candidate };
    }
    await page.waitForTimeout(100);
  }
  throw new Error("Unable to locate the Umami date filter safely.");
}

async function find90DayOption(page, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const candidates = page.locator(
      '[role="option"]:visible,[role="menuitem"]:visible,' +
        '[role="menuitemradio"]:visible,button:visible',
    );
    const count = Math.min(await candidates.count(), 160);
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      const date = classifyDateFilterLabel(
        await candidate.innerText().catch(() => ""),
      );
      if (date === UMAMI_SCREENSHOT_DATE) return candidate;
    }
    await page.waitForTimeout(100);
  }
  throw new Error("Unable to locate the Umami 90-day date option safely.");
}

async function select90DayRange(page) {
  try {
    const control = await findDateFilterControl(page);
    if (control.date === UMAMI_SCREENSHOT_DATE) return;

    await control.locator.click();
    const option = await find90DayOption(page);
    await option.click();
  } catch {
    throw new Error("Unable to select the Umami 90-day date range safely.");
  }
}

function observeExpectedPageviewsRange(page) {
  let matchingEvidence = null;
  let lastEvidence = null;
  let endpointFingerprint = null;

  const onResponse = (response) => {
    const evidence = evaluatePageviewsRange(
      response.url(),
      response.status(),
    );
    if (!evidence.relevant) return;
    const fingerprint = pageviewsEndpointFingerprint(response.url());
    if (
      !fingerprint ||
      (endpointFingerprint && fingerprint !== endpointFingerprint)
    ) {
      return;
    }
    endpointFingerprint ??= fingerprint;
    lastEvidence = evidence;
    if (evidence.valid) matchingEvidence = evidence;
  };
  page.on("response", onResponse);

  return {
    async waitForMatch(timeoutMs = 30000) {
      const deadline = Date.now() + timeoutMs;
      while (!matchingEvidence && Date.now() < deadline) {
        await page.waitForTimeout(100);
      }
      if (matchingEvidence) return matchingEvidence;

      if (!lastEvidence) {
        throw new Error(
          "Umami 90-day validation failed: no pageviews response observed.",
        );
      }
      throw new Error(
        `Umami 90-day validation failed: ${lastEvidence.reason}; HTTP ${lastEvidence.status}; unit ${lastEvidence.unit}; span ${lastEvidence.spanDays} days.`,
      );
    },
    reset() {
      matchingEvidence = null;
      lastEvidence = null;
    },
    stop() {
      page.off("response", onResponse);
    },
  };
}

async function capture(theme, output) {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1400 },
    deviceScaleFactor,
    colorScheme: theme,
  });

  await context.addInitScript(
    ({ selectedTheme }) => {
      localStorage.setItem("zen.theme", selectedTheme);
    },
    { selectedTheme: theme },
  );

  const page = await context.newPage();
  const rangeObserver = observeExpectedPageviewsRange(page);
  let pageErrorCount = 0;
  page.on("pageerror", () => {
    pageErrorCount += 1;
  });

  try {
    const initialResponse = await navigateSafely(
      page,
      targetUrl,
      "initial",
    );
    const redirectedUrl = await assertPublicSharePage(page);
    const redirectedDate = redirectedUrl.searchParams.get("date");
    if (redirectedDate !== UMAMI_SCREENSHOT_DATE) {
      console.log(
        `Selecting Umami date after redirect; previous date ${safeDateEnum(redirectedDate)}.`,
      );
      rangeObserver.reset();
      await select90DayRange(page);
    }

    const rangeEvidence = await rangeObserver.waitForMatch();
    const finalUrl = await assertPublicSharePage(page);
    const finalDate = finalUrl.searchParams.get("date");
    if (finalDate !== UMAMI_SCREENSHOT_DATE) {
      throw new Error(
        `Umami final date validation failed: expected ${UMAMI_SCREENSHOT_DATE}; received ${finalDate ? "other-redacted" : "missing"}.`,
      );
    }

    console.log(
      `Confirmed Umami pageviews range; HTTP ${rangeEvidence.status}; unit ${rangeEvidence.unit}; span ${rangeEvidence.spanDays} days.`,
    );

    await page.addStyleTag({
      content: `
        header,
        nav,
        aside,
        [role="navigation"],
        [data-testid*="account" i],
        [data-testid*="profile" i],
        [class*="account-menu" i],
        [class*="profile-menu" i] {
          display: none !important;
        }

        * {
          caret-color: transparent !important;
        }
      `,
    });

    const chartCanvas = page.locator("canvas:visible").first();
    await chartCanvas.waitFor({ state: "visible", timeout: 30000 });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(1500);

    const upstreamChartRegion = page
      .locator('div[style*="min-height: 520px"]')
      .filter({ has: page.locator("canvas") })
      .first();
    let chartBox = null;
    if (
      (await upstreamChartRegion.count()) > 0 &&
      (await upstreamChartRegion.isVisible())
    ) {
      chartBox = await upstreamChartRegion.boundingBox();
    }
    chartBox ??= await chartCanvas.boundingBox();
    if (!chartBox || chartBox.width <= 0 || chartBox.height <= 0) {
      throw new Error("Umami chart has invalid dimensions.");
    }

    const kpiBox = await findKpiBox(page, chartBox);
    if (!kpiBox) {
      throw new Error("Unable to locate the Umami KPI summary safely.");
    }

    const horizontalPadding = 16;
    const topPadding = 2;
    const bottomPadding = 16;

    const x = Math.max(0, Math.min(kpiBox.x, chartBox.x) - horizontalPadding);

    const y = Math.max(0, Math.min(kpiBox.y, chartBox.y) - topPadding);

    const right =
      Math.max(kpiBox.x + kpiBox.width, chartBox.x + chartBox.width) +
      horizontalPadding;

    const bottom =
      Math.max(kpiBox.y + kpiBox.height, chartBox.y + chartBox.height) +
      bottomPadding;

    const viewport = page.viewportSize();
    if (!viewport) throw new Error("Browser viewport is unavailable.");

    const clip = {
      x,
      y,
      width: Math.min(viewport.width, right) - x,
      height: Math.min(viewport.height, bottom) - y,
    };
    if (clip.width <= 0 || clip.height <= 0) {
      throw new Error("Calculated screenshot region is invalid.");
    }

    const rawScreenshot = await page.screenshot({
      animations: "disabled",
      clip,
      type: "png",
    });
    const missingTopPadding =
      (horizontalPadding - topPadding) * deviceScaleFactor;

    const { data: backgroundPixel, info: backgroundInfo } = await sharp(
      rawScreenshot,
    )
      .extract({
        left: 0,
        top: 0,
        width: 1,
        height: 1,
      })
      .raw()
      .toBuffer({ resolveWithObject: true });

    const background = {
      r: backgroundPixel[0],
      g: backgroundPixel[1],
      b: backgroundPixel[2],
      alpha: backgroundInfo.channels === 4 ? backgroundPixel[3] / 255 : 1,
    };

    await sharp(rawScreenshot)
      .extend({
        top: missingTopPadding,
        background,
      })
      .png({ compressionLevel: 9, adaptiveFiltering: true })
      .toFile(output);

    const bytes = await verifyPng(output);
    console.log(
      `Saved ${theme} screenshot (${bytes} bytes); HTTP ${initialResponse.status()}; page errors ${pageErrorCount}.`,
    );
    return await readFile(output);
  } finally {
    rangeObserver.stop();
    await context.close();
  }
}

try {
  const light = await capture(
    "light",
    `${outputDirectory}/umami-overview-light.png`,
  );
  const dark = await capture(
    "dark",
    `${outputDirectory}/umami-overview-dark.png`,
  );
  if (light.equals(dark)) {
    throw new Error("Light and dark screenshots are unexpectedly identical.");
  }
} finally {
  await browser.close();
}
