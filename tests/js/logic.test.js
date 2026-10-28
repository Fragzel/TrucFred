import assert from "node:assert/strict";
import test from "node:test";

import {
  ALL_ELECTRO,
  NO_STYLE,
  embedUrl,
  emptyMarks,
  entryRelease,
  fold,
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
  localDay,
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
  releaseWeek,
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
  trackId,
  zonedInstant,
} from "../../site/logic.js";

const RULES = { new_days: 7, new_max_age_days: 14, stale_hours: 36 };
const NOW = new Date("2026-10-22T10:00:00Z"); // jeudi
const release = (overrides = {}) => ({
  id: "r_1",
  title: "Lumières froides",
  edition: null,
  type: "single",
  artists: [{ id: "a_1", name: "Beyoncé" }],
  sort_date: "2026-10-16",
  first_seen: "2026-10-16T04:00:00Z",
  backfill: false,
  links: [{ platform: "spotify" }],
  ...overrides,
});
const noFilter = { tab: "todo", query: "", platforms: null, types: null, style: null, newOnly: false };

test("la semaine de sortie commence le vendredi", () => {
  assert.equal(releaseWeek("2026-10-16"), "2026-10-16"); // vendredi
  assert.equal(releaseWeek("2026-10-17"), "2026-10-16"); // samedi
  assert.equal(releaseWeek("2026-10-22"), "2026-10-16"); // jeudi
  assert.equal(releaseWeek("2026-10-15"), "2026-10-09"); // jeudi précédent
});

test("jour local selon le fuseau", () => {
  assert.equal(localDay(new Date("2026-10-21T22:30:00Z"), "Europe/Paris"), "2026-10-22");
  assert.equal(localDay(new Date("2026-10-21T22:30:00Z"), "UTC"), "2026-10-21");
});

test("nouveauté : récente, vue il y a peu, hors catalogue", () => {
  assert.equal(isNew(release(), NOW, RULES, "Europe/Paris"), true);
  assert.equal(isNew(release({ backfill: true }), NOW, RULES, "Europe/Paris"), false);
  assert.equal(isNew(release({ first_seen: "2026-10-14T04:00:00Z" }), NOW, RULES, "Europe/Paris"), false);
  assert.equal(isNew(release({ sort_date: "2026-10-01" }), NOW, RULES, "Europe/Paris"), false);
});

test("recherche insensible aux accents et à la casse", () => {
  assert.equal(fold("ÉCHOS Beyoncé"), "echos beyonce");
  assert.equal(matches(release(), { ...noFilter, query: "beyonce lumieres" }, () => false), true);
  assert.equal(matches(release(), { ...noFilter, query: "inconnu" }, () => false), false);
});

test("filtres de plateforme, de type et de nouveauté", () => {
  assert.equal(matches(release(), { ...noFilter, platforms: new Set(["soundcloud"]) }, () => true), false);
  assert.equal(matches(release(), { ...noFilter, types: new Set(["album", "single"]) }, () => true), true);
  assert.equal(matches(release(), { ...noFilter, newOnly: true }, () => false), false);
});

test("regroupement par semaine, la plus récente d'abord", () => {
  const weeks = groupByWeek([
    release({ id: "a", sort_date: "2026-10-09" }),
    release({ id: "b", sort_date: "2026-10-17" }),
    release({ id: "c", sort_date: "2026-10-16" }),
  ]);
  assert.deepEqual(
    weeks.map(({ week, releases }) => [week, releases.map((r) => r.id)]),
    [
      ["2026-10-16", ["b", "c"]],
      ["2026-10-09", ["a"]],
    ],
  );
  // Même jour, même détection : l'identifiant décide, quel que soit l'ordre reçu.
  const sameDay = ["r_1", "r_3", "r_2"].map((id) => release({ id }));
  assert.deepEqual(groupByWeek(sameDay)[0].releases.map((r) => r.id), ["r_3", "r_2", "r_1"]);
  assert.deepEqual(groupByWeek(sameDay.reverse())[0].releases.map((r) => r.id), ["r_3", "r_2", "r_1"]);
});

