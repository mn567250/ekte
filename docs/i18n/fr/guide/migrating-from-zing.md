# Si vous venez de zing

> [🇬🇧 English](../../../guide/migrating-from-zing.md) · [🇨🇳 中文](../../zh-CN/guide/migrating-from-zing.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/migrating-from-zing.md) · [🇵🇹 Português](../../pt/guide/migrating-from-zing.md) · [🇮🇹 Italiano](../../it/guide/migrating-from-zing.md) · [🇩🇪 Deutsch](../../de/guide/migrating-from-zing.md) · [🇳🇴 Norsk](../../nb/guide/migrating-from-zing.md)

ekte poursuit [zing](https://github.com/cenbonew/zing) (dernière version :
0.11.0) sous un nouveau nom. Ce qui change pour une installation existante :

- **Paquet et commande.** `pip install ekte` (auparavant `zing-audit`), la
  commande `ekte` (auparavant `zing`), le paquet Python `ekte`. Les extras
  gardent leur nom, p. ex. `pip install 'ekte[web]'`. Les deux paquets ne
  partagent ni commande ni module : `zing-audit` peut rester installé à côté
  d'ekte.
- **Variables d'environnement.** `EKTE_*` remplace `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). Une ancienne variable `ZING_*` fonctionne
  encore tant que son nom `EKTE_*` n'est pas défini ; ekte la signale une fois
  sur stderr.
- **Répertoire de données.** Au premier lancement, ekte copie `~/.zing` vers
  `~/.ekte` (historique, surveillances, base de connaissances) si `~/.ekte`
  n'existe pas encore, puis ne travaille plus qu'avec `~/.ekte`. `~/.zing` reste
  tel quel, pour zing s'il tourne encore ; supprimez-le vous-même quand vous n'en
  avez plus besoin. Un répertoire défini par `EKTE_DATA_DIR`, `ZING_DATA_DIR` ou
  `--data-dir` est utilisé tel quel.
- **Interface web.** La langue, le thème et les filtres, ainsi qu'une clé
  maîtresse enregistrée dans le gestionnaire de mots de passe du navigateur, sont
  repris. L'interface classique de zing n'existe plus : ses adresses (`/tools`, `/console`) ouvrent la page d'audit (`/`).
- **Rapports et sondes.** Les rapports, les webhooks et les noms de fichiers
  indiquent `ekte` (p. ex. `"tool": "ekte"`, `ekte-report.json`), tout comme les
  sondes envoyées aux relais. Les scripts qui y cherchent `zing` doivent être
  mis à jour.
- **Calendrier.** Toute la couche de compatibilité (la lecture de `ZING_*`, la copie de `~/.zing`, la reprise des réglages du navigateur, des cookies et de la clé maîtresse enregistrée, et les adresses de l'interface classique) est obsolète et supprimée dans ekte **1.0.0** (1.0.0rc1 est la première version sans elle). D'ici là, chaque partie continue de fonctionner et son avis nomme cette version ; les anciennes adresses de page `/v2/…` redirigent elles aussi jusqu'à 1.0.0. ekte ne supprime jamais un ancien `~/.zing`, même quand la copie est supprimée.
