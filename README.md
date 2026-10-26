# TrucFred : nouvelles sorties des artistes suivis

Une page web qui liste les nouvelles sorties (albums, EP, singles, nouveaux sons, clips) des
artistes que je suis sur Spotify, SoundCloud et YouTube, triées par semaine de sortie, avec un lien
vers chaque plateforme. Une sortie présente sur plusieurs plateformes n'occupe qu'une carte. Voir
le [plan](docs/PLAN.md).

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
6. **Clé API YouTube** : sur la [console Google Cloud](https://console.cloud.google.com/), crée
   un projet, puis :
   - dans *API et services > Bibliothèque*, active **YouTube Data API v3** ;
   - dans *API et services > Identifiants*, crée une **clé API**, puis restreins-la à « YouTube
     Data API v3 » (*Restrictions relatives aux API*).
   - Aucune autorisation OAuth, aucun écran de consentement et rien à publier : une clé API
     n'expire pas.
7. **Abonnements publics** : sur le compte YouTube dont on suit les abonnements, *Paramètres >
   Confidentialité*, décoche « Garder tous mes abonnements privés ». C'est ce qui permet de les
   lire avec une simple clé.
8. **Mise en route YouTube** : `uv run newrel auth youtube --write-env`.
   - Le script demande la clé API et la chaîne (adresse `https://www.youtube.com/@…`, `@handle`
     ou identifiant `UC…`), puis vérifie que ses abonnements sont lisibles.
   - Il enregistre le secret `YOUTUBE_API_KEY` et la variable `YOUTUBE_CHANNEL_ID`.
     `--write-env` les écrit aussi dans `.env.local`, dont la commande de tri a besoin.
9. **Tri des abonnements** : `uv run newrel triage youtube`, puis commite `youtube.toml` (voir
   [Tri des abonnements YouTube](#tri-des-abonnements-youtube)).
10. **Mot de passe de la page** : `uv run newrel auth site --write-env` (voir
    [Page protégée par mot de passe](#page-protégée-par-mot-de-passe)).
11. **Premier run** : `gh workflow run update.yml`, ou attendre le passage du lendemain matin.
    - Le premier passage sur un artiste range dans l'historique ce qui a plus de 14 jours (pas de
      badge « Nouveau ») ; une sortie plus récente garde son badge.
    - Les vraies nouveautés apparaissent à partir du run suivant.

## Commandes

| Commande | Effet |
|---|---|
| `uv run newrel fetch spotify` | Interroge Spotify à blanc et liste les sorties trouvées, sans rien écrire. Limité à 10 appels catalogue (`--budget N` pour changer), pris sur le quota quotidien du workflow |
| `uv run newrel run` | Run complet en local : état dans `data/`, site dans `_site/` |
| `uv run newrel serve` | Sert le site sur <http://127.0.0.1:8000>, avec les données de `data/` ou, à défaut, `site/sample.json` |
| `uv run newrel fetch soundcloud` | Interroge SoundCloud à blanc, sans rien écrire |
| `uv run newrel fetch youtube` | Trie tes abonnements YouTube et liste les clips trouvés, sans rien écrire |
| `uv run newrel triage youtube` | Trie tes abonnements YouTube et te demande ton avis sur les chaînes douteuses (`--all` : sur toutes) |
| `uv run newrel auth spotify` | Ré-autorise Spotify (voir le runbook) |
| `uv run newrel auth soundcloud` | Vérifie l'accès SoundCloud et enregistre secrets et URN |
| `uv run newrel auth youtube` | Vérifie la clé API et la chaîne YouTube (abonnements publics), puis enregistre clé et chaîne |
| `uv run newrel auth ntfy` | Active les notifications sur ton téléphone (voir plus bas) |
| `uv run newrel auth site` | Définit ou change le mot de passe de la page (voir plus bas) |
| `uv run newrel schema` | Régénère `schema/releases.schema.json` après une modification de `models.py` |

Tests et qualité :

```
uv run pytest
node --test tests/js/logic.test.js tests/js/vault.test.js tests/js/player.test.js
uv run ruff check
uv run ruff format
```

Pour travailler en local sur les vraies données :

```
git fetch origin data
git worktree add data origin/data
```

## Tri des abonnements YouTube

Tes abonnements YouTube mélangent artistes, labels et chaînes sans rapport avec la musique.
Chaque run les trie, et seules les chaînes musicales sont suivies : artistes, labels et chaînes
de promo.

- **Ordre du tri**, pour chaque abonnement :
  1. `youtube.toml` tranche d'abord : `artists` (à suivre) et `ignore` (à écarter) ;
  2. une chaîne déjà suivie le reste, pour éviter les va-et-vient d'un jour à l'autre ;
  3. des indices gratuits : chaîne « - Topic » ou VEVO, même nom qu'un artiste suivi sur Spotify
     ou SoundCloud (suivie), sujets YouTube sans rapport avec la musique (écartée) ;
  4. sinon, un examen des 20 dernières vidéos : part de la catégorie Musique, nombre d'artistes
     différents en tête des titres (« Autre artiste - Titre » : label ou chaîne de promo ; les
     reprises ne comptent pas), part de clips et d'audios, part de titres au nom de la chaîne
     (un artiste qui n'utilise pas la catégorie Musique est reconnu ainsi).
- **Labels et chaînes de promo** : une chaîne qui publie des titres de plusieurs artistes est
  suivie comme un artiste, puisque leurs sorties comptent aussi. `uv run newrel triage youtube`
  en affiche la liste à part, avec les @handles : une chaîne trop prolifique s'écarte dans
  `ignore` de `youtube.toml`.
  - Leurs vidéos gardent leur titre complet (« Artiste - Morceau ») et sont attribuées à la
    chaîne. L'artiste nommé en tête du titre compte pour les doublons : la vidéo rejoint la même
    sortie publiée par l'artiste sur Spotify ou SoundCloud.
- **Chaînes douteuses** : elles ne sont pas suivies. Le run affiche « N chaîne(s) à trier » ;
  `uv run newrel triage youtube` te les présente une par une (sujets, raison, derniers titres ;
  `v` ouvre la chaîne). Tes réponses vont dans `youtube.toml`, qu'il faut commiter et pousser.
- **Revoir le tri automatique** : `uv run newrel triage youtube --all` passe toutes les chaînes
  en revue, avec la proposition automatique comme réponse par défaut.
- **Ce qui est écrit dans `youtube.toml`** : seulement tes réponses utiles, une chaîne douteuse
  tranchée ou un classement automatique corrigé. Une chaîne non musicale écartée d'office n'y
  apparaît pas.
- **Ce qui compte comme une sortie** : les clips et audios officiels, c'est-à-dire les vidéos de
  1 à 20 minutes (`min_duration_seconds`, `max_duration_minutes`), en catégorie Musique, avec
  une mention explicite (« Clip officiel », « Audio »…) ou titrées « Artiste - Morceau » au nom
  de la chaîne. Les Shorts, lives, teasers, making-of, interviews et épisodes de web-séries sont
  exclus.
- **Sur la page** : un clip rejoint la carte du single Spotify ou SoundCloud du même titre. Sans
  équivalent, il a sa propre carte, de type « Vidéo ».
- **Coût** : environ 1 unité de quota par chaîne suivie et par run, sur 10 000 par jour.

## Déjà vu et favoris

La page a trois onglets : « À découvrir », « Déjà vus » et « Favoris ». Chaque sortie
n'apparaît que dans un seul d'entre eux, et un favori ne s'affiche que dans « Favoris ». Retirer
l'étoile renvoie la sortie là où elle était : « Déjà vus » si elle avait été marquée vue,
« À découvrir » sinon.

Chaque onglet a sa couleur, reprise par les boutons qui y rangent une sortie : violet pour
« À découvrir » (et tout ce qui lance la lecture), bleu-vert pour « Déjà vus », or pour
« Favoris ». Le rose signale les nouveautés ; « Masquer » et les boutons secondaires restent gris.

- **Ranger une sortie** : le bouton « Déjà vu » d'une carte la déplace dans « Déjà vus ».
  Recliquer dessus la remet dans « À découvrir ». « Tout marquer comme vu » range d'un coup
  toutes les sorties affichées, et chaque action peut être annulée pendant quelques secondes.
  - La carte rangée (ou étoilée) reste à sa place, estompée, jusqu'au prochain changement
    d'onglet ou de filtre. Sinon la voisine, souvent du même artiste, glisserait sous le pointeur
    et un second clic la rangerait aussi. Le second clic d'un double-clic est ignoré.
  - Dans « Déjà vus », « Tout remettre dans À découvrir » fait l'inverse sur les sorties
    affichées : avec la recherche, on remet d'un coup tous les titres d'un artiste.
- **Favoris** : l'étoile d'une carte l'ajoute aux favoris. Un favori garde une copie de la
  sortie, il reste donc visible même après sa sortie de la fenêtre de 90 jours (badge
  « Archive »).
- **Masquer une sortie** : le lien « Masquer » d'une carte cache cette sortie seulement, des
  onglets « À découvrir » et « Déjà vus » ; les autres titres de l'artiste restent. Un favori
  n'a pas ce lien. La liste « Sorties masquées » en bas de page permet de les réafficher.
  - Jusqu'au 26/10, « Masquer » cachait tout un compte : ceux masqués ainsi le restent, et se
    réaffichent depuis la même liste.
  - Le masquage ne concerne que la page.
  - Pour ne plus du tout collecter un compte, ni recevoir de notification à son sujet,
    ajoute-le dans `exclude`, section `[soundcloud]` de `config.toml`, ou dans `ignore` de
    `youtube.toml`.
- **Stockage** : les marques sont enregistrées dans le navigateur (localStorage). Elles ne sont
  pas synchronisées entre appareils, faute de serveur. Pour les transférer, utilise
  « Exporter » puis « Importer » en bas de page. L'import fusionne sans rien effacer.
- **Fusions** : quand deux sorties sont fusionnées (par exemple la même sortie trouvée sur deux
  plateformes), leurs marques suivent automatiquement, grâce aux `aliases` de `releases.json`.

## Écouter depuis la page

Un seul lecteur, le même pour Spotify, SoundCloud et YouTube, fixé en bas de l'écran.

- **▶ sur la pochette** lance la sortie ; sur la sortie en cours, il met en pause ou reprend. La
  musique continue pendant que tu changes d'onglet, filtres ou ranges des cartes.
- **Commandes** : ▶ / ❚❚, ⏮ (début du titre, ou titre précédent), ⏭ (titre ou sortie suivante),
  ✕ pour arrêter, et une barre de progression : un clic ou un glissé saute à cet endroit.
- **Enchaînement** : à la fin d'un titre, le lecteur passe au suivant de l'EP, puis à la sortie
  suivante de la liste affichée.
- **Trier en écoutant** : le lecteur a ses boutons ☆ Favori, Déjà vu et Masquer. « Déjà vu » et
  « Masquer » rangent la sortie et passent à la suivante ; « Favori » la garde et laisse jouer.
  Chaque action s'annule depuis le message qui s'affiche.
- **⤢ Agrandir** : la sortie en cours sur la moitié basse de l'écran (pochette, infos, titres,
  commandes et boutons de tri), pour trier les sorties une par une ; la liste reste utilisable
  au-dessus. Raccourcis : espace (lecture ou pause),
  ← → (précédent, suivant), F (favori), V (déjà vu), M (masquer), Échap (réduire). La musique
  continue en réduisant.
- **EP et albums** : ▶, ou le lien « N titres », agrandit la carte sur toute la largeur et liste
  ses titres. « Tout lire » part du premier ; un clic sur un titre joue ce titre.
- **Plateformes** : SoundCloud puis YouTube passent en premier, car ils jouent les morceaux
  entiers sans compte. Une sortie présente sur plusieurs plateformes propose « Lire sur … ».
  - Spotify joue les morceaux entiers si son lecteur intégré voit ta connexion à
    open.spotify.com, sinon des extraits de 30 secondes : sans le cookie de session, sa page
    arrive avec `"isAnonymous": true`. Sur un extrait (durée de 30 s environ, ou plus courte que
    celle du titre), le lecteur dit pourquoi, selon le navigateur :
    - **Firefox** range par défaut les cookies de Spotify à part sur chaque site (protection
      totale contre les cookies) : connecté ou non, le lecteur intégré ne voit pas la session.
      Bouclier à gauche de l'adresse, désactiver la protection pour ce site : la page se
      recharge, et Spotify joue les titres entiers si tu es connecté dans Firefox.
    - **Téléphone et Safari** : le lecteur intégré de Spotify n'y joue que des extraits, même
      connecté. « Écouter sur Spotify » ouvre le titre entier.
    - **Chrome, Edge** : « Se reconnecter à Spotify » ouvre la connexion dans un onglet, et le
      lecteur se recharge quand tu reviens sur la page. Si c'est toujours un extrait, les cookies
      tiers sont bloqués : les autoriser pour ce site.
  - YouTube : le son seul, vidéo cachée, à ta demande (26/10). Ses règles veulent la vidéo
    visible, sur au moins 200 × 200 px : YouTube pourrait un jour bloquer la lecture intégrée
    depuis la page. Pour revenir à une vidéo visible, voir `.player-media.is-video` dans
    `site/style.css`.
- **Comment c'est fait** (`site/player.js`) : le lecteur officiel de la plateforme est chargé dans
  une iframe, cachée sous la pochette, et piloté par messages, comme le font les bibliothèques
  officielles, mais sans charger leurs scripts : la page n'exécute que son propre code.
  - Si un lecteur ne répond pas au bout de 10 secondes, il apparaît tel quel, avec ses propres
    commandes.
  - Pas de spectre en direct : le son est joué par le lecteur de la plateforme, que la page ne
    peut pas écouter, et Spotify a fermé son API d'analyse audio fin 2024.
- **Listes de titres** : celles des playlists SoundCloud arrivent avec elles. Spotify demande un
  appel par album : chaque run en lit 10 (`tracklist_calls` de `[spotify]`), pris sur le quota du
  jour avant les artistes, une fois pour toutes. Les EP déjà connus le 26/10 sont complétés en
  une semaine environ ; d'ici là, « Tout lire » joue la sortie d'un bloc.

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
- **Sorties masquées** : le serveur ne les connaît pas. Pour ne plus entendre parler d'un compte,
  exclus-le dans `config.toml` ou `youtube.toml`.
- **En cas d'échec** : une notification ratée ne fait pas échouer le run, elle laisse seulement
  un avertissement.

## Doublons entre plateformes

- **Une seule carte.** Une sortie présente sur plusieurs plateformes n'occupe qu'une carte, avec
  un lien par plateforme. Il faut pour cela le même artiste, le même titre normalisé et la même
  édition, à 60 jours près : un son SoundCloud ou un clip sort souvent des semaines avant ou
  après la sortie officielle. Le clip, l'audio et la lyric video d'un même titre sur YouTube se
  regroupent aussi, à 7 jours près.
- **Titres.** La normalisation retire un préfixe « Artiste - » (ou « Artiste ft. Invité - »),
  ainsi que les mentions comme `[Free DL]`, `(Clip officiel)`, `(Official Music Video)`,
  `(Original Mix)`, `[Full EP]`, « OUT NOW on @label », les `#hashtags`, les numéros de catalogue
  (`[HP340]`), `| 4K`, `(feat. …)` ou « ft. … » en fin de titre, et « EP » final. Sur YouTube, le
  titre affiché est nettoyé de la même façon.
- **Labels.** Sur SoundCloud et YouTube, « Artiste - Titre » crédite l'artiste nommé, même
  publié par un label (« Hellfish - Call Me Master » chez PRSPCT rejoint l'album de Hellfish).
  Deux titres qui créditent chacun quelqu'un doivent créditer le même artiste : deux « Intro »
  d'un même label restent séparées. Sur une carte qui a un lien Spotify, seuls les artistes de
  Spotify s'affichent, pas le label.
- **Remixes.** Un EP de remixes (« Titre (Remixes) ») regroupe les remixes publiés un par un sur
  une autre plateforme. Un remix, une version VIP ou live reste sinon une sortie à part.
- **Date affichée.** C'est celle de Spotify quand elle est précise au jour.
- **Artistes.** Un même nom normalisé sur plusieurs plateformes désigne le même artiste :
  « Nora Velasco Official » sur SoundCloud, « NoraVelascoVEVO » sur YouTube et « Nora Velasco »
  sur Spotify, par exemple.
  - Si un nom correspond à plusieurs comptes sur une même plateforme (homonymes), rien n'est
    fusionné automatiquement. Exception : sur YouTube, la chaîne d'un artiste et sa chaîne VEVO
    ou « - Topic » sont un seul artiste.
  - `aliases.toml` permet de forcer une fusion (`[[same]]`) ou de l'interdire (`[[never]]`).
- **Albums SoundCloud.** Les sons d'un album ou d'un EP SoundCloud sont couverts par la carte de
  l'album.
- **Coût SoundCloud.** La liste de tes comptes suivis donne leur nombre de sons et de playlists.
  Un compte dont ces compteurs n'ont pas bougé ne coûte aucun appel.

## Styles musicaux

Chaque carte affiche un ou deux styles sous le nom de l'artiste ; le survol donne les genres
d'origine. Le menu « Style » des filtres n'affiche que les sorties d'un style.

- **Une quinzaine de styles.** L'électro, majoritaire, est découpée en sous-styles (Hardcore /
  Gabber, Techno, Drum & Bass, Dubstep / Bass, House / Disco, Trance / Psy, Hardstyle, et
  « Autre électro »). Le reste est regroupé en familles : Rap, R&B / Soul, Pop, Rock / Metal,
  Reggae / Dub, Jazz / Blues, Latino / Monde, Folk / Country, Classique / BO.
  - Le menu ne propose que les styles présents, avec leur nombre de sorties, plus « Toute
    l'électro » et « Sans style connu ».
  - La recherche trouve aussi les genres d'origine : « gabber », « drill »…
- **D'où viennent les genres**, sans aucun appel en plus :
  - Spotify : les genres de chaque artiste suivi (Spotify n'en donne pas par album) ;
  - SoundCloud : le genre et les tags de chaque son ou playlist ;
  - YouTube : les sujets et les tags de chaque vidéo, les sujets et les mots-clés de chaque
    chaîne.
- **Tags appâts.** Les tags d'une vidéo YouTube (ou d'un son SoundCloud) citent souvent d'autres
  genres pour être trouvés. Seuls ceux de la famille de ses sujets (ou du genre déclaré) comptent.
- **Choix du style** (`src/newrel/styles.py`) : chaque genre est rangé dans un style par une
  liste de règles, des plus précises aux plus larges (« hardcore punk » est du rock, « hardcore
  hip hop » du rap). Une sortie prend d'abord le style de ses propres genres, puis ceux de son
  artiste, sur n'importe quelle plateforme, puis ceux de l'ensemble de ses sorties. Un deuxième
  style n'apparaît que s'il pèse au moins la moitié du premier.
- **Premier run après l'ajout des styles (25/10/2026).** Les comptes SoundCloud dont des sons
  connus ont été lus avant sont relus une fois en entier : environ 220 comptes, soit 450 appels
  et 5 minutes de plus, dans le budget de 15 minutes de la source.
- `uv run newrel fetch <source>` affiche les genres trouvés à côté de chaque sortie.

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
| YouTube : « abonnements privés » | Les abonnements de la chaîne sont repassés en privé : décoche à nouveau « Garder tous mes abonnements privés » dans les paramètres YouTube. En attendant, les chaînes déjà suivies continuent d'être vérifiées. |
| YouTube : « HTTP 400 (API_KEY_INVALID…) » | La clé API a été supprimée ou régénérée : crée-en une autre, puis `uv run newrel auth youtube --write-env`. |
| Avertissement « YouTube : N chaîne(s) à trier » | `uv run newrel triage youtube`, puis commite et pousse `youtube.toml`. |
| YouTube suit une chaîne qui n'est pas un artiste | `uv run newrel triage youtube --all`, ou ajoute son identifiant (`UC…`) ou son handle (`@…`) dans `ignore` de `youtube.toml`. |
| Un artiste YouTube manque | Ajoute son identifiant ou son handle dans `artists` de `youtube.toml`. |
| Run rouge « la page est protégée mais le secret SITE_PASSWORD est absent » | Le secret a été supprimé : `uv run newrel auth site`. Rien n'a été publié en clair. |
| Run rouge « state.json illisible » qui cite `STATE_KEY` ou un déchiffrement impossible | `STATE_KEY` a disparu ou changé. Si tu as encore la bonne valeur (dans `.env.local`), remets-la avec `gh secret set STATE_KEY`. Sinon, repars de zéro. |
| Mot de passe de la page oublié | `uv run newrel auth site` en définit un nouveau, sans toucher à l'état. |
| Repartir de zéro | `git push origin --delete data`, puis relance le workflow. |

## Confidentialité et conditions d'utilisation

- Le dépôt est public : le code et les logs Actions sont lisibles par tous. Les données (artistes
  suivis, sorties) ne sont chiffrées que si la page est
  [protégée par mot de passe](#page-protégée-par-mot-de-passe).
- YouTube : les abonnements de la chaîne suivie sont publics sur YouTube, condition pour les
  lire sans autorisation. Côté dépôt, seules les chaînes musicales suivies sont enregistrées
  dans l'état, et les logs ne nomment jamais une chaîne écartée ou douteuse (seulement leur
  nombre). `youtube.toml` est public lui aussi, avec le nom de chaque chaîne que tu y as rangée.
- La page est en `noindex`, n'envoie pas son adresse aux sites qu'elle ouvre (`no-referrer`), et
  sa politique de sécurité (CSP) n'exécute que ses propres scripts.
- Aucun secret n'est versionné, et les tokens obtenus pendant un run sont masqués dans les logs.
- Le token du bouton « Lancer la mise à jour » reste dans le navigateur. Son stockage est
  partagé avec tes autres sites `<toi>.github.io`. S'il fuitait, il ne permettrait que de lancer
  ou d'annuler des runs de ce dépôt, sans lire ni modifier ses fichiers ou ses secrets.
- Usage strictement personnel :
  - chaque sortie renvoie vers sa plateforme (Spotify, SoundCloud, YouTube), avec son logo ;
  - il n'y a aucun lecteur embarqué ;
  - les pochettes et vignettes sont chargées depuis le CDN de chaque plateforme, jamais
    recopiées.
- Les limites des conditions d'utilisation des plateformes sont détaillées au §3.5 du
  [plan](docs/PLAN.md).
