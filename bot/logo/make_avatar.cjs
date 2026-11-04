// Bot avatar from the site's brand mark (platform/dist/assets/mark.svg): full-bleed square,
// because Telegram crops the photo to a circle. Usage: node make_avatar.cjs (needs sharp)
const path = require("path");
const sharp = require("sharp");

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="640" height="640">
  <rect width="64" height="64" fill="#153e35"/>
  <text x="15" y="46" fill="#fff" font-family="Georgia" font-size="52" font-style="italic">s</text>
  <circle cx="46" cy="43" r="4" fill="#e3ab54"/>
</svg>`;
const out = path.join(__dirname, "bot-avatar.png");
const circle = Buffer.from(`<svg width="640" height="640"><circle cx="320" cy="320" r="320"/></svg>`);
(async () => {
  await sharp(Buffer.from(svg)).png().toFile(out);
  await sharp(out).composite([{ input: circle, blend: "dest-in" }]).png()
    .toFile(path.join(__dirname, "bot-avatar-preview-circle.png"));
  console.log(out);
})();
