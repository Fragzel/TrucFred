// Page des nouvelles sorties : charge releases.json, affiche onglets, filtres et cartes.
import {
  ALL_ELECTRO,
  ELECTRO_STYLES,
  NO_STYLE,
  PLATFORM_LABELS,
  STYLE_LABELS,
  TYPE_LABELS,
  dayToUtc,
  embedUrl,
  emptyMarks,
  entryRelease,
  formatDuration,
  formatHash,
  groupByWeek,
  hasTracks,
  hiddenAccounts,
  hiddenReleases,
  inPlaylist,
  isNew,
  isSpotifyPreview,
  lateSources,
  matches,
  mergeMarks,
  migrateMarks,
  movePlaylistEntry,
  notices,
  parseHash,
  parseMarks,
  playableLinks,
  playerSource,
  playlistEntries,
  releasesForTab,
  releasesShown,
  removePlaylistEntry,
  spotifyPreviewCause,
  styleCounts,
  tabCounts,
  tabOf,
  toggleFavorite,
  toggleFavoriteTrack,
  toggleHidden,
  toggleHiddenRelease,
  togglePlaylist,
  toggleSeen,
} from "./logic.js";
import { createPlayer } from "./player.js";
import { deriveKey, isSealed, unseal } from "./vault.js";

// Logos (Simple Icons, CC0) affichés avec chaque lien, conformément aux règles d'attribution.
const ICONS = {
  youtube:
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>',
  soundcloud:
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M23.999 14.165c-.052 1.796-1.612 3.169-3.4 3.169h-8.18a.68.68 0 0 1-.675-.683V7.862a.747.747 0 0 1 .452-.724s.75-.513 2.333-.513a5.364 5.364 0 0 1 2.763.755 5.433 5.433 0 0 1 2.57 3.54c.282-.08.574-.121.868-.12.884 0 1.73.358 2.347.992s.948 1.49.922 2.373ZM10.721 8.421c.247 2.98.427 5.697 0 8.672a.264.264 0 0 1-.53 0c-.395-2.946-.22-5.718 0-8.672a.264.264 0 0 1 .53 0ZM9.072 9.448c.285 2.659.37 4.986-.006 7.655a.277.277 0 0 1-.55 0c-.331-2.63-.256-5.02 0-7.655a.277.277 0 0 1 .556 0Zm-1.663-.257c.27 2.726.39 5.171 0 7.904a.266.266 0 0 1-.532 0c-.38-2.69-.257-5.21 0-7.904a.266.266 0 0 1 .532 0Zm-1.647.77a26.108 26.108 0 0 1-.008 7.147.272.272 0 0 1-.542 0 27.955 27.955 0 0 1 0-7.147.275.275 0 0 1 .55 0Zm-1.67 1.769c.421 1.865.228 3.5-.029 5.388a.257.257 0 0 1-.514 0c-.21-1.858-.398-3.549 0-5.389a.272.272 0 0 1 .543 0Zm-1.655-.273c.388 1.897.26 3.508-.01 5.412-.026.28-.514.283-.54 0-.244-1.878-.347-3.54-.01-5.412a.283.283 0 0 1 .56 0Zm-1.668.911c.4 1.268.257 2.292-.026 3.572a.257.257 0 0 1-.514 0c-.241-1.262-.354-2.312-.023-3.572a.283.283 0 0 1 .563 0Z"/></svg>',
  spotify:
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>',
};

const EMPTY_TAB = {
  todo: "Tout est vu : les prochaines sorties arriveront ici.",
  seen: "Rien ici pour l'instant : marque une sortie avec « Déjà vu » pour la ranger ici.",
  fav: "Aucun favori : clique sur l'étoile d'une sortie pour l'ajouter ici.",
};
const STORAGE_KEY = "newrel.marks";
const TOKEN_KEY = "newrel.githubToken";
const DISPATCHED_KEY = "newrel.dispatchedAt";
const VOLUME_KEY = "newrel.volume";
const DISPATCH_PAUSE_MS = 30 * 60_000; // le temps que le run se lance, tourne et redéploie la page
// Création d'un token « fine-grained » pré-remplie : seule la permission Actions (écriture).
const TOKEN_URL = `https://github.com/settings/personal-access-tokens/new?${new URLSearchParams({
  name: "Nouvelles sorties : lancement manuel",
  description: "Lance la mise à jour (workflow update.yml) depuis la page.",
  expires_in: "366",
  actions: "write",
})}`;

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

// Sortie dont vient la carte d'un titre favori : « Sur l'EP « Basse saison » ».
const ALBUM_OF = { album: "l'album", ep: "l'EP", single: "le single" };

const page = {
  data: null,
  byId: new Map(), // sorties des données, par identifiant
  filters: parseHash(location.hash),
  now: new Date(),
  marks: emptyMarks(),
  visible: [],
  kept: new Map(), // cartes rangées ailleurs, gardées à leur place jusqu'au prochain onglet ou filtre
  // { id, platform, track, list, release } : sortie jouée, plateforme, index du titre (null : tout),
  // entrée de la liste de lecture ({ key, index }, null hors de la liste) et la sortie elle-même.
  player: null,
  queue: null, // bouton qui a ouvert la liste de lecture, tant qu'elle est ouverte
  open: null, // carte agrandie sur la liste de ses titres
  order: [], // identifiants des cartes affichées, dans l'ordre : ⏮ et ⏭ du lecteur
  seeking: false, // la barre de progression est en train d'être glissée
  focus: false, // lecteur agrandi, sur la moitié basse de l'écran
  volume: { level: 100, muted: false }, // gardé dans ce navigateur
  spotifyLogin: null, // « reconnecting » : connexion ouverte dans un onglet ; « retried » : déjà rechargé
};
const $ = (selector) => document.querySelector(selector);

