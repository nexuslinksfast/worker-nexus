const fs = require("fs");
const path = require("path");
const { parseCliArgs } = require("./cli");
const { createBrowserContext } = require("./browser");
const { saveJsonFile } = require("./write-json");
const steamrip = require("../sources/steamrip");
const fitgirl = require("../sources/fitgirl");
const freegog = require("../sources/freegog");
const onlinefixFixes = require("../sources/onlinefix-fixes");

const SOURCES = {
  steamrip,
  fitgirl,
  freegog,
  "onlinefix-fixes": onlinefixFixes
};

async function runSource(sourceId, argv) {
  const source = SOURCES[sourceId];
  if (!source) {
    throw new Error(`Unknown source "${sourceId}". Available sources: ${Object.keys(SOURCES).join(", ")}`);
  }

  const options = parseCliArgs(argv);
  const outputPath = path.join(process.cwd(), "public", `${source.outputName}.json`);
  let existingDownloads = [];

  if (fs.existsSync(outputPath)) {
    try {
      const existingRaw = fs.readFileSync(outputPath, "utf8");
      const existingJson = JSON.parse(existingRaw);
      if (Array.isArray(existingJson.downloads)) {
        existingDownloads = existingJson.downloads;
      }
    } catch (error) {
      console.warn(`Could not read existing cache from ${outputPath}: ${error.message}`);
    }
  }

  const { browser, context } = await createBrowserContext();

  try {
    const downloads = await source.scrape(context, {
      ...options,
      existingDownloads
    });
    if (!downloads.length) {
      throw new Error(`Source "${sourceId}" returned 0 downloads. Existing JSON will be preserved.`);
    }

    await saveJsonFile(outputPath, {
      name: source.displayName,
      downloads
    });
    console.log(`Saved ${downloads.length} items to ${outputPath}.`);
  } finally {
    await context.close();
    await browser.close();
  }
}

module.exports = {
  runSource
};
