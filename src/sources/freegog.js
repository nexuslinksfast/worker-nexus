const { cleanTitle, randomBetween, sleep } = require("../lib/utils");

const SITE_BASE_URL = "https://freegogpcgames.com/";
const INDEX_BASE_URL = "https://freegogpcgames.com/a-z-games-list/";

function normalizeUrl(url) {
  if (!url) {
    return null;
  }

  if (/^magnet:/i.test(url)) {
    return url.trim();
  }

  try {
    return new URL(url, SITE_BASE_URL).toString();
  } catch {
    return null;
  }
}

function decodeHtmlEntities(value) {
  return value
    .replace(/&#038;/g, "&")
    .replace(/&#38;/g, "&")
    .replace(/&amp;/g, "&");
}

function decodeGeneratorMagnet(url) {
  if (!url) {
    return null;
  }

  try {
    const parsed = new URL(url);
    const encoded = parsed.searchParams.get("url");
    if (!encoded) {
      return null;
    }

    const decodedBase64 = Buffer.from(encoded, "base64").toString("utf8");
    const htmlDecoded = decodeHtmlEntities(decodedBase64);

    try {
      return decodeURIComponent(htmlDecoded);
    } catch {
      return htmlDecoded;
    }
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

async function extractIndexEntries(page) {
  return page.evaluate(() => {
    const isValidGameLink = (anchor) => {
      const href = anchor.href;
      const text = (anchor.textContent || "").trim();

      if (!href || !text) {
        return false;
      }

      if (!href.startsWith("https://freegogpcgames.com/")) {
        return false;
      }

      if (
        href === "https://freegogpcgames.com/" ||
        href.includes("/category/") ||
        href.includes("/tag/") ||
        href.includes("/page/") ||
        href.includes("/updated-games/") ||
        href.includes("/a-z-games-list/") ||
        href.includes("/games-by-year/") ||
        href.includes("/about-us/") ||
        href.includes("/contact") ||
        href.includes("/faqs/") ||
        href.includes("#")
      ) {
        return false;
      }

      return text.length >= 2;
    };

    const containers = [
      document.querySelector(".entry-content"),
      document.querySelector("main"),
      document.querySelector(".site-main"),
      document.querySelector("article"),
      document.body
    ].filter(Boolean);

    const container = containers.find((node) => node.querySelector("li a[href]")) || document.body;

    const links = Array.from(container.querySelectorAll("li a[href], h2 a[href], article a[href], a[href]"));
    const unique = new Map();

    for (const anchor of links) {
      if (!isValidGameLink(anchor)) {
        continue;
      }

      const href = anchor.href;
      if (!unique.has(href)) {
        unique.set(href, {
          title: (anchor.textContent || "").trim(),
          url: href
        });
      }
    }

    return Array.from(unique.values());
  });
}

async function resolveIndexLinks(context, options) {
  const page = await context.newPage();

  try {
    console.log(`Scanning FreeGOG A-Z page: ${INDEX_BASE_URL}`);
    await page.goto(INDEX_BASE_URL, {
      waitUntil: "domcontentloaded",
      timeout: 45000
    });

    await sleep(randomBetween(1200, 2600));
    const entries = await extractIndexEntries(page);
    console.log(`Found ${entries.length} FreeGOG game links.`);
    return entries;
  } finally {
    await page.close();
  }
}

async function extractPostDetails(page, url) {
  await page.goto(url, {
    waitUntil: "domcontentloaded",
    timeout: 45000
  });

  await sleep(randomBetween(500, 1200));

  return page.evaluate((postUrl) => {
    const EXCLUDED_HOSTS = new Set([
      "freegogpcgames.com",
      "www.freegogpcgames.com",
      "gog.com",
      "www.gog.com",
      "facebook.com",
      "instagram.com",
      "twitter.com",
      "x.com",
      "youtube.com",
      "youtu.be",
      "reddit.com",
      "discord.gg",
      "discord.com"
    ]);

    const article =
      document.querySelector(".entry-content") ||
      document.querySelector("article") ||
      document.querySelector("main") ||
      document.body;

    const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();
    const pick = (...values) => values.map(normalizeText).find(Boolean) || null;
    const bodyText = normalizeText(article.innerText || document.body.innerText || "");
    const sizeMatch = bodyText.match(
      /(?:storage|file\s*size|size)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:KB|MB|GB|TB))/i
    );

    const hostMatches = (hostname, entries) =>
      entries.has(hostname) || Array.from(entries).some((entry) => hostname.endsWith(`.${entry}`));

    const generatorLinks = [];
    const directUris = [];

    for (const anchor of Array.from(article.querySelectorAll("a[href]"))) {
      const href = anchor.href;
      if (!href) {
        continue;
      }

      if (/^magnet:/i.test(href)) {
        if (!directUris.includes(href)) {
          directUris.push(href);
        }
        continue;
      }

      if (!/^https?:/i.test(href)) {
        continue;
      }

      let parsedUrl;
      try {
        parsedUrl = new URL(href);
      } catch {
        continue;
      }

      const hostname = parsedUrl.hostname.replace(/^www\./i, "").toLowerCase();
      const anchorText = normalizeText(anchor.textContent);
      const surroundingText = normalizeText(anchor.parentElement?.innerText || "");
      const articleTextBeforeLink = normalizeText(
        (anchor.closest("p, div, section, li")?.innerText || "").slice(0, 400)
      );
      const looksLikeTorrentStep =
        /torrent|magnet|secure download|download now|download torrent|copy magnet/i.test(
          anchorText
        ) ||
        /torrent|magnet|secure download|download now|download torrent|copy magnet/i.test(
          surroundingText
        ) ||
        /download here|supported download client|drm-free|official drm-free gog installer/i.test(
          articleTextBeforeLink
        );

      if (
        hostname === "gdl.freegogpcgames.xyz" ||
        hostname.endsWith(".freegogpcgames.xyz") ||
        hostname === "freegogpcgames.com" ||
        hostname.endsWith(".freegogpcgames.com")
      ) {
        const isDifferentPage = parsedUrl.toString() !== postUrl;
        const pathLooksLikeDownloadStep =
          /download|torrent|secure|client|generate|get/i.test(parsedUrl.pathname) ||
          parsedUrl.searchParams.toString().length > 0;

        if (
          isDifferentPage &&
          (looksLikeTorrentStep || pathLooksLikeDownloadStep) &&
          !generatorLinks.includes(parsedUrl.toString())
        ) {
          generatorLinks.push(parsedUrl.toString());
        }
        continue;
      }

      if (hostMatches(hostname, EXCLUDED_HOSTS)) {
        continue;
      }

      if (looksLikeTorrentStep && !directUris.includes(parsedUrl.toString())) {
        directUris.push(parsedUrl.toString());
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
      fileSize: sizeMatch ? normalizeText(sizeMatch[1]) : null,
      generatorLinks,
      directUris
    };
  }, url);
}

async function resolveGeneratorLink(page, url) {
  await page.goto(url, {
    waitUntil: "domcontentloaded",
    timeout: 45000
  });

  await sleep(randomBetween(3500, 5500));

  try {
    await page.waitForFunction(
      () => {
        const magnetAnchor = document.querySelector('a[href^="magnet:"]');
        const inputWithMagnet = Array.from(document.querySelectorAll("input, textarea")).find(
          (element) => typeof element.value === "string" && element.value.startsWith("magnet:")
        );
        const clipboardNode = Array.from(document.querySelectorAll("[data-clipboard-text]")).find(
          (element) =>
            typeof element.getAttribute("data-clipboard-text") === "string" &&
            element.getAttribute("data-clipboard-text").startsWith("magnet:")
        );

        return Boolean(magnetAnchor || inputWithMagnet || clipboardNode);
      },
      { timeout: 12000 }
    );
  } catch {
    // The page may still expose the magnet in HTML even if the countdown check timed out.
  }

  return page.evaluate(() => {
    const candidates = [];
    const maybePush = (value) => {
      if (typeof value !== "string") {
        return;
      }

      const trimmed = value.trim();
      if (!trimmed) {
        return;
      }

      candidates.push(trimmed);

      try {
        const decoded = decodeURIComponent(trimmed);
        if (decoded && decoded !== trimmed) {
          candidates.push(decoded.trim());
        }
      } catch {
        // Ignore malformed URI components.
      }
    };

    const magnetAnchor = document.querySelector('a[href^="magnet:"]')?.getAttribute("href");
    if (magnetAnchor) {
      maybePush(magnetAnchor);
    }

    for (const element of Array.from(document.querySelectorAll("input, textarea"))) {
      if (typeof element.value === "string" && element.value.startsWith("magnet:")) {
        maybePush(element.value);
      }

      if (typeof element.value === "string" && /magnet%3a|urn%3abtih/i.test(element.value)) {
        maybePush(element.value);
      }
    }

    for (const element of Array.from(document.querySelectorAll("[data-clipboard-text]"))) {
      const value = element.getAttribute("data-clipboard-text");
      if (typeof value === "string" && (value.startsWith("magnet:") || /magnet%3a|urn%3abtih/i.test(value))) {
        maybePush(value);
      }
    }

    for (const element of Array.from(document.querySelectorAll("[value]"))) {
      const value = element.getAttribute("value");
      if (typeof value === "string" && (value.startsWith("magnet:") || /magnet%3a|urn%3abtih/i.test(value))) {
        maybePush(value);
      }
    }

    for (const element of Array.from(document.querySelectorAll("[onclick]"))) {
      const onclick = element.getAttribute("onclick") || "";
      const match = onclick.match(/magnet:[^"'\\s<]+/i);
      if (match) {
        maybePush(match[0]);
      }

      if (/magnet%3a|urn%3abtih/i.test(onclick)) {
        maybePush(onclick);
      }
    }

    for (const script of Array.from(document.scripts)) {
      const scriptText = script.textContent || "";
      if (!scriptText) {
        continue;
      }

      const directMatch = scriptText.match(/magnet:\?xt=urn:btih:[^\s"'<>\\]+/i);
      if (directMatch) {
        maybePush(directMatch[0]);
      }

      const encodedMatch = scriptText.match(/magnet%3A%3Fxt%3Durn%3Abtih%3A[^"'<>\\\s]+/i);
      if (encodedMatch) {
        maybePush(encodedMatch[0]);
      }
    }

    const textNodes = [document.body?.innerText || "", document.body?.textContent || ""];
    for (const text of textNodes) {
      const match = text.match(/magnet:\?xt=urn:btih:[^\s"'<>]+/i);
      if (match) {
        maybePush(match[0]);
      }

      const encodedMatch = text.match(/magnet%3A%3Fxt%3Durn%3Abtih%3A[^\s"'<>]+/i);
      if (encodedMatch) {
        maybePush(encodedMatch[0]);
      }
    }

    return (
      candidates.find((value) => typeof value === "string" && /^magnet:\?xt=urn:btih:/i.test(value)) ||
      null
    );
  });
}

async function fetchWithRetries(page, entry, retries = 2) {
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const details = await extractPostDetails(page, entry.url);
      const resolvedUris = [...(details.directUris || [])];

      if (!resolvedUris.length && !(details.generatorLinks || []).length) {
        console.warn(`No generator links found in "${entry.url}"`);
      }

      for (const generatorLink of details.generatorLinks || []) {
        const magnetLink = decodeGeneratorMagnet(generatorLink);
        if (magnetLink && !resolvedUris.includes(magnetLink)) {
          resolvedUris.push(magnetLink);
        }
      }

      if (!resolvedUris.length && (details.generatorLinks || []).length) {
        console.warn(`Generator links could not be decoded in "${entry.url}" (${details.generatorLinks.length} generator links found)`);
      }

      return {
        title: cleanTitle(details.title || entry.title),
        uploadDate: details.uploadDate || null,
        fileSize: details.fileSize || null,
        uris: resolvedUris.map(normalizeUrl).filter(Boolean)
      };
    } catch (error) {
      if (attempt === retries) {
        console.warn(`Failed to scrape "${entry.url}": ${error.message}`);
        return {
          title: cleanTitle(entry.title),
          uploadDate: null,
          fileSize: null,
          uris: []
        };
      }

      await sleep(randomBetween(1200, 2400));
    }
  }

  return {
    title: cleanTitle(entry.title),
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

      const entry = queue.shift();
      if (!entry) {
        break;
      }

      const cached = options.existingMap.get(cleanTitle(entry.title));
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

      const scraped = await fetchWithRetries(page, entry);
      progress.completed += 1;

      if (!scraped.uris.length) {
        progress.skipped += 1;
        console.log(`[${progress.completed}/${progress.total}] Skipped ${scraped.title} (no usable URIs)`);
      } else {
        if (options.maxItems && results.length >= options.maxItems) {
          break;
        }

        results.push(scraped);
        console.log(`[${progress.completed}/${progress.total}] ${scraped.title}`);
      }

      await sleep(randomBetween(120, 450));
    }
  } finally {
    await page.close();
  }
}

async function scrape(context, options) {
  const entries = await resolveIndexLinks(context, options);
  const existingMap = buildExistingDownloadsMap(options.existingDownloads);

  if (options.maxItems) {
    console.log(`Test mode active. Targeting ${options.maxItems} valid items.`);
  }

  const queue = [...entries];
  const results = [];
  const workerCount = Math.min(options.workerOverride || 6, queue.length);
  const progress = {
    completed: 0,
    total: queue.length,
    skipped: 0,
    reused: 0
  };

  console.log(`Loaded ${existingMap.size} cached FreeGOG entries.`);
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
    console.log(`Skipped ${progress.skipped} FreeGOG items because no usable URIs were found.`);
  }

  if (progress.reused) {
    console.log(`Reused ${progress.reused} FreeGOG items from the existing JSON.`);
  }

  if (options.isTestMode && results.length) {
    console.log("Sample results:");
    console.log(JSON.stringify(results.slice(0, 3), null, 2));
  }

  return results;
}

module.exports = {
  displayName: "FreeGOG",
  outputName: "freegog",
  scrape
};
