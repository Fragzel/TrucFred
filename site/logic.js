// Fonctions pures de la page : filtres, styles, recherche, semaines, nouveautés, fraîcheur.
// Aucune dépendance au DOM : testées avec `node --test tests/js/logic.test.js`.

export const TYPE_LABELS = { album: "Album", ep: "EP", single: "Single", track: "Son", video: "Vidéo" };
export const PLATFORM_LABELS = { spotify: "Spotify", soundcloud: "SoundCloud", youtube: "YouTube" };
// Styles calculés par newrel (styles.py), dans l'ordre du menu : l'électro d'abord, en sous-styles.
export const STYLE_LABELS = {
  hardcore: "Hardcore / Gabber",
  techno: "Techno",
  dnb: "Drum & Bass",
  bass: "Dubstep / Bass",
  house: "House / Disco",
  trance: "Trance / Psy",
  hardstyle: "Hardstyle",
  electro: "Électro",
  rap: "Rap",
  rnb: "R&B / Soul",
  pop: "Pop",
  rock: "Rock / Metal",
  reggae: "Reggae / Dub",
  jazz: "Jazz / Blues",
  world: "Latino / Monde",
  folk: "Folk / Country",
  classical: "Classique / BO",
};
export const ELECTRO_STYLES = ["hardcore", "techno", "dnb", "bass", "house", "trance", "hardstyle", "electro"];
/** Valeurs du menu « Style » en plus des styles eux-mêmes. */
export const ALL_ELECTRO = "electro-all";
export const NO_STYLE = "none";

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

/** Décalage d'un fuseau à un instant donné (heure affichée − heure UTC), en millisecondes. */
function zoneOffset(ms, timeZone) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
      .formatToParts(ms)
      .map((part) => [part.type, Number(part.value)]),
  );
  const shown = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
  return shown - Math.floor(ms / 1000) * 1000;
}

/** Instant (ms UTC) d'une heure locale « HH:MM », un jour donné, dans un fuseau (heure d'été comprise). */
export function zonedInstant(day, time, timeZone) {
  const [year, month, date] = day.split("-").map(Number);
  const [hours, minutes] = time.split(":").map(Number);
  const naive = Date.UTC(year, month - 1, date, hours, minutes);
  return naive - zoneOffset(naive - zoneOffset(naive, timeZone), timeZone);
}

/** Sources en retard, pour proposer un lancement manuel.
 * - SoundCloud : aucun run depuis l'heure prévue du jour (marge comprise).
 * - Spotify : le quota de 24 h est revenu (next_check_at passé) sans qu'aucun run ne l'utilise. */