const safeUrl = (url) => (/^https:\/\//.test(url ?? "") ? url : "#");
const plural = (count, word) => `${count} ${word}${count > 1 ? "s" : ""}`;
/** Lettre affichée à la place d'une pochette absente. */
const initial = (release) => (release.artists[0]?.name || release.title || "?").slice(0, 1).toUpperCase();
const albumLine = (album) => ["Sur", ALBUM_OF[album.type], `« ${album.title} »`].filter(Boolean).join(" ");

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

function readSetting(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** Enregistre (ou efface avec null) un réglage ; false si le navigateur refuse. */
function writeSetting(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

// --- Page protégée par mot de passe --------------------------------------------------------------
// releases.json arrive chiffré (voir vault.js). « Se souvenir de cet appareil » garde la clé dérivée
// dans IndexedDB, et non le mot de passe : une clé non exportable ne peut pas être relue, seulement
// utilisée par les pages de fragzel.github.io (qui partagent ce stockage).

const KEY_DB = "newrel";
const KEY_STORE = "keys";

/** Opération sur la clé mémorisée ; null si le navigateur refuse IndexedDB (navigation privée…). */
function keyStore(mode, operation) {
  return new Promise((resolve) => {
    try {
      const opening = indexedDB.open(KEY_DB, 1);
      opening.onupgradeneeded = () => opening.result.createObjectStore(KEY_STORE);
      opening.onerror = () => resolve(null);
      opening.onsuccess = () => {
        const db = opening.result;
        const transaction = db.transaction(KEY_STORE, mode);
        const request = operation(transaction.objectStore(KEY_STORE));
        const done = (value) => {
          db.close();
          resolve(value);
        };
        transaction.oncomplete = () => done(request.result ?? null);
        transaction.onerror = () => done(null);
        transaction.onabort = () => done(null);
      };
    } catch {
      resolve(null);
    }
  });
}

const rememberKey = (kdf, key) =>
  keyStore("readwrite", (store) => store.put({ salt: kdf.salt, iterations: kdf.iterations, key }, "site"));
const forgetKey = () => keyStore("readwrite", (store) => store.delete("site"));

async function rememberedKey(kdf) {
  const entry = await keyStore("readonly", (store) => store.get("site"));
  return entry?.salt === kdf.salt && entry.iterations === kdf.iterations ? entry.key : null;
}

/** Données en clair : avec la clé mémorisée, sinon une fois le bon mot de passe saisi. */
async function unlock(envelope) {
  const remembered = await rememberedKey(envelope.kdf);
  if (remembered) {
    try {
      return await unseal(envelope, remembered);
    } catch {
      await forgetKey(); // mot de passe changé depuis : on le redemande
    }
  }
  document.body.classList.add("locked");
  const form = $("#unlock");
  form.hidden = false;
  $("#password").focus();
  return new Promise((resolve) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      $("#unlock-error").hidden = true;
      try {
        const key = await deriveKey($("#password").value, envelope.kdf);
        const data = await unseal(envelope, key);
        if ($("#remember").checked) await rememberKey(envelope.kdf, key);
        form.hidden = true;
        document.body.classList.remove("locked");
        resolve(data);
      } catch {
        $("#unlock-error").hidden = false;
        $("#password").select();
      } finally {
        button.disabled = false;
      }
    });
  });
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
  if (source.next_check_at && Date.parse(source.next_check_at) > page.now.getTime()) {
    parts.push(`Prochaine vérification possible le ${stampFormat.format(new Date(source.next_check_at))}.`);
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
  renderLate();
}

// --- Lancement manuel ----------------------------------------------------------------------------
// GitHub retarde souvent le cron de plusieurs heures. Quand un passage est en retard, la page
// propose de lancer le workflow : via un token « Actions » gardé dans ce navigateur, ou sur GitHub.

const repository = () => (/^[\w.-]+\/[\w.-]+$/.test(page.data.repository ?? "") ? page.data.repository : null);

function renderLate() {
  const { data } = page;
  const late = repository() ? lateSources(data, page.now) : [];
  const dispatched = Number(readSetting(DISPATCHED_KEY)) || 0;
  const box = $("#late");
  box.hidden = !late.length || page.now.getTime() - dispatched < DISPATCH_PAUSE_MS;
  $("#token-tools").hidden = !readSetting(TOKEN_KEY);
  if (box.hidden) return;
  const planned = data.schedule.time.replace(/^0?(\d+):(\d+)$/, "$1 h $2");
  const quotaBack = late.join() === "spotify" && data.sources.spotify.next_check_at;
  const hour = new Intl.DateTimeFormat("fr-FR", { timeStyle: "short", timeZone: data.timezone });
  $("#late-text").textContent = quotaBack
    ? `Le quota Spotify est de nouveau disponible depuis ${hour.format(new Date(quotaBack))}, mais aucune mise à jour ne l'a utilisé.`
    : `La mise à jour prévue à ${planned} n'a pas encore tourné : GitHub retarde parfois les tâches planifiées.`;
}

function openRunDialog(error = "") {
  $("#run-github").href = `https://github.com/${repository()}/actions/workflows/update.yml`;
  $("#run-token-link").href = TOKEN_URL;
  $("#run-token").value = "";
  const message = $("#run-error");
  message.textContent = error;
  message.hidden = !error;
  $("#run-dialog").showModal();
}

async function dispatch(token) {
  const button = $("#run-now");
  button.disabled = true;
  try {
    const response = await fetch(`https://api.github.com/repos/${repository()}/actions/workflows/update.yml/dispatches`, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main" }),
    });
    if (response.status === 204) {
      writeSetting(DISPATCHED_KEY, String(Date.now()));
      $("#late").hidden = true;
      showToast("Mise à jour lancée : recharge la page dans une dizaine de minutes.");
    } else if ([401, 403, 404].includes(response.status)) {
      // Token expiré, révoqué ou sans la permission « Actions » sur ce dépôt : on l'oublie.
      writeSetting(TOKEN_KEY, null);
      renderLate();
      const reason = response.status === 401 ? "expiré ou révoqué" : "sans la permission « Actions : Read and write » sur ce dépôt";
      openRunDialog(`GitHub a refusé le token (${reason}) : il a été oublié.`);
    } else {
      showToast(`GitHub n'a pas lancé la mise à jour (HTTP ${response.status}) : réessaie plus tard.`);
    }
  } catch {
    showToast("GitHub est injoignable : réessaie dans un instant.");
  } finally {
    button.disabled = false;
  }
}

function onRunNow() {
  const token = readSetting(TOKEN_KEY);
  if (token) dispatch(token);
  else openRunDialog();
}

function onRunDialogSubmit(event) {
  if (event.submitter?.value !== "save") return; // « Fermer »
  const token = $("#run-token").value.trim();
  if (!token) {
    event.preventDefault();
    $("#run-token").focus();
    return;
  }
  if (!writeSetting(TOKEN_KEY, token)) showToast("Stockage du navigateur indisponible : le token ne sera pas gardé.");
  renderLate();
  dispatch(token);
}

// --- Filtres -------------------------------------------------------------------------------------

function renderChips(fieldset, name, entries, selected) {
  fieldset.querySelectorAll("label").forEach((label) => label.remove());
  for (const [value, text] of entries) {
    const label = document.createElement("label");
    label.className = `chip chip-${value}`;
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
  // Les favoris comptent aussi : un titre d'EP en favori est un « Son ».
  const all = [...releases, ...releasesForTab(releases, page.marks, "fav")];
  const types = Object.keys(TYPE_LABELS).filter((type) => all.some((release) => release.type === type));
  renderChips($("#platforms"), "platform", platforms.map((p) => [p, PLATFORM_LABELS[p]]), page.filters.platforms);
  renderChips($("#types"), "type", types.map((t) => [t, TYPE_LABELS[t]]), page.filters.types);
  $("#q").value = page.filters.query;
  $("#new-only").checked = page.filters.newOnly;
}

/** Menu « Style » : seulement les styles présents, avec leur nombre de sorties (autres filtres
 * appliqués), l'électro groupée en sous-styles. */
function renderStyleMenu(pool) {
  const menu = $("#style");
  const counts = styleCounts(pool);
  const selected = page.filters.style;
  const option = (value, text) =>
    Object.assign(document.createElement("option"), { value, textContent: `${text} (${counts[value] ?? 0})` });
  const shown = (value) => counts[value] || value === selected;
  const group = (label, options) => {
    const node = Object.assign(document.createElement("optgroup"), { label });
    node.append(...options);
    return options.length ? [node] : [];
  };
  const electro = ELECTRO_STYLES.filter(shown).map((style) =>
    option(style, style === "electro" ? "Autre électro" : STYLE_LABELS[style]),
  );
  const others = Object.keys(STYLE_LABELS)
    .filter((style) => !ELECTRO_STYLES.includes(style) && shown(style))
    .map((style) => option(style, STYLE_LABELS[style]));
  menu.replaceChildren(
    Object.assign(document.createElement("option"), { value: "", textContent: "Tous les styles" }),
    ...group("Électro", electro.length ? [option(ALL_ELECTRO, "Toute l'électro"), ...electro] : []),
    ...group("Autres styles", others),
    ...(shown(NO_STYLE) ? [option(NO_STYLE, "Sans style connu")] : []),
  );
  menu.value = selected ?? "";
  // Données d'avant les styles : pas de menu, plutôt qu'un menu réduit à « Sans style connu ».
  menu.hidden = !selected && counts[NO_STYLE] === pool.length;
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
    style: $("#style").value || null,
    newOnly: $("#new-only").checked,
  };
}

function updateHash() {
  history.replaceState(null, "", formatHash(page.filters) || `${location.pathname}${location.search}`);
}

// --- Cartes et liste -----------------------------------------------------------------------------

