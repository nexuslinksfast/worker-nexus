const { cleanTitle, randomBetween, sleep } = require("../lib/utils");

const BASE_URL = "https://steamrip.com/";
const LIST_URLS = [
  "https://steamrip.com/games-list-page/",
  "https://steamrip.com/all-games-list/",
  "https://steamrip.com/games-list/"
];

function normalizeUrl(url) {
  if (!url) {
    return null;
  }

  try {
    return new URL(url, BASE_URL).toString();
  } catch {
    return null;
  }
}

function buildExistingDownloadsMap(existingDownloads = []) {
  const map = new Map();

  for (const download of existingDownloads) {
    const title = cleanTitle(download?.title);
    if (!title) {
      continue;
    }

    if (!Array.isArray(download.uris) || !download.uris.length) {
      continue;
    }

    map.set(title, {
      title,
      uploadDate: download.uploadDate || null,
      fileSize: download.fileSize || null,
      uris: download.uris
    });
  }

  return map;
}

async function extractGameLinks(page) {
  return page.evaluate(() => {
    const isGamePostLink = (href, text) => {
      if (!href || !text) {
        return false;
      }

      const normalizedHref = href.trim();
      const normalizedText = text.trim();

      if (!normalizedHref.startsWith("https://steamrip.com/")) {
        return false;
      }

      if (
        normalizedHref.includes("/games-list-page/") ||
        normalizedHref.includes("/all-games-list/") ||
        normalizedHref.includes("/updated-games/") ||
        normalizedHref.includes("/category/") ||
        normalizedHref.includes("/tag/") ||
        normalizedHref.includes("/faq/") ||
        normalizedHref.includes("/discord") ||
        normalizedHref.includes("#")
      ) {
        return false;
      }

      if (normalizedText.length < 3) {
        return false;
      }

      return /free download/i.test(normalizedText);
    };

    const candidates = [
      document.querySelector("article"),
      document.querySelector(".entry-content"),
      document.querySelector(".td-post-content"),
      document.querySelector("main"),
      document.body
    ].filter(Boolean);

    const container =
      candidates.find((node) => /all games list/i.test(node.textContent || "")) ||
      document.body;

    const unique = new Map();
    const anchors = Array.from(container.querySelectorAll("a[href]"));

    for (const anchor of anchors) {
      const href = anchor.href;
      const text = (anchor.textContent || "").trim();

      if (!isGamePostLink(href, text)) {
        continue;
      }

      if (!unique.has(href)) {
        unique.set(href, {
          title: text,
          url: href
        });
      }
    }

    return Array.from(unique.values());
  });
}

async function extractPostDetails(postPage, url) {
  await postPage.goto(url, {
    waitUntil: "domcontentloaded",
    timeout: 45000
  });

  await sleep(randomBetween(500, 1200));

  return postPage.evaluate(() => {
    const SOCIAL_HOSTS = new Set([
      "discord.gg",
      "discord.com",
      "facebook.com",
      "instagram.com",
      "patreon.com",
      "reddit.com",
      "telegram.me",
      "t.me",
      "tiktok.com",
      "twitter.com",
      "x.com",
      "youtube.com",
      "youtu.be"
    ]);

    const DOWNLOAD_HOSTS = new Set([
      "1fichier.com",
      "buzzheavier.com",
      "ddownload.com",
      "fuckingfast.co",
      "gofile.io",
      "krakenfiles.com",
      "mediafire.com",
      "mega.nz",
      "multiup.io",
      "pixeldrain.com",
      "qiwi.gg",
      "rapidgator.net",
      "send.cm",
      "sendcm.com",
      "upload.ee",
      "vikingfile.com"
    ]);

    const article =
      document.querySelector(".entry-content") ||
      document.querySelector(".td-post-content") ||
      document.querySelector("article") ||
      document.body;

    const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();
    const pick = (...values) => values.map(normalizeText).find(Boolean) || null;
    const bodyText = normalizeText(article.innerText || document.body.innerText || "");
    const fileSizeMatch = bodyText.match(
      /(?:file\s*size|size)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:KB|MB|GB|TB))/i
    );

    const hostMatches = (hostname, entries) =>
      entries.has(hostname) || Array.from(entries).some((entry) => hostname.endsWith(`.${entry}`));

    const uris = [];

    for (const anchor of Array.from(article.querySelectorAll("a[href]"))) {
      const href = anchor.href;
      if (!href || !/^https?:/i.test(href)) {
        continue;
      }

      let parsedUrl;
      try {
        parsedUrl = new URL(href);
      } catch {
        continue;
      }

      const hostname = parsedUrl.hostname.replace(/^www\./i, "").toLowerCase();
      if (hostname.includes("steamrip.com")) {
        continue;
      }

      if (hostname === "megadb.net" || hostname.endsWith(".megadb.net")) {
        continue;
      }

      if (hostMatches(hostname, SOCIAL_HOSTS)) {
        continue;
      }

      const anchorText = normalizeText(anchor.textContent);
      const surroundingText = normalizeText(anchor.parentElement?.innerText || "");
      const looksLikeDownload =
        hostMatches(hostname, DOWNLOAD_HOSTS) ||
        /download|mirror|gofile|buzzheavier|pixeldrain|vikingfile|qiwi/i.test(anchorText) ||
        /download|mirror|gofile|buzzheavier|pixeldrain|vikingfile|qiwi/i.test(surroundingText);

      if (looksLikeDownload) {
        const normalized = parsedUrl.toString();
        if (normalized && !uris.includes(normalized)) {
          uris.push(normalized);
        }
      }
    }

    return {
      title: pick(
        document.querySelector("h1.entry-title")?.textContent,
        document.querySelector("title")?.textContent,
        article.querySelector("h1, h2")?.textContent
      ),
      uploadDate: pick(
        document.querySelector('meta[property="article:published_time"]')?.content,
        document.querySelector("time[datetime]")?.getAttribute("datetime")
      ),
      fileSize: fileSizeMatch ? normalizeText(fileSizeMatch[1]) : null,
      uris
    };
  });
}

