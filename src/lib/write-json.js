const fs = require("fs/promises");
const path = require("path");

async function saveJsonFile(outputPath, payload) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

module.exports = {
  saveJsonFile
};
