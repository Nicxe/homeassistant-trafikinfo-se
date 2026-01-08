const fs = require("fs");
const path = require("path");

const mainTemplate = fs.readFileSync(
  path.join(__dirname, ".release", "release-notes.hbs"),
  "utf8"
);

module.exports = {
  tagFormat: "v${version}",
  branches: [
    "main",
    { name: "beta", prerelease: true }
  ],
  plugins: [
    [
      "@semantic-release/commit-analyzer",
      { preset: "conventionalcommits" }
    ],
    [
      "@semantic-release/release-notes-generator",
      {
        preset: "conventionalcommits",
        writerOpts: {
          mainTemplate
        }
      }
    ],
    [
      "@semantic-release/exec",
      {
        prepareCmd:
          "jq '.version = \"${nextRelease.version}\"' custom_components/trafikinfo_se/manifest.json > manifest.tmp && mv manifest.tmp custom_components/trafikinfo_se/manifest.json && cd custom_components && zip -r trafikinfo_se.zip trafikinfo_se"
      }
    ],
    [
      "@semantic-release/github",
      {
        draft: true,
        assets: [
          {
            path: "custom_components/trafikinfo_se.zip",
            label: "trafikinfo_se.zip"
          }
        ]
      }
    ]
  ]
};