async function fetchWithRetries(postPage, game, retries = 2) {
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const details = await extractPostDetails(postPage, game.url);
      return {
        title: cleanTitle(details.title || game.title),
        uploadDate: details.uploadDate || null,
        fileSize: details.fileSize || null,
        uris: details.uris || []
      };
    } catch (error) {
      if (attempt === retries) {
        console.warn(`Failed to scrape "${game.url}": ${error.message}`);
        return {
          title: cleanTitle(game.title),
          uploadDate: null,
          fileSize: null,
          uris: []
        };
      }

      await sleep(randomBetween(1200, 2400));
    }
  }

  return {
    title: cleanTitle(game.title),
    uploadDate: null,
    fileSize: null,
    uris: []
  };
}

async function runWorker(context, queue, results, progress, options) {
  const page = await context.newPage();

  try {
    while (queue.length > 0) {
      if (options.maxItems && results.length >= options.maxItems) {
        break;
      }

      const game = queue.shift();
      if (!game) {
        break;
      }

      const cached = options.existingMap.get(cleanTitle(game.title));
      if (cached) {
        progress.completed += 1;
        progress.reused += 1;
        results.push({
          title: cached.title,
          uploadDate: cached.uploadDate,
          fileSize: cached.fileSize,
          uris: cached.uris
        });
        console.log(`[${progress.completed}/${progress.total}] Reused ${cached.title}`);
        continue;
      }

      const scraped = await fetchWithRetries(page, game);
      progress.completed += 1;

      if (!scraped.uris.length) {
        progress.skipped += 1;
        console.log(`[${progress.completed}/${progress.total}] Skipped ${scraped.title} (no usable URIs)`);
      } else {
        if (options.maxItems && results.length >= options.maxItems) {
          break;
        }

        results.push({
          title: scraped.title,
          uploadDate: scraped.uploadDate,
          fileSize: scraped.fileSize,
          uris: scraped.uris
        });
        console.log(`[${progress.completed}/${progress.total}] ${scraped.title}`);
      }

      await sleep(randomBetween(150, 500));
    }
  } finally {
    await page.close();
  }
}

async function resolveGameLinks(context) {
  const listPage = await context.newPage();

  try {
    let games = [];
    let resolvedListUrl = null;

    for (const candidateUrl of LIST_URLS) {
      try {
        console.log(`Trying list URL: ${candidateUrl}`);
        await listPage.goto(candidateUrl, {
          waitUntil: "domcontentloaded",
          timeout: 45000
        });

        await sleep(randomBetween(1800, 3500));
        games = await extractGameLinks(listPage);

        if (games.length) {
          resolvedListUrl = candidateUrl;
          break;
        }
      } catch (error) {
        console.warn(`List URL failed: ${candidateUrl} -> ${error.message}`);
      }
    }

    if (!games.length) {
      throw new Error(
        "No se encontraron juegos en SteamRIP. Revisa si Cloudflare bloqueó la sesión o si la estructura volvió a cambiar."
      );
    }

    console.log(`Resolved list URL: ${resolvedListUrl}`);
    console.log(`Found ${games.length} game links.`);

    return games;
  } finally {
    await listPage.close();
  }
}

async function scrape(context, options) {
  const games = await resolveGameLinks(context);
  const existingMap = buildExistingDownloadsMap(options.existingDownloads);
  if (options.maxItems) {
    console.log(`Test mode active. Targeting ${options.maxItems} valid items.`);
  }

  const queue = [...games];
  const results = [];
  const workerCount = Math.min(options.workerOverride || 6, queue.length);
  const progress = {
    completed: 0,
    total: queue.length,
    skipped: 0,
    reused: 0
  };

  console.log(`Loaded ${existingMap.size} cached SteamRip entries.`);
  console.log(`Using ${workerCount} workers.`);

  await Promise.all(
    Array.from({ length: workerCount }, () =>
      runWorker(context, queue, results, progress, { ...options, existingMap })
    )
  );

  if (options.maxItems && results.length > options.maxItems) {
    results.length = options.maxItems;
  }

  results.sort((a, b) => a.title.localeCompare(b.title, "en"));

  if (progress.skipped) {
    console.log(`Skipped ${progress.skipped} items because no usable URIs were found.`);
  }

  if (progress.reused) {
    console.log(`Reused ${progress.reused} SteamRip items from the existing JSON.`);
  }

  if (options.isTestMode && results.length) {
    console.log("Sample results:");
    console.log(JSON.stringify(results.slice(0, 3), null, 2));
  }

  return results;
}

module.exports = {
  displayName: "SteamRip",
  outputName: "steamrip",
  scrape
};