test("onglet et filtres ⇄ hash d'URL", () => {
  const filters = {
    tab: "fav",
    query: "nuit blanche",
    platforms: new Set(["spotify"]),
    types: new Set(["single", "ep"]),
    style: "techno",
    newOnly: true,
  };
  const back = parseHash(formatHash(filters));
  assert.deepEqual({ ...back, platforms: [...back.platforms], types: [...back.types] }, {
    tab: "fav",
    query: "nuit blanche",
    platforms: ["spotify"],
    types: ["ep", "single"],
    style: "techno",
    newOnly: true,
  });
  assert.equal(formatHash(noFilter), "");
  assert.deepEqual(parseHash(""), noFilter);
  assert.equal(parseHash("#tab=inconnu").tab, "todo");
  assert.equal(parseHash("#s=inconnu").style, null);
  assert.equal(parseHash(`#s=${ALL_ELECTRO}`).style, ALL_ELECTRO);
});

test("filtre de style : un style, toute l'électro, ou sans style", () => {
  const techno = release({ styles: ["techno", "rap"], genres: ["acid techno"] });
  const rap = release({ styles: ["rap"] });
  const unknown = release({ styles: [] });
  const old = release(); // favori gardé avant l'arrivée des styles
  const kept = (style) =>
    [techno, rap, unknown, old].filter((item) => matches(item, { ...noFilter, style }, () => true));
  assert.deepEqual(kept("rap"), [techno, rap]);
  assert.deepEqual(kept(ALL_ELECTRO), [techno]);
  assert.deepEqual(kept(NO_STYLE), [unknown, old]);
  assert.deepEqual(kept(null), [techno, rap, unknown, old]);
  assert.deepEqual(styleCounts([techno, rap, unknown, old]), {
    [ALL_ELECTRO]: 1,
    [NO_STYLE]: 2,
    techno: 1,
    rap: 2,
  });
});

test("recherche dans les styles et les genres", () => {
  const techno = release({ styles: ["hardcore"], genres: ["Gabber", "frenchcore"] });
  const search = (query) => matches(techno, { ...noFilter, query }, () => true);
  assert.equal(search("gabber"), true);
  assert.equal(search("hardcore"), true);
  assert.equal(search("drill"), false);
});

test("déjà vu : la sortie change d'onglet, et revient si on décoche", () => {
  const releases = [release({ id: "a" }), release({ id: "b" })];
  let marks = toggleSeen(emptyMarks(), "a", NOW);
  assert.deepEqual(releasesForTab(releases, marks, "todo").map((r) => r.id), ["b"]);
  assert.deepEqual(releasesForTab(releases, marks, "seen").map((r) => r.id), ["a"]);
  assert.deepEqual(tabCounts(releases, marks), { todo: 1, seen: 1, fav: 0 });
  marks = toggleSeen(marks, "a", NOW);
  assert.deepEqual(tabCounts(releases, marks), { todo: 2, seen: 0, fav: 0 });
});

test("une sortie rangée ailleurs reste à sa place jusqu'au changement d'onglet", () => {
  const artist = [{ id: "a_1", name: "Polyphia" }];
  const releases = ["a", "b", "c"].map((id) => release({ id, artists: artist }));
  const marks = toggleSeen(emptyMarks(), "a", NOW);
  const shown = (tab, kept) => releasesShown(releases, marks, tab, new Set(kept)).map((r) => r.id);
  assert.deepEqual(shown("todo", ["a"]), ["b", "c", "a"]); // la voisine ne prend pas sa place
  assert.deepEqual(shown("todo", []), ["b", "c"]);
  assert.deepEqual(shown("seen", ["a"]), ["a"]); // déjà dans l'onglet : pas en double
  const hidden = toggleHidden(marks, artist[0], NOW);
  assert.deepEqual(releasesShown(releases, hidden, "todo", new Set(["a"])), []); // compte masqué
  assert.deepEqual(tabCounts(releases, marks), { todo: 2, seen: 1, fav: 0 }); // compteurs exacts
});

test("tout marquer : un lot partiellement vu devient entièrement vu", () => {
  const marks = toggleSeen(toggleSeen(emptyMarks(), "a", NOW), ["a", "b"], NOW);
  assert.deepEqual(Object.keys(marks.seen).sort(), ["a", "b"]);
  assert.deepEqual(toggleSeen(marks, ["a", "b"], NOW).seen, {});
});