function card(release, fresh, moved) {
  const node = $("#tpl-card").content.firstElementChild.cloneNode(true);
  node.dataset.id = release.id;
  node.classList.toggle("is-moved", moved);
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
    cover.textContent = initial(release);
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
  const album = node.querySelector(".album");
  album.hidden = !release.album;
  if (release.album) album.textContent = albumLine(release.album);
  album.title = album.textContent;
  const styles = node.querySelector(".styles");
  styles.textContent = (release.styles ?? []).map((style) => STYLE_LABELS[style] ?? style).join(" · ");
  styles.hidden = !styles.textContent;
  if (release.genres?.length) styles.title = `Genres : ${release.genres.join(", ")}`;
  const date = node.querySelector(".date");
  date.textContent = releaseDate(release);
  date.dateTime = release.date;
  const open = page.open === release.id;
  if (hasTracks(release)) {
    const starred = (release.tracklist ?? []).filter((track) => page.marks.favTracks[track.url]).length;
    const toggle = Object.assign(document.createElement("button"), {
      type: "button",
      className: "show-tracks",
      textContent: `${plural(release.tracklist?.length || release.tracks, "titre")}${starred ? ` · ★ ${starred}` : ""}`,
      title: starred ? `${plural(starred, "titre")} en favori` : "",
    });
    toggle.setAttribute("aria-expanded", String(open));
    node.querySelector(".tracks").replaceChildren(document.createTextNode(" · "), toggle);
  }
  renderTracklist(node, release, open);
  node.classList.toggle("is-playing", page.player?.id === release.id);
  const play = node.querySelector(".play");
  play.hidden = playableLinks(release).length === 0;
  renderPlayButton(play, release);
  node.querySelector(".links").append(...platformLinks(release));

  const listButton = node.querySelector(".mark-list");
  listButton.hidden = play.hidden;
  renderListButton(listButton, playlistEntries(release), release.title);
  const seen = Boolean(page.marks.seen[release.id]);
  const favorite = isFavorite(release);
  const seenButton = node.querySelector(".mark-seen");
  seenButton.setAttribute("aria-pressed", String(seen));
  seenButton.textContent = seen ? "✓ Vu" : "✓ Déjà vu";
  seenButton.title = seen ? "Remettre dans « À découvrir »" : "Ranger dans « Déjà vus »";
  seenButton.hidden = favorite; // un favori ne vit que dans l'onglet « Favoris »
  const hidden = Boolean(page.marks.hiddenReleases[release.id]);
  const hideButton = node.querySelector(".mark-hide");
  hideButton.hidden = favorite;
  hideButton.textContent = hidden ? "Réafficher" : "Masquer";
  hideButton.title = hidden ? "Réafficher cette sortie" : "Masquer cette sortie";
  const star = node.querySelector(".mark-fav");
  star.setAttribute("aria-pressed", String(favorite));
  star.textContent = favorite ? "★" : "☆";
  const starLabel = favorite ? "Retirer des favoris" : "Ajouter aux favoris";
  star.setAttribute("aria-label", `${starLabel} : ${release.title}`);
  star.title = starLabel;
  return node;
}

/** Sortie en favori ; pour la carte d'un titre d'EP, ce titre. */
const isFavorite = (release) =>
  Boolean(release.track ? page.marks.favTracks[release.track.url] : page.marks.fav[release.id]);

/** « ＋ Liste » (carte, titre ou lecteur) : enfoncé quand tout est déjà dans la liste de lecture. */
function renderListButton(button, entries, title, text = ["＋ Liste", "✓ Dans la liste"]) {
  const listed = inPlaylist(page.marks, entries);
  button.setAttribute("aria-pressed", String(listed));
  button.textContent = text[Number(listed)];
  const label = listed ? "Retirer de la liste de lecture" : "Ajouter à la liste de lecture";
  button.setAttribute("aria-label", `${label} : ${title}`);
  if (!button.matches(".player-mark")) button.title = label; // ceux du lecteur gardent leur raccourci
}

/** Liens vers chaque plateforme, avec son logo (cartes et lecteur agrandi). */
function platformLinks(release) {
  return release.links.map((link) => {
    const anchor = document.createElement("a");
    Object.assign(anchor, { className: `platform platform-${link.platform}`, href: safeUrl(link.url), target: "_blank", rel: "noopener" });
    anchor.innerHTML = ICONS[link.platform] ?? "";
    const platform = PLATFORM_LABELS[link.platform] ?? link.platform;
    anchor.setAttribute("aria-label", `Écouter « ${release.title} » sur ${platform}`);
    anchor.append(document.createTextNode(platform));
    return anchor;
  });
}

/** Carte agrandie : la liste de ses titres, chacun jouable. */
function renderTracklist(node, release, open) {
  node.classList.toggle("is-open", open);
  const box = node.querySelector(".tracklist-box");
  box.hidden = !open;
  if (!open) return;
  box.querySelector(".tracklist").replaceChildren(...trackItems(release));
  box.querySelector(".tracklist-empty").hidden = (release.tracklist ?? []).length > 0;
}

/** Titres d'une sortie, chacun jouable, avec son étoile et son « ＋ » pour la liste de lecture ;
 * celui en cours est marqué. */
function trackItems(release) {
  const current = page.player?.id === release.id ? page.player.track : null;
  return (release.tracklist ?? []).map((track, index) => {
    const item = document.createElement("li");
    const button = Object.assign(document.createElement("button"), { type: "button", className: "track" });
    if (index === current) button.setAttribute("aria-current", "true");
    button.disabled = !embedUrl(track.platform, track.url);
    const name = Object.assign(document.createElement("span"), { className: "track-title", textContent: track.title });
    const length = Object.assign(document.createElement("span"), {
      className: "track-duration",
      textContent: formatDuration(track.duration_ms),
    });
    button.append(name, length);
    button.setAttribute("aria-label", `Écouter « ${track.title} »`);
    const favorite = Boolean(page.marks.favTracks[track.url]);
    const star = Object.assign(document.createElement("button"), {
      type: "button",
      className: "track-mark track-fav",
      textContent: favorite ? "★" : "☆",
      title: favorite ? "Retirer des favoris" : "Ajouter aux favoris",
    });
    star.setAttribute("aria-pressed", String(favorite));
    star.setAttribute("aria-label", `${star.title} : ${track.title}`);
    const add = Object.assign(document.createElement("button"), {
      type: "button",
      className: "track-mark track-add",
      disabled: button.disabled,
    });
    renderListButton(add, playlistEntries(release, track), track.title, ["＋", "✓"]);
    for (const control of [button, star, add]) control.dataset.index = String(index);
    item.append(button, star, add);
    return item;
  });
}

function renderTabs() {
  const counts = tabCounts(page.data.releases, page.marks);
  for (const button of document.querySelectorAll(".tab")) {
    const tab = button.dataset.tab;
    const selected = tab === page.filters.tab;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    button.querySelector(".tab-count").textContent = counts[tab];
  }
}

