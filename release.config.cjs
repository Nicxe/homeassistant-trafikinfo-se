const config = require("@nicxe/semantic-release-config")({
  componentDir: "custom_components/trafikinfo_se",
  manifestPath: "custom_components/trafikinfo_se/manifest.json",
  projectName: "Trafikinfo SE",
  repoSlug: "Nicxe/homeassistant-trafikinfo-se"
}
);

const githubPlugin = config.plugins.find(
  (plugin) => Array.isArray(plugin) && plugin[0] === "@semantic-release/github"
);

if (githubPlugin?.[1]) {
  githubPlugin[1].successCommentCondition = false;
}

module.exports = config;