test("favori : visible dans son onglet, même hors fenêtre de 90 jours", () => {
  const kept = release({ id: "ancien", title: "Vieux tube" });
  const marks = toggleFavorite(toggleFavorite(emptyMarks(), kept, NOW), release({ id: "a" }), NOW);
  const favorites = releasesForTab([release({ id: "a" })], marks, "fav");
  assert.deepEqual(favorites.map((r) => [r.id, Boolean(r.archived)]), [["ancien", true], ["a", false]]);
  assert.equal(favorites[0].title, "Vieux tube");
  assert.deepEqual(toggleFavorite(marks, kept, NOW).fav.ancien, undefined);
});

test("chaque sortie n'apparaît que dans un seul onglet, le favori l'emporte", () => {
  const releases = [release({ id: "a" }), release({ id: "b" }), release({ id: "c" })];
  let marks = toggleSeen(emptyMarks(), ["a", "b"], NOW);
  marks = toggleFavorite(marks, releases[0], NOW); // vu et favori
  marks = toggleFavorite(marks, releases[2], NOW); // favori jamais marqué vu
  const ids = (tab) => releasesForTab(releases, marks, tab).map((r) => r.id);
  assert.deepEqual([ids("todo"), ids("seen"), ids("fav")], [[], ["b"], ["a", "c"]]);
  assert.deepEqual(tabCounts(releases, marks), { todo: 0, seen: 1, fav: 2 });
  assert.deepEqual([tabOf("a", marks), tabOf("b", marks), tabOf("c", marks)], ["fav", "seen", "fav"]);
  // Sans l'étoile, chacun retourne là où il était : « a » dans les vus, « c » à découvrir.
  marks = toggleFavorite(toggleFavorite(marks, releases[0], NOW), releases[2], NOW);
  assert.deepEqual([ids("todo"), ids("seen"), ids("fav")], [["c"], ["a", "b"], []]);
});

test("sortie masquée : elle seule quitte les onglets, les autres titres de l'artiste restent", () => {
  const artist = [{ id: "a_1", name: "Polyphia" }];
  const releases = ["a", "b", "c"].map((id) => release({ id, title: `Titre ${id}`, artists: artist }));
  let marks = toggleSeen(toggleHiddenRelease(emptyMarks(), releases[0], NOW), "b", NOW);
  marks = toggleHiddenRelease(marks, releases[1], NOW); // vue, puis masquée
  const ids = (tab) => releasesForTab(releases, marks, tab).map((r) => r.id);
  assert.deepEqual([ids("todo"), ids("seen")], [["c"], []]);
  assert.deepEqual(tabCounts(releases, marks), { todo: 1, seen: 0, fav: 0 });
  assert.deepEqual(
    hiddenReleases(releases, marks).map((r) => [r.id, r.title, r.artist]),
    [["a", "Titre a", "Polyphia"], ["b", "Titre b", "Polyphia"]],
  );
  assert.deepEqual(releasesShown(releases, marks, "todo", new Map([["a", releases[0]]])).map((r) => r.id), ["c", "a"]);
  marks = toggleHiddenRelease(marks, { id: "a" }, NOW); // « Réafficher » en bas de page
  assert.deepEqual(ids("todo"), ["a", "c"]);
  assert.deepEqual(hiddenReleases([], marks), []); // sortie de la fenêtre : plus listée
});

test("compte masqué avant le 26/10 : retiré des onglets sauf des favoris, et réaffichable", () => {
  const label = { id: "a_label", name: "Exode Records" };
  const releases = [
    release({ id: "l1", artists: [label] }),
    release({ id: "l2", artists: [label] }),
    release({ id: "x", artists: [{ id: "a_x", name: "Nora" }, label] }), // label en invité
  ];
  let marks = toggleHidden(emptyMarks(), label, NOW);
  marks = toggleFavorite(marks, releases[1], NOW);
  const ids = (tab) => releasesForTab(releases, marks, tab).map((r) => r.id);
  assert.deepEqual([ids("todo"), ids("fav")], [["x"], ["l2"]]);
  assert.deepEqual(tabCounts(releases, marks), { todo: 1, seen: 0, fav: 1 });
  assert.deepEqual(hiddenAccounts(releases, marks), [{ id: "a_label", name: "Exode Records", releases: 2 }]);
  marks = toggleHidden(marks, label, NOW);
  assert.deepEqual(ids("todo"), ["l1", "x"]);
  const old = parseMarks('{"version": 1, "seen": {"a": "2026-10-01"}, "fav": {}}');
  assert.deepEqual(old.hidden, {}); // marques enregistrées avant le masquage
});