function render() {
  const { releases, rules, timezone } = page.data;
  const fresh = (release) => isNew(release, page.now, rules, timezone);
  const { tab } = page.filters;
  const pool = releasesForTab(releases, page.marks, tab);
  page.visible = pool.filter((release) => matches(release, page.filters, fresh));
  const own = new Set(page.visible.map((release) => release.id));
  const shown = releasesShown(releases, page.marks, tab, page.kept).filter((release) =>
    matches(release, page.filters, fresh),
  );
  renderStyleMenu(pool.filter((release) => matches(release, { ...page.filters, style: null }, fresh)));
  renderTabs();
  const fragment = document.createDocumentFragment();
  const weeks = groupByWeek(shown);
  page.order = weeks.flatMap((week) => week.releases.map((release) => release.id));
  for (const { week, releases: items } of weeks) {
    const section = $("#tpl-week").content.firstElementChild.cloneNode(true);
    section.querySelector("h2").textContent = `Semaine du vendredi ${weekFormat.format(dayToUtc(week))}`;
    section.querySelector(".count").textContent = plural(items.length, "sortie");
    const cards = items.map((release) => card(release, fresh(release), !own.has(release.id)));
    section.querySelector(".grid").append(...cards);
    fragment.append(section);
  }
  $("#list").replaceChildren(fragment);
  const empty = $("#empty");
  empty.hidden = shown.length > 0;
  if (!releases.length && page.filters.tab !== "fav") {
    empty.textContent = "Pas encore de sorties : la première collecte n'a pas eu lieu.";
  } else {
    empty.textContent = pool.length ? "Aucune sortie ne correspond à ces filtres." : EMPTY_TAB[page.filters.tab];
  }
  // Au-dessus de la liste : combien de sorties sont affichées, et l'action sur toutes à la fois.
  const filtered = Boolean(formatHash({ ...page.filters, tab: "todo" }));
  $("#reset").hidden = !filtered;
  $("#shown").textContent = pool.length
    ? `${plural(page.visible.length, "sortie")}${page.visible.length < pool.length ? ` sur ${pool.length}` : ""}`
    : "";
  const markAll = $("#mark-all");
  markAll.hidden = tab === "fav" || page.visible.length < 2;
  markAll.className = `btn btn-tone ${tab === "seen" ? "tone-todo" : "tone-seen"}`;
  markAll.textContent = tab === "seen" ? "↺ Tout remettre dans « À découvrir »" : "✓ Tout marquer comme vu";
  renderHidden();
  renderMarkButtons();
  renderFocus();
  renderQueue();
}

/** Sorties masquées, et comptes masqués avant le 26/10, avec un bouton pour les réafficher. */
// --- Lecture -------------------------------------------------------------------------------------
// Un seul lecteur pour les trois plateformes, en bas de l'écran et hors de la liste : changer
// d'onglet, filtrer ou ranger une carte n'interrompt pas la musique. Le lecteur de la plateforme est
// piloté par messages (player.js) et caché sous la pochette, vidéo YouTube comprise.

const player = createPlayer($("#player-frame"), onPlayerChange);
page.volume = readVolume();
player.setVolume(page.volume.muted ? 0 : page.volume.level);
const clock = (seconds) => formatDuration(seconds * 1000) || "0:00";

/** Joue une sortie, ou l'un de ses titres. Avec des titres connus, « tout » commence au premier :
 * la page les enchaîne elle-même, avec une barre de progression par titre. `list` : l'entrée de la
 * liste de lecture jouée ; on y reste tant qu'on ne change pas de sortie (ses titres s'enchaînent). */
function play(release, { platform = null, track = null, list = null } = {}) {
  const links = playableLinks(release);
  const first = track === null && !platform && release.tracklist?.length > 1 ? 0 : track;
  const link = links.find((candidate) => candidate.platform === platform) ?? links[0];
  if (!link && first === null) return;
  const current = page.player?.id === release.id ? page.player.list : null;
  page.player = { id: release.id, platform: link?.platform ?? null, track: first, list: list ?? current, release };
  renderPlayer();
  render();
}

function stopPlayer() {
  page.player = null;
  player.stop();
  renderPlayer();
  render();
}

function renderPlayer() {
  const dock = $("#player");
  const release = page.player && findRelease(page.player.id);
  const source = release && playerSource(release, page.player, location.origin);
  if (!source?.src) {
    dock.hidden = true;
    player.stop();
    closeFocus();
    document.documentElement.style.removeProperty("--dock");
    return;
  }
  const track = page.player.track === null ? null : release.tracklist[page.player.track];
  const artists = release.artists.map((artist) => artist.name).join(", ");
  const title = track ? track.title : release.title;
  const from = track ? release.title : release.album?.title; // la sortie qui contient le titre joué
  $("#player-title").textContent = title;
  $("#player-subtitle").textContent = from ? `${artists} · ${from}` : artists;
  const cover = $("#player-cover");
  cover.hidden = !release.cover;
  if (release.cover) cover.src = safeUrl(release.cover.url);
  $("#player-media").classList.toggle("is-video", source.platform === "youtube");
  const name = PLATFORM_LABELS[source.platform];
  Object.assign($("#player-source"), { href: safeUrl(source.url), textContent: `Écouter sur ${name}` });
  const links = track ? [] : playableLinks(release);
  $("#player-platforms").replaceChildren(
    ...(links.length > 1 ? links.filter((link) => link.platform !== source.platform) : []).map((link) => {
      const button = Object.assign(document.createElement("button"), {
        type: "button",
        className: "player-platform",
        textContent: `Lire sur ${PLATFORM_LABELS[link.platform]}`,
      });
      button.dataset.platform = link.platform;
      return button;
    }),
  );
  if (player.state?.src !== source.src) {
    player.load({ platform: source.platform, src: source.src, title: `Lecteur ${name} : ${title}` });
  }
  renderMarkButtons();
  renderFocus();
  dock.hidden = false;
  updateDockSpace();
}

/** Place laissée en bas de la page (dernières cartes, messages) : celle du lecteur, agrandi ou non. */
function updateDockSpace() {
  const panel = page.focus ? $("#focus") : $("#player");
  if (panel.hidden) document.documentElement.style.removeProperty("--dock");
  else document.documentElement.style.setProperty("--dock", `${panel.offsetHeight}px`);
}

/** État du lecteur de la plateforme : bouton lecture, barre de progression, fin du titre. */
function onPlayerChange(state) {
  const playing = state.playing;
  for (const toggle of document.querySelectorAll('[data-player="toggle"]')) {
    toggle.textContent = playing ? "❚❚" : "▶";
    toggle.setAttribute("aria-label", playing ? "Pause" : "Lecture");
  }
  for (const seek of document.querySelectorAll(".player-seek")) {
    seek.disabled = !(state.duration > 0) || state.failed;
    if (!page.seeking) seek.value = String(state.duration > 0 ? Math.round((state.position / state.duration) * 1000) : 0);
  }
  if (!page.seeking) setTimes("position", state.position);
  setTimes("duration", state.duration);
  // Lecteur muet : on le montre tel quel, avec ses propres commandes.
  $("#player-media").classList.toggle("is-native", state.failed);
  renderVolume(state);
  renderSpotifyLogin(state);
  const release = page.player && findRelease(page.player.id);
  const button = release && $(`.card[data-id="${release.id}"] .play`);
  if (button) renderPlayButton(button, release);
  if (state.ended && release) playNext({ ended: true });
  updateDockSpace();
}

// --- Volume : un bouton qui ouvre un curseur, dans le bandeau et dans le lecteur agrandi ----------

function readVolume() {
  try {
    const saved = JSON.parse(readSetting(VOLUME_KEY));
    const level = Math.min(100, Math.max(0, Math.round(Number(saved?.level))));
    if (Number.isFinite(level)) return { level, muted: Boolean(saved.muted) };
  } catch {
    // réglage absent ou illisible : volume plein
  }
  return { level: 100, muted: false };
}

/** Nouveau volume (0 à 100) ou son coupé ; appliqué au lecteur et gardé dans ce navigateur. */
function setVolume({ level = page.volume.level, muted = page.volume.muted }) {
  page.volume = { level, muted: muted && level > 0 };
  player.setVolume(page.volume.muted ? 0 : level);
  writeSetting(VOLUME_KEY, JSON.stringify(page.volume));
  renderVolume(player.state);
}

