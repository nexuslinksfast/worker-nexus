const fs = require("fs");
const path = require("path");

function loadSourceStatus(source) {
  const filePath = path.join(process.cwd(), "public", source.file);

  try {
    const raw = fs.readFileSync(filePath, "utf8");
    const json = JSON.parse(raw);
    let entries = 0;

    if (source.key === "instant-gaming") {
      const sections = [
        "hero",
        "trending",
        "preorders",
        "bestsellers",
        "reviews",
        "weekly_deals"
      ];
      entries = sections.reduce((sum, section) => {
        if (Array.isArray(json[section])) {
          return sum + json[section].length;
        }
        return sum;
      }, 0);
    } else {
      entries = Array.isArray(json.downloads) ? json.downloads.length : 0;
    }

    if (entries > 0) {
      return {
        ...source,
        status: source.updatedThisRun ? "healthy" : "stale",
        entries,
        dataUpdatedAt: source.updatedThisRun ? new Date().toISOString() : null
      };
    }
  } catch {
    return {
      ...source,
      status: "failed",
      entries: 0,
      dataUpdatedAt: null
    };
  }

  return {
    ...source,
    status: "failed",
    entries: 0,
    dataUpdatedAt: null
  };
}

function main() {
  const now = new Date().toISOString();
  const repository = process.env.REPOSITORY;
  const runId = process.env.RUN_ID;
  const runNumber = Number(process.env.RUN_NUMBER || 0);
  const serverUrl = process.env.SERVER_URL;

  const sources = [
    {
      key: "steamrip",
      name: "SteamRip",
      file: "steamrip.json",
      updatedThisRun: process.env.STEAMRIP_UPDATED === "true"
    },
    {
      key: "fitgirl",
      name: "FitGirl",
      file: "fitgirl.json",
      updatedThisRun: process.env.FITGIRL_UPDATED === "true"
    },
    {
      key: "freegog",
      name: "FreeGOG",
      file: "freegog.json",
      updatedThisRun: process.env.FREEGOG_UPDATED === "true"
    },
    {
      key: "onlinefix",
      name: "OnlineFix",
      file: "onlinefix.json",
      updatedThisRun: process.env.ONLINEFIX_UPDATED === "true"
    },
    {
      key: "onlinefix-fixes",
      name: "OnlineFix Fixes",
      file: "onlinefix-fixes.json",
      updatedThisRun: process.env.ONLINEFIX_FIXES_UPDATED === "true"
    },
    {
      key: "iggames",
      name: "IGGames",
      file: "iggames.json",
      updatedThisRun: process.env.IGGAMES_UPDATED === "true"
    },
    {
      key: "insaneramzes",
      name: "InsaneRamZes",
      file: "InsaneRamZes.json",
      updatedThisRun: process.env.INSANERAMZES_UPDATED === "true"
    },
    {
      key: "instant-gaming",
      name: "Instant Gaming",
      file: "instant-gaming-deals.json",
      updatedThisRun: process.env.INSTANT_GAMING_UPDATED === "true"
    },
    {
      key: "dodi",
      name: "DODI",
      file: "dodi.json",
      updatedThisRun: process.env.DODI_UPDATED === "true"
    },
    {
      key: "rexagames",
      name: "RexaGames",
      file: "rexagames.json",
      updatedThisRun: process.env.REXAGAMES_UPDATED === "true"
    }
  ];

  const output = {
    generatedAt: now,
    runId,
    runNumber,
    repository,
    actionsUrl: `${serverUrl}/${repository}/actions/runs/${runId}`,
    sources: [],
    summary: {
      healthy: 0,
      stale: 0,
      failed: 0
    }
  };

  for (const source of sources) {
    const status = loadSourceStatus(source);
    output.summary[status.status] += 1;
    output.sources.push(status);
  }

  fs.writeFileSync(
    path.join(process.cwd(), "public", "status.json"),
    `${JSON.stringify(output, null, 2)}\n`,
    "utf8"
  );

  console.log("Generated public/status.json");
}

main();