test("heure locale → instant, de part et d'autre du passage à l'heure d'hiver", () => {
  assert.equal(new Date(zonedInstant("2026-10-24", "06:17", "Europe/Paris")).toISOString(), "2026-10-24T04:17:00.000Z");
  assert.equal(new Date(zonedInstant("2026-10-25", "06:17", "Europe/Paris")).toISOString(), "2026-10-25T05:17:00.000Z");
});

test("bouton de lancement : seulement pour une source en retard", () => {
  const data = (sources) => ({ timezone: "Europe/Paris", schedule: { time: "06:17", grace_minutes: 45 }, sources });
  const at = (iso) => new Date(iso);
  const ranYesterday = {
    spotify: { last_attempt_at: "2026-10-24T09:48:00Z", next_check_at: "2026-10-25T09:58:00Z" },
    soundcloud: { last_attempt_at: "2026-10-24T09:48:00Z", next_check_at: null },
  };
  // 6 h 40 : on laisse encore sa chance au cron (prévu à 6 h 17, 45 min de marge).
  assert.deepEqual(lateSources(data(ranYesterday), at("2026-10-25T05:40:00Z")), []);
  // 8 h 30 : pas de run aujourd'hui ; SoundCloud est en retard, Spotify attend son quota (10 h 58).
  assert.deepEqual(lateSources(data(ranYesterday), at("2026-10-25T07:30:00Z")), ["soundcloud"]);
  // 11 h 30 : le quota Spotify est revenu et personne ne l'a utilisé.
  assert.deepEqual(lateSources(data(ranYesterday), at("2026-10-25T10:30:00Z")), ["spotify", "soundcloud"]);
  // Le run est passé à 10 h 59 : plus rien n'est en retard.
  const ranToday = {
    spotify: { last_attempt_at: "2026-10-25T09:59:00Z", next_check_at: "2026-10-26T10:09:00Z" },
    soundcloud: { last_attempt_at: "2026-10-25T09:59:00Z", next_check_at: null },
  };
  assert.deepEqual(lateSources(data(ranToday), at("2026-10-25T10:30:00Z")), []);
  assert.deepEqual(lateSources({ ...data(ranYesterday), schedule: null }, at("2026-10-25T10:30:00Z")), []);
});

test("marques : lecture tolérante, fusion de sorties et import", () => {
  assert.deepEqual(parseMarks("{abîmé"), emptyMarks());
  assert.deepEqual(parseMarks(null), emptyMarks());
  assert.deepEqual(parseMarks('{"version": 2, "seen": {}, "fav": {}}'), emptyMarks());
  const marks = toggleHiddenRelease(toggleSeen(emptyMarks(), "r_ancien", NOW), release({ id: "r_ancien" }), NOW);
  const migrated = migrateMarks(marks, { r_ancien: "r_nouveau" });
  assert.deepEqual([Object.keys(migrated.seen), Object.keys(migrated.hiddenReleases)], [["r_nouveau"], ["r_nouveau"]]);
  const merged = mergeMarks(toggleSeen(emptyMarks(), "a", NOW), toggleHiddenRelease(emptyMarks(), release({ id: "b" }), NOW));
  assert.deepEqual([Object.keys(merged.seen), Object.keys(merged.hiddenReleases)], [["a"], ["b"]]);
  assert.deepEqual(parseMarks('{"version": 1, "seen": {}, "fav": {}, "hidden": {}}').hiddenReleases, {}); // avant le 26/10
});

test("bannières : données périmées et source en difficulté", () => {
  const data = {
    generated_at: "2026-10-20T04:00:00Z",
    rules: RULES,
    sources: {
      spotify: { status: "auth_expired", message: "ré-autorise", last_success_at: "2026-10-20T04:00:00Z" },
      soundcloud: { status: "ok", message: null, last_success_at: "2026-10-19T04:00:00Z" },
    },
  };
  const kinds = notices(data, NOW).map((notice) => [notice.kind, notice.level, notice.platform]);
  assert.deepEqual(kinds, [
    ["stale", "warning", undefined],
    ["source", "error", "spotify"],
    ["source-stale", "warning", "soundcloud"],
  ]);
  const fresh = { ...data, generated_at: "2026-10-22T04:00:00Z", sources: {} };
  assert.deepEqual(notices(fresh, NOW), []);
});