function renderVolume(state) {
  const supported = state?.volumeSupported !== false;
  const { level, muted } = page.volume;
  const heard = muted ? 0 : level;
  const icon = heard === 0 ? "🔇" : heard < 34 ? "🔈" : heard < 67 ? "🔉" : "🔊";
  for (const button of document.querySelectorAll('[data-volume="toggle"]')) {
    button.textContent = supported ? icon : "🔊";
    button.setAttribute("aria-label", `Volume : ${supported ? `${heard} %` : "celui de l'appareil"}`);
  }
  for (const pop of document.querySelectorAll(".volume-pop")) {
    const slider = pop.querySelector(".player-volume");
    slider.disabled = !supported;
    if (document.activeElement !== slider) slider.value = String(level);
    slider.hidden = !supported;
    pop.querySelector(".volume-value").hidden = !supported;
    pop.querySelector(".volume-value").textContent = `${heard} %`;
    pop.querySelector(".volume-note").hidden = supported;
    const mute = pop.querySelector(".volume-mute");
    mute.hidden = !supported;
    mute.textContent = muted ? "🔊" : "🔇";
    mute.setAttribute("aria-label", muted ? "Remettre le son" : "Couper le son");
    mute.title = mute.getAttribute("aria-label");
  }
}

/** Ferme les curseurs de volume ouverts ; true s'il y en avait un. */
function closeVolume(except = null) {
  let closed = false;
  for (const pop of document.querySelectorAll(".volume-pop")) {
    if (pop === except || pop.hidden) continue;
    pop.hidden = true;
    pop.parentElement.querySelector('[data-volume="toggle"]').setAttribute("aria-expanded", "false");
    closed = true;
  }
  return closed;
}

function onVolumeClick(control) {
  if (control.dataset.volume === "mute") {
    setVolume({ muted: !page.volume.muted });
    return;
  }
  const pop = control.parentElement.querySelector(".volume-pop");
  closeVolume(pop);
  pop.hidden = !pop.hidden;
  control.setAttribute("aria-expanded", String(!pop.hidden));
  if (!pop.hidden) pop.querySelector(".player-volume:not([hidden])")?.focus();
}

function setTimes(kind, seconds) {
  for (const element of document.querySelectorAll(`[data-time="${kind}"]`)) element.textContent = clock(seconds);
}

/** Titre d'EP en cours, que visent l'étoile et le « ＋ Liste » du lecteur ; null quand la sortie
 * joue d'un bloc ou n'a qu'un titre. */
function playingTrack(release) {
  if (page.player.track === null || !(release.tracklist?.length > 1)) return null;
  return release.tracklist[page.player.track] ?? null;
}

/** Ce que le lecteur ajoute à la liste de lecture : le titre en cours, sinon la sortie. */
function playingEntries(release) {
  const track = playingTrack(release);
  return track ? playlistEntries(release, track) : playlistEntries(release);
}

/** Boutons de tri du lecteur (bandeau et agrandi), d'après les marques de la sortie en cours. Quand
 * un titre d'EP joue, l'étoile et « ＋ Liste » visent ce titre. */
function renderMarkButtons() {
  const release = page.player && findRelease(page.player.id);
  if (!release) return;
  const track = playingTrack(release);
  const starred = track ? Boolean(page.marks.favTracks[track.url]) : isFavorite(release);
  const star = starred ? "★" : "☆";
  // Un favori ne vit que dans « Favoris », et la carte d'un titre n'a pas d'onglet à elle.
  const stays = Boolean(page.marks.fav[release.id] || release.track);
  const states = {
    fav: [starred, track ? `${star} Ce titre` : `${star} Favori`],
    seen: [Boolean(page.marks.seen[release.id]), page.marks.seen[release.id] ? "✓ Vu" : "✓ Déjà vu"],
    hide: [Boolean(page.marks.hiddenReleases[release.id]), page.marks.hiddenReleases[release.id] ? "Masquée" : "Masquer"],
  };
  for (const button of document.querySelectorAll("[data-mark]")) {
    const kind = button.dataset.mark;
    button.hidden = stays && (kind === "seen" || kind === "hide");
    if (kind === "list") {
      renderListButton(button, playingEntries(release), track?.title ?? release.title);
      continue;
    }
    const [pressed, text] = states[kind];
    button.setAttribute("aria-pressed", String(pressed));
    button.textContent = text;
  }
}

/** Tri depuis le lecteur : « Déjà vu » et « Masquer » rangent la sortie et passent à la suivante,
 * « Favori » et « ＋ Liste » la gardent (ou le titre en cours) et laissent la musique continuer. */
function onTriage(kind) {
  const release = page.player && findRelease(page.player.id);
  if (!release) return;
  const track = playingTrack(release);
  if (kind === "list") toggleList(playingEntries(release), track?.title ?? release.title);
  else if (kind === "fav" && track) markTrack(release, track);
  else if (kind === "fav") markRelease(release, kind);
  // Un favori reste un favori, et la carte d'un titre n'a pas d'onglet où être rangée.
  else if (!page.marks.fav[release.id] && !release.track && markRelease(release, kind)) playNeighbour(1);
}

const FIREFOX_SHIELD = "clique sur le bouclier à gauche de l'adresse et désactive la protection pour ce site";
const SPOTIFY_PREVIEW_NOTES = {
  mobile: "Extrait de 30 s : sur téléphone, Spotify ne joue que des extraits dans une page. « Écouter sur Spotify » ouvre le titre entier.",
  safari: "Extrait de 30 s : dans Safari, Spotify ne joue que des extraits dans une page. « Écouter sur Spotify » ouvre le titre entier.",
  firefox: `Extrait de 30 s : Firefox cache ta session Spotify à cette page ; ${FIREFOX_SHIELD}.`,
  cookies: "Extrait de 30 s : Spotify ne te reconnaît pas dans ce navigateur.",
};
const SPOTIFY_RETRIED_NOTES = {
  firefox: `Toujours un extrait : ${FIREFOX_SHIELD}.`,
  cookies:
    "Toujours un extrait : es-tu bien connecté dans l'onglet Spotify ? Sinon, ce navigateur bloque les cookies tiers : autorise-les pour ce site dans ses réglages.",
};

/** Extrait de 30 s : la page dit pourquoi, selon le navigateur. Là où une connexion peut suffire,
 * le bouton l'ouvre dans un onglet ; au retour sur la page, le lecteur Spotify est rechargé. */
function renderSpotifyLogin(state) {
  const release = page.player && findRelease(page.player.id);
  const track = release && page.player.track !== null ? release.tracklist?.[page.player.track] : null;
  const preview = isSpotifyPreview(state, track);
  const cause = spotifyPreviewCause(navigator.userAgent);
  $("#player-login").hidden = !preview || !(cause in SPOTIFY_RETRIED_NOTES);
  const note = $("#player-note");
  note.hidden = !preview;
  note.textContent =
    (page.spotifyLogin === "retried" && SPOTIFY_RETRIED_NOTES[cause]) || SPOTIFY_PREVIEW_NOTES[cause];
  note.title = note.textContent;
}

function onSpotifyReturn() {
  if (document.visibilityState !== "visible" || page.spotifyLogin !== "reconnecting") return;
  page.spotifyLogin = "retried";
  if (player.state?.platform === "spotify") player.reload();
}

/** ▶ d'une carte : lecture, ou pause et reprise pour la sortie en cours. */
function renderPlayButton(button, release) {
  const current = page.player?.id === release.id;
  const playing = current && player.state?.playing;
  button.textContent = playing ? "❚❚" : "▶";
  const label = playing ? "Mettre en pause" : current ? "Reprendre" : `Écouter « ${release.title} »`;
  button.setAttribute("aria-label", label);
  button.title = playing ? "Pause" : "Écouter ici";
}

/** ⏭, ou fin d'un titre : titre suivant de la sortie, sinon sortie suivante de la liste. Une sortie
 * jouée d'un bloc (playlist SoundCloud, album Spotify) enchaîne seule ses titres : on la laisse finir. */
function playNext({ ended = false } = {}) {
  const release = findRelease(page.player.id);
  const { track } = page.player;
  if (track !== null && release.tracklist?.[track + 1]) play(release, { track: track + 1 });
  else if (ended && track === null && hasTracks(release)) return;
  else playNeighbour(1);
}

