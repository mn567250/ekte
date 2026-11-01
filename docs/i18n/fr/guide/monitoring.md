# Surveillance

> [🇬🇧 English](../../../guide/monitoring.md) · [🇨🇳 中文](../../zh-CN/guide/monitoring.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/monitoring.md) · [🇵🇹 Português](../../pt/guide/monitoring.md) · [🇮🇹 Italiano](../../it/guide/monitoring.md) · [🇩🇪 Deutsch](../../de/guide/monitoring.md) · [🇳🇴 Norsk](../../nb/guide/monitoring.md)

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
des alertes — l'anglais par défaut ; `--alert-lang en|zh|fr|es|pt|it|de|nb`. La
charge utile JSON générique garde ses clés et ses valeurs machine (`risk_level`,
`score`, …) neutres, traduit les valeurs lisibles (`text`, `headline`,
`key_findings`) et indique la `language`.

**Dans l'interface web**, `ekte serve` exécute les mêmes surveillances dans un
planificateur en arrière-plan au sein du processus serveur, enregistre chaque
exécution dans l'**Historique** et envoie les mêmes alertes webhook. Ouvrez une exécution dans l'**Historique** et
choisissez **Planifier comme surveillance**. ekte copie la configuration de
cette exécution (relais, modèle, modèle annoncé, fournisseur, suite, dimensions
personnalisées) dans une surveillance en pause sur la page **Surveillances** ;
définissez-y son intervalle et sa clé API (l'Historique ne stocke jamais de
clés) puis activez-la. Intervalle, clé, **Seuil d'alerte**, webhooks et
**Langue des alertes** se modifient directement sur chaque surveillance. Un
clic sur le nom replie la carte au nom, à l'état et à la dernière exécution
(**Tout replier** / **Tout déplier** au-dessus de la liste ; mémorisé par
navigateur), et le panneau de filtres (recherche, état, dernier risque, type
d'endpoint, relais, suite) réduit une longue liste comme dans l'**Historique**.

Chaque surveillance a sa propre langue d'alerte (par défaut celle de
l'interface), peut être exécutée maintenant, mise en pause ou supprimée, et
reste liée au profil de la base de connaissances avec lequel elle a été créée
jusqu'à ce que vous la reliiez à nouveau.

Les surveillances arrivées à échéance s'exécutent en même temps, chacune comme
son propre audit, mais jamais plus d'un audit à la fois par hôte de relais et au
plus `EKTE_MAX_PARALLEL_AUDITS` au total ; une exécution attend qu'un créneau se
libère (un audit que vous lancez à la main peut aussi attendre derrière les
surveillances en cours). L'heure d'une exécution est celle où son audit démarre,
après une éventuelle attente. La détection de régression compare avec la plus
récente exécution enregistrée du même relais et du même modèle, quel que soit le
nombre d'autres exécutions enregistrées depuis. Les webhooks d'alerte d'une
exécution sont envoyés en même temps, si bien qu'un webhook lent ou hors service
ne retarde pas les autres. Les clés sont stockées chiffrées dans
votre répertoire de données local et ne sont jamais renvoyées au navigateur.

**Stockage des clés API.** Par défaut, ekte **n'enregistre pas** les clés API
des surveillances : une clé saisie reste uniquement dans la mémoire de
`ekte serve` et n'est jamais écrite sur le disque. Après un redémarrage, la page
**Surveillances** indique celles qui ont de nouveau besoin de leur clé ; elles
attendent (sans exécution en échec ni alerte) que vous la saisissiez. Les
surveillances sans clé et les références `env:`/`file:` continuent de tourner.
Pour que les clés survivent aux redémarrages, choisissez **Enregistrer chiffrées
sur cette machine** sous **Stockage des clés API** sur la page **Surveillances** :
les clés sont alors conservées dans `watches.db`, chiffrées avec une clé
maîtresse. Revenir en arrière déplace les clés enregistrées en mémoire et les
efface de `watches.db`. La notice de la page indique le mode actif, demande
confirmation avant un changement et rapporte ce qui a été déplacé. Une
installation qui
enregistrait déjà des clés chiffrées, ou qui définit `EKTE_SECRET_KEY`, continue
de les enregistrer jusqu'à ce que vous changiez.

**Clé maîtresse.** Les clés API des surveillances sont chiffrées avec une clé
maîtresse qu'ekte n'écrit jamais sur le disque. La première fois que vous
enregistrez une clé API, la page **Surveillances** la crée et l'affiche une
seule fois : copiez-la ou téléchargez-la, conservez-la dans un gestionnaire de
mots de passe (votre navigateur peut l'enregistrer), puis collez-la pour
confirmer. Après chaque redémarrage de `ekte serve`, la page la redemande (le
navigateur peut la remplir) ; d'ici là, les surveillances qui en ont besoin
attendent, tandis que celles sans clé ou avec des clés `env:`/`file:` continuent
de s'exécuter. La barre d'état de la page propose aussi **Verrouiller**,
**Renouveler** et **Clé oubliée ?** (supprime les clés API chiffrées pour que
vous puissiez les saisir à nouveau). Pour un usage sans intervention ou sous
Docker, passez la clé dans `EKTE_SECRET_KEY` (voir
[Docker](docker.md)) ; `ekte secret status | export | rotate` la
gèrent en ligne de commande.