test("lecteurs intégrés : adresses reconnues, le reste refusé", () => {
  assert.equal(embedUrl("spotify", "https://open.spotify.com/album/7LC9ePeF5sz"), "https://open.spotify.com/embed/album/7LC9ePeF5sz");
  assert.equal(embedUrl("spotify", "https://open.spotify.com/track/abc123"), "https://open.spotify.com/embed/track/abc123");
  const sc = new URL(embedUrl("soundcloud", "https://soundcloud.com/nora/sets/echos"));
  assert.equal(sc.origin + sc.pathname, "https://w.soundcloud.com/player/");
  assert.equal(sc.searchParams.get("url"), "https://soundcloud.com/nora/sets/echos");
  assert.equal(sc.searchParams.get("auto_play"), "true");
  const yt = new URL(embedUrl("youtube", "https://www.youtube.com/watch?v=4HjkTBd4bIE", "https://fragzel.github.io"));
  assert.equal(yt.origin + yt.pathname, "https://www.youtube-nocookie.com/embed/4HjkTBd4bIE");
  assert.equal(yt.searchParams.get("enablejsapi"), "1"); // pilotable par messages…
  assert.equal(yt.searchParams.get("origin"), "https://fragzel.github.io"); // … depuis cette page
  assert.equal(yt.searchParams.get("controls"), "0"); // les commandes sont celles de la page
  for (const [platform, url] of [
    ["spotify", "https://evil.test/album/x"],
    ["soundcloud", "http://soundcloud.com/nora/nuit"], // pas en https
    ["youtube", "https://www.youtube.com/watch?v=\"><script>"],
    ["youtube", "pas une adresse"],
  ]) {
    assert.equal(embedUrl(platform, url), null, url);
  }
});

test("lecture : la plateforme des titres d'abord, sinon les morceaux entiers sans compte", () => {
  const links = [
    { platform: "spotify", url: "https://open.spotify.com/album/e1" },
    { platform: "soundcloud", url: "https://soundcloud.com/nora/sets/echos" },
    { platform: "youtube", url: "https://www.youtube.com/watch?v=4HjkTBd4bIE" },
  ];
  const single = release({ links });
  assert.deepEqual(playableLinks(single).map((link) => link.platform), ["soundcloud", "youtube", "spotify"]);
  const tracklist = [
    { platform: "spotify", title: "Un", url: "https://open.spotify.com/track/t1", duration_ms: 185_000 },
    { platform: "spotify", title: "Deux", url: "https://open.spotify.com/track/t2", duration_ms: 61_400 },
  ];
  const ep = release({ type: "ep", tracks: 2, links, tracklist });
  assert.equal(playableLinks(ep)[0].platform, "spotify");
  assert.equal(hasTracks(ep), true);
  assert.equal(hasTracks(single), false);
  assert.deepEqual(playerSource(ep, { platform: "soundcloud", track: null }), {
    platform: "soundcloud",
    url: "https://soundcloud.com/nora/sets/echos",
    src: embedUrl("soundcloud", "https://soundcloud.com/nora/sets/echos"),
  });
  assert.deepEqual(playerSource(ep, { platform: "soundcloud", track: 1 }), {
    platform: "spotify",
    url: "https://open.spotify.com/track/t2",
    src: "https://open.spotify.com/embed/track/t2",
  });
  const unplayable = release({ links: [{ platform: "spotify", url: "https://evil.test/x" }] });
  assert.equal(playerSource(unplayable, { platform: null, track: null }), null);
  assert.deepEqual([formatDuration(185_000), formatDuration(61_400), formatDuration(null)], ["3:05", "1:01", ""]);
});

