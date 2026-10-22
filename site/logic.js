// Fonctions pures de la page : filtres, recherche, semaines, nouveautés, fraîcheur.
// Aucune dépendance au DOM : testées avec `node --test tests/js/logic.test.js`.

export const TYPE_LABELS = { album: "Album", ep: "EP", single: "Single", track: "Son" };
export const PLATFORM_LABELS = { spotify: "Spotify", soundcloud: "SoundCloud" };

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/** Minuscules sans accents, pour la recherche. */
export function fold(text) {
  return String(text ?? "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

/** "AAAA-MM-JJ" → millisecondes UTC à minuit. */
export function dayToUtc(day) {
  const [year, month, date] = day.split("-").map(Number);
  return Date.UTC(year, month - 1, date);
}

/** Millisecondes UTC → "AAAA-MM-JJ". */
export function utcToDay(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Jour "AAAA-MM-JJ" d'un instant dans un fuseau donné. */
export function localDay(instant, timeZone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(instant);
  const part = (type) => parts.find((p) => p.type === type).value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/** Vendredi qui ouvre la semaine de sortie contenant ce jour : les sorties tombent le vendredi. */
export function releaseWeek(day) {
  const ms = dayToUtc(day);
  const sinceFriday = (new Date(ms).getUTCDay() + 2) % 7;
  return utcToDay(ms - sinceFriday * DAY_MS);
}

/** Sortie récente, vue pour la première fois il y a peu, et pas issue du catalogue historique. */
export function isNew(release, now, rules, timeZone) {
  if (release.backfill) return false;
  if (now.getTime() - Date.parse(release.first_seen) > rules.new_days * DAY_MS) return false;
  const age = (dayToUtc(localDay(now, timeZone)) - dayToUtc(release.sort_date)) / DAY_MS;
  return age <= rules.new_max_age_days;
}

/** Filtres : `platforms` et `types` à null acceptent tout. */
export function matches(release, filters, isNewRelease) {
  if (filters.platforms && !release.links.some((link) => filters.platforms.has(link.platform))) {
    return false;
  }
  if (filters.types && !filters.types.has(release.type)) return false;
  if (filters.newOnly && !isNewRelease(release)) return false;
  const words = fold(filters.query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = fold(
    [release.title, release.edition ?? "", ...release.artists.map((artist) => artist.name)].join(" "),
  );
  return words.every((word) => haystack.includes(word));
}

/** Regroupe par semaine de sortie, la plus récente d'abord. */
export function groupByWeek(releases) {
  const sorted = [...releases].sort(
    (a, b) => b.sort_date.localeCompare(a.sort_date) || b.first_seen.localeCompare(a.first_seen),
  );
  const weeks = [];
  for (const release of sorted) {
    const week = releaseWeek(release.sort_date);
    if (weeks.at(-1)?.week !== week) weeks.push({ week, releases: [] });
    weeks.at(-1).releases.push(release);
  }
  return weeks;
}

/** Hash d'URL → onglet et filtres. */
export function parseHash(hash) {
  const params = new URLSearchParams(String(hash ?? "").replace(/^#/, ""));
  const set = (key) => (params.has(key) ? new Set(params.get(key).split(",").filter(Boolean)) : null);
  return {
    tab: TABS.includes(params.get("tab")) ? params.get("tab") : "todo",
    query: params.get("q") ?? "",
    platforms: set("p"),
    types: set("t"),
    newOnly: params.get("new") === "1",
  };
}

/** Onglet et filtres → hash d'URL ("" pour l'onglet par défaut sans filtre). */
export function formatHash(filters) {
  const params = new URLSearchParams();
  if (filters.tab && filters.tab !== "todo") params.set("tab", filters.tab);
  if (filters.query) params.set("q", filters.query);
  if (filters.platforms) params.set("p", [...filters.platforms].sort().join(","));
  if (filters.types) params.set("t", [...filters.types].sort().join(","));
  if (filters.newOnly) params.set("new", "1");
  const text = params.toString();
  return text ? `#${text}` : "";
}

// --- Marques « déjà vu » et favoris -------------------------------------------------------------
// Gardées dans le navigateur (localStorage) : propres à un navigateur, transférables par
// export/import. Un favori garde une copie de la sortie pour survivre à la fenêtre de 90 jours.

export const TABS = ["todo", "seen", "fav"];

export function emptyMarks() {
  return { version: 1, seen: {}, fav: {}, hidden: {} };
}

/** Marques lues depuis le stockage ; un contenu absent ou abîmé donne des marques vides. */
export function parseMarks(text) {
  try {
    const data = JSON.parse(text);
    const isMap = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
    if (data?.version === 1 && isMap(data.seen) && isMap(data.fav)) {
      const hidden = isMap(data.hidden) ? { ...data.hidden } : {}; // absent avant le 22/10
      return { version: 1, seen: { ...data.seen }, fav: { ...data.fav }, hidden };
    }
  } catch {
    // contenu illisible : on repart de zéro plutôt que de bloquer la page
  }
  return emptyMarks();
}

/** Reporte les marques d'une sortie fusionnée (ancien identifiant) sur son identifiant actuel. */
export function migrateMarks(marks, aliases) {
  const move = (bucket) =>
    Object.fromEntries(Object.entries(bucket).map(([id, value]) => [aliases?.[id] ?? id, value]));
  return { ...marks, seen: move(marks.seen), fav: move(marks.fav) };
}

/** Fusionne des marques importées avec les marques existantes (rien n'est retiré). */
export function mergeMarks(current, imported) {
  return {
    version: 1,
    seen: { ...imported.seen, ...current.seen },
    fav: { ...imported.fav, ...current.fav },
    hidden: { ...imported.hidden, ...current.hidden },
  };
}

/** Compte masqué : on regarde l'artiste principal (l'uploader pour un son SoundCloud). */
export function hiddenAccount(release, marks) {
  const main = release.artists[0];
  return Boolean(main && marks.hidden[main.id]);
}

export function toggleHidden(marks, artist, now) {
  const hidden = { ...marks.hidden };
  if (hidden[artist.id]) delete hidden[artist.id];
  else hidden[artist.id] = { at: now.toISOString(), name: artist.name };
  return { ...marks, hidden };
}

/** Comptes masqués, avec le nombre de sorties qu'ils cachent en ce moment. */
export function hiddenAccounts(releases, marks) {
  const counts = new Map();
  for (const release of releases) {
    const main = release.artists[0];
    if (main && marks.hidden[main.id]) counts.set(main.id, (counts.get(main.id) ?? 0) + 1);
  }
  return Object.entries(marks.hidden)
    .map(([id, entry]) => ({ id, name: entry.name, releases: counts.get(id) ?? 0 }))
    .sort((a, b) => a.name.localeCompare(b.name, "fr"));
}

export function toggleSeen(marks, ids, now) {
  const seen = { ...marks.seen };
  const list = [ids].flat();
  const allSeen = list.every((id) => seen[id]);
  for (const id of list) {
    if (allSeen) delete seen[id];
    else seen[id] ??= now.toISOString();
  }
  return { ...marks, seen };
}

export function toggleFavorite(marks, release, now) {
  const fav = { ...marks.fav };
  if (fav[release.id]) delete fav[release.id];
  else fav[release.id] = { at: now.toISOString(), release };
  return { ...marks, fav };
}

/** Onglet d'une sortie : chacune n'apparaît que dans un seul. Un favori prime sur « déjà vu ». */
export function tabOf(id, marks) {
  if (marks.fav[id]) return "fav";
  return marks.seen[id] ? "seen" : "todo";
}

/** Sorties d'un onglet. Les favoris sortis de la fenêtre reviennent depuis leur copie.
 * Les comptes masqués disparaissent de « À découvrir » et « Déjà vus », pas des favoris. */
export function releasesForTab(releases, marks, tab) {
  if (tab === "fav") {
    const current = new Map(releases.map((release) => [release.id, release]));
    return Object.entries(marks.fav).map(
      ([id, entry]) => current.get(id) ?? { ...entry.release, id, archived: true },
    );
  }
  return releases.filter((release) => tabOf(release.id, marks) === tab && !hiddenAccount(release, marks));
}

export function tabCounts(releases, marks) {
  const counts = { todo: 0, seen: 0, fav: Object.keys(marks.fav).length };
  for (const release of releases) {
    const tab = tabOf(release.id, marks);
    if (tab !== "fav" && !hiddenAccount(release, marks)) counts[tab] += 1;
  }
  return counts;
}

/** Problèmes à signaler en haut de page : données périmées, source en panne ou partielle. */
export function notices(data, now) {
  const limit = data.rules.stale_hours * HOUR_MS;
  const result = [];
  const age = now.getTime() - Date.parse(data.generated_at);
  if (age > limit) result.push({ kind: "stale", level: "warning", hours: Math.floor(age / HOUR_MS) });
  for (const [platform, source] of Object.entries(data.sources ?? {})) {
    const sinceSuccess = source.last_success_at ? now.getTime() - Date.parse(source.last_success_at) : 0;
    if (source.status && source.status !== "ok") {
      result.push({
        kind: "source",
        level: source.status === "partial" ? "info" : "error",
        platform,
        status: source.status,
        message: source.message ?? "",
        quotaResetAt: source.quota_reset_at ?? null,
      });
    } else if (sinceSuccess > limit) {
      result.push({ kind: "source-stale", level: "warning", platform, hours: Math.floor(sinceSuccess / HOUR_MS) });
    }
  }
  return result;
}