/** ⏮ : début du titre après 3 secondes, sinon titre précédent, sinon sortie précédente. */
function playPrevious() {
  const release = findRelease(page.player.id);
  const { track } = page.player;
  if ((player.state?.position ?? 0) > 3) player.seek(0);
  else if (track > 0) play(release, { track: track - 1 });
  else playNeighbour(-1);
}

// --- Lecteur agrandi ------------------------------------------------------------------------------
// La sortie en cours sur la moitié basse de l'écran, avec ses titres et les boutons de tri : on trie
// les sorties une par une, au clavier si l'on veut. La liste reste utilisable au-dessus, et le bandeau
// reste chargé dessous : la musique ne s'arrête pas.

function openFocus() {
  page.focus = true;
  renderFocus();
  $("#focus-close").focus();
}

function closeFocus() {
  if (!page.focus) return;
  page.focus = false;
  renderFocus();
  if (!$("#player").hidden) $("#player-expand").focus();
}

function renderFocus() {
  const box = $("#focus");
  const release = page.player && findRelease(page.player.id);
  box.hidden = !page.focus || !release;
  if (box.hidden) {
    updateDockSpace();
    return;
  }
  const track = page.player.track === null ? null : release.tracklist?.[page.player.track];
  const cover = $("#focus-cover");
  cover.hidden = !release.cover;
  if (release.cover) cover.src = safeUrl(release.cover.url);
  const empty = $("#focus-cover-empty");
  empty.hidden = Boolean(release.cover);
  empty.textContent = initial(release);
  $("#focus-type").textContent = TYPE_LABELS[release.type] ?? release.type;
  $("#focus-new").hidden = !isNew(release, page.now, page.data.rules, page.data.timezone);
  $("#focus-title").textContent = release.title;
  const epStar = $("#focus-fav");
  const epFavorite = Boolean(page.marks.fav[release.id]);
  epStar.hidden = !playingTrack(release);
  epStar.textContent = epFavorite ? "★" : "☆";
  const whole = ALBUM_OF[release.type] ? `${ALBUM_OF[release.type]} entier` : "la sortie entière";
  epStar.title = epFavorite ? `Retirer ${whole} des favoris` : `Ajouter ${whole} aux favoris`;
  epStar.setAttribute("aria-pressed", String(epFavorite));
  epStar.setAttribute("aria-label", `${epFavorite ? "Retirer des favoris" : "Ajouter aux favoris"} : ${release.title}`);
  const current = $("#focus-track");
  current.hidden = !track;
  current.textContent = track ? `♪ ${track.title}` : "";
  $("#focus-artists").textContent = release.artists.map((artist) => artist.name).join(", ");
  const count = hasTracks(release) ? ` · ${plural(release.tracklist?.length || release.tracks, "titre")}` : "";
  const from = release.album ? ` · ${albumLine(release.album)}` : "";
  $("#focus-details").textContent = `${releaseDate(release)}${count}${from}`;
  const styles = $("#focus-styles");
  styles.textContent = (release.styles ?? []).map((style) => STYLE_LABELS[style] ?? style).join(" · ");
  styles.title = release.genres?.length ? `Genres : ${release.genres.join(", ")}` : "";
  styles.hidden = !styles.textContent;
  $("#focus-links").replaceChildren(...platformLinks(release));
  $("#focus-tracklist").replaceChildren(...trackItems(release));
  const position = page.player.list ? listPosition() : -1;
  const todo = tabCounts(page.data.releases, page.marks).todo;
  $("#focus-count").textContent =
    position === -1
      ? `${plural(todo, "sortie")} à découvrir`
      : `Liste de lecture : ${position + 1} sur ${page.marks.playlist.length}`;
  updateDockSpace();
}

/** Raccourcis du lecteur agrandi. Ils laissent les champs tranquilles, et ne doublent pas ce que
 * le clavier fait déjà : espace sur un bouton, flèches sur une barre de progression. */
function onFocusKey(event) {
  if (!page.focus || event.ctrlKey || event.metaKey || event.altKey) return;
  const target = event.target;
  if (target.matches?.("input:not(.player-seek, .player-volume), select, textarea")) return;
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  if (key === " " && target.matches?.("button, a")) return;
  if (key.startsWith("Arrow") && target.matches?.(".player-seek, .player-volume")) return;
  const action = {
    " ": () => player.toggle(),
    ArrowRight: () => playNext(),
    ArrowLeft: playPrevious,
    ArrowUp: () => setVolume({ level: Math.min(100, page.volume.level + 10), muted: false }),
    ArrowDown: () => setVolume({ level: Math.max(0, page.volume.level - 10) }),
    f: () => onTriage("fav"),
    l: () => onTriage("list"),
    v: () => onTriage("seen"),
    m: () => onTriage("hide"),
    // Un curseur de volume ouvert se ferme d'abord, puis la liste de lecture.
    Escape: () => closeVolume() || closeQueue() || closeFocus(),
  }[key];
  if (!action) return;
  event.preventDefault();
  action();
}

/** Sortie précédente ou suivante : dans la liste de lecture quand on la lit, sinon parmi les cartes
 * affichées. */
function playNeighbour(step) {
  if (page.player?.list) {
    const index = listPosition();
    // Entrée en cours retirée entre-temps : la suivante a pris sa place.
    playListEntry(index === -1 ? page.player.list.index + Math.min(step, 0) : index + step);
    return;
  }
  const index = page.order.indexOf(page.player?.id);
  const id = page.order[index === -1 ? 0 : index + step];
  const release = id && findRelease(id);
  if (!release) return;
  if (hasTracks(release)) page.open = release.id;
  play(release);
}

// --- Liste de lecture ----------------------------------------------------------------------------
// Une seule liste, gardée avec les marques (export, import, autres onglets). Un panneau à droite,
// ouvert depuis le lecteur ou au-dessus des cartes : la page reste utilisable à côté.

/** Place de l'entrée jouée dans la liste ; -1 si elle en a été retirée. */
function listPosition() {
  return page.marks.playlist.findIndex((entry) => entry.key === page.player.list.key);
}

/** Joue l'entrée `index` de la liste ; au-delà du bout, rien : la lecture s'arrête là. */
function playListEntry(index) {
  const entry = page.marks.playlist[index];
  if (entry) play(entryRelease(entry, page.byId), { list: { key: entry.key, index } });
}

/** Ajoute à la liste (ou en retire, si tout y est déjà) des titres ou une sortie. */
function toggleList(entries, title) {
  const listed = inPlaylist(page.marks, entries);
  const count = entries.length > 1 ? ` (${plural(entries.length, "titre")})` : "";
  const message = `« ${title} »${count} ${listed ? "retiré de" : "ajouté à"} la liste de lecture.`;
  applyMarks(togglePlaylist(page.marks, entries, new Date()), message);
}

function openQueue(opener) {
  page.queue = opener;
  renderQueue();
  $("#queue-close").focus();
}

/** Ferme la liste de lecture et rend le focus au bouton qui l'a ouverte ; true si elle était ouverte. */
function closeQueue() {
  const opener = page.queue;
  if (!opener) return false;
  page.queue = null;
  renderQueue();
  if (opener.offsetParent) opener.focus(); // encore affiché (le lecteur a pu se fermer entre-temps)
  return true;
}

/** Durée d'une liste : « 47 min », « 1 h 05 ». */
function totalDuration(ms) {
  const minutes = Math.round(ms / 60_000);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
}