test("extrait Spotify : 30 s, ou plus court que le titre quand on connaît sa durée", () => {
  const state = (platform, duration) => ({ platform, duration });
  assert.equal(isSpotifyPreview(state("spotify", 30)), true);
  assert.equal(isSpotifyPreview(state("spotify", 21.9)), true);
  assert.equal(isSpotifyPreview(state("spotify", 214)), false);
  assert.equal(isSpotifyPreview(state("spotify", 0)), false); // durée pas encore connue
  assert.equal(isSpotifyPreview(state("soundcloud", 30)), false);
  assert.equal(isSpotifyPreview(state("spotify", 25), { duration_ms: 26_000 }), false); // titre court
  assert.equal(isSpotifyPreview(state("spotify", 30), { duration_ms: 185_000 }), true);
});

test("cause d'un extrait Spotify d'après le navigateur", () => {
  const ua = {
    chrome: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    edge: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
    firefox: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:144.0) Gecko/20100101 Firefox/144.0",
    safari: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Safari/605.1.15",
    iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1",
    android: "Mozilla/5.0 (Linux; Android 16; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
    firefoxAndroid: "Mozilla/5.0 (Android 16; Mobile; rv:144.0) Gecko/144.0 Firefox/144.0",
  };
  assert.equal(spotifyPreviewCause(ua.chrome), "cookies");
  assert.equal(spotifyPreviewCause(ua.edge), "cookies");
  assert.equal(spotifyPreviewCause(ua.firefox), "firefox");
  assert.equal(spotifyPreviewCause(ua.safari), "safari");
  assert.equal(spotifyPreviewCause(ua.iphone), "mobile");
  assert.equal(spotifyPreviewCause(ua.android), "mobile");
  assert.equal(spotifyPreviewCause(ua.firefoxAndroid), "mobile");
  assert.equal(spotifyPreviewCause(), "cookies");
});

// --- Titres favoris et liste de lecture ------------------------------------------------------------

const TRACKS = [
  { platform: "spotify", title: "Marée basse", url: "https://open.spotify.com/track/t1", duration_ms: 214_000 },
  { platform: "spotify", title: "Ressac", url: "https://open.spotify.com/track/t2", duration_ms: 187_000 },
];
const ep = release({
  id: "ep",
  title: "Basse saison",
  type: "ep",
  tracks: 2,
  tracklist: TRACKS,
  links: [{ platform: "spotify", url: "https://open.spotify.com/album/e1" }],
});
const single = release({ id: "s", links: [{ platform: "soundcloud", url: "https://soundcloud.com/nora/nuit" }] });
const keys = (marks) => marks.playlist.map((entry) => entry.key);

test("titre favori : sa propre carte dans « Favoris », l'EP reste à découvrir", () => {
  const marks = toggleFavoriteTrack(emptyMarks(), ep, TRACKS[1], NOW);
  assert.deepEqual(releasesForTab([ep], marks, "todo").map((r) => r.id), ["ep"]);
  const [card] = releasesForTab([ep], marks, "fav");
  assert.equal(card.id, trackId(TRACKS[1].url));
  assert.deepEqual([card.type, card.title, card.album.title, card.archived], ["track", "Ressac", "Basse saison", undefined]);
  assert.equal(card.album.tracklist, undefined); // la copie de l'EP ne garde pas ses titres
  assert.equal(hasTracks(card), false);
  assert.equal(playerSource(card, { platform: null, track: null }).src, "https://open.spotify.com/embed/track/t2");
  assert.deepEqual(tabCounts([ep], marks), { todo: 1, seen: 0, fav: 1 });
  assert.equal(matches(card, { ...noFilter, query: "basse saison" }, () => false), true); // par son EP
  assert.equal(releasesForTab([], marks, "fav")[0].archived, true); // EP sorti de la fenêtre
  // Retiré des favoris, il garde sa place jusqu'au prochain onglet.
  const removed = toggleFavoriteTrack(marks, ep, TRACKS[1], NOW);
  assert.deepEqual(removed.favTracks, {});
  assert.deepEqual(releasesShown([ep], removed, "fav", new Map([[card.id, card]])).map((r) => r.id), [card.id]);
});

test("carte d'un titre : identifiant court, stable, propre à chaque adresse", () => {
  assert.match(trackId(TRACKS[0].url), /^t_[0-9a-z]+$/);
  assert.equal(trackId(TRACKS[0].url), trackId(`${TRACKS[0].url}`));
  assert.notEqual(trackId(TRACKS[0].url), trackId(TRACKS[1].url));
});

