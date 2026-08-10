const { cleanTitle, randomBetween, sleep } = require("../lib/utils");

const SITE_BASE_URL = "https://online-fix.me/";
const INDEX_BASE_URL = "https://online-fix.me/games/";
const FLARESOLVERR_URL = process.env.FLARESOLVERR_URL || "http://127.0.0.1:8191/v1";
const MAX_INDEX_PAGES = 180;
let flareSolverrSessionCounter = 0;

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

function decodeHtml(value) {
  return (value || "")
    .replace(/&amp;/gi, "&")
    .replace(/&#038;|&#38;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">");
}

function stripTags(value) {
  return decodeHtml((value || "").replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
}

function nextFlareSolverrSessionId() {
  flareSolverrSessionCounter += 1;
  return `onlinefix-fixes-${Date.now()}-${flareSolverrSessionCounter}`;
}

async function callFlareSolverr(payload) {
  const response = await fetch(FLARESOLVERR_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`FlareSolverr HTTP ${response.status}: ${body}`);
  }

  const result = await response.json();
  if (result.status !== "ok") {
    throw new Error(result.message || "FlareSolverr returned a non-ok status.");
  }

  return result;
}

async function createFlareSolverrSession() {
  const sessionId = nextFlareSolverrSessionId();
  await callFlareSolverr({
    cmd: "sessions.create",
    session: sessionId
  });
  console.log(`OnlineFix Fixes -> FlareSolverr session created: ${sessionId}`);
  return sessionId;
}

async function destroyFlareSolverrSession(sessionId) {
  if (!sessionId) {
    return;
  }

  try {
    await callFlareSolverr({
      cmd: "sessions.destroy",
      session: sessionId
    });
    console.log(`OnlineFix Fixes -> FlareSolverr session destroyed: ${sessionId}`);
  } catch (error) {
    console.warn(`OnlineFix Fixes -> could not destroy FlareSolverr session "${sessionId}": ${error.message}`);
  }
}

async function fetchWithFlareSolverr(url, sessionId) {
  console.log(`OnlineFix Fixes -> FlareSolverr request: ${url}`);

  const result = await callFlareSolverr({
    cmd: "request.get",
    url,
    maxTimeout: 60000,
    session: sessionId,
    session_ttl_minutes: 10
  });

  const solution = result.solution || {};
  if (solution.status !== 200) {
    throw new Error(`FlareSolverr target returned HTTP ${solution.status || "unknown"}.`);
  }

  console.log(`OnlineFix Fixes -> FlareSolverr solved: ${url}`);
  return solution.response || "";
}

async function ensureLoggedIn(context) {
  const username = process.env.ONLINEFIX_USERNAME;
  const password = process.env.ONLINEFIX_PASSWORD;

  if (!username || !password) {
    throw new Error(
      'OnlineFix Fixes requires ONLINEFIX_USERNAME and ONLINEFIX_PASSWORD environment variables.'
    );
  }

  const page = await context.newPage();

  try {
    await page.goto(SITE_BASE_URL, {
      waitUntil: "domcontentloaded",
      timeout: 45000
    });

    await sleep(randomBetween(1200, 2200));

    const alreadyLoggedIn = await page.evaluate(() => {
      return Boolean(
        document.querySelector('a[href*="logout"]') ||
          document.querySelector('a[href*="do=logout"]') ||
          Array.from(document.querySelectorAll("a, button, span")).some((element) =>
            /logout|выход/i.test((element.textContent || "").trim())
          )
      );
    });

    if (alreadyLoggedIn) {
      console.log("OnlineFix Fixes session already authenticated.");
      return;
    }

    const loginTrigger = page
      .locator('a[href*="login"], button:has-text("Войти"), a:has-text("Войти"), a:has-text("Login")')
      .first();

    if ((await loginTrigger.count()) > 0) {
      await loginTrigger.click().catch(() => {});
      await sleep(randomBetween(600, 1200));
    }

    const usernameLocator = page.locator(
      'input[name="login_name"], input[name="username"], input[autocomplete="username"], input[type="text"]'
    ).first();
    const passwordLocator = page.locator(
      'input[name="login_password"], input[name="password"], input[autocomplete="current-password"], input[type="password"]'
    ).first();

    await usernameLocator.waitFor({ state: "visible", timeout: 15000 });
    await passwordLocator.waitFor({ state: "visible", timeout: 15000 });

    await usernameLocator.fill(username);
    await passwordLocator.fill(password);

    const submitLocator = page.locator(
      'button[type="submit"], input[type="submit"], button:has-text("Войти"), button:has-text("Login")'
    ).first();

    await Promise.all([
      page.waitForLoadState("domcontentloaded").catch(() => {}),
      submitLocator.click()
    ]);

    await sleep(randomBetween(1500, 2500));

    const loginSuccessful = await page.evaluate(() => {
      return Boolean(
        document.querySelector('a[href*="logout"]') ||
          document.querySelector('a[href*="do=logout"]') ||
          Array.from(document.querySelectorAll("a, button, span")).some((element) =>
            /logout|выход/i.test((element.textContent || "").trim())
          )
      );
    });

    if (!loginSuccessful) {
      throw new Error("OnlineFix Fixes login did not complete successfully.");
    }

    console.log("OnlineFix Fixes login successful.");
  } finally {
    await page.close();
  }
}

async function extractIndexEntries(page) {
  return page.evaluate(() => {
    const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();
    const isValidGameLink = (anchor) => {
      const href = anchor.href;
      const text = normalizeText(anchor.textContent);

      if (!href || !text) {
        return false;
      }

      if (!href.startsWith("https://online-fix.me/")) {
        return false;
      }

      if (
        href === "https://online-fix.me/games/" ||
        href.includes("/category/") ||
        href.includes("/tag/") ||
        href.includes("#") ||
        href.includes("index.php?do=")
      ) {
        return false;
      }

      if (/^Материалы за/i.test(text) || /^Epic Games Store$/i.test(text)) {
        return false;
      }

      return /по сети/i.test(text);
    };

    const container =
      document.querySelector("#dle-content") ||
      document.querySelector(".base.shortstory") ||
      document.querySelector("main") ||
      document.body;

    const links = Array.from(
      container.querySelectorAll("h2 a[href], .shortstoryHead a[href], .base.shortstory a[href], a[href]")
    );
    const unique = new Map();

    for (const anchor of links) {
      if (!isValidGameLink(anchor)) {
        continue;
      }

      const href = anchor.href;
      if (!unique.has(href)) {
        unique.set(href, {
          title: normalizeText(anchor.textContent),
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

    while (true) {
      const pageUrl = pageNumber === 1 ? INDEX_BASE_URL : `${INDEX_BASE_URL}page/${pageNumber}/`;
      console.log(`Scanning OnlineFix Fixes page ${pageNumber}: ${pageUrl}`);

      await page.goto(pageUrl, {
        waitUntil: "domcontentloaded",
        timeout: 45000
      });

      await sleep(randomBetween(1800, 3200));

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

      if (options.maxItems && entries.length >= options.maxItems * 4) {
        break;
      }

      const hasNextPage = await page.evaluate((current) => {
        return Array.from(document.querySelectorAll("a[href]")).some((anchor) =>
          anchor.href.includes(`/games/page/${current + 1}/`)
        );
      }, pageNumber);

      if (!hasNextPage || pageNumber >= MAX_INDEX_PAGES) {
        break;
      }

      pageNumber += 1;
    }

    console.log(`Found ${entries.length} OnlineFix Fixes game links.`);
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

  await sleep(randomBetween(1200, 2400));

  return page.evaluate(() => {
    const article =
      document.querySelector('[itemprop="articleBody"]') ||
      document.querySelector(".full-text.clearfix") ||
      document.querySelector(".full-text") ||
      document.querySelector(".text") ||
      document.querySelector("article") ||
      document.body;
    const quote = article.querySelector(".quote");
    const root = quote || article || document.body;

    const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();
    const pick = (...values) => values.map(normalizeText).find(Boolean) || null;

    const uploadUrls = [];
    const hosterUrls = [];
    const driveUrls = [];

    for (const anchor of Array.from(root.querySelectorAll("a[href]"))) {
      const href = anchor.href;
      const text = normalizeText(anchor.textContent);

      if (!href || !/^https?:/i.test(href)) {
        continue;
      }

      const isUploads =
        /uploads\.online-fix\.me/i.test(href) ||
        (/download the fix from the server/i.test(text) && /online-fix/i.test(href));
      const isHosters =
        /hosters\.online-fix\.me/i.test(href) || (/online-fix/i.test(text) && /hosters|server/i.test(text));
      const isDrive = /drive\.online-fix\.me/i.test(href) || (/online-fix/i.test(text) && /drive/i.test(text));

      if (isUploads && !uploadUrls.includes(href)) {
        uploadUrls.push(href);
      }

      if (isHosters && !hosterUrls.includes(href)) {
        hosterUrls.push(href);
      }

      if (isDrive && !driveUrls.includes(href)) {
        driveUrls.push(href);
      }
    }

    return {
      title: pick(document.querySelector("h1")?.textContent, document.querySelector("title")?.textContent),
      uploadDate: pick(
        document.querySelector("time[datetime]")?.getAttribute("datetime"),
        document.querySelector('meta[property="article:published_time"]')?.content,
        document.querySelector('meta[name="pubdate"]')?.content
      ),
      fileSize: null,
      serverUrls: [...uploadUrls, ...hosterUrls, ...driveUrls],
      uploadUrls,
      hosterUrls,
      driveUrls
    };
  });
}

function extractFixUrisFromHtml(html, baseUrl) {
  const uris = [];
  const anchorRegex = /<a\b[^>]*href=(["'])(.*?)\1[^>]*>([\s\S]*?)<\/a>/gi;
  let match;

  while ((match = anchorRegex.exec(html)) !== null) {
    const href = decodeHtml(match[2]);
    const text = stripTags(match[3]);

    if (!href) {
      continue;
    }

    const looksLikeFixRepair =
      /fix repair/i.test(text) ||
      /fix[ _.-]*repair/i.test(href) ||
      (/fix/i.test(text) && /\.(rar|zip|7z)(?:$|\?)/i.test(href));

    if (!looksLikeFixRepair) {
      continue;
    }

    try {
      const absoluteHref = new URL(href, baseUrl).toString();
      if (!uris.includes(absoluteHref)) {
        uris.push(absoluteHref);
      }
    } catch {
      continue;
    }
  }

  if (uris.length === 0) {
    const directHrefRegex = /href\s*=\s*(["'])([^"']+\.(?:rar|zip|7z))(?:\?[^"']*)?\1/gi;
    let directMatch;

    while ((directMatch = directHrefRegex.exec(html)) !== null) {
      try {
        const absoluteHref = new URL(decodeHtml(directMatch[2]), baseUrl).toString();
        if (!uris.includes(absoluteHref) && /fix/i.test(absoluteHref)) {
          uris.push(absoluteHref);
        }
      } catch {
        continue;
      }
    }
  }

  return uris;
}

function extractFixRepairDirectoriesFromHtml(html, baseUrl) {
  const directories = [];
  const anchorRegex = /<a\b[^>]*href=(["'])(.*?)\1[^>]*>([\s\S]*?)<\/a>/gi;
  let match;

  while ((match = anchorRegex.exec(html)) !== null) {
    const href = decodeHtml(match[2]);
    const text = stripTags(match[3]);

    if (!href) {
      continue;
    }

    const looksLikeFixRepairDir =
      /fix repair/i.test(text) ||
      /fix repair\/?$/i.test(href) ||
      /fix[ _.-]*repair/i.test(href);

    if (!looksLikeFixRepairDir) {
      continue;
    }

    try {
      const absoluteHref = new URL(href, baseUrl).toString();
      if (!directories.includes(absoluteHref)) {
        directories.push(absoluteHref);
      }
    } catch {
      continue;
    }
  }

  if (directories.length === 0) {
    const directDirRegex = /href\s*=\s*(["'])([^"']*fix(?:%20|[ _.-])*repair\/?)\1/gi;
    let directMatch;

    while ((directMatch = directDirRegex.exec(html)) !== null) {
      try {
        const absoluteHref = new URL(decodeHtml(directMatch[2]), baseUrl).toString();
        if (!directories.includes(absoluteHref)) {
          directories.push(absoluteHref);
        }
      } catch {
        continue;
      }
    }
  }

  return directories;
}

async function fetchFixUris(details, sessionId) {
  const uris = [];
  const uploadUrls = details.uploadUrls || [];
  const hosterUrls = details.hosterUrls || [];
  const driveUrls = details.driveUrls || [];

  console.log(
    `OnlineFix Fixes -> server candidates: uploads=${uploadUrls.length}, hosters=${hosterUrls.length}, drive=${driveUrls.length}`
  );

  for (const serverUrl of uploadUrls) {
      try {
      console.log(`OnlineFix Fixes -> opening uploads page: ${serverUrl}`);
      const html = await fetchWithFlareSolverr(serverUrl, sessionId);
      const fixUris = extractFixUrisFromHtml(html, serverUrl);
      const fixRepairDirs = extractFixRepairDirectoriesFromHtml(html, serverUrl);

      console.log(
        `OnlineFix Fixes -> uploads page parsed: fixFiles=${fixUris.length}, fixRepairDirs=${fixRepairDirs.length}`
      );
      if (fixUris.length === 0 && fixRepairDirs.length === 0) {
        console.log(
          `OnlineFix Fixes -> uploads html preview: ${html.slice(0, 400).replace(/\s+/g, " ")}`
        );
      }

      for (const uri of fixUris) {
        if (!uris.includes(uri)) {
          uris.push(uri);
        }
      }

      for (const directoryUrl of fixRepairDirs) {
        try {
          console.log(`OnlineFix Fixes -> opening uploads repair dir: ${directoryUrl}`);
          const repairHtml = await fetchWithFlareSolverr(directoryUrl, sessionId);
          const repairUris = extractFixUrisFromHtml(repairHtml, directoryUrl);

          console.log(`OnlineFix Fixes -> uploads repair dir parsed: repairFiles=${repairUris.length}`);

          for (const uri of repairUris) {
            if (!uris.includes(uri)) {
              uris.push(uri);
            }
          }
        } catch (error) {
          console.warn(
            `Failed to resolve OnlineFix Fixes uploads repair directory "${directoryUrl}": ${error.message}`
          );
        }
      }
    } catch (error) {
      console.warn(`Failed to resolve OnlineFix Fixes uploads page "${serverUrl}": ${error.message}`);
    }
  }

  for (const serverUrl of hosterUrls) {
      try {
        console.log(`OnlineFix Fixes -> opening hosters page: ${serverUrl}`);
      const html = await fetchWithFlareSolverr(serverUrl, sessionId);
      const fixUris = extractFixUrisFromHtml(html, serverUrl);
      const fixRepairDirs = extractFixRepairDirectoriesFromHtml(html, serverUrl);

      console.log(
        `OnlineFix Fixes -> hosters page parsed: fixFiles=${fixUris.length}, fixRepairDirs=${fixRepairDirs.length}`
      );

      for (const uri of fixUris) {
        if (!uris.includes(uri)) {
          uris.push(uri);
        }
      }

      for (const directoryUrl of fixRepairDirs) {
        try {
          console.log(`OnlineFix Fixes -> opening repair dir: ${directoryUrl}`);
          const repairHtml = await fetchWithFlareSolverr(directoryUrl, sessionId);
          const repairUris = extractFixUrisFromHtml(repairHtml, directoryUrl);

          console.log(`OnlineFix Fixes -> repair dir parsed: repairFiles=${repairUris.length}`);

          for (const uri of repairUris) {
            if (!uris.includes(uri)) {
              uris.push(uri);
            }
          }
        } catch (error) {
          console.warn(
            `Failed to resolve OnlineFix Fixes repair directory "${directoryUrl}": ${error.message}`
          );
        }
      }
    } catch (error) {
      console.warn(`Failed to resolve OnlineFix Fixes server page "${serverUrl}": ${error.message}`);
    }
  }

  // `drive.online-fix.me` is more fragile under FlareSolverr. Only try it if
  // hosters did not yield any Fix Repair links.
  if (uris.length === 0) {
    for (const serverUrl of driveUrls) {
      try {
        console.log(`OnlineFix Fixes -> opening drive page: ${serverUrl}`);
        const html = await fetchWithFlareSolverr(serverUrl, sessionId);
        const fixUris = extractFixUrisFromHtml(html, serverUrl);
        const fixRepairDirs = extractFixRepairDirectoriesFromHtml(html, serverUrl);

        console.log(
          `OnlineFix Fixes -> drive page parsed: fixFiles=${fixUris.length}, fixRepairDirs=${fixRepairDirs.length}`
        );
        if (fixUris.length === 0 && fixRepairDirs.length === 0) {
          console.log(
            `OnlineFix Fixes -> drive html preview: ${html.slice(0, 400).replace(/\s+/g, " ")}`
          );
        }

        for (const uri of fixUris) {
          if (!uris.includes(uri)) {
            uris.push(uri);
          }
        }

        for (const directoryUrl of fixRepairDirs) {
          try {
            console.log(`OnlineFix Fixes -> opening drive repair dir: ${directoryUrl}`);
            const repairHtml = await fetchWithFlareSolverr(directoryUrl, sessionId);
            const repairUris = extractFixUrisFromHtml(repairHtml, directoryUrl);

            console.log(`OnlineFix Fixes -> drive repair dir parsed: repairFiles=${repairUris.length}`);

            for (const uri of repairUris) {
              if (!uris.includes(uri)) {
                uris.push(uri);
              }
            }
          } catch (error) {
            console.warn(
              `Failed to resolve OnlineFix Fixes repair directory "${directoryUrl}": ${error.message}`
            );
          }
        }
      } catch (error) {
        console.warn(`Failed to resolve OnlineFix Fixes server page "${serverUrl}": ${error.message}`);
      }
    }
  }

  return uris;
}

async function fetchWithRetries(page, entry, sessionId, retries = 2) {
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const details = await extractPostDetails(page, entry.url);
      const uris = await fetchFixUris(details, sessionId);

      return {
        title: cleanTitle(details.title || entry.title),
        uploadDate: details.uploadDate || null,
        fileSize: details.fileSize || null,
        uris
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

      await sleep(randomBetween(2500, 4500));
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
  const sessionId = await createFlareSolverrSession();

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

      const scraped = await fetchWithRetries(page, entry, sessionId);
      progress.completed += 1;

      if (!scraped.uris.length) {
        progress.skipped += 1;
        console.log(`[${progress.completed}/${progress.total}] Skipped ${scraped.title} (no fix URIs found)`);
      } else {
        if (options.maxItems && results.length >= options.maxItems) {
          break;
        }

        results.push(scraped);
        console.log(`[${progress.completed}/${progress.total}] ${scraped.title}`);
      }

      await sleep(randomBetween(2000, 3500));
    }
  } finally {
    await destroyFlareSolverrSession(sessionId);
    await page.close();
  }
}

async function scrape(context, options) {
  await ensureLoggedIn(context);
  const entries = await resolveIndexLinks(context, options);
  const existingMap = buildExistingDownloadsMap(options.existingDownloads);

  if (options.maxItems) {
    console.log(`Test mode active. Targeting ${options.maxItems} valid items.`);
  }

  const queue = [...entries];
  const results = [];
  const workerCount = Math.min(options.workerOverride || 2, queue.length);
  const progress = {
    completed: 0,
    total: queue.length,
    skipped: 0,
    reused: 0
  };

  console.log(`Loaded ${existingMap.size} cached OnlineFix Fixes entries.`);
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
    console.log(`Skipped ${progress.skipped} OnlineFix Fixes items because no fix URIs were found.`);
  }

  if (progress.reused) {
    console.log(`Reused ${progress.reused} OnlineFix Fixes items from the existing JSON.`);
  }

  if (options.isTestMode && results.length) {
    console.log("Sample results:");
    console.log(JSON.stringify(results.slice(0, 3), null, 2));
  }

  return results;
}

module.exports = {
  displayName: "OnlineFix Fixes",
  outputName: "onlinefix-fixes",
  scrape
};
