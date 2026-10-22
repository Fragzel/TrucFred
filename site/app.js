// Page des nouvelles sorties : charge releases.json, affiche les filtres et les cartes.
import {
  PLATFORM_LABELS,
  TYPE_LABELS,
  dayToUtc,
  formatHash,
  groupByWeek,
  isNew,
  matches,
  notices,
  parseHash,
} from "./logic.js";

// Logo Spotify (Simple Icons, CC0), affiché avec chaque lien conformément aux règles d'attribution.
const ICONS = {
  spotify:
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>',
};

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

const page = { data: null, filters: parseHash(location.hash), now: new Date() };
const $ = (selector) => document.querySelector(selector);

const safeUrl = (url) => (/^https:\/\//.test(url ?? "") ? url : "#");
const plural = (count, word) => `${count} ${word}${count > 1 ? "s" : ""}`;

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
    query: $("#q").value.trim(),
    platforms: selection("platform"),
    types: selection("type"),
    newOnly: $("#new-only").checked,
  };
}

function card(release, fresh) {
  const node = $("#tpl-card").content.firstElementChild.cloneNode(true);
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
  node.querySelector(".title").textContent = release.title;
  node.querySelector(".artists").textContent = release.artists.map((artist) => artist.name).join(", ");
  const date = node.querySelector(".date");
  date.textContent = releaseDate(release);
  date.dateTime = release.date;
  if (release.tracks > 1) node.querySelector(".tracks").textContent = ` · ${plural(release.tracks, "titre")}`;
  const links = node.querySelector(".links");
  for (const link of release.links) {
    const anchor = document.createElement("a");
    Object.assign(anchor, { className: `platform platform-${link.platform}`, href: safeUrl(link.url), target: "_blank", rel: "noopener" });
    anchor.innerHTML = ICONS[link.platform] ?? "";
    anchor.append(document.createTextNode(`Écouter sur ${PLATFORM_LABELS[link.platform] ?? link.platform}`));
    links.append(anchor);
  }
  return node;
}

function render() {
  const { releases, rules, timezone } = page.data;
  const fresh = (release) => isNew(release, page.now, rules, timezone);
  const visible = releases.filter((release) => matches(release, page.filters, fresh));
  const fragment = document.createDocumentFragment();
  for (const { week, releases: items } of groupByWeek(visible)) {
    const section = $("#tpl-week").content.firstElementChild.cloneNode(true);
    section.querySelector("h2").textContent = `Semaine du vendredi ${weekFormat.format(dayToUtc(week))}`;
    section.querySelector(".count").textContent = plural(items.length, "sortie");
    section.querySelector(".grid").append(...items.map((release) => card(release, fresh(release))));
    fragment.append(section);
  }
  $("#list").replaceChildren(fragment);
  const empty = $("#empty");
  empty.hidden = visible.length > 0;
  empty.textContent = releases.length
    ? "Aucune sortie ne correspond à ces filtres."
    : "Pas encore de sorties : la première collecte n'a pas eu lieu.";
}

function onFiltersChanged() {
  page.filters = readFilters();
  history.replaceState(null, "", formatHash(page.filters) || `${location.pathname}${location.search}`);
  render();
}

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
  renderHeader();
  renderFilters();
  render();

  let timer;
  $("#filters").addEventListener("input", (event) => {
    clearTimeout(timer);
    timer = setTimeout(onFiltersChanged, event.target.id === "q" ? 150 : 0);
  });
  $("#filters").addEventListener("submit", (event) => event.preventDefault());
  $("#reset").addEventListener("click", () => {
    page.filters = parseHash("");
    history.replaceState(null, "", `${location.pathname}${location.search}`);
    renderFilters();
    render();
  });
  window.addEventListener("hashchange", () => {
    page.filters = parseHash(location.hash);
    renderFilters();
    render();
  });
}

main();
