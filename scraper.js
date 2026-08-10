const { runSource } = require("./src/lib/runner");

async function main() {
  const sourceId = process.argv[2] && !process.argv[2].startsWith("--") ? process.argv[2] : "steamrip";
  const cliArgs = process.argv[2] && !process.argv[2].startsWith("--")
    ? process.argv.slice(3)
    : process.argv.slice(2);

  await runSource(sourceId, cliArgs);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
