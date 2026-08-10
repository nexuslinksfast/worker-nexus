const fs = require("fs");

function main() {
  const [, , filePath, expectedName, sourceId] = process.argv;

  if (!filePath || !expectedName || !sourceId) {
    throw new Error("Usage: node src/tools/validate-json.js <filePath> <expectedName> <sourceId>");
  }

  const raw = fs.readFileSync(filePath, "utf8");
  const data = JSON.parse(raw);

  if (sourceId === "instant-gaming") {
    const hasSections = [
      "hero",
      "trending",
      "preorders",
      "bestsellers",
      "reviews",
      "weekly_deals"
    ].every((section) => Array.isArray(data[section]));

    if (!hasSections) {
      throw new Error(`Invalid JSON structure for ${sourceId}`);
    }

    const totalItems = [
      ...data.hero,
      ...data.trending,
      ...data.preorders,
      ...data.bestsellers,
      ...data.reviews,
      ...data.weekly_deals
    ].length;

    if (totalItems === 0) {
      throw new Error(`Invalid JSON for ${sourceId}: no items found`);
    }

    console.log(`${sourceId} entries: ${totalItems}`);
    return;
  }

  if (!data || data.name !== expectedName || !Array.isArray(data.downloads) || data.downloads.length === 0) {
    throw new Error(`Invalid JSON for ${sourceId}`);
  }

  console.log(`${sourceId} entries: ${data.downloads.length}`);
}

main();
