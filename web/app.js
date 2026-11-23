// Seekr's search page: reads the query from the address bar, asks the server, shows the results.
const PAGE_SIZE = 10;
const MAX_RESULTS = 30; // the reranker scores the best 30 pages per query

const form = document.getElementById("search-form");
const input = document.getElementById("q");
const statusLine = document.getElementById("status");
const resultList = document.getElementById("results");
const pager = document.getElementById("pager");
const prevButton = document.getElementById("prev");
const nextButton = document.getElementById("next");
const pageLabel = document.getElementById("page-label");

function readUrl() {
  const params = new URLSearchParams(location.search);
  const page = Math.max(1, parseInt(params.get("page"), 10) || 1);
  return { query: params.get("q") || "", page };
}

async function search(query, page) {
  input.value = query;
  document.body.classList.toggle("searching", query !== "");
  document.title = query ? `${query} - Seekr` : "Seekr";
  resultList.replaceChildren();
  pager.hidden = true;
  statusLine.textContent = query ? "Searching…" : "";
  if (!query) return;
  try {
    const offset = (page - 1) * PAGE_SIZE;
    const response = await fetch(`/ui/search?q=${encodeURIComponent(query)}&offset=${offset}`);
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "That search didn't work.");
    showResults(data, page);
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

function showResults(data, page) {
  const first = (page - 1) * PAGE_SIZE + 1;
  const last = first + data.results.length - 1;
  statusLine.textContent = data.results.length
    ? `Results ${first}–${last} · ${data.took_ms} ms`
    : `No results for “${data.query}”.`;
  resultList.append(...data.results.map(resultItem));
  pageLabel.textContent = `Page ${page}`;
  prevButton.disabled = page === 1;
  nextButton.disabled = data.results.length < PAGE_SIZE || page * PAGE_SIZE >= MAX_RESULTS;
  pager.hidden = prevButton.disabled && nextButton.disabled;
}

function resultItem(result) {
  const item = document.createElement("li");
  item.className = "result";
  const title = document.createElement("a");
  title.className = "title";
  title.href = result.url;
  title.textContent = result.title; // textContent never interprets HTML, so a page title can't inject code
  const meta = document.createElement("div");
  meta.className = "meta";
  const badge = document.createElement("span");
  badge.className = `badge ${relevanceLevel(result.relevance)}`;
  badge.textContent = `${Math.round(result.relevance * 100)}% relevant`;
  badge.title = "How well this page answers your query, according to the relevance model";
  const url = document.createElement("span");
  url.className = "url";
  url.textContent = result.url.replace(/^https?:\/\//, "").replace(/\/$/, "");
  meta.append(badge, url);
  const snippet = document.createElement("p");
  snippet.className = "snippet";
  snippet.innerHTML = result.snippet; // safe: the server escaped the page text and only added <mark> tags
  item.append(title, meta, snippet);
  return item;
}

function relevanceLevel(relevance) {
  if (relevance >= 0.8) return "high";
  return relevance >= 0.4 ? "mid" : "low";
}

function go(query, page) {
  const pagePart = page > 1 ? `&page=${page}` : "";
  history.pushState(null, "", query ? `/?q=${encodeURIComponent(query)}${pagePart}` : "/");
  window.scrollTo(0, 0);
  search(query, page);
}

form.addEventListener("submit", (event) => {
  event.preventDefault(); // stop the browser's own page reload; we fetch the results ourselves
  go(input.value.trim(), 1);
});
prevButton.addEventListener("click", () => go(readUrl().query, readUrl().page - 1));
nextButton.addEventListener("click", () => go(readUrl().query, readUrl().page + 1));
window.addEventListener("popstate", () => search(readUrl().query, readUrl().page)); // Back/Forward buttons
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement !== input) {
    event.preventDefault();
    input.focus();
    input.select();
  }
});

// Dark mode: follow the system setting until the visitor picks one with the button.
const root = document.documentElement;
try {
  const saved = localStorage.getItem("seekr-theme");
  if (saved) root.dataset.theme = saved;
} catch (error) {} // storage can be blocked (private mode); the page still works
document.getElementById("theme").addEventListener("click", () => {
  const isDark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = isDark ? "light" : "dark";
  try {
    localStorage.setItem("seekr-theme", root.dataset.theme);
  } catch (error) {}
});

search(readUrl().query, readUrl().page);
