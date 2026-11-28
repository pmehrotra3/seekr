// Musafir's page: the landing page, the results view and free API key signup.
const PAGE_SIZE = 10;
const MAX_RESULTS = 30; // the reranker scores the best 30 pages per query
const KINDS = ["all", "images", "videos", "news"];

const $ = (id) => document.getElementById(id);
const forms = document.querySelectorAll("form.search");
const inputs = [...forms].map((form) => form.elements.q);

function readUrl() {
  const params = new URLSearchParams(location.search);
  const kind = KINDS.includes(params.get("tab")) ? params.get("tab") : "all";
  return { query: (params.get("q") || "").trim(), page: Math.max(1, parseInt(params.get("page"), 10) || 1), kind };
}

function link(query, page = 1, kind = "all") {
  if (!query) return "/";
  return `/?q=${encodeURIComponent(query)}${kind !== "all" ? `&tab=${kind}` : ""}${page > 1 ? `&page=${page}` : ""}`;
}

async function search(query, page, kind = "all") {
  inputs.forEach((input) => (input.value = query));
  document.body.classList.toggle("searching", query !== "");
  $("home").hidden = query !== "";
  $("results-view").hidden = query === "";
  document.title = query ? `${query} - Musafir` : "Musafir: search without the noise";
  $("results").replaceChildren();
  $("about").replaceChildren();
  $("about").hidden = true;
  $("pager").hidden = true;
  $("results").className = `results ${kind}`;
  document.querySelectorAll(".tabs a").forEach((tab) => {
    tab.href = link(query, 1, tab.dataset.kind);
    tab.classList.toggle("active", tab.dataset.kind === kind);
  });
  if (!query) return;
  $("status").textContent = "Searching…";
  try {
    const offset = kind === "images" ? 0 : (page - 1) * PAGE_SIZE;
    const response = await fetch(`/ui/search?q=${encodeURIComponent(query)}&offset=${offset}&kind=${kind}`);
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "That search didn't work.");
    showResults(data, page, kind);
  } catch (error) {
    $("status").textContent = error.message;
  }
}

const NOTHING = {
  all: "No results. Try different words.",
  images: "No pictures for this search.",
  videos: "No videos for this search. Videos come from pages that embed one, so there are only a few thousand.",
  news: "No news stories for this search.",
};

function showResults(data, page, kind) {
  const first = kind === "images" ? 1 : (page - 1) * PAGE_SIZE + 1;
  $("status").textContent = data.results.length
    ? `Results ${first}–${first + data.results.length - 1} · ${(data.took_ms / 1000).toFixed(2)} seconds`
    : NOTHING[kind];
  const render = { all: resultItem, images: imageItem, videos: videoItem, news: resultItem }[kind];
  $("results").append(...data.results.map(render));
  if (data.about) showAbout(data.about);
  $("page-label").textContent = `Page ${page}`;
  $("prev").disabled = page === 1;
  $("next").disabled = kind === "images" || data.results.length < PAGE_SIZE || page * PAGE_SIZE >= MAX_RESULTS;
  $("pager").hidden = $("prev").disabled && $("next").disabled;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text) node.textContent = text; // textContent never interprets HTML, so page text can't inject code
  return node;
}

const siteName = (url) => new URL(url).hostname.replace(/^www\./, "");
const DATE = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });

function picture(src, className, alt = "") {
  const image = element("img", className);
  image.src = src; // https only (checked on the server)
  image.alt = alt;
  image.loading = "lazy";
  image.referrerPolicy = "no-referrer"; // don't tell the image's site what was searched
  return image;
}

function resultItem(result) {
  const date = result.published ? ` · ${DATE.format(new Date(result.published))}` : "";
  const site = element("div", "site", siteName(result.url) + date);
  const title = element("a", "title", result.title);
  title.href = result.url;
  const snippet = element("p", "snippet");
  snippet.innerHTML = result.snippet; // safe: the server escaped the page text and only added <mark> tags
  const text = element("div", "text");
  text.append(site, title, snippet);
  const item = element("li", "result");
  item.append(text);
  if (result.image) {
    const image = picture(result.image, "thumb");
    image.onerror = () => image.remove();
    item.append(image);
  }
  return item;
}

