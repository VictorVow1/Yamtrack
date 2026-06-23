// fork:tabbed-discover -- Alpine mixin for the Discover tab bar.
//
// Spread into the upstream discoverPage() component so the host file keeps only a
// one-line hook:
//
//     ...window.discoverTabs("{% url 'discover_tab' %}"),
//
// `this` inside these methods resolves to the merged component, so selectedMedia /
// discoverDebug come from the host. selectedTab is re-seeded from the server's
// first-enabled tab by each tablist's x-init once the rows render, so the default
// here only covers the brief moment before that runs.
window.discoverTabs = function (tabUrl) {
  return {
    selectedTab: "trending",
    selectedTabByMedia: {},
    switchTab(tabKey) {
      if (!tabKey || tabKey === this.selectedTab) {
        return;
      }
      this.selectedTab = tabKey;
      const params = new URLSearchParams();
      params.set("media_type", this.selectedMedia);
      params.set("tab", tabKey);
      if (this.discoverDebug) {
        params.set("discover_debug", "1");
      }
      htmx.ajax("GET", `${tabUrl}?${params.toString()}`, {
        target: "#discover-tab-content",
        swap: "innerHTML",
      });
    },
    switchTabFor(mediaType, tabKey) {
      if (!mediaType || !tabKey) {
        return;
      }
      if ((this.selectedTabByMedia[mediaType] || "trending") === tabKey) {
        return;
      }
      this.selectedTabByMedia = { ...this.selectedTabByMedia, [mediaType]: tabKey };
      const params = new URLSearchParams();
      params.set("media_type", mediaType);
      params.set("tab", tabKey);
      params.set("layout", "grid");
      params.set("active_media_type", "all");
      if (this.discoverDebug) {
        params.set("discover_debug", "1");
      }
      htmx.ajax("GET", `${tabUrl}?${params.toString()}`, {
        target: `#all-media-grid-${mediaType}`,
        swap: "innerHTML",
      });
    },
  };
};
