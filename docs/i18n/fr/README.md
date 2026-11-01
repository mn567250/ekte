# ekte — vérification de la réalité des relais LLM

> [🇬🇧 English](../../../README.md) · [🇨🇳 中文](../zh-CN/README.md) · **🇫🇷 Français** · [🇪🇸 Español](../es/README.md) · [🇵🇹 Português](../pt/README.md) · [🇮🇹 Italiano](../it/README.md) · [🇩🇪 Deutsch](../de/README.md) · [🇳🇴 Norsk](../nb/README.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](../../../LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](../../../pyproject.toml)

**ekte** est un outil local d'abord qui vérifie si un relais d'API (revendeur /
proxy) sert réellement le modèle qu'il annonce — ou s'il lui substitue en douce
un modèle moins cher, tronque votre fenêtre de contexte, simule le streaming ou
gonfle la facturation des tokens. Bref : obtenez-vous ce pour quoi vous payez ?
Il parle l'**API OpenAI Chat Completions**, l'**API Anthropic Messages** et
l'**API OpenAI Responses** (`/v1/responses`) — détectées automatiquement, ou
imposées avec `--api openai|anthropic|responses`.

Vous lui donnez l'endpoint d'un relais et le modèle qu'il prétend servir ; ekte
exécute une batterie de sondes en boîte noire, compare le comportement observé à
une base de connaissances intégrée de **98 profils de modèles de 7
fournisseurs**, et rend un verdict clair, étayé par des preuves — en ligne de
commande, dans une interface web locale ou en JSON pour un autre outil ou LLM.

> ekte fournit **des preuves en boîte noire d'écarts et de risques, pas une
> preuve cryptographique de fraude.** Voir [Utilisation responsable](guide/privacy.md#utilisation-responsable).

## Pourquoi

Le marché des clés de relais regorge d'offres du type « GPT-4o à un dixième du
prix ». Beaucoup sont honnêtes. Certaines ne le sont pas — et les malhonnêtes
sont difficiles à repérer à l'œil nu :

- Vous demandez `gpt-4o` ; on vous sert discrètement `gpt-4o-mini` ou un modèle ouvert.
- Le relais annonce un contexte de 1M de tokens mais tronque en silence à 32K.
- Le « streaming » est la réponse complète mise en tampon puis redécoupée, sans aucun gain de latence.
- Les tokens `usage` déclarés sont gonflés, et votre solde fond plus vite qu'il ne devrait.
- Un modèle censé prendre en charge l'appel d'outils / le mode JSON ne le fait discrètement pas.

ekte transforme un « quelque chose cloche » en rapport reproductible.

## Installation

Nécessite Python 3.11+ sous Linux, macOS ou Windows.

```bash
pip install 'ekte[web]'          # ou : uv tool install 'ekte[web]'
```

L'extra `web` ajoute l'interface web locale ; omettez-le pour la seule ligne de
commande. Depuis les sources, avec uv ou dans Docker : [Installation](guide/install.md).

## Démarrage rapide

```bash
export EKTE_API_KEY=sk-your-relay-key

# auditer un relais par rapport au modèle qu'il prétend servir
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard

# le contrôle le plus fort : comparer à une référence de confiance du même modèle
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o

# ou à la souris : l'interface web locale
ekte serve
```

Plus d'exemples, les fichiers de configuration et l'utilisation depuis des
scripts ou des agents LLM : [Démarrage rapide](guide/quickstart.md). L'interface
web : [Interface web](guide/web-ui.md).

## Ce qui est vérifié

ekte note dix dimensions. Les quatre **dimensions cœur** — identité du modèle,
fenêtre de contexte, capacités annoncées et facturation & consommation — révèlent
le plus directement une tromperie sur la marchandise. Les noms sont ceux de
l'interface web et des rapports.

| Dimension | Id | Ce qu'elle détecte |
|---|---|---|
| **Identité du modèle** | `model_identity` | Déclassement ou substitution silencieuse du modèle |
| **Fenêtre de contexte** | `context_window` | Troncature silencieuse du contexte et « lost in the middle » |
| **Capacités annoncées** | `capability` | Appel d'outils, mode JSON, sortie maximale ou vision annoncés mais non fournis |
| **Conformité du protocole** | `protocol` | Paramètres de requête et attributs de réponse supprimés ou ignorés |
| **Facturation et consommation** | `billing` | Consommation de tokens gonflée ou absente |
| **Connectivité** | `connectivity` | Joignabilité de l'endpoint et la liste de modèles annoncée |
| **Authenticité du streaming** | `streaming` | Faux streaming (mise en tampon puis découpage) |
| **Fiabilité en concurrence** | `reliability` | Échecs et ralentissements sous charge concurrente |
| **Sécurité du transport** | `security` | HTTP en clair, écho de secrets, prompts système injectés, falsification |
| **Performance** | `performance` | La régularité de la latence, du temps jusqu'au premier token et du débit |

Le fonctionnement de chaque vérification et la façon dont le verdict est
établi : [Méthodologie](guide/methodology.md).

## Documentation

| Guide de l'utilisateur | |
|---|---|
| [Installation](guide/install.md) | pip, uv, depuis les sources, extras optionnels |
| [Démarrage rapide](guide/quickstart.md) | Premiers audits, fichiers de configuration, utilisation par des scripts et des agents LLM |
| [Interface web](guide/web-ui.md) | Pages, audits en arrière-plan, analyses, langues |
| [Suites et mode comparaison](guide/suites.md) | Suites, suite personnalisée, référence de confiance, juge LLM |
| [Performance](guide/performance.md) | La section performance, la sonde et les délais d'expiration des requêtes |
| [Surveillance](guide/monitoring.md) | Ré-audits planifiés, alertes webhook, stockage des clés API |
| [Audits d'embedding, de rerank, d'images et d'audio](guide/other-endpoints.md) | Audits d'endpoints qui ne sont pas du chat |
| [Base de connaissances](guide/knowledge-base.md) | Profils de modèles et ajout des vôtres |
| [Rapports](guide/reports.md) | Formats et contenu des rapports |
| [Confidentialité et données locales](guide/privacy.md) | Ce qui reste sur votre machine ; utilisation responsable |
| [GitHub Action](guide/github-action.md) | Conditionner un workflow de CI à un audit de relais |
| [Docker](guide/docker.md) | Exécuter l'interface web dans un conteneur |
| [Méthodologie](guide/methodology.md) | Chaque vérification, son barème et ses réserves |
| [Si vous venez de zing](guide/migrating-from-zing.md) | Ce qui change pour une installation zing existante |

| Référence (en anglais) | |
|---|---|
| [Ligne de commande](../../reference/cli.md) | Toutes les commandes et options, et les codes de sortie |
| [Schémas du rapport et du webhook](../../reference/schemas.md) | Les formats JSON et leur `schema_version` |
| [Stabilité et compatibilité](../../reference/stability.md) | Ce que protège semver, dépréciation, versions de Python et systèmes pris en charge |
| [Journal des modifications](../../../CHANGELOG.md) | Les changements de chaque version |

Contribuer : [Guide de contribution](../../CONTRIBUTING.md) et
[Guide du développeur](../../dev/developer-guide.md) (en anglais).
Problèmes de sécurité : [Politique de sécurité](../../SECURITY.md).

## Licence

[Apache-2.0](../../../LICENSE)
