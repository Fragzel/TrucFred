// Déchiffrement de releases.json quand la page est protégée (voir src/newrel/protect.py).
// WebCrypto seul : clé dérivée du mot de passe (PBKDF2-SHA256), puis AES-256-GCM.
// Aucune dépendance au DOM : testé avec `node --test tests/js/vault.test.js`.

export const FORMAT = "newrel-aes-gcm/1";

export function isSealed(data) {
  return data?.format === FORMAT && typeof data.kdf?.salt === "string";
}

const bytes = (base64) => Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));

/** Même forme que le serveur : espaces de bord retirés, Unicode NFC. */
export function normalize(password) {
  return String(password ?? "").trim().normalize("NFC");
}

/** Clé AES non exportable : elle peut être mémorisée (IndexedDB) sans pouvoir être relue. */
export async function deriveKey(password, kdf) {
  const material = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(normalize(password)),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt: bytes(kdf.salt), iterations: kdf.iterations },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"],
  );
}

/** Données déchiffrées ; rejette si la clé ne convient pas (mot de passe erroné ou changé). */
export async function unseal(envelope, key) {
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes(envelope.iv) }, key, bytes(envelope.ciphertext));
  return JSON.parse(new TextDecoder().decode(plain));
}
