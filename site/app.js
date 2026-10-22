// Page des nouvelles sorties : charge releases.json, affiche onglets, filtres et cartes.
import {
  PLATFORM_LABELS,
  TYPE_LABELS,
  dayToUtc,
  emptyMarks,
  formatHash,
  groupByWeek,
  isNew,
  matches,
  mergeMarks,
  migrateMarks,
  notices,
  parseHash,
  parseMarks,
  releasesForTab,
  tabCounts,
  tabOf,
  toggleFavorite,
  toggleSeen,
} from "./logic.js";

// Logos (Simple Icons, CC0) affichés avec chaque lien, conformément aux règles d'attribution.
const ICONS = {
  soundcloud:
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M23.999 14.165c-.052 1.796-1.612 3.169-3.4 3.169h-8.18a.68.68 0 0 1-.675-.683V7.862a.747.747 0 0 1 .452-.724s.75-.513 2.333-.513a5.364 5.364 0 0 1 2.763.755 5.433 5.433 0 0 1 2.57 3.54c.282-.08.574-.121.868-.12.884 0 1.73.358 2.347.992s.948 1.49.922 2.373ZM10.721 8.421c.247 2.98.427 5.697 0 8.672a.264.264 0 0 1-.53 0c-.395-2.946-.22-5.718 0-8.672a.264.264 0 0 1 .53 0ZM9.072 9.448c.285 2.659.37 4.986-.006 7.655a.277.277 0 0 1-.55 0c-.331-2.63-.256-5.02 0-7.655a.277.277 0 0 1 .556 0Zm-1.663-.257c.27 2.726.39 5.171 0 7.904a.266.266 0 0 1-.532 0c-.38-2.69-.257-5.21 0-7.904a.266.266 0 0 1 .532 0Zm-1.647.77a26.108 26.108 0 0 1-.008 7.147.272.272 0 0 1-.542 0 27.955 27.955 0 0 1 0-7.147.275.275 0 0 1 .55 0Zm-1.67 1.769c.421 1.865.228 3.5-.029 5.388a.257.257 0 0 1-.514 0c-.21-1.858-.398-3.549 0-5.389a.272.272 0 0 1 .543 0Zm-1.655-.273c.388 1.897.26 3.508-.01 5.412-.026.28-.514.283-.54 0-.244-1.878-.347-3.54-.01-5.412a.283.283 0 0 1 .56 0Zm-1.668.911c.4 1.268.257 2.292-.026 3.572a.257.257 0 0 1-.514 0c-.241-1.262-.354-2.312-.023-3.572a.283.283 0 0 1 .563 0Z"/></svg>',
  spotify:
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>',
};

const TAB_LABELS = { todo: "À découvrir", seen: "Déjà vus", fav: "Favoris" };
const EMPTY_TAB = {
  todo: "Tout est vu : les prochaines sorties arriveront ici.",
  seen: "Rien ici pour l'instant : marque une sortie avec « Déjà vu » pour la ranger ici.",
  fav: "Aucun favori : clique sur l'étoile d'une sortie pour l'ajouter ici.",
};
const STORAGE_KEY = "newrel.marks";

const dayFormat = new Intl.DateTimeFormat("fr-FR", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const monthFormat = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric", timeZone: "UTC" });
const weekFormat = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const stampFormat = new Intl.DateTimeFormat("fr-FR", { dateStyle: "long", timeStyle: "short" });

const page = { data: null, filters: parseHash(location.hash), now: new Date(), marks: emptyMarks(), visible: [] };
const $ = (selector) => document.querySelector(selector);

const safeUrl = (url) => (/^https:\/\//.test(url ?? "") ? url : "#");
const plural = (count, word) => `${count} ${word}${count > 1 ? "s" : ""}`;

// --- Stockage des marques (un navigateur peut refuser localStorage : la page marche quand même) --

function loadMarks() {
  try {
    return parseMarks(localStorage.getItem(STORAGE_KEY));
  } catch {
    return emptyMarks();
  }
}

function saveMarks() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(page.marks));
  } catch {
    showToast("Stockage du navigateur indisponible : tes marques seront perdues à la fermeture.");
  }
}

