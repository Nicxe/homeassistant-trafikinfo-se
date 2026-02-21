const config = require("@nicxe/semantic-release-config")({
  kind: "assets",
  projectName: "Trafikinfo SE Alert Card",
  repoSlug: "Nicxe/homeassistant-trafikinfo-se-card",
  assets: [
    {
      path: "trafikinfo-se-alert-card.js",
      label: "trafikinfo-se-alert-card.js"
    }
  ]
}
);

const githubPlugin = config.plugins.find(
  (plugin) => Array.isArray(plugin) && plugin[0] === "@semantic-release/github"
);

if (githubPlugin?.[1]) {
  githubPlugin[1].successCommentCondition = false;
}

module.exports = config;
