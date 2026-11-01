# Exécuter l'interface web dans Docker

> [🇬🇧 English](../../../guide/docker.md) · [🇨🇳 中文](../../zh-CN/guide/docker.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/docker.md) · [🇵🇹 Português](../../pt/guide/docker.md) · [🇮🇹 Italiano](../../it/guide/docker.md) · [🇩🇪 Deutsch](../../de/guide/docker.md) · [🇳🇴 Norsk](../../nb/guide/docker.md)

`ekte serve` est un outil mono-utilisateur sans connexion. Hors d'un conteneur,
il n'écoute jamais que sur l'interface de bouclage (`127.0.0.1`, `::1`,
`localhost`) et refuse toute autre adresse d'écoute. Un conteneur est la seule
exception : le serveur doit écouter sur les interfaces propres du conteneur pour
que la publication de port de Docker puisse l'atteindre.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# ouvrir http://localhost:8000
```

**Publiez toujours sur `127.0.0.1`** (`-p 127.0.0.1:8000:8000`, et non
`-p 8000:8000`). Un simple `-p 8000:8000` expose l'interface — et chaque clé API
saisie dedans ou stockée dans une surveillance — à votre réseau.

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `EKTE_CONTAINER` | non définie (`1` dans l'image) | Autorise une écoute hors bouclage. ekte vérifie aussi qu'il tourne réellement dans un conteneur (`/.dockerenv`, `/run/.containerenv` ou Kubernetes) ; la définir sur un hôte ordinaire n'ouvre pas le serveur. |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` dans l'image) | Adresse d'écoute. Tout ce qui n'est pas le bouclage exige `EKTE_CONTAINER=1`. `--host` l'emporte sur elle. |
| `EKTE_PORT` | `8000` | Port à l'intérieur du conteneur. `--port` l'emporte sur elle. |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` dans l'image) | Historique des audits, surveillances (y compris leurs clés API) et vos propres entrées de la base de connaissances. Montez un volume ici pour les conserver. |
| `EKTE_SECRET_KEY` | non définie | Clé maîtresse qui chiffre les clés API stockées des surveillances : la clé que la page **Surveillances** (ou `ekte secret rotate`) vous a affichée, ou `file:/run/secrets/ekte_key` / `env:VAR`. Si elle n'est pas définie, vous saisissez la clé sur la page **Surveillances** après chaque démarrage du conteneur. Elle n'est jamais stockée dans `EKTE_DATA_DIR`. La définir sur un répertoire de données neuf choisit le stockage chiffré des clés ; sans elle, les clés API des surveillances ne sont pas stockées du tout et doivent être saisies à nouveau après chaque démarrage du conteneur. Voir plus bas. |
| `EKTE_KB_DIR` | non définie | Répertoire YAML supplémentaire de la base de connaissances, monté en lecture seule par exemple (`-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb`). |
| `EKTE_NO_USER_KB` | non définie | `1` ignore les entrées de la base de connaissances ajoutées dans l'interface (`kb.db`). |
| `EKTE_ALLOWED_HOSTS` | non définie | Noms d'hôte supplémentaires, séparés par des virgules, auxquels l'interface répond, si vous l'atteignez sous un autre nom que `localhost`/`127.0.0.1`. |

**Si vous venez de l'image zing.** Renommez les options `-e ZING_*` en
`EKTE_*`. ekte lit encore une variable `ZING_*` dont le nom `EKTE_*` n'est pas
défini, mais l'image définit elle-même `EKTE_CONTAINER`, `EKTE_HOST`,
`EKTE_PORT` et `EKTE_DATA_DIR`, si bien qu'un ancien `ZING_HOST`, `ZING_PORT`
ou `ZING_DATA_DIR` n'a aucun effet dans le conteneur. Le volume de données reste
sur `/data` et l'utilisateur non privilégié garde l'uid 10001, de sorte qu'un
volume `zing-data` existant peut être monté tel quel (`-v zing-data:/data`). La
reprise des `ZING_*` est obsolète et supprimée dans ekte 1.0.0 (voir la
[politique de stabilité](../../../reference/stability.md#deprecation-zing)).

## Ce qui protège l'interface

- **Liste d'hôtes autorisés.** Les requêtes dont l'en-tête `Host` n'est ni
  `localhost`, ni `127.0.0.1`, ni `[::1]`, ni listé dans `EKTE_ALLOWED_HOSTS`
  sont refusées. Cela empêche le DNS rebinding, où un site web fait pointer son
  propre domaine vers `127.0.0.1` pour parler aux serveurs locaux. Le port n'est
  pas vérifié, donc n'importe quel port publié sur l'hôte fonctionne.
- **Contrôles d'origine et de JSON.** Les requêtes qui modifient l'état et
  viennent d'une autre origine sont refusées, et les corps de requête doivent
  être en `application/json`, si bien qu'un autre site web ne peut pas
  soumettre de formulaires à l'API locale.
- **En-têtes de sécurité.** L'interface ne peut pas être intégrée dans un cadre
  par d'autres sites (`X-Frame-Options`, `frame-ancestors`), et aucun référent
  ne quitte la page.
- **Clés des surveillances chiffrées.** Les clés API stockées sont chiffrées
  avec une clé maîtresse qui n'est jamais écrite sur le volume de données, si
  bien qu'une copie du volume ne révèle aucune clé API. Sans `EKTE_SECRET_KEY`,
  la page **Surveillances** affiche la clé une fois à sa création et la demande
  après chaque démarrage du conteneur ; les surveillances qui en ont besoin
  attendent jusque-là. Pour des redémarrages sans intervention, transmettez-la
  comme secret Docker (le serveur la garde en mémoire ; exécutez un seul
  processus serveur par volume de données) :

  ```bash
  # la clé que la page Surveillances vous a affichée, ou une nouvelle : ekte secret rotate
  docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data \
    -v "$PWD/ekte_key:/run/secrets/ekte_key:ro" \
    -e EKTE_SECRET_KEY=file:/run/secrets/ekte_key ekte
  ```

  Une `EKTE_SECRET_KEY` qui n'est pas la clé utilisée par les clés API stockées
  est refusée (l'interface l'indique). Renouvelez-la avec `ekte secret rotate` ;
  une clé perdue ne peut être réinitialisée que sur la page **Surveillances**,
  ce qui supprime les clés API stockées.
- **Données réservées au propriétaire.** Le répertoire de données est créé en
  `0700` et chaque fichier de base de données en `0600` ; l'image s'exécute
  sous un utilisateur non privilégié.
