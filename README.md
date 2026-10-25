# TrucFred : nouvelles sorties des artistes suivis

Une page web qui liste les nouvelles sorties (albums, EP, singles, nouveaux sons) des artistes
que je suis sur Spotify et SoundCloud, triées par semaine de sortie, avec un lien vers chaque
plateforme. Une sortie présente sur les deux plateformes n'occupe qu'une carte. Voir le
[plan](docs/PLAN.md).

- **Collecte** : un workflow GitHub Actions planifié (tous les jours vers 6 h 17, heure de Paris)
  lance `newrel`, un script Python.
- **État** : la branche `data` contient `state.json` et `releases.json`, chiffrés quand la page
  est protégée par mot de passe. Elle est réécrite à chaque run, en un seul commit sans
  historique.
- **Site** : HTML et JavaScript natif, sans build, servi par GitHub Pages à l'adresse
  <https://fragzel.github.io/TrucFred/>.

## Mise en route (une seule fois)

1. **Outils** : [uv](https://docs.astral.sh/uv/), puis `uv sync`. La CLI GitHub doit être connectée
   (`gh auth status`).
2. **App Spotify** : sur le [dashboard](https://developer.spotify.com/dashboard), crée une app
   (API « Web API ») avec la redirect URI `http://127.0.0.1:8888/callback`.
   - Le Development Mode exige un abonnement **Premium** actif sur le compte propriétaire de
     l'app.
   - Si l'API répond 403, ajoute ton compte dans *User Management*.
3. **Autorisation** : `uv run newrel auth spotify`.
   - Le script demande le Client ID et le Client Secret, ouvre le navigateur, puis enregistre les
     secrets `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` et `SPOTIFY_REFRESH_TOKEN`, ainsi que la
     variable `SPOTIFY_AUTHORIZED_AT`, dans le dépôt via `gh`.
   - Ajoute `--write-env` pour écrire aussi ces valeurs dans `.env.local` (ignoré par git), qui
     sert aux runs locaux.
4. **App SoundCloud** : sur <https://soundcloud.com/you/apps>, crée une app. Il faut un
   abonnement **Artist Pro**. Si le formulaire demande une redirect URI, mets
   `http://127.0.0.1:8899/callback` (elle ne sert pas aujourd'hui).
5. **Mise en route SoundCloud** : `uv run newrel auth soundcloud`.
   - Le script demande le Client ID, le Client Secret et l'adresse de ton profil
     (`https://soundcloud.com/…`).
   - Il vérifie que l'API laisse lire tes comptes suivis avec un simple jeton d'application. Il
     n'y a aucune autorisation à donner, car tes abonnements SoundCloud sont publics.
   - Il enregistre ensuite les secrets `SOUNDCLOUD_CLIENT_ID` et `SOUNDCLOUD_CLIENT_SECRET`,
     ainsi que la variable `SOUNDCLOUD_USER_URN`. L'option `--write-env` marche aussi.
6. **Mot de passe de la page** : `uv run newrel auth site` (voir
   [Page protégée par mot de passe](#page-protégée-par-mot-de-passe)).
7. **Premier run** : `gh workflow run update.yml`, ou attendre le passage du lendemain matin.
   - Une plateforme qui n'a encore jamais été lue démarre à zéro : tout ce qu'elle trouve est
     classé comme historique (pas de badge « Nouveau »).
   - Les vraies nouveautés apparaissent à partir du run suivant.

## Commandes

| Commande | Effet |
|---|---|
| `uv run newrel fetch spotify` | Interroge Spotify à blanc et liste les sorties trouvées, sans rien écrire. Limité à 10 appels catalogue (`--budget N` pour changer), pris sur le quota quotidien du workflow |
| `uv run newrel run` | Run complet en local : état dans `data/`, site dans `_site/` |
| `uv run newrel serve` | Sert le site sur <http://127.0.0.1:8000>, avec les données de `data/` ou, à défaut, `site/sample.json` |
| `uv run newrel fetch soundcloud` | Interroge SoundCloud à blanc, sans rien écrire |
| `uv run newrel auth spotify` | Ré-autorise Spotify (voir le runbook) |
| `uv run newrel auth soundcloud` | Vérifie l'accès SoundCloud et enregistre secrets et URN |
| `uv run newrel auth ntfy` | Active les notifications sur ton téléphone (voir plus bas) |
| `uv run newrel auth site` | Définit ou change le mot de passe de la page (voir plus bas) |
| `uv run newrel schema` | Régénère `schema/releases.schema.json` après une modification de `models.py` |

Tests et qualité :

```
uv run pytest
node --test tests/js/logic.test.js tests/js/vault.test.js
uv run ruff check
uv run ruff format
```

Pour travailler en local sur les vraies données :

```
git fetch origin data
git worktree add data origin/data
```

## Déjà vu et favoris

La page a trois onglets : « À découvrir », « Déjà vus » et « Favoris ». Chaque sortie
n'apparaît que dans un seul d'entre eux, et un favori ne s'affiche que dans « Favoris ». Retirer
l'étoile renvoie la sortie là où elle était : « Déjà vus » si elle avait été marquée vue,
« À découvrir » sinon.

- **Ranger une sortie** : le bouton « Déjà vu » d'une carte la déplace dans « Déjà vus ».
  Recliquer dessus la remet dans « À découvrir ». « Tout marquer comme vu » range d'un coup
  toutes les sorties affichées, et chaque action peut être annulée pendant quelques secondes.
- **Favoris** : l'étoile d'une carte l'ajoute aux favoris. Un favori garde une copie de la
  sortie, il reste donc visible même après sa sortie de la fenêtre de 90 jours (badge
  « Archive »).
- **Masquer un compte** : le lien « Masquer » d'une carte cache toutes les sorties dont ce
  compte est l'artiste principal, utile pour un label trop prolifique. Les favoris restent
  visibles. La liste « Comptes masqués » en bas de page permet de les réafficher.
  - Le masquage ne concerne que la page.
  - Pour ne plus du tout collecter un compte, ni recevoir de notification à son sujet,
    ajoute-le dans `exclude`, section `[soundcloud]` de `config.toml`.
- **Stockage** : les marques sont enregistrées dans le navigateur (localStorage). Elles ne sont
  pas synchronisées entre appareils, faute de serveur. Pour les transférer, utilise
  « Exporter » puis « Importer » en bas de page. L'import fusionne sans rien effacer.
- **Fusions** : quand deux sorties sont fusionnées (par exemple la même sortie trouvée sur deux
  plateformes), leurs marques suivent automatiquement, grâce aux `aliases` de `releases.json`.

## Notifications sur le téléphone

Après chaque run qui trouve de vraies nouveautés, un message arrive sur ton téléphone via
[ntfy](https://ntfy.sh), par exemple « 6 nouvelles sorties », suivi de la liste. Un clic ouvre
la page.

- **Mise en route** : `uv run newrel auth ntfy`.
  - La commande tire au hasard un nom de canal et te demande de t'y abonner dans l'app ntfy
    (Android, iOS ou navigateur).
  - Elle envoie ensuite un message de test, puis enregistre le canal dans le secret
    `NTFY_TOPIC`.
- **Confidentialité** : le nom du canal fait office de mot de passe ; quiconque le connaît peut
  lire les messages.
- **Ce qui est notifié** :
  - seulement les sorties apparues pendant le run, hors catalogue ;
  - une sortie déjà vue sur une autre plateforme ne l'est pas une deuxième fois ;
  - `types` dans `[notify]` permet par exemple de ne garder que les albums, EP et singles.
- **Comptes masqués** : ceux masqués sur la page ne sont pas connus du serveur. Exclus-les dans
  `config.toml` si tu ne veux plus en entendre parler.
- **En cas d'échec** : une notification ratée ne fait pas échouer le run, elle laisse seulement
  un avertissement.

## Doublons entre plateformes

- **Une seule carte.** Une sortie présente à la fois sur Spotify et sur SoundCloud n'occupe qu'une
  carte, avec un lien par plateforme. Il faut pour cela le même artiste, le même titre normalisé
  et des dates proches de 7 jours au plus.
- **Titres.** La normalisation retire un préfixe « Artiste - », ainsi que les mentions comme
  `[Free DL]`, `(Clip officiel)` ou `(feat. …)`.
- **Date affichée.** C'est celle de Spotify quand elle est précise au jour.
- **Artistes.** Un même nom normalisé sur les deux plateformes désigne le même artiste :
  « Nora Velasco Official » sur SoundCloud et « Nora Velasco » sur Spotify, par exemple.
  - Si un nom correspond à plusieurs comptes sur une même plateforme (homonymes), rien n'est
    fusionné automatiquement.
  - `aliases.toml` permet de forcer une fusion (`[[same]]`) ou de l'interdire (`[[never]]`).
- **Albums SoundCloud.** Les sons d'un album ou d'un EP SoundCloud sont couverts par la carte de
  l'album.
- **Coût SoundCloud.** La liste de tes comptes suivis donne leur nombre de sons et de playlists.
  Un compte dont ces compteurs n'ont pas bougé ne coûte aucun appel.

## Quota Spotify

En Development Mode, le catalogue Spotify accepte environ **100 appels par 24 h**. Ce chiffre a
été mesuré le 22/10/2026 (Spotify ne le documente pas), et il est partagé par toutes les apps de
ton compte développeur ainsi que par `newrel fetch` en local.

- **Budget** : chaque run dépense au plus 90 appels (`daily_catalog_calls` dans `config.toml`),
  ce qui laisse 10 appels pour tes essais en local.
- **Coût par artiste** :
  - 1 appel suffit pour relire le total de ses albums et singles ;
  - s'il augmente, 2 appels de plus lisent le détail ;
  - un artiste est de toute façon relu en détail au moins une fois par mois.
- **Ordre de passage** : d'abord les artistes jamais vérifiés, puis les plus en retard sur leur
  rythme, environ tous les 2 jours pour un artiste actif (une sortie dans l'année) et tous les
  7 jours pour un artiste en sommeil.
- **Montée en charge** : les premiers jours, les artistes jamais vérifiés coûtent 2 appels
  chacun. La page indique combien restent à vérifier.
- **Si le quota est épuisé** : l'heure de reprise, donnée par `Retry-After`, est mémorisée.
  Aucun appel catalogue n'est fait avant cette heure, mais les abonnements continuent d'être lus.
- **Un seul passage par 24 h** : le quota court sur 24 h à partir du passage précédent. Un run
  lancé plus tôt (à la main, ou un cron en avance) lit les abonnements mais ne touche pas au
  catalogue. La page affiche l'heure de la prochaine vérification possible ; le délai se règle
  avec `quota_window_hours` dans `config.toml`.

## Lancer la mise à jour à la main

GitHub retarde souvent le cron de 6 h 17 de plusieurs heures. Quand un passage est en retard, la
page affiche un bandeau avec un bouton « Lancer la mise à jour » :

- **Quand il apparaît** :
  - aucun run n'a eu lieu depuis 6 h 17, 45 minutes après l'heure prévue (`schedule_time` et
    `schedule_grace_minutes` dans `config.toml`) ;
  - ou le quota Spotify de 24 h est revenu sans qu'aucun run ne l'ait utilisé.
- **Après un clic**, le bouton disparaît pendant 30 minutes, le temps que le run tourne et
  redéploie la page.
- **Sans token**, le bouton ouvre une fenêtre avec le lien vers le workflow sur GitHub : il reste
  à cliquer sur « Run workflow ».
- **Avec un token**, le clic lance directement le run. Pour en créer un :
  - suis le lien « créer un token GitHub » de la fenêtre ; il pré-remplit un token
    *fine-grained* valable un an, avec la seule permission *Actions : Read and write* ;
  - dans « Repository access », choisis « Only select repositories », puis ce dépôt ;
  - colle le token dans la fenêtre.
- **Où vit le token** : uniquement dans le localStorage de ce navigateur, jamais dans le dépôt.
  Un token refusé par GitHub (expiré ou révoqué) est oublié automatiquement. « Oublier le
  token », en bas de page, le retire à la main.

## Page protégée par mot de passe

Le dépôt est public : sans protection, n'importe qui peut lire la page, la branche `data`, les
artefacts et les résumés des runs. Avec un mot de passe, tout cela est chiffré.

- **Mise en route** : `uv run newrel auth site`.
  - Laisse le champ vide pour tirer un mot de passe au hasard (5 groupes de 4 lettres, facile à
    taper sur un téléphone), puis range-le dans ton gestionnaire de mots de passe.
  - La commande enregistre le secret `SITE_PASSWORD` et, la première fois, `STATE_KEY` (la clé
    de l'état). Le run complet suivant chiffre tout ; pour ne pas attendre :
    `gh workflow run update.yml`, sans `offline`, qui ne réécrirait pas la branche `data`.
- **Sur la page** : le mot de passe est demandé à la première visite.
  - « Se souvenir de cet appareil » garde dans le navigateur la clé de déchiffrement, pas le mot
    de passe. Cette clé ne peut pas être relue, seulement utilisée par les pages de
    `<toi>.github.io`.
  - « Verrouiller cet appareil », en bas de page, l'oublie.
- **Ce qui est chiffré** (AES-256-GCM) :
  - `releases.json` (page, branche `data`, artefacts), avec une clé dérivée du mot de passe
    (PBKDF2-SHA256, 600 000 itérations) ;
  - `state.json`, avec `STATE_KEY`, une clé aléatoire indépendante du mot de passe : changer de
    mot de passe ne fait donc pas perdre l'état ;
  - le résumé des runs ne cite plus aucun titre, seulement des chiffres.
- **Changer de mot de passe** : relance `uv run newrel auth site`. Après le run suivant, chaque
  appareil redemande le mot de passe une fois.
- **Garde-fou** : si le secret `SITE_PASSWORD` disparaît, le run s'arrête au lieu de republier la
  page en clair.
- **Limites** :
  - sans serveur, rien ne limite les essais : qui copie les données peut tester des mots de passe
    hors ligne. D'où le tirage au hasard (environ 94 bits) ; un mot de passe choisi doit faire au
    moins 12 caractères ;
  - restent publics : le code, les compteurs des logs (appels, nouveautés) et la taille des
    données ;
  - tes abonnements SoundCloud restent visibles sur SoundCloud lui-même.
- **Runs locaux** : `newrel run`, `fetch` et `serve` ont besoin de `STATE_KEY` et
  `SITE_PASSWORD` pour lire la branche `data`. Ajoute `--write-env` dès la première mise en route :
  GitHub ne rend jamais la valeur d'un secret.

## Runbook

| Situation | Quoi faire |
|---|---|
| Run rouge « refresh token refusé (invalid_grant) » ou « autorisé il y a 170 jours » | `uv run newrel auth spotify`. Le refresh token Spotify expire 6 mois après l'autorisation, et les rafraîchissements ne prolongent pas ce délai. En attendant, les sorties des artistes déjà connus continuent d'arriver ; seuls les nouveaux abonnements sont figés. |
| Avertissement « nouveau refresh token qui n'a pas pu être enregistré » | Spotify fait tourner le refresh token. Crée un PAT *fine-grained* limité à ce dépôt, avec la permission *Secrets : read and write*, et enregistre-le dans le secret `NEWREL_SECRETS_PAT` : le workflow mettra alors le token à jour à chaque run. |
| Run rouge « abonnements reçus contre N au run précédent » | Si la baisse est voulue (gros ménage dans tes abonnements) : `gh workflow run update.yml -f accept_drop=true`. |
| Bannière « Données vieilles de … » sur la page | Le cron ne tourne plus : un dépôt public sans activité pendant 60 jours voit ses runs planifiés désactivés. Relance-le avec `gh workflow enable update.yml`. |
| Avertissement « quota épuisé jusqu'au … » | Le quota a été dépassé, par exemple après trop d'appels `fetch` en local. Rien à faire : la collecte reprend toute seule à l'heure indiquée. |
| Spotify « en panne » une seule journée | Rien à faire : la page garde les données du dernier run réussi, et le run ne passe au rouge qu'au deuxième échec d'affilée. |
| Modifier uniquement la page | Pousse les changements de `site/` : le site est reconstruit sans appeler les API. Pour le reconstruire à la main : `gh workflow run update.yml -f offline=true`. |
| Run rouge « la page est protégée mais le secret SITE_PASSWORD est absent » | Le secret a été supprimé : `uv run newrel auth site`. Rien n'a été publié en clair. |
| Run rouge « state.json illisible » qui cite `STATE_KEY` ou un déchiffrement impossible | `STATE_KEY` a disparu ou changé. Si tu as encore la bonne valeur (dans `.env.local`), remets-la avec `gh secret set STATE_KEY`. Sinon, repars de zéro. |
| Mot de passe de la page oublié | `uv run newrel auth site` en définit un nouveau, sans toucher à l'état. |
| Repartir de zéro | `git push origin --delete data`, puis relance le workflow. |

## Confidentialité et conditions d'utilisation

- Le dépôt est public : le code et les logs Actions sont lisibles par tous. Les données (artistes
  suivis, sorties) ne sont chiffrées que si la page est
  [protégée par mot de passe](#page-protégée-par-mot-de-passe).
- La page est en `noindex`, n'envoie pas son adresse aux sites qu'elle ouvre (`no-referrer`), et
  sa politique de sécurité (CSP) n'exécute que ses propres scripts.
- Aucun secret n'est versionné, et les tokens obtenus pendant un run sont masqués dans les logs.
- Le token du bouton « Lancer la mise à jour » reste dans le navigateur. Son stockage est
  partagé avec tes autres sites `<toi>.github.io`. S'il fuitait, il ne permettrait que de lancer
  ou d'annuler des runs de ce dépôt, sans lire ni modifier ses fichiers ou ses secrets.
- Usage strictement personnel :
  - chaque sortie renvoie vers Spotify, avec son logo ;
  - il n'y a aucun lecteur embarqué ;
  - les pochettes sont chargées depuis le CDN de Spotify, jamais recopiées.
- Les limites des conditions d'utilisation des plateformes sont détaillées au §3.5 du
  [plan](docs/PLAN.md).
