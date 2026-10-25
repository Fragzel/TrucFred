import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { deriveKey, isSealed, normalize, unseal } from "../../site/vault.js";

// Chiffré par src/newrel/protect.py (mot de passe « écho-pqam-tvhe », 1 000 itérations) :
// le même fichier est ouvert par tests/test_protect.py.
const SEALED = JSON.parse(readFileSync(new URL("../fixtures/sealed.json", import.meta.url), "utf-8"));

test("un fichier chiffré par Python s'ouvre dans le navigateur", async () => {
  assert.ok(isSealed(SEALED));
  // Saisie décomposée (e + accent) et espaces autour : même clé qu'en Python.
  const key = await deriveKey("  écho-pqam-tvhe ", SEALED.kdf);
  assert.deepEqual(await unseal(SEALED, key), { généré: "par Python", releases: [] });
});

test("mauvais mot de passe refusé", async () => {
  const key = await deriveKey("echo-pqam-tvhe", SEALED.kdf);
  await assert.rejects(unseal(SEALED, key));
});

test("données en clair reconnues comme telles", () => {
  assert.equal(isSealed({ schema_version: 1, releases: [] }), false);
  assert.equal(isSealed(null), false);
  assert.equal(normalize(" a "), "a");
});
