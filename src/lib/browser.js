const { chromium } = require("playwright");

const REALISTIC_CHROME_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36";

async function createBrowserContext() {
  const browser = await chromium.launch({
    headless: true,
    args: ["--disable-blink-features=AutomationControlled"]
  });

  const context = await browser.newContext({
    userAgent: REALISTIC_CHROME_UA,
    locale: "en-US",
    timezoneId: "America/New_York",
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true
  });

  await context.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", {
      get: () => undefined
    });
  });

  await context.route("**/*", async (route) => {
    const resourceType = route.request().resourceType();
    if (["image", "media", "font", "stylesheet"].includes(resourceType)) {
      await route.abort();
      return;
    }

    await route.continue();
  });

  return { browser, context };
}

module.exports = {
  createBrowserContext
};
