# Confidentialité et données locales

> [🇬🇧 English](../../../guide/privacy.md) · [🇨🇳 中文](../../zh-CN/guide/privacy.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/privacy.md) · [🇵🇹 Português](../../pt/guide/privacy.md) · [🇮🇹 Italiano](../../it/guide/privacy.md) · [🇩🇪 Deutsch](../../de/guide/privacy.md) · [🇳🇴 Norsk](../../nb/guide/privacy.md)

- **Local uniquement.** `ekte serve` n'écoute que sur la boucle locale
  (`127.0.0.1`, `::1`, `localhost`), ne répond qu'à ces noms d'hôte et refuse les
  requêtes intersites ; il n'a pas de connexion par identifiant, car rien hors de
  votre machine ne peut l'atteindre. ekte ne contacte que les endpoints que vous
  configurez (cible, référence, juge, webhooks) ; il ne télécharge rien à
  l'exécution, pas même des fichiers de tokenizer.
- **Clés.** Les rapports et l'historique ne gardent qu'une empreinte d'une clé
  API. Les clés des surveillances sont stockées chiffrées dans `watches.db` ; la
  clé maîtresse qui les déchiffre n'est jamais écrite dans le répertoire de
  données (vous la conservez, voir [Surveillance](monitoring.md)), si bien qu'une
  copie du répertoire ne révèle aucune clé API. Le répertoire reste accessible à
  vous seul.
- **Répertoire de données.** `~/.ekte` (ou `EKTE_DATA_DIR`), créé en `0700` avec
  des fichiers en `0600` : `history.db` (historique des audits), `watches.db`
  (surveillances, clés chiffrées comprises) et `kb.db` (vos entrées de la base
  de connaissances). Supprimez le répertoire pour tout effacer.
  `ekte data-dir` indique où il se trouve ; `--data-dir CHEMIN` en choisit un
  autre le temps d'une exécution, par ex. `ekte serve --data-dir .` place les
  bases dans le dossier courant. Ce sont des fichiers SQLite ordinaires que
  vous pouvez ouvrir pour vos propres analyses (en lecture seule de préférence
  pendant qu'ekte tourne). Ne committez pas `watches.db` si ce dossier est un
  dépôt.
  `history_metrics` contient une ligne de valeurs mesurées par exécution et
  `history_requests` chaque enregistrement de requête (stocké là une seule fois,
  pas dans chaque rapport).

## Utilisation responsable

ekte est une aide à l'audit en boîte noire. Il **ne peut pas prouver** :

- qu'un fournisseur stocke vos prompts ou s'entraîne dessus,
- qu'il route toujours vers un seul modèle précis (les relais peuvent router de façon probabiliste),
- une fraude à la facturation au-delà de ce que l'estimation indépendante des tokens peut suggérer.

Utilisez les rapports pour votre propre vérification. **N'accusez pas
publiquement un fournisseur** sur la base d'une seule exécution sans examiner la
taille de l'échantillon, les paramètres de coût et le droit local. Lancez
`ekte compare` contre une référence de confiance avant de tirer des conclusions
fortes.
