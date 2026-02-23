const config = require("@nicxe/semantic-release-config")({
  componentDir: "custom_components/trafikinfo_se",
  manifestPath: "custom_components/trafikinfo_se/manifest.json",
  projectName: "Trafikinfo SE",
  repoSlug: "Nicxe/homeassistant-trafikinfo-se",
  assets: [
    {
      path: "custom_components/trafikinfo_se.zip",
      label: "trafikinfo_se.zip"
    },
    {
      path: "www/trafikinfo-se-alert-card.js",
      label: "trafikinfo-se-alert-card.js"
    }
  ]
});

const githubPlugin = config.plugins.find(
  (plugin) => Array.isArray(plugin) && plugin[0] === "@semantic-release/github"
);

if (githubPlugin?.[1]) {
  githubPlugin[1].successCommentCondition = false;
}

module.exports = config;
