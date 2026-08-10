function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomBetween(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function cleanTitle(rawTitle) {
  if (!rawTitle) {
    return "";
  }

  return rawTitle.replace(/\s+/g, " ").trim();
}

module.exports = {
  cleanTitle,
  randomBetween,
  sleep
};
