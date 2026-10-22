# Plan : agrégateur de nouvelles sorties musicales

> Plan rédigé le 22 octobre 2026 · Statut : étapes 0 et 1 codées, mise en route Spotify à faire (voir le README) · Package Python : `newrel`

## 0. Décisions prises (21 et 22/10/2026)

| Sujet | Décision |
|---|---|
| Plateformes | **Spotify + SoundCloud**. YouTube Music est retiré, puisque tu ne l'utilises pas ; son analyse reste au §1.2 au cas où. |
| Abonnements payants | Spotify Premium ✔ (obligatoire pour l'API en Development Mode) · SoundCloud Artist Pro ✔ (obligatoire pour l'API) |
| Visibilité | Repo **public**, données **en clair**. Le site est en `noindex` mais reste accessible à qui a l'URL. |
| Fréquence | **1 run par jour** (vers 6 h 17, heure de Paris), plus un déclenchement manuel |
| Historique affiché | **90 jours** glissants |
| Contenus | Albums, EP, singles et nouveaux sons **publiés par les artistes eux-mêmes** : pas de featurings, de compilations ni de reposts |
| Emplacement | Le dépôt reste dans OneDrive. Parade : uv copie les paquets dans `.venv` (`link-mode = "copy"`) au lieu de créer des liens durs vers son cache. |
| Noms | Dépôt public `Fragzel/TrucFred`, site <https://fragzel.github.io/TrucFred/>, package et commande `newrel` |

## 1. Faisabilité par plateforme

### 1.1 Spotify : ✅ faisable (API officielle, sous conditions 2026)

Conditions actuelles du Development Mode :
- Le **propriétaire de l'app doit avoir Premium**. Si l'abonnement s'arrête, l'app cesse de fonctionner jusqu'au réabonnement.
- **5 utilisateurs autorisés** au maximum par app (allowlist dans le dashboard). C'est suffisant pour un usage solo.
- Jusqu'à 25 Client IDs par développeur depuis juillet 2026.
- **Les quotas sont comptés par compte développeur** : toutes tes apps et tes runs locaux puisent dans le même seau. Un 429 peut porter `reason: "QUOTA_EXCEEDED"`.
- Rate limit : fenêtre glissante de 30 s, dont la valeur n'est pas publiée (plus basse qu'en Extended Quota). Il faut respecter l'en-tête `Retry-After`.
- Extended Quota Mode : réservé depuis le 15/05/2025 aux organisations (entreprise enregistrée, ≥ 250 k utilisateurs actifs mensuels). C'est hors de portée : on reste en Development Mode.

Endpoints nécessaires, dans l'état qui suit les changements de février 2026 (appliqués aux nouvelles apps depuis le 11/02/2026) :

| Endpoint | Statut | Détails utiles |
|---|---|---|
| `GET /me/following?type=artist` | ✅ disponible | scope `user-follow-read`, pagination par curseur `after`, `limit` ≤ 50 |
| `GET /artists/{id}/albums` | ✅ disponible | `include_groups` (album, single, appears_on, compilation), **`limit` 5 par défaut, 10 au maximum**, `offset`, `market` (sans token utilisateur ni `market`, le contenu est considéré comme indisponible) ; ordre des résultats non documenté |
| `GET /albums/{id}` | ✅ disponible | inutile pour le MVP |
| `GET /albums?ids=`, `GET /artists?ids=` | ❌ supprimés | plus d'appels groupés |
| `GET /browse/new-releases`, `GET /artists/{id}/top-tracks` | ❌ supprimés | pas de raccourci « nouveautés » |
| Champs `album_group`, `label`, `popularity`, `artist.followers` | ❌ supprimés | sans `album_group`, on ne sait plus de quel groupe vient un item quand on en demande plusieurs à la fois ; `external_ids` a été rétabli en mars 2026 |

Pour chaque album, l'API renvoie :
- `album_type` : `album`, `single` ou `compilation`. **Les EP sont classés en `single`.**
- `total_tracks`.
- `release_date`, avec `release_date_precision` : `year`, `month` ou `day`.
- `images`, `external_urls`, `artists`.

Authentification :
- **Le refresh token dure 6 mois au maximum** à partir de l'autorisation initiale. La règle s'applique aux nouvelles apps depuis le 18/06/2026 et aux apps existantes depuis le 20/07/2026.
  - Rafraîchir l'access token ne prolonge pas ce délai.
  - Une fois expiré, le token renvoie `400 invalid_grant` : il faut se ré-autoriser à la main.
  - Spotify n'expose pas la date d'émission, il faut donc la stocker soi-même.
  - Le flux Client Credentials n'est pas concerné.