// --- En-tête -------------------------------------------------------------------------------------

function releaseDate(release) {
  if (release.precision === "day") return dayFormat.format(dayToUtc(release.date));
  if (release.precision === "month") return monthFormat.format(dayToUtc(`${release.date}-01`));
  return release.date;
}

function duration(hours) {
  return hours >= 48 ? `${Math.floor(hours / 24)} jours` : `${hours} heures`;
}

function noticeText(notice) {
  const name = PLATFORM_LABELS[notice.platform] ?? notice.platform;
  if (notice.quotaResetAt && Date.parse(notice.quotaResetAt) > page.now.getTime()) {
    const resume = stampFormat.format(new Date(notice.quotaResetAt));
    return `${name} : quota du jour épuisé, la vérification des artistes reprendra le ${resume}.`;
  }
  if (notice.kind === "stale") {
    return `Données vieilles de ${duration(notice.hours)} : la mise à jour quotidienne ne tourne plus (onglet Actions du dépôt).`;
  }
  if (notice.kind === "source-stale") {
    return `${name} : dernière mise à jour réussie il y a ${duration(notice.hours)}.`;
  }
  const state = {
    auth_expired: "ré-autorisation nécessaire, abonnements figés",
    partial: "mise à jour partielle",
    error: "en panne, données du dernier run réussi",
  }[notice.status];
  return `${name} : ${state ?? notice.status}${notice.message ? ` (${notice.message})` : ""}.`;
}

// Spotify (Development Mode) n'accepte qu'environ 100 requêtes de catalogue par jour : chaque
// mise à jour ne vérifie qu'une partie des artistes, à tour de rôle. On l'explique sur la page.
function rotationText(platform, source) {
  if (platform !== "spotify" || !source.followed) return "";
  const s = (count) => (count > 1 ? "s" : "");
  const parts = [
    "Spotify limite l'accès à environ 100 requêtes par jour : les artistes sont vérifiés à tour de rôle.",
  ];
  if (source.checked_last_run) {
    parts.push(`Dernière mise à jour : ${plural(source.checked_last_run, "artiste")} vérifié${s(source.checked_last_run)}.`);
  }
  if (source.oldest_check_at) {
    const hours = Math.max(0, Math.floor((page.now.getTime() - Date.parse(source.oldest_check_at)) / 3_600_000));
    parts.push(`Le moins récent l'a été il y a ${duration(hours)}.`);
  }
  if (source.unchecked) {
    parts.push(`${source.unchecked} pas encore vérifié${s(source.unchecked)} (premiers jours).`);
  }
  return parts.join(" ");
}

function renderHeader() {
  const { data } = page;
  const parts = [`Mis à jour le ${stampFormat.format(new Date(data.generated_at))}`];
  const rotation = [];
  for (const [platform, source] of Object.entries(data.sources)) {
    const followed = `${plural(source.followed, "artiste")} suivi${source.followed > 1 ? "s" : ""}`;
    parts.push(`${PLATFORM_LABELS[platform] ?? platform} : ${followed}`);
    rotation.push(rotationText(platform, source));
  }
  $("#meta").textContent = parts.join(" · ");
  const rotationLine = $("#rotation");
  rotationLine.textContent = rotation.filter(Boolean).join(" ");
  rotationLine.hidden = !rotationLine.textContent;
  $("#notices").replaceChildren(
    ...notices(data, page.now).map((notice) => {
      const paragraph = document.createElement("p");
      paragraph.className = `notice notice-${notice.level}`;
      paragraph.textContent = noticeText(notice);
      return paragraph;
    }),
  );
}

// --- Filtres -------------------------------------------------------------------------------------

