import assert from "node:assert/strict";
import test from "node:test";

import {
  fold,
  formatHash,
  groupByWeek,
  isNew,
  localDay,
  matches,
  notices,
  parseHash,
  releaseWeek,
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
const noFilter = { query: "", platforms: null, types: null, newOnly: false };

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
});

test("filtres ⇄ hash d'URL", () => {
  const filters = { query: "nuit blanche", platforms: new Set(["spotify"]), types: new Set(["single", "ep"]), newOnly: true };
  const back = parseHash(formatHash(filters));
  assert.deepEqual({ ...back, platforms: [...back.platforms], types: [...back.types] }, {
    query: "nuit blanche",
    platforms: ["spotify"],
    types: ["ep", "single"],
    newOnly: true,
  });
  assert.equal(formatHash(noFilter), "");
  assert.deepEqual(parseHash(""), noFilter);
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
