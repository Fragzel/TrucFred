import assert from "node:assert/strict";
import test from "node:test";

import {
  ALL_ELECTRO,
  NO_STYLE,
  embedUrl,
  emptyMarks,
  fold,
  formatDuration,
  formatHash,
  groupByWeek,
  hasTracks,
  hiddenAccounts,
  hiddenReleases,
  isNew,
  lateSources,
  localDay,
  matches,
  mergeMarks,
  migrateMarks,
  notices,
  parseHash,
  parseMarks,
  playableLinks,
  playerSource,
  releaseWeek,
  releasesForTab,
  releasesShown,
  styleCounts,
  tabCounts,
  tabOf,
  toggleFavorite,
  toggleHidden,
  toggleHiddenRelease,
  toggleSeen,
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
  assert.deepEqual(releasesShown(releases, marks, "todo", new Set(["a"])).map((r) => r.id), ["c", "a"]);
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