function renderChips(fieldset, name, entries, selected) {
  fieldset.querySelectorAll("label").forEach((label) => label.remove());
  for (const [value, text] of entries) {
    const label = document.createElement("label");
    label.className = "chip";
    const input = document.createElement("input");
    Object.assign(input, { type: "checkbox", name, value, checked: !selected || selected.has(value) });
    label.append(input, document.createTextNode(text));
    fieldset.append(label);
  }
  fieldset.hidden = entries.length < 2;
}

function renderFilters() {
  const { releases, sources } = page.data;
  const platforms = Object.keys(PLATFORM_LABELS).filter(
    (platform) => platform in sources || releases.some((r) => r.links.some((link) => link.platform === platform)),
  );
  const types = Object.keys(TYPE_LABELS).filter((type) => releases.some((release) => release.type === type));
  renderChips($("#platforms"), "platform", platforms.map((p) => [p, PLATFORM_LABELS[p]]), page.filters.platforms);
  renderChips($("#types"), "type", types.map((t) => [t, TYPE_LABELS[t]]), page.filters.types);
  $("#q").value = page.filters.query;
  $("#new-only").checked = page.filters.newOnly;
}

function readFilters() {
  const selection = (name) => {
    const inputs = [...document.querySelectorAll(`input[name="${name}"]`)];
    const checked = inputs.filter((input) => input.checked).map((input) => input.value);
    return checked.length === inputs.length ? null : new Set(checked);
  };
  return {
    tab: page.filters.tab,
    query: $("#q").value.trim(),
    platforms: selection("platform"),
    types: selection("type"),
    newOnly: $("#new-only").checked,
  };
}

function updateHash() {
  history.replaceState(null, "", formatHash(page.filters) || `${location.pathname}${location.search}`);
}

// --- Cartes et liste -----------------------------------------------------------------------------

function card(release, fresh) {
  const node = $("#tpl-card").content.firstElementChild.cloneNode(true);
  node.dataset.id = release.id;
  const coverLink = release.cover && release.links.find((link) => link.platform === release.cover.platform);
  const cover = node.querySelector(".cover");
  cover.href = safeUrl((coverLink ?? release.links[0]).url);
  cover.setAttribute("aria-label", `${release.title} sur ${PLATFORM_LABELS[(coverLink ?? release.links[0]).platform]}`);
  if (release.cover) {
    const image = document.createElement("img");
    Object.assign(image, { src: safeUrl(release.cover.url), alt: "", loading: "lazy", decoding: "async", width: 300, height: 300 });
    cover.append(image);
  } else {
    cover.classList.add("cover-empty");
    cover.textContent = (release.artists[0]?.name || release.title || "?").slice(0, 1).toUpperCase();
  }
  node.classList.toggle("is-new", fresh);
  const type = node.querySelector(".type");
  type.textContent = TYPE_LABELS[release.type] ?? release.type;
  if (release.type_inferred) type.title = "Type déduit du nombre de titres";
  node.querySelector(".new").hidden = !fresh;
  node.querySelector(".archived").hidden = !release.archived;
  // Titre et artistes sont tronqués sur les petites cartes : le texte complet reste au survol.
  const title = node.querySelector(".title");
  title.textContent = release.title;
  title.title = release.title;
  const artists = node.querySelector(".artists");
  artists.textContent = release.artists.map((artist) => artist.name).join(", ");
  artists.title = artists.textContent;
  const date = node.querySelector(".date");
  date.textContent = releaseDate(release);
  date.dateTime = release.date;
  if (release.tracks > 1) node.querySelector(".tracks").textContent = ` · ${plural(release.tracks, "titre")}`;
  const links = node.querySelector(".links");
  for (const link of release.links) {
    const anchor = document.createElement("a");
    Object.assign(anchor, { className: `platform platform-${link.platform}`, href: safeUrl(link.url), target: "_blank", rel: "noopener" });
    anchor.innerHTML = ICONS[link.platform] ?? "";
    const platform = PLATFORM_LABELS[link.platform] ?? link.platform;
    anchor.setAttribute("aria-label", `Écouter « ${release.title} » sur ${platform}`);
    anchor.append(document.createTextNode(platform));
    links.append(anchor);
  }

  const seen = Boolean(page.marks.seen[release.id]);
  const favorite = Boolean(page.marks.fav[release.id]);
  const seenButton = node.querySelector(".mark-seen");
  seenButton.setAttribute("aria-pressed", String(seen));
  seenButton.textContent = seen ? "✓ Vu" : "Déjà vu";
  seenButton.title = seen ? "Remettre dans « À découvrir »" : "Ranger dans « Déjà vus »";
  seenButton.hidden = favorite; // un favori ne vit que dans l'onglet « Favoris »
  const star = node.querySelector(".mark-fav");
  star.setAttribute("aria-pressed", String(favorite));
  star.textContent = favorite ? "★" : "☆";
  const starLabel = favorite ? "Retirer des favoris" : "Ajouter aux favoris";
  star.setAttribute("aria-label", `${starLabel} : ${release.title}`);
  star.title = starLabel;
  return node;
}

