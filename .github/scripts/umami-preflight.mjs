import { appendFileSync } from "node:fs";

const shareUrl = process.env.UMAMI_SHARE_URL?.trim();
const outputFile = process.env.GITHUB_OUTPUT;
const summaryFile = process.env.GITHUB_STEP_SUMMARY;

function append(file, content) {
  if (file) appendFileSync(file, `${content}\n`);
}

if (!shareUrl) {
  append(outputFile, "enabled=false");
  append(
    summaryFile,
    [
      "### Umami screenshot skipped",
      "",
      "`UMAMI_SHARE_URL` is not configured. Create an anonymous Umami share link and add it as a repository Secret to enable screenshot generation.",
    ].join("\n"),
  );
  console.log("Umami screenshot skipped: UMAMI_SHARE_URL is not configured.");
  process.exit(0);
}

let parsed;
try {
  parsed = new URL(shareUrl);
} catch {
  append(
    summaryFile,
    "### Umami screenshot failed\n\n`UMAMI_SHARE_URL` is not a valid URL.",
  );
  console.error("UMAMI_SHARE_URL is not a valid URL.");
  process.exit(1);
}

if (
  parsed.protocol !== "https:" ||
  !parsed.hostname ||
  parsed.username ||
  parsed.password ||
  parsed.pathname === "/"
) {
  append(
    summaryFile,
    "### Umami screenshot failed\n\n`UMAMI_SHARE_URL` must be an HTTPS public share-page URL without embedded credentials.",
  );
  console.error(
    "UMAMI_SHARE_URL must be an HTTPS public share-page URL without embedded credentials.",
  );
  process.exit(1);
}

append(outputFile, "enabled=true");
append(
  summaryFile,
  "### Umami screenshot enabled\n\nA configured public share URL passed preflight.",
);
console.log("UMAMI_SHARE_URL passed preflight.");
