// Seekr's page: the landing page, the results view and free API key signup.
const PAGE_SIZE = 10;
const MAX_RESULTS = 30; // the reranker scores the best 30 pages per query

const $ = (id) => document.getElementById(id);
const forms = document.querySelectorAll("form.search");
const inputs = [...forms].map((form) => form.elements.q);

function readUrl() {
  const params = new URLSearchParams(location.search);
  return { query: (params.get("q") || "").trim(), page: Math.max(1, parseInt(params.get("page"), 10) || 1) };
}

async function search(query, page) {
  inputs.forEach((input) => (input.value = query));
  document.body.classList.toggle("searching", query !== "");
  $("home").hidden = query !== "";
  $("results-view").hidden = query === "";
  document.title = query ? `${query} - Seekr` : "Seekr: search without the noise";
  $("results").replaceChildren();
  $("about").replaceChildren();
  $("about").hidden = true;
  $("pager").hidden = true;
  if (!query) return;
  $("status").textContent = "Searching…";
  try {
    const offset = (page - 1) * PAGE_SIZE;
    const response = await fetch(`/ui/search?q=${encodeURIComponent(query)}&offset=${offset}`);
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "That search didn't work.");
    showResults(data, page);
  } catch (error) {
    $("status").textContent = error.message;
  }
}

function showResults(data, page) {
  const first = (page - 1) * PAGE_SIZE + 1;
  $("status").textContent = data.results.length
    ? `Results ${first}–${first + data.results.length - 1} · ${(data.took_ms / 1000).toFixed(2)} seconds`
    : `No results for “${data.query}”. Try different words.`;
  $("results").append(...data.results.map(resultItem));
  if (data.about) showAbout(data.about);
  $("page-label").textContent = `Page ${page}`;
  $("prev").disabled = page === 1;
  $("next").disabled = data.results.length < PAGE_SIZE || page * PAGE_SIZE >= MAX_RESULTS;
  $("pager").hidden = $("prev").disabled && $("next").disabled;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text) node.textContent = text; // textContent never interprets HTML, so page text can't inject code
  return node;
}

function resultItem(result) {
  const url = new URL(result.url);
  const site = element("div", "site", url.hostname.replace(/^www\./, ""));
  const title = element("a", "title", result.title);
  title.href = result.url;
  const snippet = element("p", "snippet");
  snippet.innerHTML = result.snippet; // safe: the server escaped the page text and only added <mark> tags
  const text = element("div", "text");
  text.append(site, title, snippet);
  const item = element("li", "result");
  item.append(text);
  if (result.image) {
    const image = element("img", "thumb");
    image.src = result.image; // https only (checked on the server)
    image.alt = "";
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer"; // don't tell the image's site what was searched
    image.onerror = () => image.remove();
    item.append(image);
  }
  return item;
}

// Info panel: shown when one of the top results is the page about what was searched (like a Wikipedia article).
function showAbout(about) {
  const panel = $("about");
  if (about.image) {
    const image = element("img", "about-image");
    image.src = about.image;
    image.alt = about.title;
    image.referrerPolicy = "no-referrer";
    image.onerror = () => image.remove();
    panel.append(image);
  }
  panel.append(element("h2", "about-title", about.title));
  if (about.summary) panel.append(element("p", "about-summary", about.summary));
  const source = element("a", "about-source", `Read more on ${new URL(about.url).hostname.replace(/^www\./, "")} →`);
  source.href = about.url;
  panel.append(source);
  panel.hidden = false;
}

function go(query, page = 1) {
  const pagePart = page > 1 ? `&page=${page}` : "";
  history.pushState(null, "", query ? `/?q=${encodeURIComponent(query)}${pagePart}` : "/");
  window.scrollTo(0, 0);
  search(query, page);
}

forms.forEach((form) =>
  form.addEventListener("submit", (event) => {
    event.preventDefault(); // we fetch the results ourselves instead of reloading the page
    go(form.elements.q.value.trim());
  }),
);
document.querySelectorAll(".try a").forEach((link) =>
  link.addEventListener("click", (event) => {
    event.preventDefault();
    go(new URL(link.href).searchParams.get("q"));
  }),
);
$("prev").addEventListener("click", () => go(readUrl().query, readUrl().page - 1));
$("next").addEventListener("click", () => go(readUrl().query, readUrl().page + 1));
window.addEventListener("popstate", () => search(readUrl().query, readUrl().page)); // Back/Forward buttons
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
  const saved = localStorage.getItem("seekr-theme");
  if (saved) root.dataset.theme = saved;
} catch (error) {} // storage can be blocked (private mode); the page still works
document.querySelector(".theme").addEventListener("click", () => {
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try {
    localStorage.setItem("seekr-theme", root.dataset.theme);
  } catch (error) {}
});

search(readUrl().query, readUrl().page);
