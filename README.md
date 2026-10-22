# TrucFred : nouvelles sorties des artistes suivis

Une page web qui liste les nouvelles sorties (albums, EP, singles) des artistes que je suis sur
Spotify, triées par semaine de sortie, avec un lien vers chaque plateforme. SoundCloud arrive à
l'étape 2 du [plan](docs/PLAN.md).

- **Collecte** : un workflow GitHub Actions planifié (tous les jours vers 6 h 17, heure de Paris)
  lance `newrel`, un script Python.
- **État** : la branche `data` contient `state.json` et `releases.json`. Elle est réécrite à
  chaque run, en un seul commit sans historique.
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
4. **Premier run** : `gh workflow run update.yml`, ou attendre le passage du lendemain matin.
   - Faute de branche `data`, ce premier run démarre à zéro : tout ce qu'il trouve est classé
     comme historique (pas de badge « Nouveau »).
   - Les vraies nouveautés apparaissent à partir du run suivant.

## Commandes

| Commande | Effet |
|---|---|
| `uv run newrel fetch spotify` | Interroge Spotify à blanc et liste les sorties trouvées, sans rien écrire. Limité à 10 appels catalogue (`--budget N` pour changer), pris sur le quota quotidien du workflow |
| `uv run newrel run` | Run complet en local : état dans `data/`, site dans `_site/` |
| `uv run newrel serve` | Sert le site sur <http://127.0.0.1:8000>, avec les données de `data/` ou, à défaut, `site/sample.json` |
| `uv run newrel auth spotify` | Ré-autorise Spotify (voir le runbook) |
| `uv run newrel schema` | Régénère `schema/releases.schema.json` après une modification de `models.py` |

Tests et qualité :

```
uv run pytest
node --test tests/js/logic.test.js
uv run ruff check
uv run ruff format
```

Pour travailler en local sur les vraies données :

```
git fetch origin data
git worktree add data origin/data
```

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
| Repartir de zéro | `git push origin --delete data`, puis relance le workflow. |

## Confidentialité et conditions d'utilisation

- Le dépôt est public : la liste des artistes suivis (`releases.json`, branche `data`) et les
  logs Actions sont lisibles par tous.
- La page est en `noindex`, mais reste accessible à qui en connaît l'URL.
- Aucun secret n'est versionné, et les tokens obtenus pendant un run sont masqués dans les logs.
- Usage strictement personnel :
  - chaque sortie renvoie vers Spotify, avec son logo ;
  - il n'y a aucun lecteur embarqué ;
  - les pochettes sont chargées depuis le CDN de Spotify, jamais recopiées.
- Les limites des conditions d'utilisation des plateformes sont détaillées au §3.5 du
  [plan](docs/PLAN.md).