export function lateSources(data, now) {
  if (!data.schedule) return [];
  const planned = zonedInstant(localDay(now, data.timezone), data.schedule.time, data.timezone);
  if (now.getTime() < planned + data.schedule.grace_minutes * 60_000) return [];
  return Object.entries(data.sources ?? {})
    .filter(([, source]) =>
      source.next_check_at
        ? Date.parse(source.next_check_at) <= now.getTime()
        : !source.last_attempt_at || Date.parse(source.last_attempt_at) < planned,
    )
    .map(([platform]) => platform);
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

/** Sortie du style choisi : un style, toute l'électro, ou aucun style connu (null : tout). */
export function hasStyle(release, style) {
  const styles = release.styles ?? []; // favori gardé avant l'arrivée des styles
  if (!style) return true;
  if (style === NO_STYLE) return styles.length === 0;
  if (style === ALL_ELECTRO) return styles.some((value) => ELECTRO_STYLES.includes(value));
  return styles.includes(style);
}

/** Filtres : `platforms` et `types` à null acceptent tout, comme `style`. */
export function matches(release, filters, isNewRelease) {
  if (filters.platforms && !release.links.some((link) => filters.platforms.has(link.platform))) {
    return false;
  }
  if (filters.types && !filters.types.has(release.type)) return false;
  if (!hasStyle(release, filters.style)) return false;
  if (filters.newOnly && !isNewRelease(release)) return false;
  const words = fold(filters.query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  // Les genres (« gabber », « drill ») se cherchent comme un titre ou un artiste.
  const haystack = fold(
    [
      release.title,
      release.edition ?? "",
      ...release.artists.map((artist) => artist.name),
      ...(release.styles ?? []).map((style) => STYLE_LABELS[style] ?? style),
      ...(release.genres ?? []),
    ].join(" "),
  );
  return words.every((word) => haystack.includes(word));
}

/** Nombre de sorties par valeur du menu « Style » ; une sortie à deux styles compte pour les deux. */
export function styleCounts(releases) {
  const counts = { [ALL_ELECTRO]: 0, [NO_STYLE]: 0 };
  for (const release of releases) {
    const styles = release.styles ?? [];
    for (const style of styles) counts[style] = (counts[style] ?? 0) + 1;
    if (styles.some((style) => ELECTRO_STYLES.includes(style))) counts[ALL_ELECTRO] += 1;
    if (styles.length === 0) counts[NO_STYLE] += 1;
  }
  return counts;
}

/** Regroupe par semaine de sortie, la plus récente d'abord. L'identifiant départage les sorties du
 * même jour, comme dans releases.json : une carte ne change pas de place d'un affichage à l'autre. */
export function groupByWeek(releases) {
  const sorted = [...releases].sort(
    (a, b) =>
      b.sort_date.localeCompare(a.sort_date) ||
      b.first_seen.localeCompare(a.first_seen) ||
      b.id.localeCompare(a.id),
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
  const style = params.get("s");
  return {
    tab: TABS.includes(params.get("tab")) ? params.get("tab") : "todo",
    query: params.get("q") ?? "",
    platforms: set("p"),
    types: set("t"),
    style: style in STYLE_LABELS || style === ALL_ELECTRO || style === NO_STYLE ? style : null,
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
  if (filters.style) params.set("s", filters.style);
  if (filters.newOnly) params.set("new", "1");
  const text = params.toString();
  return text ? `#${text}` : "";
}

// --- Marques « déjà vu », favoris et sorties masquées --------------------------------------------
// Gardées dans le navigateur (localStorage) : propres à un navigateur, transférables par
// export/import. Un favori garde une copie de la sortie pour survivre à la fenêtre de 90 jours.
// `hidden` : comptes masqués avant le 26/10, quand « Masquer » cachait tout un artiste ; ils
// restent masqués jusqu'à ce qu'on les réaffiche. Depuis, « Masquer » ne cache que la sortie.

export const TABS = ["todo", "seen", "fav"];

export function emptyMarks() {
  return { version: 1, seen: {}, fav: {}, hidden: {}, hiddenReleases: {} };
}

/** Marques lues depuis le stockage ; un contenu absent ou abîmé donne des marques vides. */
export function parseMarks(text) {
  try {
    const data = JSON.parse(text);
    const isMap = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
    if (data?.version === 1 && isMap(data.seen) && isMap(data.fav)) {
      const hidden = isMap(data.hidden) ? { ...data.hidden } : {}; // absent avant le 22/10
      const hiddenReleases = isMap(data.hiddenReleases) ? { ...data.hiddenReleases } : {}; // avant le 26/10
      return { version: 1, seen: { ...data.seen }, fav: { ...data.fav }, hidden, hiddenReleases };
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
  return {
    ...marks,
    seen: move(marks.seen),
    fav: move(marks.fav),
    hiddenReleases: move(marks.hiddenReleases),
  };
}

/** Fusionne des marques importées avec les marques existantes (rien n'est retiré). */
export function mergeMarks(current, imported) {
  return {
    version: 1,
    seen: { ...imported.seen, ...current.seen },
    fav: { ...imported.fav, ...current.fav },
    hidden: { ...imported.hidden, ...current.hidden },
    hiddenReleases: { ...imported.hiddenReleases, ...current.hiddenReleases },
  };
}

/** Compte masqué avant le 26/10 : on regarde l'artiste principal (l'uploader pour un son SoundCloud). */
export function hiddenAccount(release, marks) {
  const main = release.artists[0];
  return Boolean(main && marks.hidden[main.id]);
}

/** Sortie masquée, elle seule ou avec tout son compte (masquage d'avant le 26/10). */
export function isHidden(release, marks) {
  return Boolean(marks.hiddenReleases[release.id]) || hiddenAccount(release, marks);
}

export function toggleHiddenRelease(marks, release, now) {
  const hiddenReleases = { ...marks.hiddenReleases };
  if (hiddenReleases[release.id]) delete hiddenReleases[release.id];
  else {
    const artist = release.artists?.[0]?.name ?? "";
    hiddenReleases[release.id] = { at: now.toISOString(), title: release.title, artist };
  }
  return { ...marks, hiddenReleases };
}

/** Sorties masquées encore dans la fenêtre, la dernière masquée d'abord. */
export function hiddenReleases(releases, marks) {
  const current = new Set(releases.map((release) => release.id));
  return Object.entries(marks.hiddenReleases)
    .filter(([id]) => current.has(id))
    .map(([id, entry]) => ({ id, ...entry }))
    .sort((a, b) => b.at.localeCompare(a.at));
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
 * Les sorties masquées disparaissent de « À découvrir » et « Déjà vus », pas des favoris. */
export function releasesForTab(releases, marks, tab) {
  if (tab === "fav") {
    const current = new Map(releases.map((release) => [release.id, release]));
    return Object.entries(marks.fav).map(
      ([id, entry]) => current.get(id) ?? { ...entry.release, id, archived: true },
    );
  }
  return releases.filter((release) => tabOf(release.id, marks) === tab && !isHidden(release, marks));
}

/** Sorties affichées dans un onglet : les siennes, plus celles qu'on vient d'en ranger ailleurs ou
 * de masquer (`kept`). Elles restent à leur place jusqu'au prochain changement d'onglet ou de filtre : sinon la
 * carte voisine, souvent du même artiste, glisse sous le pointeur et un second clic la range aussi. */
export function releasesShown(releases, marks, tab, kept) {
  const own = releasesForTab(releases, marks, tab);
  const ids = new Set(own.map((release) => release.id));
  const known = new Map(releasesForTab(releases, marks, "fav").map((release) => [release.id, release]));
  for (const release of releases) known.set(release.id, release);
  const moved = [...kept]
    .filter((id) => !ids.has(id) && known.has(id))
    .map((id) => known.get(id))
    .filter((release) => tab === "fav" || !hiddenAccount(release, marks));
  return [...own, ...moved];
}

export function tabCounts(releases, marks) {
  const counts = { todo: 0, seen: 0, fav: Object.keys(marks.fav).length };
  for (const release of releases) {
    const tab = tabOf(release.id, marks);
    if (tab !== "fav" && !isHidden(release, marks)) counts[tab] += 1;
  }
  return counts;
}

// --- Lecture --------------------------------------------------------------------------------------
// Lecteurs intégrés officiels (iframes Spotify, SoundCloud, YouTube) : aucun script tiers dans la page.

/** Morceaux entiers sans compte d'abord : Spotify ne joue que des extraits hors connexion. */
const PLAY_ORDER = ["soundcloud", "youtube", "spotify"];

/** Adresse du lecteur intégré d'un lien (sortie ou titre) ; null si l'adresse n'est pas reconnue. */
export function embedUrl(platform, url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:") return null;
  if (platform === "spotify" && parsed.hostname === "open.spotify.com") {
    const match = parsed.pathname.match(/^\/(album|track)\/([A-Za-z0-9]+)$/);
    return match ? `https://open.spotify.com/embed/${match[1]}/${match[2]}` : null;
  }
  if (platform === "soundcloud" && parsed.hostname === "soundcloud.com") {
    const params = new URLSearchParams({
      url: parsed.href,
      auto_play: "true",
      visual: "false",
      hide_related: "true",
      show_comments: "false",
      show_reposts: "false",
      show_teaser: "false",
      show_artwork: "false", // la pochette est déjà dans le lecteur : toute la largeur pour l'onde
    });
    return `https://w.soundcloud.com/player/?${params}`;
  }
  if (platform === "youtube" && parsed.hostname === "www.youtube.com" && parsed.pathname === "/watch") {
    const id = parsed.searchParams.get("v") ?? "";
    return /^[\w-]{6,20}$/.test(id) ? `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0&playsinline=1` : null;
  }
  return null;
}

/** Liens jouables d'une sortie, le préféré d'abord : la plateforme de ses titres s'il y en a,
 * puis SoundCloud et YouTube (morceaux entiers sans compte), puis Spotify. */
export function playableLinks(release) {
  const own = release.tracklist?.[0]?.platform;
  const rank = (platform) => (platform === own ? -1 : PLAY_ORDER.indexOf(platform));
  return release.links
    .filter((link) => embedUrl(link.platform, link.url))
    .sort((a, b) => rank(a.platform) - rank(b.platform));
}

/** Ce que joue le lecteur : un titre de la sortie (`track`), ou la sortie entière sur `platform`. */
export function playerSource(release, { platform, track }) {
  const item = track === null ? null : release.tracklist?.[track];
  if (item) return { platform: item.platform, src: embedUrl(item.platform, item.url) };
  const link = release.links.find((candidate) => candidate.platform === platform) ?? playableLinks(release)[0];
  return link ? { platform: link.platform, src: embedUrl(link.platform, link.url) } : null;
}

/** Sortie à plusieurs titres : la carte s'agrandit pour les lister. */
export function hasTracks(release) {
  return (release.tracklist?.length ?? 0) > 1 || (release.tracks ?? 0) > 1;
}

/** Millisecondes → « 3:05 ». */
export function formatDuration(ms) {
  if (!ms) return "";
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
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
