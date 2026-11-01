# Suites et mode comparaison

> [🇬🇧 English](../../../guide/suites.md) · [🇨🇳 中文](../../zh-CN/guide/suites.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/suites.md) · [🇵🇹 Português](../../pt/guide/suites.md) · [🇮🇹 Italiano](../../it/guide/suites.md) · [🇩🇪 Deutsch](../../de/guide/suites.md) · [🇳🇴 Norsk](../../nb/guide/suites.md)

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

## Suite personnalisée

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
page d'audit et les surveillances.

Le **score global est la moyenne pondérée des seules dimensions choisies** ; les
dimensions laissées de côté apparaissent comme « non sélectionnées ». Le verdict
de risque porte lui aussi sur les dimensions choisies : sans l'identité du
modèle, il ne couvre qu'elles, pas le modèle réellement servi, et le dit.

## Mode comparaison et juge LLM

ekte dispose de deux modes de détection :

- **Code pur (par défaut) :** tous les détecteurs sauf `quality_judge` décident
  par du code déterministe — empreintes, balayage du contexte, arithmétique de
  facturation, timing du streaming. Aucun second modèle requis ; les résultats
  sont reproductibles.
- **Hybride code + LLM (`--judge`) :** interroge en plus un modèle juge *de
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
confirmation : réponses d'identité, paramètres de requête rejetés, canaris de
falsification et performance sont jugés côte à côte, et seule une référence
permet à la confiance du verdict d'être *élevée*. Sans `--judge-base-url`, le mode
comparaison utilise la référence comme juge.