function renderTabs() {
  const counts = tabCounts(page.data.releases, page.marks);
  for (const button of document.querySelectorAll(".tab")) {
    const tab = button.dataset.tab;
    const selected = tab === page.filters.tab;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    button.textContent = `${TAB_LABELS[tab]} (${counts[tab]})`;
  }
}

function render() {
  const { releases, rules, timezone } = page.data;
  const fresh = (release) => isNew(release, page.now, rules, timezone);
  const pool = releasesForTab(releases, page.marks, page.filters.tab);
  page.visible = pool.filter((release) => matches(release, page.filters, fresh));
  renderTabs();
  const fragment = document.createDocumentFragment();
  for (const { week, releases: items } of groupByWeek(page.visible)) {
    const section = $("#tpl-week").content.firstElementChild.cloneNode(true);
    section.querySelector("h2").textContent = `Semaine du vendredi ${weekFormat.format(dayToUtc(week))}`;
    section.querySelector(".count").textContent = plural(items.length, "sortie");
    section.querySelector(".grid").append(...items.map((release) => card(release, fresh(release))));
    fragment.append(section);
  }
  $("#list").replaceChildren(fragment);
  const empty = $("#empty");
  empty.hidden = page.visible.length > 0;
  if (!releases.length && page.filters.tab !== "fav") {
    empty.textContent = "Pas encore de sorties : la première collecte n'a pas eu lieu.";
  } else {
    empty.textContent = pool.length ? "Aucune sortie ne correspond à ces filtres." : EMPTY_TAB[page.filters.tab];
  }
  const markAll = $("#mark-all");
  markAll.hidden = page.filters.tab !== "todo" || page.visible.length < 2;
  markAll.textContent = `Tout marquer comme vu (${page.visible.length})`;
}

// --- Actions sur les marques ---------------------------------------------------------------------

let toastTimer;

function showToast(text, undo) {
  const toast = $("#toast");
  toast.replaceChildren(document.createTextNode(text));
  if (undo) {
    const button = document.createElement("button");
    Object.assign(button, { type: "button", className: "toast-undo", textContent: "Annuler" });
    button.addEventListener("click", () => {
      undo();
      toast.hidden = true;
    });
    toast.append(button);
  }
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 6000);
}

function applyMarks(marks, message) {
  const previous = page.marks;
  page.marks = marks;
  saveMarks();
  render();
  if (message) {
    showToast(message, () => {
      page.marks = previous;
      saveMarks();
      render();
    });
  }
}

function findRelease(id) {
  return releasesForTab(page.data.releases, page.marks, "fav").find((release) => release.id === id)
    ?? page.data.releases.find((release) => release.id === id);
}

