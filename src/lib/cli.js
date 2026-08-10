function parseCliArgs(argv) {
  const isTestMode = argv.includes("--test");
  const limitArg = argv.find((arg) => arg.startsWith("--limit="));
  const workersArg = argv.find((arg) => arg.startsWith("--workers="));

  const parsedLimit = limitArg ? Number.parseInt(limitArg.split("=")[1], 10) : null;
  const parsedWorkers = workersArg ? Number.parseInt(workersArg.split("=")[1], 10) : null;

  return {
    isTestMode,
    maxItems: Number.isInteger(parsedLimit) && parsedLimit > 0 ? parsedLimit : isTestMode ? 20 : null,
    workerOverride: Number.isInteger(parsedWorkers) && parsedWorkers > 0 ? parsedWorkers : null
  };
}

module.exports = {
  parseCliArgs
};
