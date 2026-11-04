# Rapports

> [🇬🇧 English](../../../guide/reports.md) · [🇨🇳 中文](../../zh-CN/guide/reports.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/reports.md) · [🇵🇹 Português](../../pt/guide/reports.md) · [🇮🇹 Italiano](../../it/guide/reports.md) · [🇩🇪 Deutsch](../../de/guide/reports.md) · [🇳🇴 Norsk](../../nb/guide/reports.md)

`ekte check` et `ekte compare` affichent un verdict et écrivent le rapport dans
`reports/` (`--out-dir`) en JSON, Markdown, HTML et PDF (`--format all`, par
défaut) ; `--format json|md|html|pdf` écrit un seul format. `--json` et `--compact`
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

## Fichiers de preuves

Avec `--evidence PATH` (`check`, `compare`, `image`, `audio`), et par défaut
pour chaque exécution enregistrée dans l'historique, ekte écrit aussi chaque
requête et réponse HTTP brute de l'exécution dans un fichier : du JSON Lines
dans un flux zstd, `<run_id>.jsonl.zst` (un répertoire donné comme `PATH`
reçoit ce nom). La première ligne décrit l'exécution ; chaque ligne suivante est
une requête avec sa réponse, y compris l'instant d'arrivée de chaque morceau de
la réponse. Le `seq` d'une ligne est le `seq` de la requête dans
`performance.requests` du rapport : chaque requête listée par le rapport peut
ainsi être retrouvée. Le champ `evidence` du rapport nomme le fichier avec son
SHA-256 et son nombre d'échanges.

```bash
ekte check --base-url https://relay.example.com/v1 --model gpt-4o --evidence reports/
zstd -dc reports/<run_id>.jsonl.zst | jq -c 'select(.seq == 12)'
```

Chaque constat nomme les requêtes sur lesquelles il repose (`evidence_seqs` ;
vide s'il ne repose sur aucune, comme le contrôle TLS). `ekte evidence-export`
prend le fichier (ou l'identifiant d'une exécution enregistrée) et le
transforme en HAR pour un visualiseur HAR ou les outils de développement du
navigateur (`--as har`), en script curl qui renvoie les requêtes
(`--as curl` ; définissez d'abord `EKTE_API_KEY`, le fichier ne contient
jamais la clé) ou en un seul document JSON (`--as json`) ; `--seq`
choisit les requêtes.

Les clés et les en-têtes sensibles sont retirés avant toute écriture (voir
[Confidentialité](privacy.md)). Chaque ligne respecte
`ekte/schemas/evidence.schema.json` ([Schémas](../../../reference/schemas.md)).
Dans l'interface web, **Afficher les preuves** sous un constat d'une exécution
enregistrée liste les requêtes du contrôle correspondant et ouvre chaque
requête et réponse brute.
