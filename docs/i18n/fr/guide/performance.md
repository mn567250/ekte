# Performance

> [🇬🇧 English](../../../guide/performance.md) · [🇨🇳 中文](../../zh-CN/guide/performance.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/performance.md) · [🇵🇹 Português](../../pt/guide/performance.md) · [🇮🇹 Italiano](../../it/guide/performance.md) · [🇩🇪 Deutsch](../../de/guide/performance.md) · [🇳🇴 Norsk](../../nb/guide/performance.md)

Chaque rapport comporte une section **performance** : latence, temps jusqu'au
premier token (TTFT), tokens/s de décodage et de bout en bout, latence et gigue
entre fragments, taux d'erreurs/d'expirations/de 429, une décomposition réseau
(connexion TCP, TLS, un aller-retour `GET /models`, temps serveur) et démarrage à
froid, chacun en count / min / mean / p50 / p75 / p90 / p95 / p99 / max / stdev.

Lorsque la sonde dédiée s'exécute, elle note la dimension **Performance**. Le
score porte sur la **régularité**, pas sur la vitesse brute : un endpoint lent
mais régulier (un modèle local ou auto-hébergé) n'est pas pénalisé de ne pas être
un centre de données ; les vérifications et leurs points figurent dans la
[Méthodologie](methodology.md#performance--performance). Les constats de performance sont au plus de gravité faible : ils font bouger le
score, jamais le verdict de risque. Sans la sonde (`standard` sans référence,
`smoke`), la dimension ne s'exécute pas et sort du score global.

- **standard** collecte la section à partir des requêtes de l'audit lui-même.
- **deep / full / custom** ajoutent une sonde dédiée : 100 requêtes non mises en
  cache de 128 tokens de sortie (un identifiant de requête aléatoire ouvre chaque
  prompt ; aucun paramètre de cache ou de raisonnement n'est envoyé) plus une
  rafale à `--concurrency`. Réglez-la avec `--performance-requests` (0 la
  désactive) et `--performance-max-tokens`.
- La sonde utilise le streaming par défaut ; `--performance-non-streaming` (ou le sélecteur
  **Streaming / Sans streaming** de l'interface web) mesure les relais qui ne
  prennent pas en charge le streaming. **full** mesure les deux modes, entrelacés, et les présente
  côte à côte.
- **compare** exécute la sonde sur les deux endpoints, en alternant les requêtes,
  et ajoute un tableau cible-vs-référence (5 requêtes par côté en `standard`, trop
  peu pour les vérifications de régularité) dont les différences sont marquées en
  vert ✓ quand la cible fait mieux et en rouge ✗ quand elle fait moins bien.

Les tokens sont comptés deux fois — depuis l'`usage` du relais et localement —,
si bien que le débit reste mesurable même sans `usage`. Le comptage local est
une estimation par une heuristique intégrée (environ ±15-20 % ; aucun tokenizer
n'est utilisé ni téléchargé), et la section l'indique toujours. Un percentile
n'est affiché qu'avec assez d'échantillons (p90 dès 10, p95 dès 20, p99 dès 100). Le
rapport JSON conserve les temps de chaque requête (des nombres uniquement, aucun
texte) ; le rapport HTML et l'interface web les tracent sur la chronologie de
l'audit.

Les audits qui s'exécutent en même temps dans `ekte serve` (plusieurs onglets du
navigateur, surveillances) ne faussent pas leurs mesures de temps respectives :
la préparation gourmande en CPU, comme la construction des longs prompts de
fenêtre de contexte, s'exécute hors de la boucle d'événements du serveur.

**Délais des requêtes.** `timeout_sec` (`--timeout`, 60 s par défaut) sert de base ;
chaque requête reçoit du temps en plus selon la taille du prompt et le budget de
sortie, pour qu'une longue sonde de fenêtre de contexte ou un modèle auto-hébergé
lent ne soit pas coupé au bout d'une minute. Les hôtes locaux et privés
(`localhost`, `127.x`, `192.168.x`, `host.docker.internal`, …) ont au moins 300 s.
`max_request_sec` (`--max-request-time`, 900 s par défaut) est le plafond absolu
de chaque requête, flux compris, si bien qu'aucune requête ne peut rester bloquée
indéfiniment. Une sonde de fenêtre de contexte qui dépasse malgré tout son délai
est signalée comme non concluante, pas comme une troncature.