- **PKCE** : d'après la communauté Spotify (ce n'est pas confirmé par la doc officielle), le refresh token est à usage unique et change à chaque rafraîchissement. Le workflow devrait alors réécrire le secret GitHub à chaque run.
- Redirect URI : `localhost` est interdit. On utilise `http://127.0.0.1:8888/callback` (le HTTP n'est permis que pour les IP loopback).

Règles d'usage (Developer Policy) :
- III.5 : *« Do not create any product or service which is integrated with streams or content from another service. »* C'est exactement ce que fait un agrégateur. Le risque est faible pour un usage perso en Development Mode, mais il existe (révocation du Client ID). Voir le §3.5.
- II.4 : le contenu doit être attribué à Spotify, et les pochettes comme les métadonnées doivent renvoyer vers l'élément Spotify.

**Méthode retenue** :
- **Authorization Code avec client secret**, et non PKCE. Le secret vit dans GitHub Secrets, et le refresh token reste réutilisable pendant ses 6 mois.
- Le token utilisateur sert **uniquement** pour `GET /me/following`.
- Le catalogue passe par **Client Credentials** + `market`, avec `GET /artists/{id}/albums` appelé une fois par groupe (`album`, puis `single`).
- Avantage : si le token utilisateur expire, seuls les nouveaux abonnements cessent d'être détectés. Les sorties des artistes déjà connus continuent d'arriver.

### 1.2 YouTube Music : ⚠️ à contourner, donc **hors périmètre**

YouTube Music n'a pas d'API officielle. Voici le comparatif des trois voies, conservé pour référence :

| Option | Ce qu'on obtient | Auth et quotas | Risques |
|---|---|---|---|
| (a) YouTube Data API v3 | Les abonnements (`subscriptions.list mine=true`) et les vidéos des chaînes (playlist « uploads »), mais **pas** les albums ni les singles YTM | OAuth `youtube.readonly`, un scope sensible : écran « app non vérifiée » et plafond de 100 utilisateurs à vie. En statut « Testing », **le refresh token expire au bout de 7 jours** : il faut passer en « In production ». 10 000 unités par jour, 1 unité par appel `subscriptions`, `channels` ou `playlistItems` | Conforme. Beaucoup de bruit (clips, Shorts, vlogs). Règle III.E.4 : les données stockées doivent être rafraîchies ou supprimées tous les 30 jours |
| (b) `ytmusicapi` 1.12.3 (16/09/2026, Python ≥ 3.10) | Les vrais albums et singles de chaque artiste (`get_artist`), mais **avec l'année seulement** ; les abonnements YTM (`get_library_subscriptions`, authentifié) | Pas d'auth pour les données publiques. OAuth : depuis novembre 2024, il faut son propre client Google de type « TVs and Limited Input devices ». Cookies navigateur valables environ 2 ans | API non documentée, donc contraire aux règles YouTube (III.D.7, III.E.6). Elle casse à chaque changement du client web (correctifs de parsing en 2025-2026). Les IP des runners peuvent être bloquées. Mettre les cookies du compte dans le CI fait courir un risque au compte |
| (c) Flux RSS de chaîne (`/feeds/videos.xml?channel_id=UC…`) | Les 15 dernières vidéos environ | Aucune auth, aucun quota | 404 intermittents signalés depuis décembre 2025 (source tierce). Des vidéos uniquement |

Verdict : j'aurais retenu un hybride, avec (a) pour les abonnements et (b) sans compte pour les sorties. **Écarté**, puisque tu n'utilises pas YouTube Music. Comme les sources sont isolées dans l'architecture, on pourra l'ajouter plus tard sans refonte.

### 1.3 SoundCloud : ✅ faisable avec Artist Pro (API officielle)

- **L'enregistrement d'apps a rouvert en libre-service en mai 2026, mais uniquement pour les abonnés Artist Pro.** Le prix tourne autour de 99 $ par an d'après la presse (à vérifier). L'app se crée sur la page « Your Apps » ou avec le CLI officiel `sc-api-auth.mjs` (Node ≥ 18).
- OAuth 2.1 :
  - Authorization Code, avec **PKCE obligatoire** ; l'access token dure environ 1 h et **le refresh token est à usage unique**.
  - Client Credentials pour les ressources publiques, avec un plafond de 50 tokens par 12 h et par app, et de 30 par heure et par IP.
- Endpoints utiles :
  - publics : `GET /users/{urn}/followings` (200 au maximum par page), `GET /users/{urn}/tracks` (`sort=desc`), `GET /users/{urn}/playlists` (champ `playlist_type`), `GET /resolve` ;
  - côté utilisateur : `GET /me/followings`, `GET /me/followings/tracks`, `GET /me/feed`.
- Champs : `created_at`, `release_year`, `release_month` et `release_day`, `artwork_url`, `permalink_url`. Les identifiants sont au format URN (`soundcloud:users:123`).
- Rate limit : environ 100 requêtes par minute et par app, avec `429` et `Retry-After`.
- Conditions d'utilisation de l'API :
  - créditer l'uploader **et** SoundCloud, avec un lien visible vers chaque son ;
  - **pas de stockage persistant** du contenu (métadonnées comprises) au-delà d'un cache de session ;
  - pas de scraping ;
  - pas d'expérience de lecture qui mélange d'autres services.
- Alternatives sans Artist Pro, non retenues :
  - le flux RSS `feeds.soundcloud.com/users/soundcloud:users:{id}/sounds.rss`, qui dépend du réglage « Include in RSS feed » de chaque créateur (état en 2026 non vérifié) ;
  - une liste manuelle des comptes suivis ;
  - l'API interne `api-v2`, avec un `client_id` récupéré sur le site : contraire aux conditions d'utilisation et fragile.

**Méthode retenue** : **Client Credentials uniquement**. Comme il n'y a aucun token utilisateur, il n'y a pas non plus de refresh token à faire tourner.
- `/users/{ton_urn}/followings` donne la liste de tes comptes suivis.
- Pour chacun, on appelle `/users/{urn}/tracks?sort=desc` et `/users/{urn}/playlists`.
- **À valider au début de l'étape 2** : que ces endpoints acceptent bien un token Client Credentials. Sinon, on se replie sur OAuth + PKCE, et le workflow réécrit le refresh token à chaque run (`gh secret set` avec un PAT de portée limitée).

### 1.4 Récapitulatif

| Plateforme | Verdict | Méthode | Coût |
|---|---|---|---|
| Spotify | Faisable | API officielle : Authorization Code pour les abonnements, Client Credentials pour le catalogue | Premium |
| SoundCloud | Faisable | API officielle : Client Credentials | Artist Pro |
| YouTube Music | À contourner | hors périmètre | — |

## 2. Architecture proposée

### 2.1 Ce que je garde et ce que je change dans ton idée de départ

**Gardé** : le script Python lancé par un cron GitHub Actions, la normalisation vers un JSON commun, le site statique sur GitHub Pages, les secrets dans GitHub Secrets et la déduplication entre plateformes.

**Changé** :
1. **Pas de commit quotidien sur `main`.** L'état vit sur une branche orpheline `data`, réécrite à chaque run (un seul commit, `push --force`). Trois raisons :
   - pas de bruit ni de conflit avec tes propres push ;
   - les métadonnées SoundCloud ne s'accumulent pas dans l'historique git, ce que les conditions d'utilisation interdisent ;
   - l'état reste lisible et réparable à la main.
2. **Deux fichiers au lieu d'un** :
   - `releases.json`, le contrat public lu par le site ;
   - `state.json`, la mémoire interne : `first_seen`, identifiants connus, statut de chaque source.
3. **Spotify sans PKCE**, avec le catalogue en Client Credentials (voir le §1.1).
4. **Des pannes isolées par source.** Une plateforme en panne garde ses dernières données au lieu de vider la page, et le run passe au rouge pour te prévenir.
5. **Pas de framework front** : du HTML et du JavaScript natif (modules ES), sans étape de build.

### 2.2 Vue d'ensemble

```
      cron 06:17 Europe/Paris · workflow_dispatch · push sur site/**
                                     │
┌─ job build (contents: read) ───────┴─────────────────────────────────────┐
│ 1. lit state.json sur la branche data (absent ⇒ démarrage à zéro)        │
│ 2. Spotify : refresh token → /me/following                               │
│              Client Credentials → /artists/{id}/albums (album, single)   │
│ 3. SoundCloud : Client Credentials → followings, tracks, playlists       │
│ 4. normalise → dédoublonne → first_seen / baseline → élague à 90 jours   │
│ 5. écrit releases.json + state.json, assemble _site/                     │
└──────────────┬──────────────────────────────────────────┬────────────────┘
               │ artefact « state »                       │ artefact Pages
   job persist (contents: write)         job deploy (pages, id-token: write)
   force-push → branche data              → https://<toi>.github.io/<repo>/
               └────────────────────┬─────────────────────┘
                                    │
               job verdict (if: always(), actions: write)
             keepalive du cron · rouge si une source est KO
```

Le job qui exécute les dépendances Python n'a aucun droit d'écriture sur le repo. Seul `persist`, qui n'exécute que git, peut écrire.

### 2.3 Collecte

Chaque source a son propre débit. Elles sont collectées l'une après l'autre : Spotify, limité par son quota, prend moins d'une minute, ce qui rend le parallélisme inutile pour l'instant.

**Spotify** : un budget de 90 appels catalogue par run (révision du 22/10/2026).
- Quota mesuré au premier run réel : `QUOTA_EXCEEDED` après 100 appels catalogue, avec `Retry-After : 86111 s`. Le Development Mode autorise donc environ **100 appels catalogue par 24 h**, partagés par toutes les apps du compte développeur.
  - Les abonnements (`/me/following`) dépendent d'un autre paquet et restent lisibles.
  - L'appel refusé n'a pas prolongé le blocage.
- Abonnements : `/me/following` avec `limit=50`, soit environ 6 appels.
- Ordre de passage :
  - d'abord les artistes jamais vérifiés ;
  - puis les plus en retard sur leur rythme : 2 jours pour un artiste actif (une sortie dans l'année), 7 jours pour un artiste en sommeil.
- Par artiste déjà connu : un appel `include_groups=album,single&limit=1`, qui sert seulement à lire le `total`.
  - Si le total n'a pas augmenté, rien de neuf : l'artiste n'a coûté qu'un appel.
  - Sinon, ou au moins une fois par mois, on fait la lecture détaillée ci-dessous.
- Lecture détaillée (premier passage, total en hausse, relecture mensuelle) : un appel `include_groups=album`, puis un appel `include_groups=single`, avec `limit=10` et `market` (réglé dans la config).
  - Deux appels séparés, car un appel combiné peut repousser les singles récents hors de la première page, et il ne dit plus de quel groupe vient chaque item.
- En régime de croisière, environ 85 artistes sont vérifiés par jour, donc chacun au moins tous les 3 jours. La montée en charge prend 4 à 5 jours, car chaque artiste jamais vérifié coûte 2 appels.
- Sur `QUOTA_EXCEEDED`, l'heure de reprise indiquée par `Retry-After` est mémorisée dans l'état, et aucun appel catalogue n'est tenté avant cette heure.
- Page suivante seulement si tous les items de la page sont inconnus et que le plus ancien entre dans la fenêtre de 90 jours, avec 5 pages au maximum.
- Garde-fou sur l'ordre, qui n'est pas documenté : on vérifie que `release_date` décroît. Sinon, on pagine jusqu'au plafond et on lève un avertissement.
- EP déduit : un `single` avec `total_tracks ≥ 4` devient un `ep`, avec `type_inferred: true`.
- Débit :
  - requêtes séquentielles à environ 2 par seconde, soit environ 5 min ;
  - `Retry-After` respecté jusqu'à 120 s ;
  - au-delà, ou sur `QUOTA_EXCEEDED`, arrêt propre en conservant les résultats partiels (les artistes restants passent en tête au run suivant) ;
  - budget de 15 min, en traitant d'abord les artistes vérifiés le moins récemment.

**SoundCloud** (environ 600 appels pour 300 comptes, soit environ 7 min à 100 requêtes par minute) :
- Un seul token Client Credentials par run.
- `/users/{ton_urn}/followings`, en suivant la pagination `next_href`, moins les comptes exclus dans `config.toml`.
- Pour chaque compte :
  - `/users/{urn}/tracks?sort=desc&limit=20` donne des items de type `track` (« son ») ;
  - `/users/{urn}/playlists` donne des `album`, `ep` ou `single` selon `playlist_type`. Les valeurs exactes restent à confirmer, et les playlists ordinaires sont ignorées.
- Les sons qui appartiennent à un album ou un EP nouvellement détecté sont rattachés à la carte de cet album.
- Date : `created_at`, convertie en date à l'heure de Paris. Les champs `release_*` servent seulement au rapprochement entre plateformes.

### 2.4 Modèle de données

`releases.json` (public, lu par le site). Le contrat exact est `schema/releases.schema.json`, généré depuis `src/newrel/models.py` :

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-24T04:21:07Z",
  "timezone": "Europe/Paris",
  "window_days": 90,
  "rules": {"new_days": 7, "new_max_age_days": 14, "stale_hours": 36},
  "sources": {
    "spotify": {"status": "ok", "message": null, "last_success_at": "2026-10-24T04:21:07Z", "followed": 148}
  },
  "aliases": {"r_3be0c19d27": "r_9f2c1a5e04"},
  "releases": [{
    "id": "r_9f2c1a5e04",
    "title": "Titre (Deluxe Edition)",
    "edition": "Deluxe Edition",
    "type": "album",
    "type_inferred": false,
    "artists": [{"id": "a_7d1e0b3c55", "name": "Artiste"}],
    "date": "2026-10-24",
    "precision": "day",
    "sort_date": "2026-10-24",
    "first_seen": "2026-10-24T04:21:07Z",
    "backfill": false,
    "tracks": 14,
    "cover": {"url": "https://i.scdn.co/image/…", "platform": "spotify"},
    "links": [
      {"platform": "spotify", "url": "https://open.spotify.com/album/…", "type": "album", "date": "2026-10-24", "precision": "day"}
    ]
  }]
}
```

`state.json` (interne, sur la branche `data`) :

```json
{
  "schema_version": 1,
  "sources": {
    "spotify": {
      "status": "ok", "message": null, "last_attempt_at": "…", "last_success_at": "…",
      "consecutive_failures": 0,
      "followings": [{"key": "spotify:artist:4Z8W…", "name": "Artiste"}], "followings_at": "…"
    }
  },
  "artists": {"spotify:artist:4Z8W…": {"name": "Artiste", "baseline_at": "…", "last_checked_at": "…"}},
  "links": {
    "spotify:album:5Ir…": {
      "item": {"key": "spotify:album:5Ir…", "title": "…", "type": "album", "date": "2026-10-24", "…": "…"},
      "first_seen": "…", "last_seen": "…", "backfill": false, "via": ["spotify:artist:4Z8W…"]
    }
  }
}
```

Règles :
- **Dates** : `date` est une date ISO partielle (`2026`, `2026-10` ou `2026-10-17`), accompagnée de `precision`.
  - Si la précision est au jour, `sort_date` est cette date.
  - Sinon, `sort_date` est `first_seen` ramené dans la période, ou le début de la période s'il s'agit d'un backfill.
- **Baseline** : la première fois qu'un artiste est vu (premier run ou nouvel abonnement), tout ce qu'on trouve est marqué `backfill: true`.
  - Ces sorties s'affichent à leur date, sans badge « Nouveau » ni notification.
  - Ainsi, le catalogue d'un artiste qu'on vient de suivre ne noie pas la semaine en cours.
- **« Nouveau »** : une sortie qui n'est pas en backfill, avec `first_seen` de moins de 7 jours **et** `sort_date` de moins de 14 jours.
- **Identifiants stables** : `r_` suivi d'une empreinte de la clé du premier lien détecté (par exemple `spotify:album:5Ir…`). Ils restent donc identiques d'un run à l'autre, même après une remise à zéro de l'état.
  - Si deux cartes fusionnent, l'identifiant le plus ancien gagne et l'autre devient un alias (`aliases`).
  - Les marques « écouté » survivent donc aux fusions.
- **Fenêtre et élagage** :
  - la page montre les sorties dont `sort_date` tombe dans les 90 derniers jours ;
  - l'état n'oublie un lien que lorsque toute sa période est sortie de la fenêtre. Sans cela, une sortie datée à l'année reviendrait comme une nouveauté.
- La pochette renvoie vers la plateforme dont elle provient (Spotify II.4).

### 2.5 Déduplication

Artistes :
- Clé de rapprochement : le nom normalisé.
  - Normalisation NFKC, casse repliée, accents retirés.
  - `&`, `+`, `×`, `and` et `et` sont unifiés.
  - On retire « the » en tête, ` - Topic`, `VEVO`, `official`, la ponctuation et les espaces.
- Deux comptes qui ont la même clé ne fusionnent que si au moins une de leurs sorties se correspond. Sinon, ils sont seulement signalés comme candidats dans le journal du run. Cela évite de fusionner des homonymes.
- Le fichier `aliases.toml`, versionné, l'emporte toujours : il force des fusions par identifiant de plateforme et liste les paires à ne jamais fusionner (`never_merge`).

Sorties (comparées seulement entre artistes fusionnés) :
- Titre normalisé : on retire `(feat. …)`, `(prod. …)`, ` - Single`, ` - EP`, `[Free DL]`, le préfixe « Artiste - » (fréquent sur SoundCloud) et la ponctuation.
- Les étiquettes d'édition (deluxe, remaster, live, remix, sped up, instrumental, etc.) vont dans le champ `edition`. Une édition donne une carte séparée ; le lien vers l'originale (`parent`) viendra avec l'étape 2.
- Dates compatibles :
  - deux dates au jour près : écart de 7 jours au plus ;
  - une date au jour et une période : la date tombe dans la période, à 7 jours près.
- Types compatibles :
  - un single, un EP et un son unique peuvent fusionner entre eux ;
  - un album ne fusionne avec une autre sortie que si le nombre de titres est identique, pour ne pas le confondre avec son single titre.
- Au sein de Spotify seul, on fusionne les versions explicit et clean d'une même sortie (même titre, même date, même nombre de titres).
- La carte fusionnée garde :
  - la date de Spotify si elle est précise au jour : un son publié la veille sur SoundCloud ne doit pas faire changer de semaine une sortie du vendredi. Sinon, la plus précise, ou la plus ancienne à précision égale ;
  - le titre et la pochette de Spotify par défaut ;
  - les liens de toutes les plateformes.

### 2.6 Stockage de l'état : la branche `data`

- La branche orpheline `data` contient `state.json` et `releases.json`. Elle est réécrite à chaque run : un seul commit, poussé avec `--force`.
- Un push fait avec `GITHUB_TOKEN` ne déclenche aucun workflow, donc il n'y a pas de boucle.
- En local :
  - `git fetch origin data`, puis `git worktree add data origin/data` (dossier ignoré par git) pour travailler sur les vraies données ;
  - `uv run newrel serve` assemble le site à partir de `data/` ou de `site/sample.json`, et le sert sur `http://127.0.0.1:8000`.
- Sans branche `data` (premier run, ou après sa suppression), le run démarre à zéro.
  - Grâce à la baseline, tout ce qu'il trouve part en historique : aucune fausse nouveauté. L'entrée `bootstrap` prévue au départ ne sert donc à rien.
  - En revanche, un `state.json` illisible arrête le run sans rien écrire.
- Règle des 60 jours (voir le §3.6) : le job `verdict` appelle l'API « enable workflow » à chaque run.
  - Il reste à vérifier que cet appel suffit à remettre le compteur à zéro.
  - La bannière de fraîcheur du site sert de filet de sécurité.

### 2.7 Site statique

- Fichiers :
  - `site/index.html` et `site/style.css` ;
  - `site/app.js`, qui gère le DOM avec `<template>` ;
  - `site/logic.js`, des fonctions pures : filtres, recherche insensible aux accents, regroupement, règle « nouveau », fraîcheur.
- Aucun build ni aucune dépendance. Tests avec `node --test` (Node 22 est installé).
- Regroupement par **semaine de sortie, du vendredi au jeudi**, puisque les sorties tombent le vendredi. Exemple de titre : « Semaine du ven. 17 oct. ».
- Filtres : plateforme, type (Album, EP, Single, Son), « nouveautés seulement » et recherche. L'état des filtres est stocké dans le hash de l'URL.
- Bannière quand `generated_at`, ou le `last_success_at` d'une source, a plus de 36 h. Comme le calcul se fait dans le navigateur, elle détecte aussi un cron désactivé ou un déploiement raté.
- Les pochettes sont chargées depuis les CDN des plateformes (`loading="lazy"`), jamais recopiées.
- Attribution :
  - logo et nom de Spotify sur les liens Spotify ;
  - « par {uploader} sur SoundCloud » pour les sons SoundCloud ;
  - pied de page « Données : Spotify, SoundCloud ».
- `<meta name="robots" content="noindex">` et un `robots.txt` avec `Disallow: /`.
- Pourquoi du JavaScript natif :
  - environ 300 lignes au total, rien à mettre à jour ;
  - Pages sert les fichiers tels quels.
  - Si l'interface grossit (plusieurs vues), on passera à Preact + htm, toujours sans build.

### 2.8 Workflow GitHub Actions

`update.yml` :
- Déclencheurs :
  - `schedule` avec `cron: '17 6 * * *'` et `timezone: 'Europe/Paris'`. La minute :17 évite l'heure pile, le moment où les runs planifiés sont le plus souvent retardés.
  - `workflow_dispatch`, avec deux entrées : `offline` pour reconstruire le site sans appeler les API, et `accept_drop` pour accepter une forte baisse d'abonnements.
  - `push` sur `site/**`, qui reconstruit le site hors ligne : on peut itérer sur l'interface sans consommer de quotas.
- `permissions: {}` au niveau global, puis les droits minimaux par job.
- `concurrency: {group: update, cancel-in-progress: false}`, avec un timeout de 30 min.
- Jobs : `build`, puis `persist` et `deploy`, puis `verdict` (voir le schéma du §2.2).
- Les actions sont épinglées par SHA et mises à jour par Dependabot.

`ci.yml` : lancé sur push et PR, il exécute ruff, pytest et `node --test`, **sans aucun secret**.

Secrets et variables :

| Nom | Type | Usage |
|---|---|---|
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | secret | les deux flux Spotify |
| `SPOTIFY_REFRESH_TOKEN` | secret | `/me/following` |
| `SPOTIFY_AUTHORIZED_AT` | variable | date de la dernière autorisation, pour l'alerte d'expiration |
| `SOUNDCLOUD_CLIENT_ID`, `SOUNDCLOUD_CLIENT_SECRET` | secret | Client Credentials |
| `NEWREL_SECRETS_PAT` | secret (optionnel) | PAT fine-grained (Secrets : write, ce dépôt seulement), utile seulement si Spotify fait tourner le refresh token |
| `NTFY_TOPIC` | secret | notifications, à l'étape 3 |

- GitHub masque les secrets, mais pas les valeurs qui en dérivent. Le script émet donc `::add-mask::` pour chaque access token et pour l'en-tête Basic, avant tout log.
- Les logs d'un repo public sont publics : jamais d'en-têtes ni de tokens dans les logs.

### 2.9 Gestion des pannes

- Chaque source renvoie un `SourceResult` : un statut (`ok`, `partial`, `error` ou `auth_expired`), un message, les abonnements et les sorties de chaque artiste vérifié.
- Ce qu'une source n'a pas pu revérifier reste tel quel dans l'état : une source en échec garde ses sorties et ses abonnements du run précédent.
- Garde-fou : si les abonnements chutent de plus de 30 % ou tombent à 0, c'est traité comme une erreur et non comme la réalité (sauf avec `accept_drop`).
- Sur un `invalid_grant` Spotify, la source passe en `auth_expired`, sans nouvel essai :
  - les abonnements restent figés à leur dernier état ;
  - le catalogue continue d'être lu via Client Credentials ;
  - le message indique la commande de ré-autorisation.
- Verdict du run :
  - rouge tout de suite sur `auth_expired`, ou si l'autorisation Spotify a 170 jours ou plus ;
  - rouge à partir du 2e échec consécutif d'une même source (erreur passagère) ;
  - simple avertissement au 1er échec, ou à partir de 150 jours d'autorisation.
- En cas d'échec d'un workflow planifié, GitHub envoie un e-mail à la personne qui a créé le workflow ou modifié le cron en dernier, c'est-à-dire toi.

## 3. Points de vigilance

### 3.1 Confidentialité (choix retenu : public, en clair)

- Sont lisibles par n'importe qui : la liste de tes artistes (dans `releases.json` et sur la branche `data`), le code et les logs Actions. Le `noindex` limite l'indexation, pas l'accès.
- Un repo privé avec GitHub Pro ne changerait rien pour le site : il resterait public. Seul GitHub Enterprise Cloud permet un site Pages privé.
- Si tu changes d'avis :
  - on chiffre `state.json` et `releases.json` en AES-GCM, avec une phrase de passe en secret, et la page déchiffre via WebCrypto ;
  - comme la branche `data` est réécrite sans historique, cette bascule restera possible plus tard.

### 3.2 Tokens : expiration et renouvellement

| Élément | Durée de vie | Renouvellement |
|---|---|---|
| Refresh token Spotify | 6 mois après l'autorisation, sans prolongation possible ; inutilisable si ton Premium s'arrête | `uv run newrel auth spotify`, environ 2 fois par an ; avertissement à J+150, run rouge à J+170 |
| Rotation éventuelle du refresh token (flux Authorization Code) | mesurée par le script d'auth : il rafraîchit une fois et regarde si Spotify émet un nouveau token. L'ancien n'est jamais réutilisé, car Spotify pourrait invalider toute la famille de tokens | en cas de rotation : réécriture du secret à chaque run via un PAT de portée limitée (`Secrets: write` sur ce seul repo) |
| Token Spotify Client Credentials | 1 h | régénéré à chaque run |
| Token SoundCloud Client Credentials | environ 1 h ; 50 émissions par 12 h et par app | une émission par run |
| Repli OAuth SoundCloud (si nécessaire) | refresh token à usage unique | réécriture du secret à chaque run, comme ci-dessus |

### 3.3 Quotas

| Ressource | Consommation par run (300 artistes) | Limite |
|---|---|---|
| Spotify | au plus 90 appels catalogue et environ 6 appels d'abonnements, moins d'1 min | environ **100 appels catalogue par 24 h** (mesuré, non documenté), partagés par toutes les apps du compte développeur et par tes runs locaux ; plus une limite de débit sur 30 s |
| SoundCloud | environ 600 appels et 1 token, environ 7 min | environ 100 requêtes par minute ; 50 tokens par 12 h |
| GitHub Actions | environ 15 min par jour au pire | gratuit et illimité pour un repo public |
| GitHub Pages | moins de 1 Mo par déploiement | site de 1 Go au plus, 100 Go par mois de bande passante, déploiement de 10 min au plus |

Au-delà d'environ 1 000 artistes, on ne vérifierait plus qu'une fois par semaine les artistes sans sortie depuis 2 ans.

### 3.4 Fragilité et changements d'API

- **Il n'y a plus aucune API non officielle dans le périmètre.** Le risque correspondant disparaît avec le retrait de YouTube Music (`ytmusicapi`) et le choix de l'API officielle SoundCloud. Restent les changements de règles des API officielles.
- Spotify a modifié les règles du Development Mode à plusieurs reprises en 2026 (février, mars, juin, juillet), et le présente comme un bac à sable sur lequel il ne faut pas bâtir. D'autres changements sont à prévoir :
  - la source Spotify est isolée du reste ;
  - les tests sur fixtures montrent vite ce qui casse.
- L'ordre des résultats de `/artists/{id}/albums` n'est pas documenté. Le garde-fou du §2.3 le vérifie à chaque run.
- Le champ `playlist_type` de SoundCloud est du texte libre, sans liste de valeurs documentée. Le script journalisera les valeurs inconnues.
- Une réponse anormale (zéro abonnement, aucune sortie) est traitée comme une erreur (voir le §2.9).

### 3.5 Conditions d'utilisation

- **Spotify, règle III.5** : elle interdit un produit « intégré avec du contenu d'un autre service ».
  - Le risque est la révocation du Client ID.
  - Pour réduire l'exposition : usage personnel, liens uniquement (aucun lecteur embarqué), attribution, `noindex`, et aucune promotion du site.
- **SoundCloud** interdit le stockage persistant du contenu.
  - La branche `data` n'a pas d'historique et les données sont rafraîchies chaque jour.
  - Mais une fenêtre de 90 jours dépasse ce qu'on peut appeler un « cache de session ». Le risque résiduel reste faible pour un usage personnel.
  - Il faut aussi créditer l'uploader et SoundCloud, et mettre un lien vers chaque son.
- GitHub Pages n'accepte pas d'usage commercial. Un usage personnel est conforme.

### 3.6 GitHub et environnement local

- Dans un repo public, le cron est **désactivé après 60 jours sans activité** sur le repo.
  - Parades : le keepalive et la bannière de fraîcheur (voir le §2.6).
  - Pour le réactiver : `gh workflow enable update.yml`.
- Le cron peut être retardé quand GitHub est très chargé, d'où le choix de la minute :17.
- Ton dossier est dans **OneDrive**, dont la synchronisation de `.git` et `.venv` provoque des conflits et des verrous de fichiers.
  - Décision : le dépôt reste dans OneDrive.
  - Parade appliquée : `link-mode = "copy"` dans `pyproject.toml`. En cas de fichiers verrouillés pendant `uv sync`, mettre la synchronisation OneDrive en pause, ou placer le venv ailleurs avec `UV_PROJECT_ENVIRONMENT`.
- Sur ta machine : Python 3.14, Node 22.13, git 2.45, gh 2.99 et uv 0.13 (installé le 22/10, avec un CPython 3.14 géré par uv).

## 4. Découpage en étapes

### Étape 0 : socle du repo

- **Objectif** : un repo public propre, avec une CI qui tourne.
- **Fichiers** : `pyproject.toml`, `uv.lock`, `.python-version` (3.14), `.gitignore`, `README.md`, `config.toml`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `src/newrel/__main__.py`.
- **Actions** :
  - installer uv, puis `git init` et `gh repo create --public` ;
  - dans Settings → Pages, choisir « GitHub Actions » comme source ;
  - optionnel : un ruleset sur `main` qui bloque les push du bot Actions.
- **Terminé quand** : la CI est verte sur un test trivial et `uv run newrel --help` répond.
- **Statut (22/10)** : fait.

### Étape 1 : MVP Spotify de bout en bout

| # | Travail | Fichiers | Terminé quand |
|---|---|---|---|
| 1.1 | Créer l'app Spotify dans le dashboard (API « Web API », redirect `http://127.0.0.1:8888/callback`) et vérifier que ton compte figure dans User Management | — | l'écran de consentement s'affiche |
| 1.2 | Auth locale : serveur loopback, échange du code, test de rotation, puis `gh secret set` et `gh variable set` | `src/newrel/sources/spotify_auth.py` | le secret et la variable apparaissent dans `gh`, et le token n'est jamais affiché |
| 1.3 | Client HTTP : débit limité, `Retry-After`, `QUOTA_EXCEEDED`, `invalid_grant` transformé en `AuthExpired`, masquage des tokens | `src/newrel/http.py`, `sources/spotify.py` | les tests respx passent sur ces quatre cas |
| 1.4 | Collecte Spotify | `sources/spotify.py` | `uv run newrel fetch spotify` (à blanc) liste les dernières sorties de tes artistes, en au plus 2 × (nombre d'artistes) + 10 appels |
| 1.5 | Modèles, état et pipeline | `models.py`, `state.py`, `pipeline.py`, `schema/releases.schema.json` | les tests golden (fixtures + état donnent le JSON attendu) et d'idempotence passent ; le 1er run est entièrement en backfill ; une source en échec reprend ses données précédentes ; un état illisible arrête le run |
| 1.6 | Site | `site/*`, `site/sample.json`, `tests/js/logic.test.js` | filtres, recherche et semaines fonctionnent sur `sample.json` ; un `generated_at` vieux de 2 jours affiche la bannière ; `node --test` passe |
| 1.7 | Workflow | `.github/workflows/update.yml` | un premier dispatch passe au vert ; le site est en ligne ; le run planifié suivant se lance seul et passe au vert ; aucun token dans les logs |
| 1.8 | Exercice de panne et runbook | `README.md` | avec un faux refresh token, le run passe au rouge, les sorties restent à jour via Client Credentials et la bannière « abonnements figés » s'affiche ; avec `SPOTIFY_AUTHORIZED_AT` reculé de 170 jours, le run passe au rouge |

**Statut (22/10)** :
- 1.3 à 1.6 sont faits ; les mêmes scénarios de panne sont couverts par les tests, avec un faux service Spotify.
- 1.1 et 1.2 t'attendent : créer l'app, puis lancer `uv run newrel auth spotify`.
- Il restera ensuite à valider 1.7 et 1.8 en conditions réelles.

### Étape 2 : SoundCloud et déduplication entre plateformes

(Cette étape suit directement Spotify, puisque YouTube Music est retiré.)

- **Objectif** : les sons, albums et EP de tes comptes SoundCloud suivis, fusionnés avec Spotify quand il s'agit de la même sortie.
- **Fichiers** : `sources/soundcloud.py`, `dedup.py`, `aliases.toml`, `config.toml` (`user_urn`, `exclude`), les tests et fixtures SoundCloud, `site/*` (filtre plateforme et attribution).
- **Terminé quand** :
  - test préalable : un token Client Credentials accède à `/users/{urn}/followings` et à `/users/{urn}/tracks`. Sinon, le repli OAuth est documenté et appliqué ;
  - `uv run newrel fetch soundcloud` (à blanc) liste les sons, albums et EP, sans les comptes exclus ;
  - une sortie présente sur les deux plateformes donne **une seule** carte avec deux liens (vérifié par un test et sur un cas réel) ;
  - une entrée `never_merge` empêche une fusion abusive ;
  - les sons d'un nouvel album SoundCloud sont rattachés à la carte de l'album ;
  - si SoundCloud tombe, Spotify est publié quand même, les données SoundCloud du run précédent restent affichées avec la bannière, et le run passe au rouge au 2e échec.

**Statut (22/10)** : code terminé et testé contre un faux service SoundCloud (fusion avec Spotify, `[[never]]`, sons rattachés à leur album, comptes suivis refusés). Écarts par rapport au plan :
- l'URN de ton compte est une variable du dépôt, `SOUNDCLOUD_USER_URN`, et non une clé de `config.toml` ;
- un compte dont le nombre de sons et de playlists n'a pas bougé ne coûte aucun appel ;
- le test préalable est intégré à `uv run newrel auth soundcloud`.

Il reste à créer l'app (Artist Pro), lancer cette commande, puis valider sur tes vraies données.

### Étape 3 : améliorations (indépendantes, dans cet ordre)

| # | Objectif | Fichiers | Terminé quand |
|---|---|---|---|
| 3a | Flux Atom des nouveautés, qui donne des notifications gratuites via n'importe quel lecteur RSS | `feed.py`, `site/` (balise `<link rel="alternate">`) | `feed.xml` passe le validateur W3C ; une nouveauté y apparaît le jour de sa détection |
| 3b | Notification push après un run qui a trouvé des nouveautés (ntfy.sh) (**code fait le 22/10** ; reste à lancer `uv run newrel auth ntfy`) | `notify.py`, secret `NTFY_TOPIC`, `[notify]` dans `config.toml` | une notification arrive sur le téléphone quand il y a du nouveau, et rien sinon |
| 3e | Masquer un compte depuis la page (**fait le 22/10**, ajouté à ta demande) | `site/app.js`, `site/logic.js` | un label masqué disparaît de « À découvrir » et « Déjà vus », pas des favoris ; il se réaffiche depuis la liste en bas de page |
| 3c | « Déjà vu » et favoris (**fait le 22/10**, avancé à ta demande) | `site/app.js`, `site/logic.js`, `site/index.html` | onglets « À découvrir », « Déjà vus » et « Favoris » ; bouton « Déjà vu » et étoile sur chaque carte ; marques en localStorage indexées par l'identifiant stable ; favoris gardés en copie au-delà de la fenêtre de 90 jours ; export et import en JSON ; les marques survivent à une fusion grâce aux alias |
| 3d | Page « Artistes » : les plateformes de chaque artiste et les candidats à la fusion | `site/artists.html` | on peut remplir `aliases.toml` sans lire les logs |

## 5. Structure du repo et dépendances

```
TrucFred/
├─ .github/
│  ├─ workflows/update.yml      # cron + dispatch + push site/** → build, persist, deploy, verdict
│  ├─ workflows/ci.yml          # lint + tests, sans secrets
│  └─ dependabot.yml            # GitHub Actions + dépendances Python
├─ config.toml                  # fenêtre de 90 j, fuseau, seuils, market et groupes Spotify
├─ aliases.toml                 # étape 2 : fusions et séparations manuelles d'artistes
├─ docs/PLAN.md
├─ schema/releases.schema.json  # généré depuis models.py : contrat entre back et front
├─ src/newrel/
│  ├─ cli.py                    # run | fetch <source> | auth <source> | serve | schema
│  ├─ config.py                 # config.toml + .env.local
│  ├─ models.py                 # état et releases.json (pydantic)
│  ├─ http.py                   # httpx + débit limité + Retry-After + masquage
│  ├─ pipeline.py               # orchestration, isolation des sources
│  ├─ state.py                  # first_seen, baseline, élagage
│  ├─ dedup.py                  # regroupement des liens d'une même sortie
│  ├─ releases.py               # construction de releases.json
│  ├─ dates.py                  # dates partielles et date de tri
│  ├─ verdict.py                # ce qui fait passer le run au rouge
│  ├─ site.py, github.py        # assemblage du site, appels à gh
│  ├─ feed.py, notify.py        # étape 3
│  └─ sources/
│     ├─ base.py                # SourceContext → SourceResult
│     ├─ spotify.py
│     ├─ spotify_auth.py
│     └─ soundcloud.py          # étape 2
├─ site/                        # index.html, app.js, logic.js, style.css, robots.txt, sample.json
├─ tests/                       # pytest (faux service Spotify avec respx) + js/logic.test.js
├─ package.json                 # type « module » pour node --test, aucune dépendance
├─ pyproject.toml, uv.lock, .python-version
└─ README.md                    # mise en route et runbook

branche orpheline « data » :     state.json, releases.json (+ feed.xml à l'étape 3)
```

Dépendances :

| Couche | Dépendances | Pourquoi |
|---|---|---|
| Python, exécution | `httpx`, `pydantic` v2, `tzdata` (Windows seulement, pour le fuseau Europe/Paris) | un client maison d'environ 150 lignes plutôt que `spotipy` : seulement 3 endpoints, risque de retard sur les changements de 2026, gestion de `Retry-After` et cache de token sur disque inadaptés. pydantic valide les données et génère le schéma JSON |
| Python, développement | `pytest`, `respx`, `ruff` | tests sur fixtures, simulation des API, lint et formatage |
| Bibliothèque standard | `tomllib`, `xml.etree`, `http.server`, `secrets` | configuration, flux Atom, callback OAuth local |
| Front | aucune | Node 22 sert uniquement à `node --test` |
| Outils | `uv`, `gh` (connecté), git, Node ≥ 18 (pour le CLI SoundCloud) | |
| GitHub Actions | `actions/checkout`, `astral-sh/setup-uv`, `actions/upload-artifact`, `actions/download-artifact`, `actions/configure-pages`, `actions/upload-pages-artifact`, `actions/deploy-pages` | épinglées par SHA |

## 6. Questions encore ouvertes (non bloquantes)

1. **Marché Spotify** : `FR` par défaut pour le paramètre `market` des appels Client Credentials (réglable dans `config.toml`). Faut-il un autre pays ?
2. **Comptes SoundCloud à exclure** (labels, amis, curateurs) : à trancher à l'étape 2, sur ta liste réelle.
3. **Canal de notification** pour l'étape 3b : ntfy (push mobile, gratuit), e-mail ou Discord ?
4. **Domaine personnel** pour le site : optionnel.

## Sources (consultées le 21/10/2026)

**Spotify**
- [Migration guide, février 2026](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- Changelogs : [février 2026](https://developer.spotify.com/documentation/web-api/references/changes/february-2026), [mars 2026](https://developer.spotify.com/documentation/web-api/references/changes/march-2026), [juillet 2026](https://developer.spotify.com/documentation/web-api/references/changes/july-2026)
- Blog : [Update on Developer Access and Platform Security (06/02/2026)](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security), [Introducing refresh token expiration (18/06/2026)](https://developer.spotify.com/blog/2026-06-18-refresh-token-expiration)
- Concepts : [Quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes), [Rate limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits), [Redirect URI](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri), [Refreshing tokens](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens)
- Référence : [Get Followed Artists](https://developer.spotify.com/documentation/web-api/reference/get-followed), [Get Artist's Albums](https://developer.spotify.com/documentation/web-api/reference/get-an-artists-albums)
- [Developer Policy](https://developer.spotify.com/policy)
- Communauté : [rotation des refresh tokens PKCE](https://community.spotify.com/t5/Spotify-for-Developers/Refreshing-tokens-for-PKCE-authorised-users/td-p/5023175)

**YouTube**
- [Coût des quotas de la Data API](https://developers.google.com/youtube/v3/determine_quota_cost)
- [Google OAuth 2.0 : expiration des refresh tokens](https://developers.google.com/identity/protocols/oauth2)
- [YouTube API Developer Policies](https://developers.google.com/youtube/terms/developer-policies)
- ytmusicapi : [PyPI](https://pypi.org/project/ytmusicapi/), [OAuth](https://ytmusicapi.readthedocs.io/en/stable/setup/oauth.html), [Browsing](https://ytmusicapi.readthedocs.io/en/stable/reference/browsing.html)
- [Flux RSS YouTube, 404 intermittents (source tierce)](https://finder.wprssaggregator.com/rss-feeds/platform/youtube)

**SoundCloud**
- [Register an app](https://developers.soundcloud.com/docs/api/register-app)
- [Blog : API credentials CLI, OpenAPI, GitHub (16/06/2026)](https://developers.soundcloud.com/blog/api-credentials-cli-openapi-github)
- [API Guide](https://developers.soundcloud.com/docs/api/guide), [Rate limits](https://developers.soundcloud.com/docs/api/rate-limits), [API Terms of Use](https://developers.soundcloud.com/docs/api/terms-of-use)
- [Spécification OpenAPI (soundcloud/api)](https://github.com/soundcloud/api)
- [Prix d'Artist Pro (TechCrunch, déc. 2024)](https://techcrunch.com/2024/12/17/soundcloud-introduces-a-new-cheaper-paid-plan-for-artists)

**GitHub**
- [Disabling and enabling a workflow (règle des 60 jours)](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/disabling-and-enabling-a-workflow)
- [Events that trigger workflows (schedule)](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [Workflow syntax (cron et fuseau horaire)](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [Facturation de GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [Limites de GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits), [Visibilité de Pages (Enterprise Cloud)](https://docs.github.com/en/enterprise-cloud@latest/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site), [Plans GitHub](https://docs.github.com/get-started/learning-about-github/githubs-products)
