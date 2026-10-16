// The app in a browser against a real engine (see global-setup.ts): open media, detect, edit by
// transcript, review suggestions, zoom, export and render, in both themes.
import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { copyFileSync, existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { basename, extname, join } from "node:path";

const { port, token, media } = JSON.parse(process.env.CB_E2E ?? "{}") as { port: number; token: string; media: string };

async function boot(page: Page) {
  await page.goto(`/?port=${port}&token=${token}`);
  await expect(page.locator(".status.ok")).toBeVisible();
}

/**
 * A private copy of a fixture (and of its saved project, if any). The engine keeps projects open
 * between tests, so reusing one file would leak state across tests, repeats and retries.
 */
function fresh(file: string): string {
  const ext = extname(file);
  const name = `${basename(file, ext)}-${randomUUID().slice(0, 8)}${ext}`;
  copyFileSync(join(media, file), join(media, name));
  const project = join(media, `${file}.claudebolt.json`);
  if (existsSync(project)) {
    const p = JSON.parse(readFileSync(project, "utf-8"));
    p.id = randomUUID().replace(/-/g, "").slice(0, 12);
    for (const src of p.sources) src.path = join(media, name);
    writeFileSync(join(media, `${name}.claudebolt.json`), JSON.stringify(p));
  }
  return name;
}

/** Open a fresh copy of a fixture by typing its path on the start screen, as a browser user would. */
async function open(page: Page, file: string): Promise<string> {
  const name = fresh(file);
  await boot(page);
  await page.getByPlaceholder("Paste a file path and press Enter").fill(join(media, name));
  await page.keyboard.press("Enter");
  await expect(page.locator(".workspace")).toBeVisible();
  await expect(page.locator(".waveform")).not.toHaveClass(/loading/);
  return name;
}

const pill = (page: Page) => page.locator(".dock-head .pill");
const regions = (page: Page) => page.locator('.waveform [part~="region"]');

async function seek(page: Page, t: number) {
  await page.evaluate((t) => {
    const m = document.querySelector<HTMLMediaElement>("video, audio")!;
    m.currentTime = t;
  }, t);
}

test("start screen connects to the engine and remembers the theme", async ({ page }) => {
  await boot(page);
  await expect(page.getByRole("heading", { name: /Cut the dead air/ })).toBeVisible();
  await page.getByRole("radio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("radio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("a missing file shows an error that can be dismissed", async ({ page }) => {
  await boot(page);
  await page.getByPlaceholder("Paste a file path and press Enter").fill(join(media, "nope.mp4"));
  await page.keyboard.press("Enter");
  const toast = page.locator(".toast.error");
  await expect(toast).toContainText("not found");
  await toast.getByRole("button", { name: "Dismiss" }).click();
  await expect(toast).toHaveCount(0);
});

test("opening a video shows the player and the file name", async ({ page }) => {
  const name = await open(page, "video.mp4");
  await expect(page.locator(".viewer video")).toHaveCount(1);
  await expect(page.locator(".crumb")).toHaveText(name);
  await expect(page.locator(".legend")).toContainText("Run detection");
});

test("detecting silences marks the timeline, and undo restores it", async ({ page }) => {
  const name = await open(page, "detect.wav");
  await expect(page.locator(".audio-card")).toContainText(name);
  await expect(pill(page)).toHaveText("−0%");
  await page.getByRole("button", { name: "Detect silences" }).click();
  await expect(pill(page)).not.toHaveText("−0%");
  await expect(page.locator(".legend")).toContainText("Silence");
  await expect(regions(page).first()).toBeAttached();
  await expect(page.locator(".inspector-foot .result")).toContainText("removed");
  await expect(page.locator(".inspector-foot .hint")).toContainText("than the last run");

  await page.getByRole("button", { name: "Undo" }).click();
  await expect(pill(page)).toHaveText("−0%");
  await expect(regions(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(pill(page)).not.toHaveText("−0%");
});

test("speech mode dims the loudness threshold and says why", async ({ page }) => {
  await open(page, "speech.wav");
  await page.getByRole("radio", { name: "Speech" }).click();
  await expect(page.locator(".section.off")).toBeVisible();
  await expect(page.locator(".inspector")).toContainText("Speech mode ignores the loudness threshold.");
  await page.getByRole("radio", { name: "Volume" }).click();
  await expect(page.locator(".section.off")).toHaveCount(0);
});

test("the transcript follows playback and words can be cut", async ({ page }) => {
  await open(page, "talk.wav");
  const words = page.locator(".words .w");
  await expect(words).toHaveText(["Hello ", "um ", "world. ", "Again ", "there. "]);

  await seek(page, 3.1);
  await expect(page.locator(".w.now")).toHaveText("Again ");
  await expect(page.locator(".w.past")).toHaveCount(3);

  // scrolling by hand pauses follow; the pill brings it back
  await page.locator(".tab-body .scroll").hover();
  await page.mouse.wheel(0, 120);
  await expect(page.getByRole("button", { name: "Follow" })).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Back to playhead" }).click();
  await expect(page.getByRole("button", { name: "Follow" })).toHaveAttribute("aria-pressed", "true");

  await words.nth(1).click();
  await expect(page.locator(".selbar")).toContainText("1 word selected");
  await page.keyboard.press("d");
  await expect(words.nth(1)).toHaveClass(/gone/);
  await expect(page.locator(".selbar")).toHaveCount(0);
  await expect(pill(page)).not.toHaveText("−0%");
});

test("filler suggestions can be reviewed and cut, and show up in activity", async ({ page }) => {
  await open(page, "fillers.wav");
  await page.getByRole("button", { name: "Find fillers & retakes" }).click();
  await expect(page.getByRole("tab", { name: /Suggestions/ })).toHaveAttribute("aria-selected", "true");
  const props = page.locator(".prop");
  await expect(props).toHaveCount(1);
  await expect(props.first()).toContainText("Filler");
  await expect(props.first().locator(".prop-text")).toHaveText("um");

  await props.first().getByRole("button", { name: "Cut" }).click();
  await expect(page.getByText("No pending suggestions")).toBeVisible();
  await expect(page.locator(".legend")).toContainText("Filler");
  await expect(page.locator(".tab .live")).toBeVisible();

  await page.getByRole("tab", { name: /Activity/ }).click();
  await expect(page.locator(".feed-item").first()).toContainText("You");
  await page.locator(".feed-item").first().getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(".legend")).not.toContainText("Filler");
});

test("the timeline zooms with buttons, keys and back to fit", async ({ page }) => {
  await open(page, "zoom.wav");
  const width = () =>
    page.evaluate(() => document.querySelector(".waveform > div")!.shadowRoot!.querySelector(".scroll")!.scrollWidth);
  const fit = await width();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect.poll(width).toBeGreaterThan(fit * 2);
  await page.getByRole("button", { name: "Fit whole file" }).click();
  await expect.poll(width).toBe(fit);
  await page.locator(".workspace").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("=");
  await expect.poll(width).toBeGreaterThan(fit);
  await page.keyboard.press("0");
  await expect.poll(width).toBe(fit);
});

test("export writes an edit decision list for other editors", async ({ page }) => {
  await open(page, "export.mp4");
  await page.getByRole("button", { name: "Detect silences" }).click();
  await expect(pill(page)).not.toHaveText("−0%");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Export" });
  await dialog.locator(".choice", { hasText: "EDL" }).click();
  const done = dialog.locator(".notice.ok");
  await expect(done).toContainText(".edl");
  const path = (await done.textContent())!.replace(/^.*?Wrote /, "").trim();
  expect(statSync(path).size).toBeGreaterThan(0);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("render produces the edited audio file", async ({ page }) => {
  const name = await open(page, "render.wav");
  await page.getByRole("button", { name: "Detect silences" }).click();
  await expect(pill(page)).not.toHaveText("−0%");
  await page.keyboard.press("Control+e");
  const dialog = page.getByRole("dialog", { name: "Export" });
  await dialog.locator(".choice", { hasText: "WAV" }).click();
  await dialog.getByRole("button", { name: "Render", exact: true }).click();
  await expect(dialog.locator(".notice.ok")).toContainText("Saved", { timeout: 60_000 });
  const out = join(media, name.replace(/\.wav$/, ".edited.wav"));
  expect(existsSync(out)).toBe(true);
  expect(statSync(out).size).toBeGreaterThan(1000);
});

test("settings lists speech models and closes with Escape", async ({ page }) => {
  await boot(page);
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.locator(".list-row", { hasText: "small.en" })).toBeVisible();
  await expect(dialog.getByRole("radio", { name: "System" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});
