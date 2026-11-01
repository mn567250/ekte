# Démarrage rapide

> [🇬🇧 English](../../../guide/quickstart.md) · [🇨🇳 中文](../../zh-CN/guide/quickstart.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/quickstart.md) · [🇵🇹 Português](../../pt/guide/quickstart.md) · [🇮🇹 Italiano](../../it/guide/quickstart.md) · [🇩🇪 Deutsch](../../de/guide/quickstart.md) · [🇳🇴 Norsk](../../nb/guide/quickstart.md)

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
fichier de configuration complet se trouve dans [`examples/ekte.yaml`](../../../../examples/ekte.yaml).

Le fichier porte une version de format (`version: 1` ; un fichier sans version est au format 1). Les types erronés et les valeurs invalides sont rejetés avec le fichier, la ligne et la clé ; les clés inconnues sont ignorées avec un avertissement jusqu'à ekte 1.0.0, qui les rejette. `ekte config migrate` met à jour un ancien fichier. Le schéma est [`docs/schemas/config.schema.json`](../../../schemas/config.schema.json).

## Comme outil pour un LLM / agent

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