function imageItem(result) {
  const card = element("a", "image-card");
  card.href = result.url;
  const image = picture(result.image, "", result.title);
  image.onerror = () => card.parentElement?.remove();
  card.append(image, element("span", "image-title", result.title), element("span", "site", siteName(result.url)));
  const item = element("li", "");
  item.append(card);
  return item;
}

function videoItem(result) {
  const youtube = result.video.match(/youtube\.com\/watch\?v=([\w-]{11})/);
  const poster = youtube ? `https://i.ytimg.com/vi/${youtube[1]}/hqdefault.jpg` : result.image;
  const player = element("a", "video-thumb");
  player.href = result.video;
  if (poster) player.append(picture(poster, ""));
  player.append(element("span", "play", "▶"));
  const title = element("a", "title", result.title);
  title.href = result.video;
  const page = element("a", "site", `on ${siteName(result.url)}`);
  page.href = result.url;
  const text = element("div", "text");
  text.append(title, page);
  const item = element("li", "result video");
  item.append(player, text);
  return item;
}

// Info panel: shown when one of the top results is the page about what was searched (like a Wikipedia article).
function showAbout(about) {
  const panel = $("about");
  if (about.image) {
    const image = picture(about.image, "about-image", about.title);
    image.onerror = () => image.remove();
    panel.append(image);
  }
  panel.append(element("h2", "about-title", about.title));
  if (about.summary) panel.append(element("p", "about-summary", about.summary));
  const source = element("a", "about-source", `Read more on ${siteName(about.url)} →`);
  source.href = about.url;
  panel.append(source);
  panel.hidden = false;
}

function go(query, page = 1, kind = "all") {
  history.pushState(null, "", link(query, page, kind));
  window.scrollTo(0, 0);
  search(query, page, kind);
}

forms.forEach((form) =>
  form.addEventListener("submit", (event) => {
    event.preventDefault(); // we fetch the results ourselves instead of reloading the page
    go(form.elements.q.value.trim(), 1, readUrl().kind); // stay on the same tab
  }),
);
document.querySelectorAll(".try a").forEach((example) =>
  example.addEventListener("click", (event) => {
    event.preventDefault();
    go(new URL(example.href).searchParams.get("q"));
  }),
);
document.querySelectorAll(".tabs a").forEach((tab) =>
  tab.addEventListener("click", (event) => {
    event.preventDefault();
    go(readUrl().query, 1, tab.dataset.kind);
  }),
);
const here = () => readUrl();
$("prev").addEventListener("click", () => go(here().query, here().page - 1, here().kind));
$("next").addEventListener("click", () => go(here().query, here().page + 1, here().kind));
window.addEventListener("popstate", () => search(here().query, here().page, here().kind)); // Back/Forward buttons
document.addEventListener("keydown", (event) => {
  const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
  if (event.key === "/" && !typing) {
    event.preventDefault();
    const input = inputs.find((input) => input.offsetParent) || inputs[0]; // the visible search box
    input.focus();
    input.select();
  }
});

// Free API key: the server returns it once; it only keeps a hash.
$("example").textContent = $("example").textContent.replace("https://seekr.pranavmehrotra.com", location.origin);
$("key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  button.disabled = true;
  $("key-status").textContent = "";
  try {
    const response = await fetch("/ui/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: event.target.elements.name.value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Couldn't create a key.");
    $("key").textContent = data.key;
    $("key-box").hidden = false;
    $("example").textContent = $("example").textContent.replace(/Bearer \S+"/, `Bearer ${data.key}"`);
  } catch (error) {
    $("key-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
$("copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("key").textContent);
    $("copy").textContent = "Copied";
  } catch (error) {
    getSelection().selectAllChildren($("key")); // clipboard blocked: select it so it can be copied by hand
  }
});

// Dark mode: follow the system setting until the visitor picks one.
const root = document.documentElement;
try {
  const saved = localStorage.getItem("musafir-theme");
  if (saved) root.dataset.theme = saved;
} catch (error) {} // storage can be blocked (private mode); the page still works
document.querySelector(".theme").addEventListener("click", () => {
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try {
    localStorage.setItem("musafir-theme", root.dataset.theme);
  } catch (error) {}
});

search(here().query, here().page, here().kind);