function onCardClick(event) {
  const button = event.target.closest(".mark-seen, .mark-fav");
  if (!button) return;
  const release = findRelease(button.closest(".card").dataset.id);
  if (!release) return;
  if (button.classList.contains("mark-fav")) {
    const { archived, ...snapshot } = release;
    const marks = toggleFavorite(page.marks, snapshot, new Date());
    const destination = { todo: "« À découvrir »", seen: "« Déjà vus »" }[tabOf(release.id, marks)];
    const message = marks.fav[release.id]
      ? `« ${release.title} » rangé dans « Favoris ».`
      : `« ${release.title} » retiré des favoris${archived ? "" : `, de retour dans ${destination}`}.`;
    applyMarks(marks, message);
    return;
  }
  const seen = Boolean(page.marks.seen[release.id]);
  const message = seen ? `« ${release.title} » remis dans « À découvrir ».` : `« ${release.title} » rangé dans « Déjà vus ».`;
  applyMarks(toggleSeen(page.marks, release.id, new Date()), message);
}

function onMarkAll() {
  const ids = page.visible.map((release) => release.id);
  if (!ids.length || !confirm(`Ranger les ${ids.length} sorties affichées dans « Déjà vus » ?`)) return;
  applyMarks(toggleSeen(page.marks, ids, new Date()), `${plural(ids.length, "sortie")} rangée${ids.length > 1 ? "s" : ""} dans « Déjà vus ».`);
}

function onExport() {
  const blob = new Blob([JSON.stringify(page.marks, null, 2)], { type: "application/json" });
  const link = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob),
    download: "nouvelles-sorties-marques.json",
  });
  link.click();
  URL.revokeObjectURL(link.href);
}

async function onImport(event) {
  const [file] = event.target.files;
  event.target.value = "";
  if (!file) return;
  const imported = parseMarks(await file.text());
  const count = Object.keys(imported.seen).length + Object.keys(imported.fav).length;
  if (!count) {
    showToast("Fichier non reconnu : aucune marque importée.");
    return;
  }
  const merged = mergeMarks(page.marks, migrateMarks(imported, page.data.aliases));
  applyMarks(merged, `${plural(count, "marque")} importée${count > 1 ? "s" : ""}.`);
}

function selectTab(tab) {
  page.filters = { ...page.filters, tab };
  updateHash();
  render();
}

function onTabKey(event) {
  const tabs = [...document.querySelectorAll(".tab")];
  const index = tabs.indexOf(event.target);
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
  if (index < 0 || !step) return;
  const next = tabs[(index + step + tabs.length) % tabs.length];
  next.focus();
  selectTab(next.dataset.tab);
}

// --- Démarrage -----------------------------------------------------------------------------------

async function main() {
  try {
    const response = await fetch("releases.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    page.data = await response.json();
  } catch (error) {
    const empty = $("#empty");
    empty.hidden = false;
    empty.textContent = `Impossible de charger les données (${error.message}).`;
    return;
  }
  // Deux sorties ont pu être fusionnées depuis la dernière visite : leurs marques suivent.
  page.marks = migrateMarks(loadMarks(), page.data.aliases);
  saveMarks();
  renderHeader();
  renderFilters();
  render();

  let timer;
  $("#filters").addEventListener("input", (event) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      page.filters = readFilters();
      updateHash();
      render();
    }, event.target.id === "q" ? 150 : 0);
  });
  $("#filters").addEventListener("submit", (event) => event.preventDefault());
  $("#reset").addEventListener("click", () => {
    page.filters = { ...parseHash(""), tab: page.filters.tab };
    updateHash();
    renderFilters();
    render();
  });
  for (const button of document.querySelectorAll(".tab")) {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
    button.addEventListener("keydown", onTabKey);
  }
  $("#list").addEventListener("click", onCardClick);
  $("#mark-all").addEventListener("click", onMarkAll);
  $("#export").addEventListener("click", onExport);
  $("#import").addEventListener("change", onImport);
  window.addEventListener("hashchange", () => {
    page.filters = parseHash(location.hash);
    renderFilters();
    render();
  });
  // Les marques changées dans un autre onglet du navigateur s'appliquent ici aussi.
  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    page.marks = loadMarks();
    render();
  });
}

main();