function renderQueue() {
  const { playlist } = page.marks;
  const opened = Boolean(page.queue);
  for (const button of document.querySelectorAll("[data-queue]")) {
    button.setAttribute("aria-expanded", String(opened));
    button.querySelector(".queue-count").textContent = playlist.length || "";
    if (button.matches(".player-button")) button.setAttribute("aria-label", `Liste de lecture (${playlist.length})`);
  }
  document.body.classList.toggle("has-queue", opened);
  const box = $("#queue");
  box.hidden = !opened;
  if (!opened) return;
  const ms = playlist.reduce((total, entry) => total + (entry.track?.duration_ms ?? 0), 0);
  $("#queue-summary").textContent = playlist.length
    ? `${plural(playlist.length, "titre")}${ms ? ` · ${totalDuration(ms)}` : ""}`
    : "";
  $("#queue-empty").hidden = playlist.length > 0;
  $("#queue-play").disabled = !playlist.length;
  $("#queue-clear").disabled = !playlist.length;
  const current = page.player?.list?.key;
  $("#queue-list").replaceChildren(...playlist.map((entry, index) => queueItem(entry, index, entry.key === current)));
}

/** Une ligne de la liste : la jouer, la monter, la descendre ou la retirer. */
function queueItem(entry, index, current) {
  const release = entryRelease(entry, page.byId);
  const item = Object.assign(document.createElement("li"), { className: "queue-item" });
  if (current) item.setAttribute("aria-current", "true");
  const playButton = Object.assign(document.createElement("button"), {
    type: "button",
    className: "queue-play",
    disabled: playableLinks(release).length === 0,
  });
  playButton.setAttribute("aria-label", `Écouter « ${release.title} »`);
  let art;
  if (release.cover) {
    art = Object.assign(document.createElement("img"), { src: safeUrl(release.cover.url), alt: "", loading: "lazy", width: 40, height: 40 });
  } else {
    art = Object.assign(document.createElement("span"), { textContent: initial(release) });
  }
  art.classList.add("queue-art");
  const text = Object.assign(document.createElement("span"), { className: "queue-text" });
  const artists = release.artists.map((artist) => artist.name).join(", ");
  const from = release.album?.title;
  text.append(
    Object.assign(document.createElement("span"), { className: "queue-name", textContent: release.title }),
    Object.assign(document.createElement("span"), { className: "queue-sub", textContent: from ? `${artists} · ${from}` : artists }),
  );
  const length = Object.assign(document.createElement("span"), {
    className: "queue-duration",
    textContent: formatDuration(entry.track?.duration_ms),
  });
  playButton.append(art, text, length);
  const tool = (className, symbol, label, extra = {}) => {
    const button = Object.assign(document.createElement("button"), { type: "button", className, textContent: symbol, title: label, ...extra });
    button.setAttribute("aria-label", `${label} : ${release.title}`);
    return button;
  };
  const up = tool("queue-tool queue-move", "↑", "Monter", { disabled: index === 0 });
  up.dataset.step = "-1";
  const down = tool("queue-tool queue-move", "↓", "Descendre", { disabled: index === page.marks.playlist.length - 1 });
  down.dataset.step = "1";
  const remove = tool("queue-tool queue-remove", "✕", "Retirer de la liste");
  for (const button of [playButton, up, down, remove]) button.dataset.index = String(index);
  item.append(playButton, up, down, remove);
  return item;
}

function onQueueClick(event) {
  const button = event.target.closest("button");
  if (!button) return;
  const index = Number(button.dataset.index);
  if (button.matches(".queue-play")) {
    playListEntry(index);
  } else if (button.matches(".queue-move")) {
    const step = Number(button.dataset.step);
    applyMarks(movePlaylistEntry(page.marks, index, step));
    // Le focus suit la ligne déplacée : on peut la monter plusieurs fois au clavier.
    const moved = `#queue-list [data-index="${index + step}"]`;
    ($(`${moved}.queue-move[data-step="${step}"]:not(:disabled)`) ?? $(`${moved}.queue-play`))?.focus();
  } else if (button.matches(".queue-remove")) {
    const { title } = entryRelease(page.marks.playlist[index], page.byId);
    applyMarks(removePlaylistEntry(page.marks, index), `« ${title} » retiré de la liste de lecture.`);
    ($(`#queue-list [data-index="${index}"].queue-remove`) ?? $("#queue-close")).focus();
  }
}

function onClearQueue() {
  const count = page.marks.playlist.length;
  if (!count || !confirm(`Vider la liste de lecture (${plural(count, "titre")}) ?`)) return;
  applyMarks({ ...page.marks, playlist: [] }, "Liste de lecture vidée.");
}

