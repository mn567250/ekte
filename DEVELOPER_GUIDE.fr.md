# zing — Guide du développeur

> [🇬🇧 English](DEVELOPER_GUIDE.md) · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · **🇫🇷 Français** · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md)

Ce guide s'adresse à celles et ceux qui modifient zing : comment il est construit,
comment préparer un environnement de développement, comment contribuer, et
comment il est empaqueté, exécuté dans Docker et publié. Ce que fait zing et
comment l'utiliser se trouve dans le [README](README.fr.md) ; le fonctionnement et
la notation de chaque vérification dans la [Méthodologie](docs/METHODOLOGY.fr.md).

---

## Sommaire

- [Principes](#principes)
- [Environnement de développement](#environnement-de-développement)
- [Organisation du dépôt](#organisation-du-dépôt)
- [Architecture](#architecture)
  - [Déroulement d'un audit](#déroulement-dun-audit)
  - [Clients](#clients)
  - [Détecteurs et barèmes](#détecteurs-et-barèmes)
  - [Notation et verdict](#notation-et-verdict)
  - [Base de connaissances](#base-de-connaissances)
  - [Bibliothèque de prompts](#bibliothèque-de-prompts)
  - [Rapports](#rapports)
  - [Auditeurs autonomes](#auditeurs-autonomes)
  - [Serveur web](#serveur-web)
  - [Interface web côté navigateur](#interface-web-côté-navigateur)
  - [Données locales](#données-locales)
- [Contribuer](#contribuer)
  - [Pull requests](#pull-requests)
  - [Ajouter un détecteur](#ajouter-un-détecteur)
  - [Modifier la base de connaissances](#modifier-la-base-de-connaissances)
  - [Modifier les prompts des sondes](#modifier-les-prompts-des-sondes)
  - [Traductions](#traductions)
  - [Documentation](#documentation)
- [Tests](#tests)
- [Docker](#docker)
- [Intégration continue](#intégration-continue)
- [Publication des versions](#publication-des-versions)
- [Sécurité](#sécurité)
- [Licence](#licence)

## Principes

zing est une aide à l'audit en boîte noire : l'exactitude et le fait de **ne pas
accuser à tort des relais honnêtes** comptent davantage que d'attraper chaque
astuce possible. Gardez cette exigence en tête pour chaque modification.

- **Des preuves, pas des accusations.** Les constats signalent *écarts et
  risques*, jamais une « fraude ». Préférez *non concluant* à une supposition. Un
  nouveau chemin de gravité ÉLEVÉE exige des preuves solides et reproductibles,
  et doit être difficile à déclencher sur un endpoint honnête.
- **Pas de réseau dans les tests.** Les tests des détecteurs s'exécutent contre
  le serveur simulé en processus de `tests/conftest.py` (httpx `MockTransport`),
  jamais contre une API réelle.
- **Les secrets ne sortent pas.** Les clés d'API sont réduites à une empreinte,
  jamais stockées dans les rapports. Tout nouveau chemin de sortie doit faire
  passer le texte contrôlé par le relais par `zing.utils.redact` et l'échapper
  pour son format.
- **Les mêmes sondes pour tous.** Les textes des sondes sont en anglais et fixes,
  quelle que soit la langue de l'interface, pour que le même relais obtienne le
  même verdict (voir [Bibliothèque de prompts](#bibliothèque-de-prompts)).
- **Local uniquement.** zing ne contacte que les endpoints configurés par
  l'utilisateur, et l'interface web n'écoute que sur la boucle locale (voir
  [Serveur web](#serveur-web)).

## Environnement de développement

Nécessite Python 3.10+. Node.js est facultatif : les tests du JavaScript du
navigateur s'exécutent sous `node` et sont ignorés sans lui.

```bash
git clone https://github.com/cenbonew/zing
cd zing
pip install -e '.[dev,web]'   # éditable, avec outils de dev et interface web
pytest                        # suite de tests
ruff check zing tests         # lint
mypy zing                     # vérification de types
```

Avec uv : `uv venv && uv pip install -e '.[dev,web]'`. Aucune
bibliothèque système n'est nécessaire, rapports PDF compris.

Lancez depuis les sources avec `zing …` ou `python -m zing …`. `zing serve` sert
l'interface web directement depuis `zing/web/static/`, donc un rechargement du
navigateur prend en compte les modifications ; il n'y a pas d'étape de build.

## Organisation du dépôt

```text
zing/
  cli.py               CLI Typer : check, compare, models, kb*, serve, watch, embed, rerank, image, audio
  config.py            configuration YAML, références de secrets (env:/file:), AuditOptions
  runner.py            run_audit() : relie tout et exécute les détecteurs
  context.py           AuditContext remis à chaque détecteur
  models.py            contrats de données pydantic : TargetConfig, Finding, DetectorResult, AuditReport, …
  scoring.py           scores de dimension, poids, score global, verdict de risque, confiance
  clients/             clients HTTP : compatible OpenAI, Anthropic Messages, OpenAI Responses
  detectors/           un fichier par détecteur, plus base.py (registre), scale.py, helpers.py
  judge/               le juge LLM de confiance utilisé par quality_judge
  knowledge/           schéma, chargeur, stockage utilisateur (kb.db), import, prompt de recherche, instantanés
    data/              profils de fournisseurs intégrés (*.yaml)
  prompts/en.json      tout texte que zing envoie à une API de LLM
  perf/                enregistrement par requête et section performance du rapport
  report/              rendus JSON / Markdown / HTML / PDF et écriture
  embed_audit.py       auditeur autonome d'embedding et de rerank
  media_audit.py       auditeur autonome d'images et d'audio (TTS)
  notify.py            alertes webhook (Slack / Feishu / DingTalk / JSON générique)
  datadir.py           le répertoire de données local et ses fichiers SQLite
  secretbox.py         chiffrement des secrets stockés ; la clé maîtresse en mémoire
  i18n/                traductions partagées par l'interface web et les alertes
    locales/           <code>.json par langue, fragments/<feature>/<code>.json
  utils/               expurgation, analyse SSE, statistiques, estimation de tokens
  web/
    server.py          application FastAPI : pages, API JSON, flux SSE d'audit, planificateur des surveillances
    jobs.py            tâches d'audit en arrière-plan et le verrou par relais
    security.py        écoute locale, liste d'hôtes autorisés, contrôles Origin/JSON, en-têtes
    history.py         stockage de l'historique des audits (history.db)
    analytics_store.py ses tables d'analyse : métriques par exécution, enregistrements de requêtes
    analytics.py       requêtes d'analyse : indicateurs, séries temporelles, classements
    watches.py         stockage des surveillances (watches.db)
    masterkey.py       états et actions de la clé maîtresse (serveur et `zing secret`)
    static/            pages de l'interface classique et scripts partagés (lang.js, i18n.js, …)
    static/v2/         pages, styles et scripts de la nouvelle interface
tests/                 suite pytest ; conftest.py contient le relais simulé
docs/                  METHODOLOGY (7 langues), CI.md, DOCKER.md, PUBLISHING.md
examples/zing.yaml     fichier de configuration commenté
prototypes/            prototypes HTML statiques de l'interface web (non livrés)
action.yml             l'action composite GitHub
Dockerfile             image de l'interface web
```

## Architecture

### Déroulement d'un audit

`zing check`, `zing compare`, `zing watch`, le flux d'audit de l'interface web et
son planificateur de surveillances aboutissent tous à la même fonction,
`zing.runner.run_audit()` :

1. **Configuration.** `zing/config.py` fusionne la configuration YAML et les
   options de ligne de commande en `TargetConfig` (cible, référence et juge
   facultatifs) et `AuditOptions` (suite, dimensions, taille des sondes, sortie).
   Les clés d'API données en `env:VAR` ou `file:/chemin` sont résolues ici.
2. **Base de connaissances.** `load_knowledge_base()` charge les profils intégrés,
   `--kb-dir`/`ZING_KB_DIR` et le `kb.db` de l'utilisateur, puis résout le modèle
   **annoncé** (par défaut le modèle demandé) vers un profil. Une surveillance
   transmet à la place son instantané épinglé.
3. **Clients.** `make_client()` crée un client pour la cible (et la référence)
   dans le protocole choisi ou détecté automatiquement. Un `RequestRecorder`
   enveloppe chaque appel pour la section performance.
4. **Détecteurs.** `select_detectors()` retient les détecteurs enregistrés pour
   la suite (ou les dimensions personnalisées), en écartant ceux qui exigent un
   juge ou une référence absents. Ils s'exécutent **séquentiellement**, à dessein :
   des requêtes concurrentes déclencheraient des limites de débit et fausseraient
   les mesures de temps (les sondes de fiabilité et de performance gèrent
   elles-mêmes une concurrence bornée). `run_detector()` chronomètre chacun et
   transforme un plantage en résultat de statut **Erreur**, de sorte qu'une
   réponse aberrante du relais n'interrompt jamais l'audit.
5. **Notation.** `scoring.build_dimensions()` et `build_verdict()` transforment
   les résultats des détecteurs en scores de dimension, score global et note,
   verdict de risque et confiance.
6. **Rapport.** Tout aboutit dans un `AuditReport` (`zing/models.py`) avec la
   cible expurgée, l'instantané du profil de la base de connaissances, la section
   performance et les langues des sondes. La CLI le rend et l'écrit ; l'interface
   web le diffuse.

`run_audit()` accepte un rappel `on_event` ; le serveur web transforme ses
événements (détecteur démarré/terminé avec des constats compacts, temps par
requête regroupés) en Server-Sent Events pour la vue en direct.

### Clients

`zing/clients/` contient un client par protocole — `openai_compatible.py`
(Chat Completions), `anthropic.py` (Messages) et `responses.py` (Responses) —
avec la même interface, bâtis sur la mécanique HTTP commune de `base.py`.
`make_client()` dans `clients/__init__.py` en choisit un d'après `--api` ou le
détecte à partir de l'URL de base et du modèle. Les détecteurs ne parlent qu'à
cette interface (`RequestSpec` en entrée, `CompletionOutcome` en sortie) et sont
donc indépendants du protocole.

Les clients adaptent aussi les requêtes à ce que le modèle accepte (`base.py`) :
le runner initialise `unsupported_params` depuis le profil, les paramètres
d'échantillonnage qui y figurent sont omis et, sur Chat Completions, un
`max_tokens` listé envoie la limite en `max_completion_tokens`. Une 4xx qui nomme
un tel paramètre l'ajoute à l'ensemble et répète la requête une fois adaptée (la
tentative refusée est enregistrée avec la phase `param_retry`). Une sonde qui
juge le refus brut définit `RequestSpec.exact_params`.

### Détecteurs et barèmes

Un détecteur est un fichier autonome dans `zing/detectors/` : une sous-classe de
`Detector` (`base.py`) avec un `id`, un `name`, une `dimension`, la première
suite où il s'exécute (`min_suite`), un `cost_hint` approximatif pour
`--dry-run`, et `async def run(self, ctx) -> DetectorResult`. `@register`
l'ajoute au registre ; `zing/detectors/__init__.py` importe chaque module pour
que le registre soit complet.

Chaque détecteur publie son **barème** (`SCALE`, construit avec `scale.py`) :
chaque résultat possible de chaque vérification avec ses points, son statut et sa
gravité. Les constats sont créés à partir du barème
(`SCALE.finding(check, outcome, …)`), de sorte que rapport et comportement ne
peuvent diverger. `Scale` note par la moyenne de ses vérifications ;
`DeductionScale` part de 100 et retranche ou plafonne. L'interface web affiche le
barème sous **Barème** ; la [Méthodologie](docs/METHODOLOGY.fr.md) reproduit
chaque barème. `connectivity.py` est l'exemple canonique et le plus court.

Les détecteurs partagent une même boucle d'événements avec tous les autres
audits de `zing serve` ; le travail gourmand en CPU ne doit donc pas s'y
exécuter : une boucle bloquée retarde les requêtes des autres audits et gonfle
les latences qu'ils mesurent. `helpers.build_filler()` construit le texte de
remplissage en temps linéaire et mémorise les quelques dernières tailles, et les
détecteurs de fenêtre de contexte et de cache de prompt l'appellent (ainsi que
`build_haystack()`) via `asyncio.to_thread`. Les comptes de tokens viennent de
`zing/utils/tokenize.py`, une heuristique en bibliothèque standard : zing
n'importe aucune bibliothèque de tokenizer et ne télécharge rien à l'exécution,
si bien qu'il fonctionne dans des environnements restreints. L'argument
`tokenizer` d'`estimate_tokens()` est accepté mais ne change pas le compte, et
les champs de rapport `tokens_exact` / `exact_tokenizer` sont conservés pour la
compatibilité et toujours à false.

### Notation et verdict

`zing/scoring.py` contient `DIMENSION_WEIGHTS` et les règles du verdict : le score
d'une dimension est la moyenne à poids égal de ses détecteurs, le score global la
moyenne pondérée des dimensions exécutées, et le niveau de risque suit l'échelle
de gravité décrite dans
[Méthodologie → Comment zing note](docs/METHODOLOGY.fr.md#comment-zing-note).
Chaque dimension consigne son calcul dans `DimensionScore.breakdown`, qui
alimente les **Dimension details** des rapports et les lignes dépliables des
**Contrôles par dimension** de l'interface web.

### Base de connaissances

`zing/knowledge/` définit le schéma des profils (`schema.py` : `ProviderProfile`,
`ModelProfile`, `FingerprintProbe`), charge et fusionne les couches
(`loader.py` : YAML intégré → `ZING_KB_DIR`/`--kb-dir` → le `kb.db` de
l'utilisateur), stocke les entrées de l'utilisateur (`store.py`), vérifie et
importe le YAML (`importer.py`), construit le prompt de recherche destiné aux
assistants externes (`research.py`) et prend un instantané du profil utilisé par
une exécution (`snapshot.py`). Les identifiants de modèle se résolvent exactement, via
les alias ou par nom normalisé, restreints par le fournisseur déclaré. Le repli
approximatif prend le plus long nom de la KB contenu dans l'identifiant annoncé
(un id de snapshot ou décoré), sauf si le reste de l'identifiant nomme un autre
niveau ou une autre variante (`-mini`, `-lite`, `-image`, …) ; un identifiant
tronqué n'est résolu que si le nom d'un seul modèle commence par lui, si bien
qu'un id ambigu comme `gpt-4` n'obtient aucun profil plutôt qu'un niveau
deviné. Chaque rapport consigne comment l'id a été résolu.

`load_knowledge_base()` met en cache les résultats fusionnés et renvoie par
défaut une copie profonde, que l'appelant peut donc modifier. Les appelants qui
ne font que la lire (listes et catalogue de l'interface web, résolution d'un
modèle) passent `copy=False` et obtiennent l'instance partagée en cache, qu'ils
ne doivent pas modifier.

Les relais sont aussi des points d'accès : `relays.py` transforme les
`base_url_hints` d'un fournisseur en URL de base utilisables (`GET /api/kb` →
`base_urls`) et enregistre un relais depuis l'interface web comme entrée de
fournisseur dans `kb.db` (`origin = relay` : un `display_name` et une URL de base,
sans modèles ; aucun changement de schéma).

### Bibliothèque de prompts

Tout texte que zing envoie à une API de LLM — sondes de chat, prompt du juge,
schémas d'outils, entrées d'embedding / rerank / image / audio — se trouve dans
`zing/prompts/en.json` et se lit avec `zing.prompts.text()` / `get()`.
`{{name}}` marque une valeur insérée à l'exécution. La langue des sondes est
fixée à l'anglais (`PROBE_LANG`), indépendamment de la langue de l'interface, car
les vérifications de réponses et les estimations de tokens sont calibrées sur ces
textes exacts. Les sondes dont la langue *est* la mesure (p. ex. fluidité en
chinois, tokenizer ou auto-identification des modèles chinois) vivent avec leurs
réponses attendues dans la base de connaissances et déclarent `prompt_lang` et un
motif `language_bound`. Le runner consigne les langues utilisées dans
`prompt_languages`.

### Rapports

`zing/report/render.py` rend un `AuditReport` en JSON, en JSON compact pour
agents, en Markdown et en HTML ; `dimensions.py` et `performance.py` rendent les
**Dimension details** et la section performance ; `pdf.py` compose le PDF avec
ReportLab à partir des mêmes données et fonctions (pur Python ; uniquement les
polices PDF standard, avec la police CID STSong-Light pour le chinois, donc rien
d'incorporé ; sans jamais charger de ressource externe), partagé par la CLI et
l'interface web ; `writer.py` écrit les fichiers. Tout texte contrôlé par le relais est
expurgé et échappé (HTML / Markdown) avant la sortie. `POST /api/report/export`
de l'interface web réutilise ces rendus pour la rangée **Télécharger le rapport**,
avec les textes lisibles traduits dans la langue de l'interface.

### Auditeurs autonomes

Embedding/rerank (`embed_audit.py`) et image/audio (`media_audit.py`) ne sont pas
des surfaces de chat ; ils ont donc leurs propres petits auditeurs avec leur
propre verdict au lieu du pipeline de détecteurs. Ils partagent les réglages HTTP
des clients, la base de connaissances (dimensions natives, tailles d'image, voix)
et la bibliothèque de prompts. Tout le décodage (en-têtes d'image, WAV) n'utilise
que la bibliothèque standard.

### Serveur web

`zing/web/server.py` est une application FastAPI créée par `create_app()` :

- **Pages.** L'interface classique (`/`, `/console`, `/history`, `/watches`,
  `/tools`) et la nouvelle interface (`/v2/`, `/v2/history`, `/v2/watches`,
  `/v2/tools`, `/v2/kb`) sont des fichiers HTML statiques. `?ui=v2` / `?ui=v1`
  bascule et un cookie mémorise le choix, de sorte qu'une URL classique redirige
  vers son équivalent une fois la nouvelle interface choisie.
- **API.** `/api/audit/stream` exécute un audit et diffuse ses événements en SSE ;
  `/api/models` liste les modèles d'un relais ; `/api/report/export` rend un
  rapport ; `/api/history…`, `/api/watches…`, `/api/kb…`, `/api/embed` et
  `/api/rerank` servent les autres pages.
- **Relais.** `POST /api/kb/relays` enregistre un relais `{name, base_url}` (400
  pour une saisie invalide, 409 si le nom ou l'URL est déjà connu).
- **Analyses.** `GET /api/analytics/options` (relais, modèles, suites, modes de
  flux, API et période couverte par l'historique), `/api/analytics/summary`
  (indicateurs de `from`–`to` face à la période précédente de même durée),
  `/api/analytics/series` (`metric` par `group=relay|model|relay_model`,
  jusqu'à 4 `keys`, en intervalles `bucket=hour|day|week|dow_hour` dans le
  fuseau horaire de l'utilisateur, `tz` ou `tz_offset` ; `dow_hour` accepte aussi `block` (heures par ligne) et
  `fold=week|4weeks|month_week`, qui revient à `week` tant que les exécutions
  ne couvrent pas 90 ou 180 jours) et
  `/api/analytics/leaderboard` (`model=` pour ses relais, ou `relay=` pour ses
  modèles). Tous acceptent les filtres `from`, `to`, `suite`, `stream_mode`,
  `api`, `source=all|manual|monitor`, `relay` et `model`.
  `zing/web/analytics.py` calcule tout en Python à partir de
  `history.analytics_runs()` : les identifiants de métrique viennent d'une
  liste fixe, les relais sont regroupés par leur entrée de la base de
  connaissances au moment de la requête, une valeur qu'une exécution n'a pas
  mesurée est laissée de côté (chaque valeur porte son `n` et sa `coverage`), et
  les intervalles de moins de `MIN_RUNS` (3) exécutions sont marqués `low_n`. Un
  paramètre invalide répond 400 ; les réponses sont en `Cache-Control: no-store`.
- **Panneaux d'analyse.** `/api/analytics/breakdown` (jusqu'à 8 `metrics` par
  `group=relay|model|relay_model|all` sur la période), `/api/analytics/errors`
  (les appels de complétion de la cible par classe de résultat
  `success|client_4xx|rate_limited|server_5xx|timeout|network|other`, par
  `group=relay|model` et par `bucket`, comptés en SQL par
  `history.analytics_request_classes()` sans charger les lignes de requêtes ;
  l'heure d'un appel est le début de son audit plus son décalage, à la minute ;
  `covered` = audits qui ont des enregistrements de requêtes) et
  `/api/analytics/integrity` (nombres de réussites / avertissements / échecs des
  détecteurs d'identité, de capacités, de vision, de streaming, de protocole,
  d'intégrité, de prompt injecté et de connectivité par relais × modèle, la part
  de modèles divergents et le rapport médian fenêtre de contexte mesurée /
  déclarée). `/api/analytics/series` accepte aussi `group=all`. Mêmes filtres et
  erreurs que ci-dessus.
- **Audits en arrière-plan.** `jobs.py` exécute chaque audit comme une tâche
  du serveur. `POST /api/jobs` en met une en file, `GET /api/jobs` liste les
  tâches en attente, en cours et récemment terminées (et les surveillances en
  cours) avec leur progression, `GET /api/jobs/{id}/events` rejoue le journal
  d'événements puis le suit en direct en SSE, et `POST /api/jobs/{id}/cancel`
  l'arrête. La nouvelle interface les utilise, un audit survit donc à la page ;
  `/api/audit/stream` (interface classique) enveloppe la même tâche et l'annule
  à la fermeture du flux. Un verrou par relais ne laisse qu'un audit (ou une
  exécution de surveillance) à la fois utiliser un relais, par nom d'hôte, toutes
  les adresses loopback comptant pour un hôte ; au plus
  `ZING_MAX_PARALLEL_AUDITS` (4 par défaut) en même temps, par ordre d'arrivée.
- **Planificateur des surveillances.** Le lifespan de l'application lance une
  boucle d'arrière-plan qui démarre chaque surveillance due comme sa propre
  tâche, si bien que les surveillances de relais différents auditent en même
  temps ; le verrou par relais s'applique toujours, donc les surveillances
  peuvent occuper les créneaux `ZING_MAX_PARALLEL_AUDITS` et un audit manuel peut
  attendre derrière elles. Le `last_run_ts` d'une exécution est le moment où son
  audit démarre (après l'attente de son relais). Chaque exécution est enregistrée
  dans l'historique ; la détection de régression la compare avec la plus récente
  exécution enregistrée de la même cible et du même modèle
  (`history.latest_for()`, une seule recherche indexée) et envoie les alertes
  webhook (`zing/notify.py`) en parallèle en cas de franchissement de seuil ou de
  régression. `POST /api/watches/{id}/run` répond 409 lorsque le planificateur
  vient de démarrer cette surveillance ; une réinitialisation de la clé
  maîtresse annule les exécutions planifiées qui n'ont pas encore démarré, et
  l'arrêt du serveur annule les exécutions en cours.
- **Compression et cache.** `caching.py` compresse en gzip les réponses de
  1 KiB ou plus (sauf les Server-Sent Events) pour les clients qui l'acceptent
  (`gzip;q=0` le refuse). Les pages et `/locales.js` sont compressés une seule
  fois, à leur construction, et servis précompressés avec
  `Content-Encoding: gzip`, `Vary: Accept-Encoding` et un ETag distinct se
  terminant par `-gz` ; les pages sont servies via `html_page(page,
  request.scope)` pour emprunter ce chemin et répondre 304 aux requêtes
  conditionnelles. Les URL des scripts et feuilles de style locaux dans les
  pages portent un `?v=<content hash>` et sont mises en cache comme immuables.
- **Sécurité.** `security.py` détermine l'adresse d'écoute (boucle locale
  uniquement, sauf dans un conteneur détecté avec `ZING_CONTAINER=1`) et installe
  `LocalOnlyMiddleware` : une liste d'hôtes autorisés contre le DNS rebinding,
  des contrôles d'`Origin` et de `Sec-Fetch-Site` contre le CSRF, des corps de
  requête JSON uniquement, et des en-têtes anti-cadre / no-sniff / no-referrer.
  L'interface n'a volontairement pas de connexion.

### Interface web côté navigateur

L'interface est en HTML, CSS et JavaScript de navigateur simples, sans modules ni
étape de build. Les pages classiques sont dans `zing/web/static/` ; la nouvelle
interface, dans `zing/web/static/v2/`, partage un en-tête (`nav.js`), le rendu
de rapport (`report.js`), le sélecteur de thème (`theme.js`) et les styles
(`tokens.css`, `zing.css`, `fields.css`, `report.css`, `perf.css`). Les scripts partagés sont
servis depuis la racine : `lang.js` (choix de la langue), `locales.js` (données
de traduction), `i18n.js` (traduction des constats), `icons.js`,
`modelpicker.js` (**Récupérer les modèles**), `secretfield.js` et `perf.js`
(graphiques de performance).

Les pages v2 **Audit** et **Outils** configurent les relais avec
`v2/relaycfg.js` : choix du relais/fournisseur → URL de base → les modèles du
relais (`/api/models`, au changement, mis en cache par URL/clé/protocole) → modèle
annoncé depuis la base de connaissances (`/api/kb/resolve` le présélectionne) →
fournisseur déduit, plus **Enregistrer dans la base** (`POST /api/kb/relays`). Ses
fonctions pures sont testées sous node ; les pages classiques gardent
`modelpicker.js`.

La page v2 **Analyses** (`v2/analytics.html`) ne lit que `/api/analytics/*`
(`options` liste aussi les paires relais × modèle, `relay_models`, pour le choix
des séries). Elle a une `<section class="card panel">` par panneau sous une
seule barre de filtres, de nouveaux panneaux s'y ajoutent donc ; filtres et vue
sont dans le fragment de l'URL (`#range=30&metric=score&…`) et dans
`localStorage`. Les graphiques viennent de `v2/charts.js`
(`ZingCharts.timeChart` : SVG en ligne dessiné à la main avec ligne médiane,
bande p25–p75, trous pour les intervalles vides, marqueurs atténués pour les
intervalles `low_n`, lignes d'annotation et infobulle au survol ; `fmt` /
`fmtDelta` formatent les valeurs selon l'unité) et de `v2/charts.css` (quatre
couleurs de série validées par thème, distinguées aussi par la forme des
marqueurs). Chaque graphique existe aussi en tableau de données.

Chaque panneau est autonome : un registre `PANELS` dans le script de la page
indique l'id de sa section, `load()` (récupérer avec les filtres et la vue
actuels, puis dessiner) et `render()` (redessiner à partir des données chargées,
p. ex. au changement de langue), si bien que les panneaux peuvent être
réorganisés sans se toucher. `ZingCharts.heatmap` dessine la grille jour de la
semaine × heure (échelle séquentielle à une teinte en cinq paliers par thème,
cases hachurées pour `low_n`, cases vides en contour), `ZingCharts.stackBars`
les barres d'erreurs empilées, et `timeChart` accepte une ligne `ref` (ratio de
facturation de 100 %).

L'en-tête de la page et le panneau de filtres sont au-dessus de cinq onglets
internes (`v2/tabs.js`, comme sur Outils et Connaissances) : chaque
entrée de `PANELS` nomme son `tab`, et seuls les panneaux de l'onglet affiché se
chargent ; un changement de filtre recharge cet onglet et marque les autres
comme périmés (`activate()` les charge à l'affichage). `tabs.js` reçoit ici
`writeHash: false`, car la page écrit elle-même toute la vue dans le fragment —
`#tab=trends&range=30&suite=…&metric=…` (`stateQuery()`), que **Copier le lien
vers cette vue** copie (un champ en lecture seule sélectionné si l'API du
presse-papiers manque ou refuse) ; un fragment sans `tab` ouvre la vue
d'ensemble, et un lien collé (`hashchange`) relit la vue. Le panneau de filtres
repliable est `v2/filterpanel.js` + `v2/filterpanel.css`, partagé avec
l'Historique : `ZingFilterPanel.create(section, {label, title, storeKey, open,
onReset})` renvoie `render({body, foot, count, summary})`,
`sync({count, summary})`, `setOpen()` et `focusStart()` ; la page possède ses
filtres et ses champs, le panneau le bouton avec le badge des filtres actifs, le
résumé d'une ligne affiché une fois replié, l'état ouvert mémorisé et
**Réinitialiser les filtres**.

**Convention de traduction.** Le texte chinois écrit dans le HTML est l'original
et reste intact ; chaque élément porte son texte anglais dans `data-en` (et
`data-en-placeholder`, `data-en-title`, `data-en-aria-label`). Le texte anglais
sert de clé de recherche pour toutes les autres langues. Les scripts utilisent
`T(zh, en)` pour le texte dynamique et `ZING_LANG.server(text)` pour le texte
venant du backend (noms des détecteurs, recommandations, phrases du verdict).

### Données locales

`zing/datadir.py` gère `$ZING_DATA_DIR` (par défaut `~/.zing`), créé en `0700`,
avec des fichiers SQLite en `0600` : `history.db` (`web/history.py`),
`watches.db` (`web/watches.py`, qui contient, chiffrées, les clés API des
surveillances) et `kb.db` (`knowledge/store.py`). Chaque appel ouvre une
connexion de courte durée ; les stockages sont donc sûrs dans le pool de threads
de FastAPI. L'option globale `--data-dir` (aussi sur `zing serve`) se contente de
définir `ZING_DATA_DIR` avec le chemin absolu, et `zing data-dir` affiche le
répertoire résolu. Un répertoire qui existe déjà garde ses droits ; seul le
`~/.zing` par défaut est restreint à `0700`. Les lignes de l'historique sont
indexées par cible et par modèle (`idx_history_target`), index qu'utilise
`history.latest_for()` pour trouver l'exécution précédente d'une surveillance.

Depuis la version 2 du schéma (`PRAGMA user_version`), `history.db` contient
aussi les tables d'analyse, définies dans `web/analytics_store.py` :
`history_metrics` (une ligne de métriques extraites par exécution : heure de
début, taux, percentiles de latence/TTFT/décodage, ratios de facturation, nombre
de constats et plus ; NULL là où l'exécution n'a pas mesuré une valeur),
`history_dimensions` (scores des dimensions et des détecteurs) et
`history_requests` (les enregistrements de requêtes de l'exécution, cible et
baseline, dans l'ordre de la liste). Les `performance.requests` d'un rapport ne
sont stockés que là : `save()` les retire de `report_json` (`requests_split`
marque la ligne) et `get()` / `latest_for()` les remettent en place, si bien
qu'un rapport se relit identique à celui enregistré ; ce que les colonnes ne
peuvent pas reproduire exactement va dans la colonne JSON `extra`.
`extract_metrics()` est pure et versionnée (`EXTRACT_VERSION`). Après la
migration, un backfill par lots (une transaction courte par lot, idempotent)
déplace les enregistrements des lignes plus anciennes, extrait leurs métriques
et ré-extrait les lignes écrites par une `EXTRACT_VERSION` antérieure ;
`history.backfill_analytics()` le relance à la demande. L'heure de début d'une
exécution est le `started_at` du rapport ; les rapports antérieurs à ce champ
reçoivent `generated_at` moins la durée couverte par leurs enregistrements de
requêtes (`started_at_estimated` = 1).

Les clés API enregistrées sont chiffrées par `zing/secretbox.py` (Fernet,
stockées sous la forme `enc:v1:…` ; les références `env:`/`file:` restent telles
quelles). La clé maîtresse elle-même n'est jamais stockée : `web/masterkey.py`
(`Vault`, partagé par le serveur et `zing secret`) la garde dans la mémoire du
serveur dès qu'elle vient de `ZING_SECRET_KEY`, d'un ancien `secret.key` ou de
l'utilisateur sur la page Surveillances, et `watches.db` ne conserve qu'une
valeur de contrôle (`secret_meta`) qui refuse une mauvaise clé. Une nouvelle clé
rechiffre chaque clé stockée et réécrit la valeur de contrôle en une seule
transaction. La clé vit dans la mémoire d'un seul processus : faites tourner un
serveur par répertoire de données.

## Contribuer

### Pull requests

- Gardez `pytest`, `ruff check zing tests` et `mypy zing` au vert (la CI exécute
  les trois sous Python 3.10–3.13).
- Décrivez l'astuce de relais ou le faux positif que la modification traite.
- Mettez à jour `CHANGELOG.md` sous `[Unreleased]`.
- Mettez à jour la documentation concernée — README, ce guide, la Méthodologie —
  dans **chaque langue** (voir [Documentation](#documentation)).

En contribuant, vous acceptez que vos contributions soient placées sous la
licence [Apache-2.0](LICENSE) du projet.

### Ajouter un détecteur

1. Créez `zing/detectors/<name>.py` et importez-le dans
   `zing/detectors/__init__.py`.
2. Définissez son `SCALE` (`Scale` ou `DeductionScale` de `scale.py`) avec chaque
   résultat de chaque vérification, et ne créez de constats que par lui.
3. Dérivez de `Detector` ; définissez `id`, `name`, `dimension`, `min_suite` et
   `cost_hint` ; mettez `requires_judge = True` ou `requires_baseline = True` s'il
   a besoin d'un juge ou d'une référence, ou redéfinissez `applies()` pour
   d'autres conditions. Décorez la classe avec `@register`.
4. Implémentez `async def run(self, ctx) -> DetectorResult` en partant de
   `self.new_result(scoring=SCALE.scoring())`. Envoyez les requêtes via
   `ctx.client` et prenez chaque prompt dans `zing/prompts/en.json`.
5. Ajoutez des tests de comportement pour le chemin signalé comme pour le chemin
   sain, avec le relais simulé de `tests/conftest.py`.
6. Traduisez les nouveaux titres et résumés de constats (voir
   [Traductions](#traductions)) et documentez le détecteur et son barème dans
   chaque fichier de [Méthodologie](docs/METHODOLOGY.fr.md).

### Modifier la base de connaissances

Les profils se trouvent dans `zing/knowledge/data/<provider>.yaml`, un fichier par
fournisseur. Chaque modèle porte sa fenêtre de contexte native, sa sortie
maximale, sa date de coupure des connaissances, son tokenizer, ses modalités, ses
capacités, ses paramètres non pris en charge, ses mots-clés d'identité et ses
empreintes (voir `zing/knowledge/schema.py`). Lorsque vous modifiez un champ
numérique, **citez une source faisant autorité** (fiche officielle du modèle,
tarifs ou documentation du fournisseur) dans la pull request : une valeur erronée
provoque des faux positifs contre des relais honnêtes.
`zing kb-import --check <fichier>` effectue les mêmes vérifications que l'import
utilisateur (schéma, limites, expressions régulières dangereuses, prompts,
collisions d'identifiants).

Les `fingerprints` au niveau du fournisseur s'exécutent sur chacun de ses
modèles. Une sonde dont l'attente ne vaut que pour certains modèles (une date de
coupure, un test de connaissances du niveau Pro, un piège de raisonnement) va
dans les `fingerprints` de ces modèles, sinon la réponse véridique d'un autre
modèle compte comme une divergence.

Renseignez toujours `identity_keywords` avec les mots du fabricant et de la
famille par lesquels le modèle se désigne. Le contrôle d'identité compte aussi
la clé du fournisseur, le nom affiché et l'id du modèle comme vraie marque,
élargis aux autres noms du fabricant dans `VENDOR_BRANDS`
(`zing/knowledge/identity.py`, qui est aussi la liste de marques concurrentes du
détecteur) ; l'import complète les mots-clés vides à partir de ces noms avec un
avertissement. Les mots de marque d'un nouveau fabricant s'y ajoutent en un
groupe.

### Modifier les prompts des sondes

Les textes des sondes sont des données de calibrage. En modifier un dans
`zing/prompts/en.json` peut changer les vérifications de réponses, les
estimations de tokens et donc les verdicts ; ajustez le détecteur et ses tests en
conséquence et mentionnez le changement dans le CHANGELOG. Ne faites jamais
suivre la langue de l'interface à une sonde.

### Traductions

L'interface et les alertes webhook partagent un même jeu de traductions dans
`zing/i18n/locales/<code>.json` :

- `meta` — code, nom de la langue dans sa propre langue pour le menu, langue
  `html`, locale des dates et ordre dans le menu ;
- `strings` — texte anglais → traduction (`en.json` est l'application identité et
  la liste de référence des textes traduisibles) ;
- `findings` — id du constat → `[titre, modèle de résumé]` (`zh.json` contient le
  catalogue chinois d'origine).

Les fonctionnalités peuvent livrer leurs textes sous forme de fragments,
`zing/i18n/locales/fragments/<feature>/<code>.json` contenant
`{"strings": {…}}`, fusionnés dans la langue au chargement. `/locales.js`
n'envoie que la langue choisie (`?lang=<code>` ou le cookie `zing_lang` posé par
`lang.js` ; sans l'un ni l'autre, toutes les langues), construit et compressé
en gzip une seule fois par variante et revalidé par `ETag` ; un changement de
langue charge la nouvelle à la demande.

- **Nouveau texte d'interface :** écrivez le chinois dans le HTML et l'anglais
  dans `data-en` (ou utilisez `T(zh, en)`), puis ajoutez la clé anglaise à
  `en.json` ou à un fragment et sa traduction dans chaque autre langue.
- **Nouvelle langue :** ajoutez `zing/i18n/locales/<code>.json` (copiez
  `de.json`) et un fichier par fragment ; le menu, les pages, les alertes et
  `--alert-lang` la prennent en compte.
- `tests/test_web_locales.py` échoue tant que chaque texte d'interface et chaque
  constat n'est pas traduit avec ses espaces réservés et son balisage intacts.

**Vocabulaire.** Un terme a une seule traduction par langue. Réutilisez le
vocabulaire que l'interface emploie déjà (noms de pages, noms des dimensions,
libellés de risque, libellés des boutons) dans les nouveaux textes et dans la
documentation.

### Documentation

La documentation existe en sept langues — anglais, chinois (`zh-CN`), français,
espagnol, portugais, italien et allemand :

| Fichier | Public |
|---|---|
| `README.md`, `README.<lang>.md` | Utilisateurs : ce que fait zing, installation, utilisation de la CLI et de l'interface web |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Contributeurs : architecture, installation, contribution, Docker, versions |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Tout le monde : chaque vérification, son barème et ses réserves |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Pages de référence (en anglais) |

Les fichiers anglais font référence. Lorsque vous en modifiez un, modifiez les
autres dans la même pull request, et utilisez dans chaque langue le vocabulaire de
l'interface (cherchez le terme dans `zing/i18n/locales/`). Les fichiers
METHODOLOGY reprennent les barèmes avec la formulation que l'interface affiche
sous **Barème**.

## Tests

```bash
pytest                       # tout
pytest tests/test_billing.py # un module
pytest -k streaming          # par mot-clé
pytest -n auto               # en parallèle, un worker par CPU (pytest-xdist)
```

- `tests/conftest.py` fournit `MockServer`, un endpoint compatible OpenAI sur
  `httpx.MockTransport` avec des réglages pour chaque écart que zing traque
  (modèle servi, auto-identification, troncature du contexte, faux streaming,
  usage absent ou gonflé, appels d'outils, mode JSON, …). Chaque réglage est par
  défaut celui d'un relais honnête.
- Les clients Anthropic et Responses ont leurs propres tests
  (`test_anthropic.py`, `test_responses.py`) ; le serveur web est testé via le
  client de test de FastAPI (`test_web*.py`), y compris les protections
  locales (`test_web_security.py`).
- Les scripts du navigateur (`lang.js`, `modelpicker.js`, `v2/relaycfg.js`, `perf.js`,
  `secretfield.js`, `v2/report.js`, les traductions) sont évalués sous `node`
  dans `test_web_*_js.py` et `test_web_locales.py` ; ils sont ignorés sans
  Node.js.
- Aucun test ne doit accéder au réseau.
- `test_cli_startup.py` garde un démarrage rapide de la CLI : importer
  `zing.cli` ne doit charger ni les clients HTTP, ni le runner, ni le chargeur
  de la base de connaissances, ni les rendus de rapport (ReportLab), ni le
  serveur web. Importez-les dans la commande qui en a besoin.
- `test_filler_perf.py` fige le texte de remplissage octet par octet et échoue
  lorsque la sonde de fenêtre de contexte bloque la boucle d'événements.
- `tests/a11y/` vérifie la nouvelle interface web selon BITV 2.0 / EN 301 549 /
  WCAG 2.1 AA dans un vrai navigateur (Playwright + axe-core), dans chaque langue
  de l'interface et les deux thèmes : `pip install -e '.[web,a11y]' && playwright
  install chromium`, puis `pytest -m a11y`. Sans Playwright, le répertoire est
  ignoré. Ce qui est automatisé et ce qui demande encore une revue BITV manuelle
  est décrit dans [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md).
- `ZING_A11Y_PAGES=history,kb` n'exécute que les tests a11y de ces pages (et
  les vérifications qui couvrent toutes les pages) ; `python -m
  tests.a11y.affected --base origin/main --head HEAD` affiche les pages
  touchées par une modification. Les deux utilisent une seule correspondance,
  `tests/a11y/pages.py` : une nouvelle page s'ajoute à ses `PAGES` et `RULES`
  ([tests/a11y/README.md](tests/a11y/README.md)).

## Docker

Le `Dockerfile` construit une image de l'interface web (Python 3.12 slim avec
l'extra `web` ; les rapports PDF ne demandent aucun paquet système). Elle
s'exécute sous un utilisateur non privilégié, avec le répertoire de données dans
`/data`.

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# ouvrir http://localhost:8000
```

**Publiez toujours sur `127.0.0.1`.** Un simple `-p 8000:8000` publie l'interface —
et chaque clé API qui y est saisie ou stockée dans une surveillance — sur votre
réseau. Dans le conteneur, le serveur doit écouter sur toutes les interfaces ;
ce n'est autorisé que si `ZING_CONTAINER=1` est défini (l'image le fait) *et*
qu'un environnement de conteneur est détecté.

| Variable | Défaut | Rôle |
|---|---|---|
| `ZING_CONTAINER` | non défini (`1` dans l'image) | Autorise une écoute hors boucle locale dans un conteneur détecté |
| `ZING_HOST` | `127.0.0.1` (`0.0.0.0` dans l'image) | Adresse d'écoute ; `--host` l'emporte |
| `ZING_PORT` | `8000` | Port ; `--port` l'emporte |
| `ZING_DATA_DIR` | `~/.zing` (`/data` dans l'image) | Historique, surveillances (leurs clés chiffrées) et vos entrées de la base de connaissances ; montez-y un volume. `--data-dir` l'emporte |
| `ZING_SECRET_KEY` | non défini | Clé maîtresse des clés API enregistrées des surveillances (une clé, ou `file:/run/secrets/…` / `env:VAR`) ; non définie, la page Surveillances la demande après chaque démarrage. Jamais stockée dans `ZING_DATA_DIR` |
| `ZING_KB_DIR` | non défini | Répertoire YAML supplémentaire pour la base de connaissances, p. ex. `-v ./profiles:/kb:ro -e ZING_KB_DIR=/kb` |
| `ZING_NO_USER_KB` | non défini | `1` ignore vos propres entrées de la base de connaissances (`kb.db`) |
| `ZING_ALLOWED_HOSTS` | non défini | Noms d'hôte supplémentaires auxquels l'interface répond, séparés par des virgules |

[docs/DOCKER.md](docs/DOCKER.md) est la référence complète (en anglais), y compris
ce qui protège l'interface.

## Intégration continue

| Workflow | Déclenché par | Rôle |
|---|---|---|
| `.github/workflows/ci.yml` | push et pull request vers `main` (et les branches d'intégration `a11y/integration`, `perf/integration`) ; chaque nuit et manuel (accessibilité seulement) | `ruff`, `mypy` et `pytest` sous Python 3.10–3.13 avec les extras `dev` et `web` ; construit la wheel et la sdist et vérifie que la wheel s'installe et charge la base de connaissances ; exécute la suite d'accessibilité (à titre informatif, elle ne fait jamais échouer l'exécution) et téléverse ses constats : toutes les pages sur les push et les exécutions nocturnes et manuelles (avec le rapport de conformité BITV), sur les pull requests seulement les pages touchées par la modification (aucune si seule la documentation change) — sauf sur les pull requests vers `perf/integration`, où la lente suite navigateur est ignorée (elle s'exécute sur les push de cette branche et sur sa pull request vers `main`) |
| `.github/workflows/release.yml` | un tag `v*` | construit, exécute `twine check` et publie sur PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | planification quotidienne, manuel | exemple d'audit de relais planifié avec l'action |

L'action composite elle-même est `action.yml`, documentée dans
[docs/CI.md](docs/CI.md).

## Publication des versions

1. Renommez `[Unreleased]` dans `CHANGELOG.md` en la nouvelle version et
   incrémentez `version` dans `pyproject.toml`.
2. Committez, créez le tag `vX.Y.Z` et poussez-le ; `release.yml` publie sur PyPI.
3. Créez la release GitHub avec les notes du CHANGELOG et mettez à jour la
   version épinglée de l'action dans les README et `docs/CI.md`.

La configuration initiale de PyPI et la procédure manuelle se trouvent dans
[docs/PUBLISHING.md](docs/PUBLISHING.md).

## Sécurité

Signalez les vulnérabilités en privé, comme décrit dans [SECURITY.md](SECURITY.md).
Sont notamment concernés : une clé ou un secret qui atteint un rapport, du texte
contrôlé par le relais qui injecte du balisage dans un rapport ou dans
l'interface, un trafic vers autre chose que les endpoints configurés, et tout
contournement des protections locales de l'interface web.

## Licence

[Apache-2.0](LICENSE)