test("liste de lecture : un titre, tous ceux d'un EP, ou la sortie entière", () => {
  const [t1, t2] = TRACKS.map((track) => track.url);
  let marks = togglePlaylist(emptyMarks(), playlistEntries(ep), NOW);
  assert.deepEqual(keys(marks), [t1, t2]);
  assert.equal(inPlaylist(marks, playlistEntries(ep, TRACKS[0])), true);
  marks = togglePlaylist(marks, playlistEntries(single), NOW);
  assert.deepEqual(keys(marks), [t1, t2, "release:s"]);
  marks = togglePlaylist(marks, playlistEntries(ep, TRACKS[1]), NOW); // déjà là : retiré
  assert.deepEqual(keys(marks), [t1, "release:s"]);
  marks = togglePlaylist(marks, playlistEntries(ep), NOW); // seul le titre manquant revient, à la fin
  assert.deepEqual(keys(marks), [t1, "release:s", t2]);
  assert.equal(inPlaylist(marks, []), false);
  marks = movePlaylistEntry(marks, 2, -1);
  assert.deepEqual(keys(marks), [t1, t2, "release:s"]);
  assert.equal(movePlaylistEntry(marks, 0, -1), marks); // déjà en tête
  assert.equal(movePlaylistEntry(marks, 2, 1), marks); // déjà en bas
  marks = removePlaylistEntry(marks, 0);
  assert.deepEqual(keys(marks), [t2, "release:s"]);
  // Ce que joue le lecteur : la carte du titre, ou la sortie (sa copie si elle a quitté la fenêtre).
  const current = new Map([[ep.id, ep]]);
  assert.deepEqual([entryRelease(marks.playlist[0], current).id, entryRelease(marks.playlist[0], current).archived], [trackId(t2), undefined]);
  assert.deepEqual([entryRelease(marks.playlist[1], current).id, entryRelease(marks.playlist[1], current).archived], ["s", true]);
  // La carte d'un titre favori donne son titre, rattaché à son EP.
  const [card] = releasesForTab([ep], toggleFavoriteTrack(emptyMarks(), ep, TRACKS[0], NOW), "fav");
  assert.deepEqual(playlistEntries(card).map((entry) => [entry.key, entry.release.id]), [[t1, "ep"]]);
});

test("marques : titres favoris et liste de lecture, lus, fusionnés et suivis", () => {
  const before = parseMarks('{"version": 1, "seen": {}, "fav": {}, "hidden": {}, "hiddenReleases": {}}');
  assert.deepEqual([before.favTracks, before.playlist], [{}, []]); // marques d'avant le 28/10
  let marks = toggleFavoriteTrack(emptyMarks(), ep, TRACKS[1], NOW);
  marks = togglePlaylist(marks, [...playlistEntries(ep), ...playlistEntries(single)], NOW);
  assert.deepEqual(parseMarks(JSON.stringify(marks)), marks);
  const broken = parseMarks(
    JSON.stringify({
      version: 1,
      seen: {},
      fav: {},
      favTracks: { "https://autre": { track: TRACKS[0], release: ep }, [TRACKS[1].url]: { track: TRACKS[1] } },
      playlist: [null, { key: "k" }, { key: "k2", track: "texte", release: single }, marks.playlist[0], marks.playlist[0]],
    }),
  );
  assert.deepEqual([broken.favTracks, keys(broken)], [{}, [TRACKS[0].url]]);
  const merged = mergeMarks(togglePlaylist(emptyMarks(), playlistEntries(single), NOW), marks);
  assert.deepEqual(keys(merged), ["release:s", TRACKS[0].url, TRACKS[1].url]);
  assert.deepEqual(Object.keys(merged.favTracks), [TRACKS[1].url]);
  const migrated = migrateMarks(marks, { ep: "ep2", s: "s2" });
  assert.equal(migrated.favTracks[TRACKS[1].url].release.id, "ep2");
  assert.deepEqual(keys(migrated), [TRACKS[0].url, TRACKS[1].url, "release:s2"]);
  assert.deepEqual(migrated.playlist.map((entry) => entry.release.id), ["ep2", "ep2", "s2"]);
});