function renderHidden() {
  const releases = hiddenReleases(page.data.releases, page.marks);
  const accounts = hiddenAccounts(page.data.releases, page.marks);
  $("#hidden-box").hidden = releases.length + accounts.length === 0;
  const s = (count) => (count > 1 ? "s" : "");
  $("#hidden-summary").textContent = [
    releases.length ? `${plural(releases.length, "sortie")} masquée${s(releases.length)}` : "",
    accounts.length ? `${plural(accounts.length, "compte")} masqué${s(accounts.length)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const item = (text, kind, id, name) => {
    const entry = document.createElement("li");
    const button = document.createElement("button");
    Object.assign(button, { type: "button", className: "btn btn-ghost unhide", textContent: "Réafficher" });
    Object.assign(button.dataset, { kind, id, name });
    entry.append(document.createTextNode(`${text} `), button);
    return entry;
  };
  $("#hidden-list").replaceChildren(
    ...releases.map((release) => item(`${release.title} — ${release.artist}`, "release", release.id, release.title)),
    ...accounts.map((account) =>
      item(`${account.name} (${plural(account.releases, "sortie")})`, "account", account.id, account.name),
    ),
  );
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

/** Sortie (ou carte d'un titre) par identifiant : dans les données, les favoris, les cartes gardées
 * à leur place, ou celle qui joue, même retirée de la liste de lecture entre-temps. */
function findRelease(id) {
  return page.byId.get(id)
    ?? releasesForTab(page.data.releases, page.marks, "fav").find((release) => release.id === id)
    ?? page.kept.get(id)
    ?? (page.player?.id === id ? page.player.release : undefined);
}

function onCardClick(event) {
  const button = event.target.closest(
    ".mark-seen, .mark-fav, .mark-hide, .mark-list, .play, .play-all, .track, .track-fav, .track-add, .show-tracks, .close-tracks",
  );
  // Second clic d'un double-clic : il annulerait le premier.
  if (!button || event.detail > 1) return;
  const release = findRelease(button.closest(".card").dataset.id);
  if (!release) return;
  if (button.matches(".play, .play-all, .track, .show-tracks, .close-tracks")) {
    onPlayClick(button, release);
    return;
  }
  if (button.matches(".track-fav, .track-add")) {
    onTrackMark(button, release);
    return;
  }
  const kind = ["hide", "fav", "list"].find((name) => button.classList.contains(`mark-${name}`)) ?? "seen";
  markRelease(release, kind);
}

/** Étoile ou « ＋ » d'un titre, dans une carte ouverte ou dans le lecteur agrandi. */
function onTrackMark(button, release) {
  const track = release.tracklist[Number(button.dataset.index)];
  if (!track) return;
  if (button.matches(".track-fav")) markTrack(release, track);
  else toggleList(playlistEntries(release, track), track.title);
}

/** Un titre d'EP en favori (ou plus) : sa carte arrive dans « Favoris », l'EP reste où il est. */
function markTrack(release, track) {
  const marks = toggleFavoriteTrack(page.marks, release, track, new Date());
  const message = marks.favTracks[track.url]
    ? `« ${track.title} » rangé dans « Favoris ».`
    : `« ${track.title} » retiré des favoris.`;
  applyMarks(marks, message);
}

/** Favori, déjà vu, masquée ou dans la liste de lecture (ou l'inverse) ; true si la sortie vient
 * d'être rangée hors de la liste (vue ou masquée). La carte reste à sa place jusqu'au prochain
 * onglet ou filtre. */
function markRelease(release, kind) {
  if (kind === "list") {
    toggleList(playlistEntries(release), release.title);
    return false;
  }
  page.kept.set(release.id, release);
  if (kind === "fav" && release.track) {
    markTrack(release.album, release.track); // carte d'un titre d'EP
    return false;
  }
  if (kind === "hide") {
    const marks = toggleHiddenRelease(page.marks, release, new Date());
    const hidden = Boolean(marks.hiddenReleases[release.id]);
    applyMarks(marks, `« ${release.title} » ${hidden ? "masquée" : "réaffichée"}.`);
    return hidden;
  }
  if (kind === "fav") {
    const { archived, ...snapshot } = release;
    const marks = toggleFavorite(page.marks, snapshot, new Date());
    const destination = { todo: "« À découvrir »", seen: "« Déjà vus »" }[tabOf(release.id, marks)];
    const message = marks.fav[release.id]
      ? `« ${release.title} » rangé dans « Favoris ».`
      : `« ${release.title} » retiré des favoris${archived ? "" : `, de retour dans ${destination}`}.`;
    applyMarks(marks, message);
    return false;
  }
  const seen = Boolean(page.marks.seen[release.id]);
  const message = seen ? `« ${release.title} » remis dans « À découvrir ».` : `« ${release.title} » rangé dans « Déjà vus ».`;
  applyMarks(toggleSeen(page.marks, release.id, new Date()), message);
  return !seen;
}

function onPlayClick(button, release) {
  if (button.matches(".show-tracks, .close-tracks")) {
    page.open = page.open === release.id ? null : release.id;
    render();
  } else if (button.matches(".track")) {
    const track = release.tracklist[Number(button.dataset.index)];
    play(release, { platform: track.platform, track: Number(button.dataset.index) });
  } else if (button.matches(".play") && page.player?.id === release.id) {
    player.toggle(); // la sortie en cours : pause ou reprise
  } else {
    if (hasTracks(release)) page.open = release.id;
    play(release);
  }
}

/** « Tout marquer comme vu » dans « À découvrir », « Tout remettre » dans « Déjà vus ». */
function onMarkAll() {
  const ids = page.visible.map((release) => release.id);
  const restore = page.filters.tab === "seen";
  const question = restore
    ? `Remettre les ${ids.length} sorties affichées dans « À découvrir » ?`
    : `Ranger les ${ids.length} sorties affichées dans « Déjà vus » ?`;
  if (!ids.length || !confirm(question)) return;
  const s = ids.length > 1 ? "s" : "";
  const done = restore ? `remise${s} dans « À découvrir »` : `rangée${s} dans « Déjà vus »`;
  applyMarks(toggleSeen(page.marks, ids, new Date()), `${plural(ids.length, "sortie")} ${done}.`);
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
  const count = [imported.seen, imported.fav, imported.hiddenReleases, imported.favTracks, imported.playlist].reduce(
    (total, bucket) => total + Object.keys(bucket).length,
    0,
  );
  if (!count) {
    showToast("Fichier non reconnu : aucune marque importée.");
    return;
  }
  const merged = mergeMarks(page.marks, migrateMarks(imported, page.data.aliases));
  applyMarks(merged, `${plural(count, "marque")} importée${count > 1 ? "s" : ""}.`);
}

function selectTab(tab) {
  page.kept.clear();
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
  if (isSealed(page.data)) {
    page.data = await unlock(page.data);
    $("#lock-tools").hidden = false;
    $("#lock").addEventListener("click", async () => {
      await forgetKey();
      location.reload();
    });
  }
  page.byId = new Map(page.data.releases.map((release) => [release.id, release]));
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
      page.kept.clear();
      page.filters = readFilters();
      updateHash();
      render();
    }, event.target.id === "q" ? 150 : 0);
  });
  $("#filters").addEventListener("submit", (event) => event.preventDefault());
  $("#reset").addEventListener("click", () => {
    page.kept.clear();
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
  $("#player-close").addEventListener("click", stopPlayer);
  $("#player-expand").addEventListener("click", openFocus);
  $("#focus-close").addEventListener("click", closeFocus);
  // Commandes du bandeau et du lecteur agrandi : les mêmes, repérées par data-player et data-mark.
  document.addEventListener("click", (event) => {
    const volume = event.target.closest("[data-volume]");
    if (volume) onVolumeClick(volume);
    else if (!event.target.closest(".volume-pop")) closeVolume(); // clic ailleurs : le curseur se ferme
    const queue = event.target.closest("[data-queue]");
    if (queue && !closeQueue()) openQueue(queue);
    const control = event.target.closest("[data-player], [data-mark]");
    if (!control || !page.player || event.detail > 1) return;
    if (control.dataset.mark) onTriage(control.dataset.mark);
    else ({ prev: playPrevious, toggle: () => player.toggle(), next: () => playNext() })[control.dataset.player]();
  });
  $("#focus-tracklist").addEventListener("click", (event) => {
    const button = event.target.closest(".track, .track-fav, .track-add");
    const release = button && page.player && findRelease(page.player.id);
    if (!release || event.detail > 1) return;
    if (button.matches(".track")) play(release, { track: Number(button.dataset.index) });
    else onTrackMark(button, release);
  });
  $("#focus-fav").addEventListener("click", () => {
    const release = page.player && findRelease(page.player.id);
    if (release) markRelease(release, "fav");
  });
  $("#queue-close").addEventListener("click", closeQueue);
  $("#queue-list").addEventListener("click", onQueueClick);
  $("#queue-play").addEventListener("click", () => playListEntry(0));
  $("#queue-clear").addEventListener("click", onClearQueue);
  document.addEventListener("keydown", onFocusKey);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !page.focus) closeVolume() || closeQueue();
  });
  $("#player-login").addEventListener("click", () => {
    page.spotifyLogin = "reconnecting";
  });
  document.addEventListener("visibilitychange", onSpotifyReturn);
  // Pendant qu'on glisse une barre, elle suit le doigt ; le lecteur ne saute qu'au lâcher.
  const seekTarget = (seek) => (Number(seek.value) / 1000) * (player.state?.duration ?? 0);
  document.addEventListener("input", (event) => {
    if (event.target.matches(".player-volume")) setVolume({ level: Number(event.target.value), muted: false });
    if (!event.target.matches(".player-seek")) return;
    page.seeking = true;
    setTimes("position", seekTarget(event.target));
  });
  document.addEventListener("change", (event) => {
    if (!event.target.matches(".player-seek")) return;
    page.seeking = false;
    player.seek(seekTarget(event.target));
  });
  $("#player-platforms").addEventListener("click", (event) => {
    const button = event.target.closest(".player-platform");
    const release = button && page.player && findRelease(page.player.id);
    if (release) play(release, { platform: button.dataset.platform });
  });
  window.addEventListener("resize", updateDockSpace);
  $("#hidden-list").addEventListener("click", (event) => {
    const button = event.target.closest(".unhide");
    if (!button) return;
    const { kind, id, name } = button.dataset;
    const marks =
      kind === "release"
        ? toggleHiddenRelease(page.marks, { id }, new Date())
        : toggleHidden(page.marks, { id, name }, new Date());
    applyMarks(marks, `« ${name} » réaffiché${kind === "release" ? "e" : ""}.`);
  });
  $("#run-now").addEventListener("click", onRunNow);
  $("#run-form").addEventListener("submit", onRunDialogSubmit);
  $("#forget-token").addEventListener("click", () => {
    writeSetting(TOKEN_KEY, null);
    renderLate();
    showToast("Token GitHub oublié par ce navigateur.");
  });
  $("#mark-all").addEventListener("click", onMarkAll);
  $("#export").addEventListener("click", onExport);
  $("#import").addEventListener("change", onImport);
  window.addEventListener("hashchange", () => {
    page.kept.clear();
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
