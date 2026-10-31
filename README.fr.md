# ekte — vérification de la réalité des relais LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · **🇫🇷 Français** · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md) · [🇳🇴 Norsk](README.nb.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**ekte** est un outil local d'abord qui vérifie si un relais d'API (revendeur /
proxy) sert réellement le modèle qu'il annonce — ou s'il lui substitue en douce
un modèle moins cher, tronque votre fenêtre de contexte, simule le streaming ou
gonfle la facturation des tokens. Bref : obtenez-vous ce pour quoi vous payez ?
Il parle l'**API OpenAI Chat Completions**, l'**API Anthropic Messages** et
l'**API OpenAI Responses** (`/v1/responses`) — détectées automatiquement, ou
imposées avec `--api openai|anthropic|responses`.

Vous lui donnez l'endpoint d'un relais et le modèle qu'il prétend servir ; ekte
exécute une batterie de sondes en boîte noire, compare le comportement observé à
une base de connaissances intégrée de **98 profils de modèles de 7
fournisseurs**, et rend un verdict clair, étayé par des preuves — en ligne de
commande, dans une interface web locale ou en JSON pour un autre outil ou LLM.

> ekte fournit **des preuves en boîte noire d'écarts et de risques, pas une
> preuve cryptographique de fraude.** Voir [Utilisation responsable](#utilisation-responsable).

Ce README s'adresse à celles et ceux qui **utilisent** ekte. La façon dont ekte
est construit, testé et publié est décrite dans le
[Guide du développeur](DEVELOPER_GUIDE.fr.md) ; le fonctionnement et la notation
de chaque vérification dans la [Méthodologie](docs/METHODOLOGY.fr.md).

---

## Sommaire

- [Pourquoi](#pourquoi)
- [Installation](#installation)
- [Démarrage rapide](#démarrage-rapide)
- [Interface web (`ekte serve`)](#interface-web-ekte-serve)
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
- [Si vous venez de zing](#si-vous-venez-de-zing)
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

ekte transforme un « quelque chose cloche » en rapport reproductible.

## Installation

Nécessite Python 3.11+. Fonctionne sous Linux, macOS et Windows (l'image Docker est Linux) ; sous Windows, les modes réservés au propriétaire du répertoire de données n'ont aucun effet, voir [Systèmes d'exploitation pris en charge](docs/STABILITY.md#os). Chacune des options ci-dessous fournit la commande `ekte`.

### Avec pip

```bash
# depuis PyPI
pip install ekte

# ou depuis les sources
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

### Avec [uv](https://docs.astral.sh/uv/)

```bash
# depuis PyPI, comme outil autonome dans votre PATH
uv tool install ekte

# ou l'exécuter une fois sans l'installer
uvx --from ekte ekte --help

# ou depuis les sources, dans un environnement virtuel local au projet
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows : .venv\Scripts\activate
```

Vous pouvez aussi installer directement depuis le dépôt Git sans le cloner :
`uv tool install git+https://github.com/mn567250/ekte`.

### Extras optionnels

- `web` — l'interface web locale (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, depuis PyPI
pip install -e '.[web]'            # pip, depuis les sources
uv tool install 'ekte[web]'  # uv, depuis PyPI
uv pip install -e '.[web]'         # uv, depuis les sources
```

L'extra `tokenizers` n'est plus nécessaire : il est vide et
n'est conservé que pour que les anciennes commandes d'installation fonctionnent
encore. ekte compte les tokens avec une heuristique intégrée et ne télécharge
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
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# ouvrir http://localhost:8000
```

Publiez toujours le port sur `127.0.0.1` comme ci-dessus. Détails et variables
d'environnement : [Guide du développeur → Docker](DEVELOPER_GUIDE.fr.md#docker) et
[docs/DOCKER.md](docs/DOCKER.md).

## Démarrage rapide

```bash
# 1) auditer un relais par rapport à ce qu'il annonce (id du modèle + indice de fournisseur)
export EKTE_API_KEY=sk-votre-cle-relais
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) le contrôle le plus fort : comparer à une référence de confiance du même modèle
export OPENAI_API_KEY=sk-votre-cle-openai
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) auditer un relais natif Anthropic (API Messages) — le protocole est détecté
#    automatiquement à partir de base_url/model, ou imposé avec --api anthropic
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) confirmer une substitution suspectée : auditer l'id RÉEL du modèle du relais par
#    rapport au profil sous lequel il est vendu (ici : un modèle Doubao vendu comme deepseek-v4-flash)
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) lister les modèles qu'un endpoint annonce
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) consulter la base de connaissances
ekte kb            # tous les profils, avec leur source
ekte kb deepseek   # un fournisseur

# 7) générer une configuration que vous pouvez versionner
ekte init          # écrit ekte.yaml
ekte check -c ekte.yaml
```

Les clés d'API peuvent être données en clair, sous la forme `env:VAR` ou
`file:/chemin` ; les rapports ne contiennent jamais qu'une empreinte de la clé. Un
fichier de configuration complet se trouve dans [`examples/ekte.yaml`](examples/ekte.yaml).

Le fichier porte une version de format (`version: 1` ; un fichier sans version est au format 1). Les types erronés et les valeurs invalides sont rejetés avec le fichier, la ligne et la clé ; les clés inconnues sont ignorées avec un avertissement jusqu'à ekte 1.0.0, qui les rejette. `ekte config migrate` met à jour un ancien fichier. Le schéma est [`docs/schemas/config.schema.json`](docs/schemas/config.schema.json).

### Comme outil pour un LLM / agent

ekte est conçu pour être piloté par un autre programme ou modèle. Tout part sur
stdout en JSON, erreurs comprises, et le code de sortie sert de verrou.

```bash
# verdict léger, adapté aux agents (~5x plus petit que --json : sans les preuves volumineuses)
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# rapport structuré complet lorsque vous avez besoin des preuves de chaque constat
ekte check --base-url ... --model gpt-4o --json

# budget d'abord : quels détecteurs s'exécutent + appels d'API estimés, SANS en faire aucun
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# verrou sur le code de sortie (1 si risque >= medium, ou score sous --fail-under) ;
# les erreurs de config/usage sortent en 2, en JSON
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# découverte lisible par machine
ekte kb --json                      # toute la base de connaissances
ekte models --base-url ... --json   # ce qu'un endpoint annonce
```

En mode `--json`/`--compact`, une configuration erronée affiche `{"error": {...}}`
(code de sortie 2) au lieu d'un message lisible, afin qu'un pipeline puisse
traiter les échecs de façon uniforme.

## Interface web (`ekte serve`)

Vous préférez cliquer ? Une interface web locale enveloppe le même moteur — sans
ligne de commande.

```bash
pip install 'ekte[web]'     # ou : uv tool install 'ekte[web]'
ekte serve                        # ouvre http://localhost:8000
```

Le formulaire guide la configuration :

1. Choisissez le **Relais / fournisseur** : un fournisseur de la base de
   connaissances ou un relais que vous avez enregistré. Son URL de base est
   remplie (les autres URL connues du fournisseur sont proposées en
   suggestions). Pour tout autre relais, choisissez **Autre (saisir l'URL)** et
   saisissez l'**URL du relais**.
2. Ajoutez la **Clé API** si le relais en demande une.
3. ekte liste lui-même les modèles du relais (au choix d'un relais et à chaque
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
La référence de confiance (**Comparer à une référence de confiance**) et les
audits d'embedding et de rerank se configurent de la même façon.

Puis **Lancer l'audit**
et suivez les vérifications **en direct** : chaque vérification affiche son score
et sa durée, et une vérification avec des constats se déplie pour montrer les
preuves. Le résultat est un rapport de verdict partageable : note, **Contrôles par
dimension** avec leurs barèmes, constats en langage clair, section performance et
**Journal d'exécution** de chaque détecteur.

Tout s'exécute sur votre machine : une clé saisie dans le navigateur n'atteint
que votre serveur ekte local et le relais audité, jamais un tiers. Voir
[Confidentialité et données locales](#confidentialité-et-données-locales).

### Pages

L'interface web se trouve sous `/v2/`, où `ekte serve` l'ouvre. Les adresses de
l'ancienne interface classique (`/`, `/history`, `/watches`, `/tools`,
`/console`) redirigent vers la page correspondante.

| Page | Adresse | À quoi elle sert |
|---|---|---|
| **Audit** | `/v2/` | Auditer un relais (éventuellement face à une référence) et lire le rapport ; les audits d'embedding et de rerank démarrent aussi ici, via le sélecteur de type de point d'accès |
| **Surveillances** | `/v2/watches` | Ré-audits planifiés avec alertes webhook |
| **Historique** | `/v2/history` | Chaque audit exécuté sur cette machine, groupé par relais + modèle annoncé, avec tendances |
| **Analyses** | `/v2/analytics` | Relais et modèles comparés dans le temps : indicateurs, graphiques avec tableaux de données, classements |
| **Connaissances** | `/v2/kb` | La base de connaissances en trois onglets — modèles, fournisseurs, relais : parcourir, activer/désactiver, ajouter les vôtres |

Sur les pages, en outre : des filtres et des tendances configurables (score,
note, latence p50, tokens/s) dans l'**Historique** ; **Planifier comme
surveillance** et **Relancer l'audit** sur chaque exécution de l'Historique ; **Télécharger le rapport**
dans tous les formats ; et un sélecteur de thème (Automatique / Clair / Sombre).
Chaque page sauf Accessibilité affiche un avis juste
sous son introduction, coloré selon son importance (information, succès,
avertissement, critique) : p. ex. le dernier audit terminé sur **Audit**, la clé
maîtresse sur **Surveillances**, les exécutions encore en traitement sur
**Historique** et **Analyses**, les entrées ignorées sur **Connaissances**.

**Audits en arrière-plan.** Un audit lancé depuis la page
**Audit** continue quand vous changez de page ou fermez l'onglet ; **Continuer en
arrière-plan** l'y envoie volontairement. L'**Historique** liste chaque audit en
file d'attente ou en cours (et chaque surveillance en cours) avec sa
progression ; **Suivre en direct** rouvre la vue en direct, qui rattrape tout ce
qui s'est déjà passé. Les audits d'un même relais s'exécutent l'un après
l'autre, pour ne jamais fausser leurs mesures de latence ou de fiabilité (toutes
les adresses loopback comptent comme un seul hôte : les modèles servis par votre
propre machine attendent aussi) ; les audits de relais différents s'exécutent
en parallèle, quatre au plus à la fois (`EKTE_MAX_PARALLEL_AUDITS`). Les
surveillances attendent leur relais de la même façon.

**Analyses.** `/v2/analytics` transforme l'historique
local en comparaisons : des indicateurs pour la période choisie (exécutions,
score médian, part à risque élevé, taux de réussite, TTFT, vitesse de sortie,
ratios de facturation) avec l'écart par rapport à la période de même durée qui
précède ; un graphique de n'importe quelle métrique par relais, modèle ou
relais × modèle, par heure, jour ou semaine (ligne médiane avec la bande
p25–p75, jusqu'à quatre séries, chaque graphique aussi en tableau de données) ;
et un classement des relais pour un modèle, ou des modèles d'un relais. Les
relais sont regroupés selon leur entrée de la base de connaissances (relais
enregistrés et fournisseurs) : renommer un relais regroupe son historique. Les
intervalles de moins de 3 exécutions sont atténués — un audit isolé peut être
une valeur aberrante ; une surveillance fournit des mesures régulières. Les
exécutions plus anciennes montrent ce qu'elles ont mesuré : la page indique sur
combien d'exécutions repose une valeur. Par défaut, elle compare une suite et
un mode de sonde (les plus fréquents), pour ne pas mélanger des exécutions
différentes ; filtres et vue sont gardés dans l'URL, une vue peut donc être
mise en favori ou partagée. Rien ne quitte la machine.

D'autres panneaux répondent à des questions plus précises : **heures de
pointe** (une carte de chaleur jour de la semaine × heure du TTFT, de la latence et de la vitesse de décodage
(médiane et queues p95 / p5), de la gigue entre jetons, des temps réseau et du relais,
du taux de réussite ou d'erreur dans votre fuseau horaire — un relais
ralentit-il ou échoue-t-il davantage aux heures chargées ? Par jour de la semaine ou, avec 90 jours d'exécutions, sur un
cycle de 4 semaines et, avec 180 jours, par semaine du mois), **erreurs et
fiabilité** (appels en échec par cause — limitation de débit (HTTP 429),
erreurs serveur (5xx), délais dépassés, erreurs réseau — dans le temps et par
relais ou modèle, à partir des enregistrements de requêtes stockés, avec le
nombre d'audits qui en disposent), **intégrité du modèle** (résultats des
vérifications d'identité, de fenêtre de contexte et de capacités par relais ×
modèle, part des audits dont le modèle renvoyé diffère et part mesurée de la
fenêtre de contexte déclarée), **facturation et jetons** (ratios de
facturation dans le temps par rapport à la ligne des 100 % — au-dessus, le
relais déclare plus de jetons que ekte n'en a comptés — ainsi que les parts de
jetons de raisonnement et d'entrée en cache) et **surcharge du relais** (le
temps de traitement déclaré par le relais à côté de l'aller-retour réseau).

**Onglets et liens de partage (Analyses).** Les panneaux sont répartis en cinq
onglets — **Vue d'ensemble** (indicateurs, classement), **Tendances**
(comparaison dans le temps, heures de pointe), **Fiabilité** (erreurs, surcoût
du relais), **Intégrité du modèle** et **Facturation** — sous l’en-tête de la
page et un panneau de filtres commun ; seul l’onglet affiché est chargé. L’URL
conserve l’onglet, les filtres et chaque option des graphiques
(`#tab=reliability&range=30&relay=…&eb=dow_hour`), et **Copier le lien vers
cette vue** la copie (ou l’affiche dans un champ à copier si le navigateur ne
le permet pas) : le lien rouvre exactement cette vue. Le panneau de filtres est
le même sur **Historique**, **Surveillances** et **Analyses** : fermé, il indique combien de
filtres sont actifs et les nomme sur une ligne (p. ex. « 30 derniers jours ·
standard · Streaming · Example Relay »), si bien qu’une vue partagée dit ce
qu’elle montre.

### Langues

Un menu de langue dans l'en-tête de chaque page bascule l'interface entre
**🇬🇧 anglais** (par défaut), **🇨🇳 chinois** (l'interface d'origine),
**🇫🇷 français**, **🇪🇸 espagnol**, **🇵🇹 portugais**, **🇮🇹 italien**,
**🇩🇪 allemand** et **🇳🇴 norvégien** (bokmål) ; le choix est mémorisé par navigateur.

Les rapports téléchargés depuis l'interface (**Télécharger le rapport** : JSON,
Markdown, HTML ou PDF) suivent la langue choisie : les clés JSON, les valeurs
d'énumération (`risk_level`, `status`, `severity`, …), les identifiants et les
preuves restent exactement ceux du rapport de la CLI (le JSON reste un rapport
ekte valide), tandis que les valeurs lisibles (titre et résumé du verdict, titres
et résumés des constats, recommandations, noms des détecteurs, notes) sont
traduites, et le nom du fichier porte la langue (`ekte-report.fr.json`,
`ekte-report.fr.pdf`). Les titres de section des fichiers Markdown/HTML/PDF
restent en anglais. Les rapports de la CLI `--format json|md|html|pdf` restent en
anglais.

**Les prompts envoyés à l'endpoint audité ne suivent pas la langue de
l'interface.** Tout texte que ekte envoie à une API de LLM est en anglais, afin
que le même relais obtienne le même verdict quel que soit le lecteur du rapport
(les vérifications de réponses et les estimations de tokens sont calibrées sur
ces textes exacts). Seules exceptions : les empreintes de la base de
connaissances dont la langue *est* la mesure — par exemple les sondes de
fluidité en chinois, de tokenizer et d'auto-identification des modèles chinois.
Chaque rapport consigne les langues de sonde réellement utilisées
(`prompt_languages`, p. ex. `["en", "zh"]`).
Chaque rapport consigne aussi la manière dont l'endpoint a été interrogé : le
protocole (`target.api` : `openai`, `anthropic` ou `responses`), si `--api auto`
l'a détecté (`target.api_auto`) et le mode de requête de la sonde de performance
(`stream_mode` : `stream`, `non_stream` ou `both` pour la suite complète). La page
d'historique de l'interface web peut filtrer sur les trois.
`started_at` consigne le début de l'audit (UTC) ; le `start_ms` de chaque
enregistrement de requête compte à partir de ce moment.

## Ce qui est vérifié

ekte note dix dimensions. Les quatre **dimensions cœur** — identité du modèle,
fenêtre de contexte, capacités annoncées et facturation & consommation — révèlent
le plus directement une tromperie sur la marchandise. Les noms sont ceux de
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

En bref (les détails sont dans la [Méthodologie](docs/METHODOLOGY.fr.md#comment-ekte-note)) :

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
| `inconclusive` | Signal insuffisant | Rien d'exploitable : identité du modèle, fenêtre de contexte et capacités annoncées ont tourné sans résultat exploitable (relais injoignable, modèle absent de la base de connaissances), ou aucune dimension hormis la connectivité n'en a produit |
| `high` | Tromperie sur la marchandise | Un constat CRITIQUE, un constat ÉLEVÉ/CRITIQUE dans une dimension cœur, ou au moins deux constats ÉLEVÉS |
| `medium` | Écarts détectés | Exactement un constat ÉLEVÉ hors des dimensions cœur, ou un constat MOYEN dans une dimension cœur |
| `low` | Globalement fiable | Tout autre constat MOYEN |
| `clean` | Cohérent (probablement authentique) | Aucun des cas ci-dessus |

Les constats de la dimension connectivité n'élèvent jamais le risque : un relais
injoignable ou limité n'a pas pu être évalué, ce qui ne prouve pas qu'un autre
modèle répond. La **confiance** du verdict (faible / moyenne / élevée) augmente
avec le nombre de dimensions cœur ayant produit un résultat, avec une référence
et avec le juge LLM.

Les avertissements de transport — HTTP en clair (`security.tls`) et échecs ou
queues lentes sous charge (`reliability.*`) — abaissent le score de leur dimension
mais n'élèvent pas non plus le risque de substitution ; le résumé les liste comme
avertissements. Une réponse altérée et une clé API renvoyée l'élèvent toujours. Le
HTTP en clair vers cette machine ou un réseau privé n'est qu'un avertissement de
faible gravité, la clé ne la quittant jamais. Un profil de la base de connaissances
apparié seulement de façon approximative (fuzzy) limite la confiance à faible, et
un détecteur sans aucune réponse exploitable est non concluant, jamais une réussite.

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
Une fenêtre plus grande que le plafond `--max-context-tokens` est signalée comme *vérifiée jusqu'au plafond*, jamais comme tronquée.

### Suite personnalisée

N'exécutez que les dimensions qui vous intéressent, ce qui économise du temps et
des tokens. Chaque détecteur de chaque dimension choisie s'exécute, comme en `deep` :

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
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
de risque porte lui aussi sur les dimensions choisies : sans l'identité du
modèle, il ne couvre qu'elles, pas le modèle réellement servi, et le dit.

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
| référence | tokens/s face à la référence de confiance, sinon à la plage publiée pour le modèle dans la base de connaissances : conforme 100 · plus lent : non compté (informatif, jamais un échec) · ≥ 2x plus rapide 60 (signe d'un modèle plus petit) · pas de référence : non compté |

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

Les audits qui s'exécutent en même temps dans `ekte serve` (plusieurs onglets du
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

ekte dispose de deux modes de détection :

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
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

Le **mode comparaison** (`ekte compare`, ou **Comparer à une référence de
confiance** dans l'interface web) exécute les mêmes sondes, au même moment,
contre une référence de confiance du modèle annoncé. C'est la meilleure voie de
confirmation : réponses d'identité, paramètres de requête rejetés, canaris de
falsification et performance sont jugés côte à côte, et seule une référence
permet à la confiance du verdict d'être *élevée*. Sans `--judge-base-url`, le mode
comparaison utilise la référence comme juge.

## Surveillance

Un relais peut servir le vrai modèle aujourd'hui et le remplacer discrètement la
semaine prochaine. `ekte watch` ré-audite selon un calendrier, enregistre chaque
exécution dans l'historique et alerte un webhook lorsque le risque franchit un
seuil ou **régresse** par rapport à l'exécution précédente.

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang fr                                     # ou --once pour cron
```

Les alertes sont formatées pour **Slack / Feishu / DingTalk / JSON générique**,
détectés automatiquement à partir de l'URL du webhook, et rédigées dans la langue
des alertes — l'anglais par défaut ; `--alert-lang en|zh|fr|es|pt|it|de|nb`. La
charge utile JSON générique garde ses clés et ses valeurs machine (`risk_level`,
`score`, …) neutres, traduit les valeurs lisibles (`text`, `headline`,
`key_findings`) et indique la `language`.

**Dans l'interface web**, `ekte serve` exécute les mêmes surveillances dans un
planificateur en arrière-plan au sein du processus serveur, enregistre chaque
exécution dans l'**Historique** et envoie les mêmes alertes webhook. Ouvrez une exécution dans l'**Historique** et
choisissez **Planifier comme surveillance**. ekte copie la configuration de
cette exécution (relais, modèle, modèle annoncé, fournisseur, suite, dimensions
personnalisées) dans une surveillance en pause sur la page **Surveillances** ;
définissez-y son intervalle et sa clé API (l'Historique ne stocke jamais de
clés) puis activez-la. Intervalle, clé, **Seuil d'alerte**, webhooks et
**Langue des alertes** se modifient directement sur chaque surveillance. Un
clic sur le nom replie la carte au nom, à l'état et à la dernière exécution
(**Tout replier** / **Tout déplier** au-dessus de la liste ; mémorisé par
navigateur), et le panneau de filtres (recherche, état, dernier risque, type
d'endpoint, relais, suite) réduit une longue liste comme dans l'**Historique**.

Chaque surveillance a sa propre langue d'alerte (par défaut celle de
l'interface), peut être exécutée maintenant, mise en pause ou supprimée, et
reste liée au profil de la base de connaissances avec lequel elle a été créée
jusqu'à ce que vous la reliiez à nouveau.

Les surveillances arrivées à échéance s'exécutent en même temps, chacune comme
son propre audit, mais jamais plus d'un audit à la fois par hôte de relais et au
plus `EKTE_MAX_PARALLEL_AUDITS` au total ; une exécution attend qu'un créneau se
libère (un audit que vous lancez à la main peut aussi attendre derrière les
surveillances en cours). L'heure d'une exécution est celle où son audit démarre,
après une éventuelle attente. La détection de régression compare avec la plus
récente exécution enregistrée du même relais et du même modèle, quel que soit le
nombre d'autres exécutions enregistrées depuis. Les webhooks d'alerte d'une
exécution sont envoyés en même temps, si bien qu'un webhook lent ou hors service
ne retarde pas les autres. Les clés sont stockées chiffrées dans
votre répertoire de données local et ne sont jamais renvoyées au navigateur.

**Stockage des clés API.** Par défaut, ekte **n'enregistre pas** les clés API
des surveillances : une clé saisie reste uniquement dans la mémoire de
`ekte serve` et n'est jamais écrite sur le disque. Après un redémarrage, la page
**Surveillances** indique celles qui ont de nouveau besoin de leur clé ; elles
attendent (sans exécution en échec ni alerte) que vous la saisissiez. Les
surveillances sans clé et les références `env:`/`file:` continuent de tourner.
Pour que les clés survivent aux redémarrages, choisissez **Enregistrer chiffrées
sur cette machine** sous **Stockage des clés API** sur la page **Surveillances** :
les clés sont alors conservées dans `watches.db`, chiffrées avec une clé
maîtresse. Revenir en arrière déplace les clés enregistrées en mémoire et les
efface de `watches.db`. La notice de la page indique le mode actif, demande
confirmation avant un changement et rapporte ce qui a été déplacé. Une
installation qui
enregistrait déjà des clés chiffrées, ou qui définit `EKTE_SECRET_KEY`, continue
de les enregistrer jusqu'à ce que vous changiez.

**Clé maîtresse.** Les clés API des surveillances sont chiffrées avec une clé
maîtresse que ekte n'écrit jamais sur le disque. La première fois que vous
enregistrez une clé API, la page **Surveillances** la crée et l'affiche une
seule fois : copiez-la ou téléchargez-la, conservez-la dans un gestionnaire de
mots de passe (votre navigateur peut l'enregistrer), puis collez-la pour
confirmer. Après chaque redémarrage de `ekte serve`, la page la redemande (le
navigateur peut la remplir) ; d'ici là, les surveillances qui en ont besoin
attendent, tandis que celles sans clé ou avec des clés `env:`/`file:` continuent
de s'exécuter. La barre d'état de la page propose aussi **Verrouiller**,
**Renouveler** et **Clé oubliée ?** (supprime les clés API chiffrées pour que
vous puissiez les saisir à nouveau). Pour un usage sans intervention ou sous
Docker, passez la clé dans `EKTE_SECRET_KEY` (voir
[docs/DOCKER.md](docs/DOCKER.md)) ; `ekte secret status | export | rotate` la
gèrent en ligne de commande.

## Audits d'embedding, de rerank, d'images et d'audio

Ces endpoints renvoient des vecteurs, des classements, des images ou de l'audio au
lieu de chat ; ekte les audite donc avec des sondes dédiées au lieu des prompts de
chat. Chacun affiche un verdict et prend en charge `--json` et `--fail-on-risk`.

### Type d'endpoint (surface), surveillances d'embedding et de rerank

Chaque audit, ligne d'historique et surveillance a un **type d'endpoint**
(`surface`) : `chat` (par défaut), `embedding` ou `rerank`. Il est indépendant de
la suite. Les audits d'embedding et de rerank passent par le même runner, le même
score (0–100, A–F), l'historique, l'analytique et les surveillances que les audits
de chat ; seuls les détecteurs diffèrent. L'historique et l'analytique filtrent par
type d'endpoint, et l'analytique n'affiche que les métriques qui s'appliquent.

Pour surveiller un endpoint d'embeddings ou de rerank, auditez-le sur la page
**Audit** (choisissez **Embeddings** ou **Reclassement** dans le sélecteur de type
de point d'accès) et
choisissez **Surveiller**, ou **Planifier comme surveillance** sur sa
ligne d'historique. La surveillance relance l'audit selon son planning, avec le
même épinglage de la base de connaissances, le même seuil d'alerte et les mêmes
alertes de régression qu'une surveillance de chat, et vérifie la **dérive** par
rapport à son exécution précédente (les vecteurs d'une sonde d'embedding, le
classement et les scores d'une sonde de rerank). La dimension annoncée d'une
surveillance d'embedding se modifie sur sa carte (vide ou 0 : depuis la base de
connaissances). Les sondes de vitesse (embeddings : latence, démarrage à froid,
entrées/s, mise à l'échelle par lots ; rerank : latence, démarrage à froid,
documents/s, 4 contre 32 documents) ne tournent que dans les suites deep, full ou
custom, ou en standard avec une référence.

### Embeddings et rerank

```bash
# La dimension de vecteur attendue est résolue depuis la base de connaissances pour le modèle annoncé.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Ou indiquer directement la dimension attendue :
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank : une sonde intégrée à réponse connue — un vrai reranker doit classer
# en premier le document manifestement pertinent.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Plus poussé : ajoute la sonde de vitesse du rerank ; --no-save garde l'exécution hors de l'historique.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# Voir d'abord les vérifications et les appels estimés, sans envoyer de requête :
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` vérifie la connectivité, la **sonde à réponse connue** (le document
manifestement pertinent doit arriver en tête), le champ `model` renvoyé, le
déterminisme (la même requête deux fois donne le même classement et les mêmes
scores) et la **dérive du classement** par rapport à l'exécution enregistrée
précédente. `ekte embed` et `ekte rerank` acceptent `--suite`,
`--save/--no-save` (enregistré par défaut, pour que l'exécution suivante ait une
référence de dérive) et `--dry-run`.

`embed` vérifie la connectivité, la **correspondance de dimension** (longueur du
vecteur renvoyé face à la dimension native du modèle annoncé — le signal phare de
tromperie sur la marchandise : un relais annonçant `text-embedding-3-large` en
3072-d mais renvoyant du 1024-d sert un substitut), le déterminisme (même entrée
→ cosinus ≈ 1), la distinction (entrées sans rapport → cosinus nettement
inférieur à 1) et le champ `model` renvoyé. Profils intégrés : OpenAI
`text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Les deux se trouvent aussi dans l'interface web : ils démarrent sur la page
**Audit** via le sélecteur de type de point d'accès (**Embeddings**,
**Reclassement**). L'audit de rerank utilise toujours les sondes
intégrées, pour que chaque exécution reste comparable pour la dérive et la
surveillance.

### Génération d'images et d'audio (TTS)

Génération d'images (`POST /v1/images/generations`) et synthèse vocale
(`POST /v1/audio/speech`), décodées avec la seule bibliothèque standard de
Python — dimensions d'image à partir des octets d'en-tête (PNG/JPEG/GIF/WebP),
durée WAV via `wave`.

```bash
# Un relais annonçant DALL·E 3 renvoie-t-il vraiment le 1792x1024 demandé ? Une image
# réduite ou de mauvaise taille (ou hors des tailles natives du modèle annoncé, selon la
# base de connaissances) est le signal phare de tromperie sur la marchandise.
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Un relais annonçant tts-1-hd renvoie-t-il un vrai audio dont la durée suit l'entrée
# (pas un substitut fixe, pas du HTML/JSON déguisé en audio) ?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
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
fournie. Elle exécute `ekte check --compact --fail-on-risk`, expose `risk` /
`score` / `rating` en sorties, écrit un résumé dans l'exécution et fait échouer le
job lorsque le verrou de risque se déclenche.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@vX.Y.Z       # épingler à un tag de version
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # secret de l'appelant ; jamais affiché
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

La clé du relais est transmise par une variable d'environnement
(`--api-key env:…`) et n'apparaît donc jamais sur une ligne de commande. Voir
[docs/CI.md](docs/CI.md) pour toutes les entrées et sorties et un exemple de
verrou de déploiement.

## Base de connaissances

ekte juge un relais d'après le **profil** du modèle qu'il annonce : fenêtre de
contexte native, sortie maximale, date de coupure des connaissances, tokenizer,
capacités, mots-clés d'identité et empreintes comportementales. Les profils
intégrés couvrent OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM et
Moonshot (`ekte kb` les liste). Il existe trois couches, les suivantes
l'emportant :

1. Les profils **intégrés**, un fichier YAML par fournisseur dans
   [`ekte/knowledge/data/`](ekte/knowledge/data).
2. **Un répertoire de vos propres fichiers YAML** : `--kb-dir ./my-profiles`
   (répétable) ou `EKTE_KB_DIR`.
3. **Vos entrées** (`kb.db` dans le répertoire de données), ajoutées sans fichier
   YAML ni installation éditable :
   - sur la page **Connaissances** de l'interface web (`/v2/kb`), avec un onglet
     pour **Modèles**, **Fournisseurs** et **Relais**. Chaque onglet liste
     l'ensemble complet — fournis, `EKTE_KB_DIR` et les vôtres (marqués **Les
     vôtres**) — avec un filtre, un interrupteur par élément et un formulaire
     **Ajouter …** : **Ajouter un modèle** → **Copier le prompt de recherche** dans
     l'assistant IA de votre choix, téléverser ou coller le YAML qu'il renvoie, puis
     **Vérifier et enregistrer** ; **Ajouter un fournisseur** accepte du YAML de
     fournisseur de la même façon ; **Ajouter un relais** demande un nom et une URL
     de base. **Quel profil un identifiant de modèle utilise-t-il ?** montre comment
     un id se résout ; vos entrées s'exportent en YAML ;
   - sur la page **Audit** de l'interface web : **Enregistrer
     dans la base** conserve le nom et l'URL de base d'un relais (une entrée de
     fournisseur sans modèles), listé sous **Connaissances → Relais** ;
   - en ligne de commande : `ekte kb-prompt <model>`, `ekte kb-import <file>`
     (ajoutez `--check` pour seulement vérifier) et `ekte kb-export`.

Avant d'enregistrer une entrée, ekte la vérifie : schéma et limites, expressions
régulières dangereuses, chaque prompt qu'elle enverrait, et identifiants de
modèle qui se résoudraient vers un autre profil. Un de vos modèles portant l'id
d'un modèle intégré le remplace (signalé comme le *masquant*), mais ne modifie
jamais les réglages propres d'un fournisseur intégré ; les empreintes sont
fusionnées par id. Désactiver un modèle, un fournisseur ou un relais fourni sur la
page **Connaissances** est aussi enregistré dans `kb.db` : un id de modèle désactivé
n'est plus résolu, un fournisseur désactivé emporte ses modèles et URL de base.
`ekte check` et `ekte serve` utilisent exactement les mêmes profils ;
`--no-user-kb` (ou `EKTE_NO_USER_KB=1`) laisse vos entrées et interrupteurs de côté.

Un modèle dont les `identity_keywords` sont vides n'est pas enregistré tel quel :
ekte complète ses propres mots de marque à partir des noms du fournisseur et du
modèle (par exemple `glm` et `z.ai`) et affiche
un avertissement pour les vérifier, car sans eux le contrôle d'identité pourrait
prendre son propre fabricant pour une marque concurrente. Le prompt de recherche
les demande explicitement à l'assistant IA.

Chaque rapport consigne le profil utilisé pour l'audit (`knowledge` : fournisseur,
modèle, manière dont l'id a été résolu, sa source et un instantané complet avec
son empreinte de contenu), si bien qu'un rapport reste vérifiable après une
modification de la base de connaissances.

## Rapports

`ekte check` et `ekte compare` affichent un verdict et écrivent le rapport dans
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

- **Local uniquement.** `ekte serve` n'écoute que sur la boucle locale
  (`127.0.0.1`, `::1`, `localhost`), ne répond qu'à ces noms d'hôte et refuse les
  requêtes intersites ; il n'a pas de connexion par identifiant, car rien hors de
  votre machine ne peut l'atteindre. ekte ne contacte que les endpoints que vous
  configurez (cible, référence, juge, webhooks) ; il ne télécharge rien à
  l'exécution, pas même des fichiers de tokenizer.
- **Clés.** Les rapports et l'historique ne gardent qu'une empreinte d'une clé
  API. Les clés des surveillances sont stockées chiffrées dans `watches.db` ; la
  clé maîtresse qui les déchiffre n'est jamais écrite dans le répertoire de
  données (vous la conservez, voir **Surveillance** plus haut), si bien qu'une
  copie du répertoire ne révèle aucune clé API. Le répertoire reste accessible à
  vous seul.
- **Répertoire de données.** `~/.ekte` (ou `EKTE_DATA_DIR`), créé en `0700` avec
  des fichiers en `0600` : `history.db` (historique des audits), `watches.db`
  (surveillances, clés chiffrées comprises) et `kb.db` (vos entrées de la base
  de connaissances). Supprimez le répertoire pour tout effacer.
  `ekte data-dir` indique où il se trouve ; `--data-dir CHEMIN` en choisit un
  autre le temps d'une exécution, par ex. `ekte serve --data-dir .` place les
  bases dans le dossier courant. Ce sont des fichiers SQLite ordinaires que
  vous pouvez ouvrir pour vos propres analyses (en lecture seule de préférence
  pendant que ekte tourne). Ne committez pas `watches.db` si ce dossier est un
  dépôt.
  `history_metrics` contient une ligne de valeurs mesurées par exécution et
  `history_requests` chaque enregistrement de requête (stocké là une seule fois,
  pas dans chaque rapport).

## Utilisation responsable

ekte est une aide à l'audit en boîte noire. Il **ne peut pas prouver** :

- qu'un fournisseur stocke vos prompts ou s'entraîne dessus,
- qu'il route toujours vers un seul modèle précis (les relais peuvent router de façon probabiliste),
- une fraude à la facturation au-delà de ce que l'estimation indépendante des tokens peut suggérer.

Utilisez les rapports pour votre propre vérification. **N'accusez pas
publiquement un fournisseur** sur la base d'une seule exécution sans examiner la
taille de l'échantillon, les paramètres de coût et le droit local. Lancez
`ekte compare` contre une référence de confiance avant de tirer des conclusions
fortes.

## Documentation complémentaire

| Document | Pour |
|---|---|
| [Méthodologie](docs/METHODOLOGY.fr.md) | Le fonctionnement de chaque vérification, son barème et ses réserves |
| [Guide du développeur](DEVELOPER_GUIDE.fr.md) | Architecture, environnement de développement, contribution, traductions, Docker, versions |
| [docs/CI.md](docs/CI.md) | La GitHub Action : entrées, sorties, exemples (en anglais) |
| [docs/DOCKER.md](docs/DOCKER.md) | Exécuter l'interface web dans un conteneur (en anglais) |
| [Stabilité et compatibilité](docs/STABILITY.md) | Ce que protège semver, dépréciation, versions de Python et systèmes pris en charge, mises à jour et retours en arrière (en anglais) |
| [CHANGELOG.md](CHANGELOG.md) | Les changements de chaque version (en anglais) |
| [SECURITY.md](SECURITY.md) | Signaler une vulnérabilité (en anglais) |

## Si vous venez de zing

ekte poursuit [zing](https://github.com/cenbonew/zing) (dernière version :
0.11.0) sous un nouveau nom. Ce qui change pour une installation existante :

- **Paquet et commande.** `pip install ekte` (auparavant `zing-audit`), la
  commande `ekte` (auparavant `zing`), le paquet Python `ekte`. Les extras
  gardent leur nom, p. ex. `pip install 'ekte[web]'`. Les deux paquets ne
  partagent ni commande ni module : `zing-audit` peut rester installé à côté
  d'ekte.
- **Variables d'environnement.** `EKTE_*` remplace `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). Une ancienne variable `ZING_*` fonctionne
  encore tant que son nom `EKTE_*` n'est pas défini ; ekte la signale une fois
  sur stderr.
- **Répertoire de données.** Au premier lancement, ekte copie `~/.zing` vers
  `~/.ekte` (historique, moniteurs, base de connaissances) si `~/.ekte`
  n'existe pas encore, puis ne travaille plus qu'avec `~/.ekte`. `~/.zing` reste
  tel quel, pour zing s'il tourne encore ; supprimez-le vous-même quand vous n'en
  avez plus besoin. Un répertoire défini par `EKTE_DATA_DIR`, `ZING_DATA_DIR` ou
  `--data-dir` est utilisé tel quel.
- **Interface web.** La langue, le thème et les filtres, ainsi qu'une clé
  maîtresse enregistrée dans le gestionnaire de mots de passe du navigateur, sont
  repris. L'interface classique de zing n'existe plus : ses adresses (`/`,
  `/history`, `/watches`, `/tools`, `/console`) ouvrent la page correspondante
  sous `/v2/`.
- **Rapports et sondes.** Les rapports, les webhooks et les noms de fichiers
  indiquent `ekte` (p. ex. `"tool": "ekte"`, `ekte-report.json`), tout comme les
  sondes envoyées aux relais. Les scripts qui y cherchent `zing` doivent être
  mis à jour.

## Licence

[Apache-2.0](LICENSE)
