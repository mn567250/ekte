# zing — vérification de la réalité des relais LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · **🇫🇷 Français** · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** est un outil local d'abord qui vérifie si un relais d'API (revendeur /
proxy) sert réellement le modèle qu'il annonce — ou s'il lui substitue en douce
un modèle moins cher, tronque votre fenêtre de contexte, simule le streaming ou
gonfle la facturation des tokens. Bref : obtenez-vous ce pour quoi vous payez ?
Il parle l'**API OpenAI Chat Completions**, l'**API Anthropic Messages** et
l'**API OpenAI Responses** (`/v1/responses`) — détectées automatiquement, ou
imposées avec `--api openai|anthropic|responses`.

Vous lui donnez l'endpoint d'un relais et le modèle qu'il prétend servir ; zing
exécute une batterie de sondes en boîte noire, compare le comportement observé à
une base de connaissances intégrée de **98 profils de modèles de 7
fournisseurs**, et rend un verdict clair, étayé par des preuves — en ligne de
commande, dans une interface web locale ou en JSON pour un autre outil ou LLM.

> zing fournit **des preuves en boîte noire d'écarts et de risques, pas une
> preuve cryptographique de fraude.** Voir [Utilisation responsable](#utilisation-responsable).

Ce README s'adresse à celles et ceux qui **utilisent** zing. La façon dont zing
est construit, testé et publié est décrite dans le
[Guide du développeur](DEVELOPER_GUIDE.fr.md) ; le fonctionnement et la notation
de chaque vérification dans la [Méthodologie](docs/METHODOLOGY.fr.md).

---

## Sommaire

- [Pourquoi](#pourquoi)
- [Installation](#installation)
- [Démarrage rapide](#démarrage-rapide)
- [Interface web (`zing serve`)](#interface-web-zing-serve)
- [Ce qui est vérifié](#ce-qui-est-vérifié)
- [Comment le verdict est établi](#comment-le-verdict-est-établi)
- [Suites](#suites)
- [Performance](#performance)
- [Mode comparaison et juge LLM](#mode-comparaison-et-juge-llm)
- [Surveillance](#surveillance)
- [Audits d'embedding, de rerank, d'images et d'audio](#audits-dembedding-de-rerank-dimages-et-daudio)
- [Utilisation en CI (GitHub Action)](#utilisation-en-ci-github-action)
- [Base de connaissances](#base-de-connaissances)
- [Rapports](#rapports)
- [Confidentialité et données locales](#confidentialité-et-données-locales)
- [Utilisation responsable](#utilisation-responsable)
- [Documentation complémentaire](#documentation-complémentaire)
- [Licence](#licence)

## Pourquoi

Le marché des clés de relais regorge d'offres du type « GPT-4o à un dixième du
prix ». Beaucoup sont honnêtes. Certaines ne le sont pas — et les malhonnêtes
sont difficiles à repérer à l'œil nu :

- Vous demandez `gpt-4o` ; on vous sert discrètement `gpt-4o-mini` ou un modèle ouvert.
- Le relais annonce un contexte de 1M de tokens mais tronque en silence à 32K.
- Le « streaming » est la réponse complète mise en tampon puis redécoupée, sans aucun gain de latence.
- Les tokens `usage` déclarés sont gonflés, et votre solde fond plus vite qu'il ne devrait.
- Un modèle censé prendre en charge l'appel d'outils / le mode JSON ne le fait discrètement pas.

zing transforme un « quelque chose cloche » en rapport reproductible.

## Installation

Nécessite Python 3.10+. Chacune des options ci-dessous fournit la commande `zing`.

### Avec pip

```bash
# depuis PyPI
pip install zing-audit

# ou depuis les sources
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### Avec [uv](https://docs.astral.sh/uv/)

```bash
# depuis PyPI, comme outil autonome dans votre PATH
uv tool install zing-audit

# ou l'exécuter une fois sans l'installer
uvx --from zing-audit zing --help

# ou depuis les sources, dans un environnement virtuel local au projet
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows : .venv\Scripts\activate
```

Vous pouvez aussi installer directement depuis le dépôt Git sans le cloner :
`uv tool install git+https://github.com/cenbonew/zing`.

### Extras optionnels

- `web` — l'interface web locale (`zing serve`).

```bash
pip install 'zing-audit[web]'      # pip, depuis PyPI
pip install -e '.[web]'            # pip, depuis les sources
uv tool install 'zing-audit[web]'  # uv, depuis PyPI
uv pip install -e '.[web]'         # uv, depuis les sources
```

L'extra `tokenizers` n'est plus nécessaire : depuis la 0.19.0, il est vide et
n'est conservé que pour que les anciennes commandes d'installation fonctionnent
encore. zing compte les tokens avec une heuristique intégrée et ne télécharge
rien à l'exécution (aucun fichier de tokenizer), si bien qu'il fonctionne aussi
dans des environnements restreints ou hors ligne qui n'atteignent que les relais
que vous auditez.

Les rapports PDF (`--format pdf` et le téléchargement PDF de l'interface web) ne
demandent aucun extra : ils sont composés avec
[ReportLab](https://www.reportlab.com/opensource/), une dépendance en pur Python,
sans bibliothèque système sous Linux, macOS ou Windows.

### Avec Docker (interface web uniquement)

Depuis une copie des sources :

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# ouvrir http://localhost:8000
```

Publiez toujours le port sur `127.0.0.1` comme ci-dessus. Détails et variables
d'environnement : [Guide du développeur → Docker](DEVELOPER_GUIDE.fr.md#docker) et
[docs/DOCKER.md](docs/DOCKER.md).

## Démarrage rapide

```bash
# 1) auditer un relais par rapport à ce qu'il annonce (id du modèle + indice de fournisseur)
export ZING_API_KEY=sk-votre-cle-relais
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) le contrôle le plus fort : comparer à une référence de confiance du même modèle
export OPENAI_API_KEY=sk-votre-cle-openai
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) auditer un relais natif Anthropic (API Messages) — le protocole est détecté
#    automatiquement à partir de base_url/model, ou imposé avec --api anthropic
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) confirmer une substitution suspectée : auditer l'id RÉEL du modèle du relais par
#    rapport au profil sous lequel il est vendu (ici : un modèle Doubao vendu comme deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) lister les modèles qu'un endpoint annonce
zing models --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY

# 6) consulter la base de connaissances
zing kb            # tous les profils, avec leur source
zing kb deepseek   # un fournisseur

# 7) générer une configuration que vous pouvez versionner
zing init          # écrit zing.yaml
zing check -c zing.yaml
```

Les clés d'API peuvent être données en clair, sous la forme `env:VAR` ou
`file:/chemin` ; les rapports ne contiennent jamais qu'une empreinte de la clé. Un
fichier de configuration complet se trouve dans [`examples/zing.yaml`](examples/zing.yaml).

### Comme outil pour un LLM / agent

zing est conçu pour être piloté par un autre programme ou modèle. Tout part sur
stdout en JSON, erreurs comprises, et le code de sortie sert de verrou.

```bash
# verdict léger, adapté aux agents (~5x plus petit que --json : sans les preuves volumineuses)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# rapport structuré complet lorsque vous avez besoin des preuves de chaque constat
zing check --base-url ... --model gpt-4o --json

# budget d'abord : quels détecteurs s'exécutent + appels d'API estimés, SANS en faire aucun
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# verrou sur le code de sortie (1 si risque >= medium, ou score sous --fail-under) ;
# les erreurs de config/usage sortent en 2, en JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# découverte lisible par machine
zing kb --json                      # toute la base de connaissances
zing models --base-url ... --json   # ce qu'un endpoint annonce
```

En mode `--json`/`--compact`, une configuration erronée affiche `{"error": {...}}`
(code de sortie 2) au lieu d'un message lisible, afin qu'un pipeline puisse
traiter les échecs de façon uniforme.

## Interface web (`zing serve`)

Vous préférez cliquer ? Une interface web locale enveloppe le même moteur — sans
ligne de commande.

```bash
pip install 'zing-audit[web]'     # ou : uv tool install 'zing-audit[web]'
zing serve                        # ouvre http://localhost:8000
```

Dans la nouvelle interface, le formulaire guide la configuration :

1. Choisissez le **Relais / fournisseur** : un fournisseur de la base de
   connaissances ou un relais que vous avez enregistré. Son URL de base est
   remplie (les autres URL connues du fournisseur sont proposées en
   suggestions). Pour tout autre relais, choisissez **Autre (saisir l'URL)** et
   saisissez l'**URL du relais**.
2. Ajoutez la **Clé API** si le relais en demande une.
3. zing liste lui-même les modèles du relais (au choix d'un relais et à chaque
   changement d'URL ou de clé ; **Actualiser les modèles** redemande). Choisissez
   le **Modèle demandé**. Un relais sans liste de modèles revient à la saisie de
   l'identifiant (**Saisir manuellement**).
4. Choisissez en option le **Modèle annoncé** parmi les modèles de la base de
   connaissances : le modèle que le relais dit servir. Si le modèle demandé est
   dans la base, il est présélectionné ; ne le changez que si le relais vend le
   modèle sous un autre nom. Le profil de fournisseur utilisé pour l'audit en
   découle.

Un relais absent de la liste peut être conservé avec **Enregistrer dans la
base** sous le nom de votre choix ; la fois suivante, il suffit de le choisir.
La référence de confiance (**Comparer à une référence de confiance**) et la page
**Outils** se configurent de la même façon. L'interface classique garde les
champs simples avec **Récupérer les modèles**.

Puis **Lancer l'audit**
et suivez les vérifications **en direct** : chaque vérification affiche son score
et sa durée, et une vérification avec des constats se déplie pour montrer les
preuves. Le résultat est un rapport de verdict partageable : note, **Contrôles par
dimension** avec leurs barèmes, constats en langage clair et section performance
(dans la nouvelle interface aussi un **Journal d'exécution** de chaque détecteur).

Tout s'exécute sur votre machine : une clé saisie dans le navigateur n'atteint
que votre serveur zing local et le relais audité, jamais un tiers. Voir
[Confidentialité et données locales](#confidentialité-et-données-locales).

### Pages

L'interface web existe en deux versions qui partagent le même serveur et les
mêmes données. L'**interface classique** s'ouvre sur `/` ; son lien **Essayer la
nouvelle interface** passe à la **nouvelle interface** sous `/v2/`, dont le lien
**Interface classique** ramène à la première. Le choix est mémorisé par
navigateur.

| Page | Interface classique | Nouvelle interface | À quoi elle sert |
|---|---|---|---|
| **Audit** | `/` | `/v2/` | Auditer un relais (éventuellement face à une référence) et lire le rapport |
| **Console** | `/console` | — | Le même audit sous forme de console compacte, façon journal |
| **Outils** | `/tools` | `/v2/tools` | Audits d'embedding et de rerank |
| **Historique** | `/history` | `/v2/history` | Chaque audit exécuté sur cette machine, groupé par relais + modèle annoncé, avec tendances |
| **Surveillances** | `/watches` | `/v2/watches` | Ré-audits planifiés avec alertes webhook |
| **Connaissances** | — | `/v2/kb` | La base de connaissances en trois onglets — modèles, fournisseurs, relais : parcourir, activer/désactiver, ajouter les vôtres |

La nouvelle interface ajoute : des filtres et des tendances configurables (score,
note, latence p50, tokens/s) dans l'**Historique** ; **Planifier comme
surveillance** et **Relancer l'audit** sur chaque exécution de l'Historique ; **Télécharger le rapport**
dans tous les formats ; un sélecteur de thème (Automatique / Clair / Sombre) ; et
la page **Connaissances**.

**Audits en arrière-plan (nouvelle interface).** Un audit lancé depuis la page
**Audit** continue quand vous changez de page ou fermez l'onglet ; **Continuer en
arrière-plan** l'y envoie volontairement. L'**Historique** liste chaque audit en
file d'attente ou en cours (et chaque surveillance en cours) avec sa
progression ; **Suivre en direct** rouvre la vue en direct, qui rattrape tout ce
qui s'est déjà passé. Les audits d'un même relais s'exécutent l'un après
l'autre, pour ne jamais fausser leurs mesures de latence ou de fiabilité (toutes
les adresses loopback comptent comme un seul hôte : les modèles servis par votre
propre machine attendent aussi) ; les audits de relais différents s'exécutent
en parallèle, quatre au plus à la fois (`ZING_MAX_PARALLEL_AUDITS`). Les
surveillances attendent leur relais de la même façon.

### Langues

Un menu de langue dans l'en-tête de chaque page bascule l'interface entre
**🇬🇧 anglais** (par défaut), **🇨🇳 chinois** (l'interface d'origine),
**🇫🇷 français**, **🇪🇸 espagnol**, **🇵🇹 portugais**, **🇮🇹 italien** et
**🇩🇪 allemand** ; le choix est mémorisé par navigateur.

Les rapports téléchargés depuis l'interface (**Télécharger le rapport** : JSON,
Markdown, HTML ou PDF) suivent la langue choisie : les clés JSON, les valeurs
d'énumération (`risk_level`, `status`, `severity`, …), les identifiants et les
preuves restent exactement ceux du rapport de la CLI (le JSON reste un rapport
zing valide), tandis que les valeurs lisibles (titre et résumé du verdict, titres
et résumés des constats, recommandations, noms des détecteurs, notes) sont
traduites, et le nom du fichier porte la langue (`zing-report.fr.json`,
`zing-report.fr.pdf`). Les titres de section des fichiers Markdown/HTML/PDF
restent en anglais. Les rapports de la CLI `--format json|md|html|pdf` restent en
anglais.

**Les prompts envoyés à l'endpoint audité ne suivent pas la langue de
l'interface.** Tout texte que zing envoie à une API de LLM est en anglais, afin
que le même relais obtienne le même verdict quel que soit le lecteur du rapport
(les vérifications de réponses et les estimations de tokens sont calibrées sur
ces textes exacts). Seules exceptions : les empreintes de la base de
connaissances dont la langue *est* la mesure — par exemple les sondes de
fluidité en chinois, de tokenizer et d'auto-identification des modèles chinois.
Chaque rapport consigne les langues de sonde réellement utilisées
(`prompt_languages`, p. ex. `["en", "zh"]`).

## Ce qui est vérifié

zing note dix dimensions. Les trois **dimensions cœur** — identité du modèle,
fenêtre de contexte et capacités annoncées — révèlent le plus directement une
tromperie sur la marchandise et pèsent le plus lourd. Les noms sont ceux de
l'interface web et des rapports.

| Dimension | Id | Poids | Ce qu'elle détecte |
|---|---|---|---|
| **Identité du modèle** | `model_identity` | 21 | Déclassement ou substitution silencieuse du modèle — auto-identification, date de coupure des connaissances, empreintes de tokenizer, le champ `model` renvoyé ; en option un juge LLM |
| **Fenêtre de contexte** | `context_window` | 19 | Troncature silencieuse du contexte (1M annoncé, le rappel échoue à 32K) et « lost in the middle » dû à des couches RAG/résumé bon marché, par aiguille dans une botte de foin et recherche dichotomique |
| **Capacités annoncées** | `capability` | 13 | Appel d'outils / mode JSON / schéma JSON / sortie maximale annoncés mais non fournis (ou *sur*-fournis, signe d'un substitut) ; **vision** — un modèle annonçant l'entrée image doit lire une image générée à réponse connue |
| **Conformité du protocole** | `protocol` | 8 | Conformité sur le fil : multi-tours, séquences d'arrêt, schéma d'erreur ; chaque paramètre de requête accepté (et respecté quand c'est visible), chaque attribut de réponse présent ; cache de réponses qui ignore temperature/seed |
| **Facturation et consommation** | `billing` | 8 | Gonflement des tokens/de l'usage et comptabilisation absente ou invérifiable, via une estimation heuristique indépendante des tokens |
| **Connectivité** | `connectivity` | 7 | Joignabilité de l'endpoint et la liste `/v1/models` annoncée |
| **Authenticité du streaming** | `streaming` | 6 | Faux streaming (mise en tampon puis découpage), d'après le nombre de fragments et leur espacement |
| **Fiabilité en concurrence** | `reliability` | 6 | Taux de succès et latence sous charge concurrente (limitation HTTP 429 comptée à part) |
| **Sécurité du transport** | `security` | 6 | HTTPS, hygiène des en-têtes, écho de secrets ; prompt système injecté caché ; falsification en transit des réponses et des appels d'outils (canaris à réponse connue) ; cache de préfixe de prompt (timing) |
| **Performance** | `performance` | 6 | La *régularité* de la latence, du temps jusqu'au premier token et du débit, le taux d'échec et le ralentissement sous charge ; la vitesse seulement face à une référence (voir [Performance](#performance)) |

La [Méthodologie](docs/METHODOLOGY.fr.md) décrit chaque sonde, l'astuce de relais
à laquelle elle répond, son barème et ses réserves sur les faux positifs.

## Comment le verdict est établi

En bref (les détails sont dans la [Méthodologie](docs/METHODOLOGY.fr.md#comment-zing-note)) :

- Chaque détecteur publie son **barème** — chaque résultat possible de chaque
  vérification avec ses points — et l'interface web l'affiche sous **Barème**.
- Le **score d'une dimension** est la moyenne à poids égal des scores de ses
  détecteurs. Un constat ÉLEVÉ/CRITIQUE impose **Échec** et un constat MOYEN fait
  passer **Réussi** à **Avertissement**, quel que soit le score. Les rapports
  l'expliquent par dimension sous **Dimension details** ; dans l'interface web,
  chaque ligne des **Contrôles par dimension** se déplie sur les mêmes détails.
- Le **score de santé global** est la moyenne pondérée des dimensions exécutées
  (poids ci-dessus), notée A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) ou F.
- Le **verdict de risque** dépend de la gravité des constats, pas du score :

| Risque | Libellé dans l'interface | Quand |
|---|---|---|
| `inconclusive` | Signal insuffisant | Aucune dimension cœur n'a produit de résultat exploitable (relais injoignable, modèle absent de la base de connaissances, ou exécution `custom` sans dimension cœur) |
| `high` | Tromperie sur la marchandise | Un constat CRITIQUE, un constat ÉLEVÉ/CRITIQUE dans une dimension cœur, ou au moins deux constats ÉLEVÉS |
| `medium` | Écarts détectés | Exactement un constat ÉLEVÉ hors des dimensions cœur, ou un constat MOYEN dans une dimension cœur |
| `low` | Globalement fiable | Tout autre constat MOYEN |
| `clean` | Cohérent (probablement authentique) | Aucun des cas ci-dessus |

Les constats de la dimension connectivité n'élèvent jamais le risque : un relais
injoignable ou limité n'a pas pu être évalué, ce qui ne prouve pas qu'un autre
modèle répond. La **confiance** du verdict (faible / moyenne / élevée) augmente
avec le nombre de dimensions cœur ayant produit un résultat, avec une référence
et avec le juge LLM.

## Suites

| Suite | Détecteurs | Coût |
|---|---|---|
| `smoke` | connectivity, security | très faible |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | faible à moyen |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (avec `--judge`) | plus élevé (les sondes de contexte long et de timing coûtent des tokens) |
| `full` | les détecteurs de `deep`, performance mesurée avec et sans streaming | le plus élevé |
| `custom` | uniquement les dimensions choisies, à la profondeur de `deep` | selon la sélection |

La sonde de fenêtre de contexte est bornée par `--max-context-tokens` (200K par
défaut), afin que l'audit d'un modèle à 1M de tokens reste abordable. `--only` /
`--skip` exécutent ou écartent des détecteurs par leur id.

### Suite personnalisée

N'exécutez que les dimensions qui vous intéressent, ce qui économise du temps et
des tokens. Chaque détecteur de chaque dimension choisie s'exécute, comme en `deep` :

```bash
zing check --base-url ... --model gpt-4o -D protocol -D performance
zing check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` est répétable ou séparé par des virgules et implique
`--suite custom` ; dans un fichier de configuration, utilisez
`run.dimensions: [protocol, performance]`. Les dimensions sont `connectivity`,
`protocol`, `context_window`, `model_identity`, `capability`, `streaming`,
`billing`, `reliability`, `security` et `performance`. Dans l'interface web, le
bouton de suite `custom` ouvre le même choix (**Dimensions à exécuter**) sur la
page d'audit, la console et les surveillances.

Le **score global est la moyenne pondérée des seules dimensions choisies** ; les
dimensions laissées de côté apparaissent comme « non sélectionnées ». Le verdict
de risque exige au moins une dimension cœur (identité du modèle, fenêtre de
contexte, capacités annoncées) : sans elle, il est *non concluant*.

## Performance

Chaque rapport comporte une section **performance** : latence, temps jusqu'au
premier token (TTFT), tokens/s de décodage et de bout en bout, latence et gigue
entre fragments, taux d'erreurs/d'expirations/de 429, une décomposition réseau
(connexion TCP, TLS, un aller-retour `GET /models`, temps serveur) et démarrage à
froid, chacun en count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev.

Lorsque la sonde dédiée s'exécute, elle note la dimension **Performance**. Le
score porte sur la **régularité**, pas sur la vitesse brute : un endpoint lent
mais régulier (un modèle local ou auto-hébergé) n'est pas pénalisé de ne pas être
un centre de données :

| Vérification | Notée sur |
|---|---|
| régularité de la latence / du TTFT | ratio de queue p90 ÷ p50 (≤ 1,3 régulière 100 · ≤ 1,75 stable 85 · ≤ 2,5 variable 65 · au-delà : erratique 40) ; au moins 10 échantillons |
| régularité du débit | ratio de queue p50 ÷ p10 des tokens/s, mêmes seuils |
| erreurs | requêtes de sonde échouées : ≤ 2 % 100 · ≤ 10 % 80 · au-delà : 50 (429 non comptés) |
| stabilité sous charge | latence p50 en rafale ÷ p50 séquentielle : ≤ 1,5x 100 · ≤ 3x 80 · au-delà : 55 |
| accès au cache | prompts uniques servis depuis un cache : 60 |
| référence | tokens/s face à la référence de confiance, sinon à la plage publiée pour le modèle dans la base de connaissances : conforme 100 · plus lent 80 (informatif, jamais un échec) · ≥ 2x plus rapide 60 (signe d'un modèle plus petit) · pas de référence : non compté |

Les constats de performance sont au plus de gravité faible : ils font bouger le
score, jamais le verdict de risque. Sans la sonde (`standard` sans référence,
`smoke`), la dimension ne s'exécute pas et sort du score global.

- **standard** collecte la section à partir des requêtes de l'audit lui-même.
- **deep / full / custom** ajoutent une sonde dédiée : 100 requêtes non mises en
  cache de 128 tokens de sortie (un identifiant de requête aléatoire ouvre chaque
  prompt ; aucun paramètre de cache ou de raisonnement n'est envoyé) plus une
  rafale à `--concurrency`. Réglez-la avec `--performance-requests` (0 la
  désactive) et `--performance-max-tokens`.
- La sonde streame par défaut ; `--performance-non-streaming` (ou le sélecteur
  **Streaming / Sans streaming** de l'interface web) mesure les relais qui ne
  savent pas streamer. **full** mesure les deux modes, entrelacés, et les présente
  côte à côte.
- **compare** exécute la sonde sur les deux endpoints, en alternant les requêtes,
  et ajoute un tableau cible-vs-référence (5 requêtes par côté en `standard`, trop
  peu pour les vérifications de régularité) dont les différences sont marquées en
  vert ✓ quand la cible fait mieux et en rouge ✗ quand elle fait moins bien.

Les tokens sont comptés deux fois — depuis l'`usage` du relais et localement —,
si bien que le débit reste mesurable même sans `usage`. Le comptage local est
une estimation par une heuristique intégrée (environ ±15-20 % ; aucun tokenizer
n'est utilisé ni téléchargé), et la section l'indique toujours. Un percentile
n'est affiché qu'avec assez d'échantillons (p90 dès 10, p95 dès 20, p99 dès 100). Le
rapport JSON conserve les temps de chaque requête (des nombres uniquement, aucun
texte) ; le rapport HTML et l'interface web les tracent sur la chronologie de
l'audit.

Les audits qui s'exécutent en même temps dans `zing serve` (plusieurs onglets du
navigateur, surveillances) ne faussent pas leurs mesures de temps respectives :
la préparation gourmande en CPU, comme la construction des longs prompts de
fenêtre de contexte, s'exécute hors de la boucle d'événements du serveur.

**Délais des requêtes.** `timeout_sec` (`--timeout`, 60 s par défaut) sert de base ;
chaque requête reçoit du temps en plus selon la taille du prompt et le budget de
sortie, pour qu'une longue sonde de fenêtre de contexte ou un modèle auto-hébergé
lent ne soit pas coupé au bout d'une minute. Les hôtes locaux et privés
(`localhost`, `127.x`, `192.168.x`, `host.docker.internal`, …) ont au moins 300 s.
`max_request_sec` (`--max-request-time`, 900 s par défaut) est le plafond absolu
de chaque requête, flux compris, si bien qu'aucune requête ne peut rester bloquée
indéfiniment. Une sonde de fenêtre de contexte qui dépasse malgré tout son délai
est signalée comme non concluante, pas comme une troncature.

## Mode comparaison et juge LLM

zing dispose de deux modes de détection :

- **Code pur (par défaut) :** tous les détecteurs sauf `quality_judge` décident
  par du code déterministe — empreintes, balayage du contexte, arithmétique de
  facturation, timing du streaming. Aucun second modèle requis ; les résultats
  sont reproductibles.
- **Hybride code + LLM (`--judge`) :** interroge en plus un modèle juge *de
  confiance* (configuré séparément, jamais la cible) pour savoir si les réponses
  de la cible ressemblent au modèle annoncé — des signaux flous comme la qualité
  et la profondeur de raisonnement que le code seul ne peut trancher. C'est le
  détecteur `quality_judge`.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

Le **mode comparaison** (`zing compare`, ou **Comparer à une référence de
confiance** dans l'interface web) exécute les mêmes sondes, au même moment,
contre une référence de confiance du modèle annoncé. C'est la meilleure voie de
confirmation : réponses d'identité, paramètres de requête rejetés, canaris de
falsification et performance sont jugés côte à côte, et seule une référence
permet à la confiance du verdict d'être *élevée*. Sans `--judge-base-url`, le mode
comparaison utilise la référence comme juge.

## Surveillance

Un relais peut servir le vrai modèle aujourd'hui et le remplacer discrètement la
semaine prochaine. `zing watch` ré-audite selon un calendrier, enregistre chaque
exécution dans l'historique et alerte un webhook lorsque le risque franchit un
seuil ou **régresse** par rapport à l'exécution précédente.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang fr                                     # ou --once pour cron
```

Les alertes sont formatées pour **Slack / Feishu / DingTalk / JSON générique**,
détectés automatiquement à partir de l'URL du webhook, et rédigées dans la langue
des alertes — l'anglais par défaut ; `--alert-lang en|zh|fr|es|pt|it|de`. La
charge utile JSON générique garde ses clés et ses valeurs machine (`risk_level`,
`score`, …) neutres, traduit les valeurs lisibles (`text`, `headline`,
`key_findings`) et indique la `language`.

**Dans l'interface web**, `zing serve` exécute les mêmes surveillances dans un
planificateur en arrière-plan au sein du processus serveur, enregistre chaque
exécution dans l'**Historique** et envoie les mêmes alertes webhook :

- **Nouvelle interface :** ouvrez une exécution dans l'**Historique** et
  choisissez **Planifier comme surveillance**. zing copie la configuration de
  cette exécution (relais, modèle, modèle annoncé, fournisseur, suite, dimensions
  personnalisées) dans une surveillance en pause sur la page **Surveillances** ;
  définissez-y son intervalle et sa clé API (l'Historique ne stocke jamais de
  clés) puis activez-la. Intervalle, clé, **Seuil d'alerte**, webhooks et
  **Langue des alertes** se modifient directement sur chaque surveillance.
- **Interface classique :** remplissez le formulaire de la page
  **Surveillances** puis **Ajouter la surveillance**.

Chaque surveillance a sa propre langue d'alerte (par défaut celle de
l'interface), peut être exécutée maintenant, mise en pause ou supprimée, et
reste liée au profil de la base de connaissances avec lequel elle a été créée
jusqu'à ce que vous la reliiez à nouveau.

Les surveillances arrivées à échéance s'exécutent en même temps, chacune comme
son propre audit, mais jamais plus d'un audit à la fois par hôte de relais et au
plus `ZING_MAX_PARALLEL_AUDITS` au total ; une exécution attend qu'un créneau se
libère (un audit que vous lancez à la main peut aussi attendre derrière les
surveillances en cours). L'heure d'une exécution est celle où son audit démarre,
après une éventuelle attente. La détection de régression compare avec la plus
récente exécution enregistrée du même relais et du même modèle, quel que soit le
nombre d'autres exécutions enregistrées depuis. Les webhooks d'alerte d'une
exécution sont envoyés en même temps, si bien qu'un webhook lent ou hors service
ne retarde pas les autres. Les clés sont stockées chiffrées dans
votre répertoire de données local et ne sont jamais renvoyées au navigateur.

**Clé maîtresse.** Les clés API des surveillances sont chiffrées avec une clé
maîtresse que zing n'écrit jamais sur le disque. La première fois que vous
enregistrez une clé API, la page **Surveillances** la crée et l'affiche une
seule fois : copiez-la ou téléchargez-la, conservez-la dans un gestionnaire de
mots de passe (votre navigateur peut l'enregistrer), puis collez-la pour
confirmer. Après chaque redémarrage de `zing serve`, la page la redemande (le
navigateur peut la remplir) ; d'ici là, les surveillances qui en ont besoin
attendent, tandis que celles sans clé ou avec des clés `env:`/`file:` continuent
de s'exécuter. La barre d'état de la page propose aussi **Verrouiller**,
**Renouveler** et **Clé oubliée ?** (supprime les clés API chiffrées pour que
vous puissiez les saisir à nouveau). Pour un usage sans intervention ou sous
Docker, passez la clé dans `ZING_SECRET_KEY` (voir
[docs/DOCKER.md](docs/DOCKER.md)) ; `zing secret status | export | rotate` la
gèrent en ligne de commande.

## Audits d'embedding, de rerank, d'images et d'audio

Ces endpoints renvoient des vecteurs, des classements, des images ou de l'audio
au lieu de chat ; zing les audite donc avec des auditeurs autonomes et ciblés
plutôt qu'avec le pipeline de chat à dix dimensions. Chacun affiche un verdict
et prend en charge `--json` et `--fail-on-risk`.

### Embeddings et rerank

```bash
# La dimension de vecteur attendue est résolue depuis la base de connaissances pour le modèle annoncé.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Ou indiquer directement la dimension attendue :
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank : une sonde intégrée à réponse connue — un vrai reranker doit classer
# en premier le document manifestement pertinent.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

`embed` vérifie la connectivité, la **correspondance de dimension** (longueur du
vecteur renvoyé face à la dimension native du modèle annoncé — le signal phare de
tromperie sur la marchandise : un relais annonçant `text-embedding-3-large` en
3072-d mais renvoyant du 1024-d sert un substitut), le déterminisme (même entrée
→ cosinus ≈ 1), la distinction (entrées sans rapport → cosinus nettement
inférieur à 1) et le champ `model` renvoyé. Profils intégrés : OpenAI
`text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Les deux se trouvent aussi sur la page **Outils** de l'interface web (**Audit
d'embedding**, **Audit de rerank**), où la sonde de rerank peut être remplacée par
votre propre requête et vos propres documents.

### Génération d'images et d'audio (TTS)

Génération d'images (`POST /v1/images/generations`) et synthèse vocale
(`POST /v1/audio/speech`), décodées avec la seule bibliothèque standard de
Python — dimensions d'image à partir des octets d'en-tête (PNG/JPEG/GIF/WebP),
durée WAV via `wave`.

```bash
# Un relais annonçant DALL·E 3 renvoie-t-il vraiment le 1792x1024 demandé ? Une image
# réduite ou de mauvaise taille (ou hors des tailles natives du modèle annoncé, selon la
# base de connaissances) est le signal phare de tromperie sur la marchandise.
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Un relais annonçant tts-1-hd renvoie-t-il un vrai audio dont la durée suit l'entrée
# (pas un substitut fixe, pas du HTML/JSON déguisé en audio) ?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` vérifie la connectivité, un format valide et décodable, la
**correspondance de taille** (largeur × hauteur décodées face à la requête et aux
tailles natives du modèle annoncé — FAIL/HIGH en cas d'écart), la distinction
(deux prompts → deux images différentes, pour démasquer un substitut fixe), le
nombre et le champ `model`. `audio` vérifie la connectivité, la validité du
conteneur/format, le respect du format, une durée non triviale qui suit la
longueur de l'entrée, la distinction et le champ `model`. La base de connaissances
fournit OpenAI DALL·E 2/3, gpt-image-1, tts-1/tts-1-hd/gpt-4o-mini-tts ainsi que
des profils image/TTS de Qwen.

## Utilisation en CI (GitHub Action)

Conditionnez n'importe quel workflow à un audit de relais avec l'action composite
fournie. Elle exécute `zing check --compact --fail-on-risk`, expose `risk` /
`score` / `rating` en sorties, écrit un résumé dans l'exécution et fait échouer le
job lorsque le verrou de risque se déclenche.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.19.0         # épingler à un tag de version
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # secret de l'appelant ; jamais affiché
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

La clé du relais est transmise par une variable d'environnement
(`--api-key env:…`) et n'apparaît donc jamais sur une ligne de commande. Voir
[docs/CI.md](docs/CI.md) pour toutes les entrées et sorties et un exemple de
verrou de déploiement.

## Base de connaissances

zing juge un relais d'après le **profil** du modèle qu'il annonce : fenêtre de
contexte native, sortie maximale, date de coupure des connaissances, tokenizer,
capacités, mots-clés d'identité et empreintes comportementales. Les profils
intégrés couvrent OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM et
Moonshot (`zing kb` les liste). Il existe trois couches, les suivantes
l'emportant :

1. Les profils **intégrés**, un fichier YAML par fournisseur dans
   [`zing/knowledge/data/`](zing/knowledge/data).
2. **Un répertoire de vos propres fichiers YAML** : `--kb-dir ./my-profiles`
   (répétable) ou `ZING_KB_DIR`.
3. **Vos entrées** (`kb.db` dans le répertoire de données), ajoutées sans fichier
   YAML ni installation éditable :
   - sur la page **Connaissances** de l'interface web (`/v2/kb`), avec un onglet
     pour **Modèles**, **Fournisseurs** et **Relais**. Chaque onglet liste
     l'ensemble complet — fournis, `ZING_KB_DIR` et les vôtres (marqués **Les
     vôtres**) — avec un filtre, un interrupteur par élément et un formulaire
     **Ajouter …** : **Ajouter un modèle** → **Copier le prompt de recherche** dans
     l'assistant IA de votre choix, téléverser ou coller le YAML qu'il renvoie, puis
     **Vérifier et enregistrer** ; **Ajouter un fournisseur** accepte du YAML de
     fournisseur de la même façon ; **Ajouter un relais** demande un nom et une URL
     de base. **Quel profil un identifiant de modèle utilise-t-il ?** montre comment
     un id se résout ; vos entrées s'exportent en YAML ;
   - sur les pages **Audit** et **Outils** de l'interface web : **Enregistrer
     dans la base** conserve le nom et l'URL de base d'un relais (une entrée de
     fournisseur sans modèles), listé sous **Connaissances → Relais** ;
   - en ligne de commande : `zing kb-prompt <model>`, `zing kb-import <file>`
     (ajoutez `--check` pour seulement vérifier) et `zing kb-export`.

Avant d'enregistrer une entrée, zing la vérifie : schéma et limites, expressions
régulières dangereuses, chaque prompt qu'elle enverrait, et identifiants de
modèle qui se résoudraient vers un autre profil. Un de vos modèles portant l'id
d'un modèle intégré le remplace (signalé comme le *masquant*), mais ne modifie
jamais les réglages propres d'un fournisseur intégré ; les empreintes sont
fusionnées par id. Désactiver un modèle, un fournisseur ou un relais fourni sur la
page **Connaissances** est aussi enregistré dans `kb.db` : un id de modèle désactivé
n'est plus résolu, un fournisseur désactivé emporte ses modèles et URL de base.
`zing check` et `zing serve` utilisent exactement les mêmes profils ;
`--no-user-kb` (ou `ZING_NO_USER_KB=1`) laisse vos entrées et interrupteurs de côté.

Chaque rapport consigne le profil utilisé pour l'audit (`knowledge` : fournisseur,
modèle, manière dont l'id a été résolu, sa source et un instantané complet avec
son empreinte de contenu), si bien qu'un rapport reste vérifiable après une
modification de la base de connaissances.

## Rapports

`zing check` et `zing compare` affichent un verdict et écrivent le rapport dans
`reports/` (`--out-dir`) en JSON, Markdown, HTML et PDF (`--format all`, par
défaut) ; `--format json|md|html|pdf` écrit un seul format. `--json` et `--compact`
écrivent plutôt sur stdout.

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

Un rapport contient le verdict (risque, confiance, score, note), les constats
clés avec leurs recommandations, les scores par dimension et les **Dimension
details**, les constats de chaque détecteur avec leurs preuves, la section
performance, le profil de la base de connaissances utilisé et les langues de
sonde. Le texte contrôlé par le relais est expurgé et échappé avant d'être écrit.

## Confidentialité et données locales

- **Local uniquement.** `zing serve` n'écoute que sur la boucle locale
  (`127.0.0.1`, `::1`, `localhost`), ne répond qu'à ces noms d'hôte et refuse les
  requêtes intersites ; il n'a pas de connexion par identifiant, car rien hors de
  votre machine ne peut l'atteindre. zing ne contacte que les endpoints que vous
  configurez (cible, référence, juge, webhooks) ; il ne télécharge rien à
  l'exécution, pas même des fichiers de tokenizer.
- **Clés.** Les rapports et l'historique ne gardent qu'une empreinte d'une clé
  API. Les clés des surveillances sont stockées chiffrées dans `watches.db` ; la
  clé maîtresse qui les déchiffre n'est jamais écrite dans le répertoire de
  données (vous la conservez, voir **Surveillance** plus haut), si bien qu'une
  copie du répertoire ne révèle aucune clé API. Le répertoire reste accessible à
  vous seul.
- **Répertoire de données.** `~/.zing` (ou `ZING_DATA_DIR`), créé en `0700` avec
  des fichiers en `0600` : `history.db` (historique des audits), `watches.db`
  (surveillances, clés chiffrées comprises) et `kb.db` (vos entrées de la base
  de connaissances). Supprimez le répertoire pour tout effacer.
  `zing data-dir` indique où il se trouve ; `--data-dir CHEMIN` en choisit un
  autre le temps d'une exécution, par ex. `zing serve --data-dir .` place les
  bases dans le dossier courant. Ce sont des fichiers SQLite ordinaires que
  vous pouvez ouvrir pour vos propres analyses (en lecture seule de préférence
  pendant que zing tourne). Ne committez pas `watches.db` si ce dossier est un
  dépôt.

## Utilisation responsable

zing est une aide à l'audit en boîte noire. Il **ne peut pas prouver** :

- qu'un fournisseur stocke vos prompts ou s'entraîne dessus,
- qu'il route toujours vers un seul modèle précis (les relais peuvent router de façon probabiliste),
- une fraude à la facturation au-delà de ce que l'estimation indépendante des tokens peut suggérer.

Utilisez les rapports pour votre propre vérification. **N'accusez pas
publiquement un fournisseur** sur la base d'une seule exécution sans examiner la
taille de l'échantillon, les paramètres de coût et le droit local. Lancez
`zing compare` contre une référence de confiance avant de tirer des conclusions
fortes.

## Documentation complémentaire

| Document | Pour |
|---|---|
| [Méthodologie](docs/METHODOLOGY.fr.md) | Le fonctionnement de chaque vérification, son barème et ses réserves |
| [Guide du développeur](DEVELOPER_GUIDE.fr.md) | Architecture, environnement de développement, contribution, traductions, Docker, versions |
| [docs/CI.md](docs/CI.md) | La GitHub Action : entrées, sorties, exemples (en anglais) |
| [docs/DOCKER.md](docs/DOCKER.md) | Exécuter l'interface web dans un conteneur (en anglais) |
| [CHANGELOG.md](CHANGELOG.md) | Les changements de chaque version (en anglais) |
| [SECURITY.md](SECURITY.md) | Signaler une vulnérabilité (en anglais) |

## Licence

[Apache-2.0](LICENSE)
