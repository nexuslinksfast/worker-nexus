const { cleanTitle, randomBetween, sleep } = require("../lib/utils");

const INDEX_BASE_URL = "https://fitgirl-repacks.site/all-my-repacks-a-z/";
const SITE_BASE_URL = "https://fitgirl-repacks.site/";
const MAX_INDEX_PAGES = 140;

function normalizeUrl(url) {
  if (!url) {
    return null;
  }

  try {
    return new URL(url, SITE_BASE_URL).toString();
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
    const isValidRepackLink = (anchor) => {
      const href = anchor.href;
      const text = (anchor.textContent || "").trim();

      if (!href || !text) {
        return false;
      }

      if (!href.startsWith("https://fitgirl-repacks.site/")) {
        return false;
      }

      if (
        href.includes("/all-my-repacks-a-z/") ||
        href.includes("/category/") ||
        href.includes("/tag/") ||
        href.includes("?lcp_page0=") ||
        href.includes("#")
      ) {
        return false;
      }

      return true;
    };

    const containers = [
      document.querySelector("#lcp_instance_0"),
      document.querySelector(".entry-content"),
      document.querySelector("article"),
      document.querySelector("main"),
      document.body
    ].filter(Boolean);

    const container = containers.find((node) => node.querySelector("li a[href]")) || document.body;
    const links = Array.from(container.querySelectorAll("li a[href], a[href]"));
    const unique = new Map();

    for (const anchor of links) {
      if (!isValidRepackLink(anchor)) {
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
  const entries = [];
  const seen = new Set();

  try {
    let pageNumber = 1;
    let totalPages = null;

    while (true) {
      const pageUrl =
        pageNumber === 1 ? INDEX_BASE_URL : `${INDEX_BASE_URL}?lcp_page0=${pageNumber}`;

      console.log(`Scanning FitGirl index page ${pageNumber}: ${pageUrl}`);

      await page.goto(pageUrl, {
        waitUntil: "domcontentloaded",
        timeout: 45000
      });

      await sleep(randomBetween(1200, 2600));

      if (totalPages === null) {
        totalPages = await page.evaluate(() => {
          const pageLinks = Array.from(document.querySelectorAll('a[href*="lcp_page0="]'));
          const pageNumbers = pageLinks
            .map((link) => {
              try {
                return Number.parseInt(new URL(link.href).searchParams.get("lcp_page0"), 10);
              } catch {
                return Number.NaN;
              }
            })
            .filter((value) => Number.isInteger(value));

          return pageNumbers.length ? Math.max(...pageNumbers) : 1;
        });
        totalPages = Math.min(totalPages || 1, MAX_INDEX_PAGES);
        console.log(`FitGirl index reports ${totalPages} pages.`);
      }

      const currentEntries = await extractIndexEntries(page);
      if (!currentEntries.length) {
        break;
      }

      for (const entry of currentEntries) {
        if (seen.has(entry.url)) {
          continue;
        }

        seen.add(entry.url);
        entries.push(entry);
      }

      if (pageNumber >= totalPages) {
        break;
      }

      if (options.maxItems && entries.length >= options.maxItems * 4) {
        break;
      }

      pageNumber += 1;
    }

    console.log(`Found ${entries.length} FitGirl repack links.`);
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

  await sleep(randomBetween(400, 1100));

  return page.evaluate(() => {
    const EXCLUDED_HOSTS = new Set([
      "fitgirl-repacks.site",
      "www.fitgirl-repacks.site",
      "wordpress.org",
      "twitter.com",
      "x.com",
      "facebook.com",
      "instagram.com",
      "youtube.com",
      "youtu.be",
      "reddit.com",
      "discord.gg",
      "discord.com",
      "jdownloader.org",
      "www.internetdownloadmanager.com",
      "tapochek.net",
      "cs.rin.ru"
    ]);

    const article =
      document.querySelector(".entry-content") ||
      document.querySelector("article") ||
      document.querySelector("main") ||
      document.body;

    const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();
    const pick = (...values) => values.map(normalizeText).find(Boolean) || null;
    const bodyText = normalizeText(article.innerText || document.body.innerText || "");
    const fileSizeMatch = bodyText.match(
      /Repack Size:\s*([0-9]+(?:\.[0-9]+)?(?:\/[0-9]+(?:\.[0-9]+)?)?\s*(?:KB|MB|GB|TB)(?:\s*\[[^\]]+\])?)/i
    );

    const uris = [];
    for (const anchor of Array.from(article.querySelectorAll("a[href]"))) {
      const href = anchor.href;
      if (!href) {
        continue;
      }

      if (/^magnet:/i.test(href)) {
        if (!uris.includes(href)) {
          uris.push(href);
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
      if (EXCLUDED_HOSTS.has(hostname)) {
        continue;
      }
    }

    return {
      title: pick(
        document.querySelector("h1.entry-title")?.textContent,
        document.querySelector("title")?.textContent
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

async function fetchWithRetries(page, entry, retries = 2) {
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const details = await extractPostDetails(page, entry.url);
      return {
        title: cleanTitle(details.title || entry.title),
        uploadDate: details.uploadDate || null,
        fileSize: details.fileSize || null,
        uris: (details.uris || []).map(normalizeUrl).filter(Boolean)
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

      await sleep(randomBetween(1000, 2200));
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
        console.log(`[${progress.completed}/${progress.total}] Skipped ${scraped.title} (no URIs)`);
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

  console.log(`Loaded ${existingMap.size} cached FitGirl entries.`);
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
    console.log(`Skipped ${progress.skipped} FitGirl items because no usable URIs were found.`);
  }

  if (progress.reused) {
    console.log(`Reused ${progress.reused} FitGirl items from the existing JSON.`);
  }

  if (options.isTestMode && results.length) {
    console.log("Sample results:");
    console.log(JSON.stringify(results.slice(0, 3), null, 2));
  }

  return results;
}

module.exports = {
  displayName: "FitGirl",
  outputName: "fitgirl",
  scrape
};
