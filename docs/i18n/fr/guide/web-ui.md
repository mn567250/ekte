# Interface web (`ekte serve`)

> [🇬🇧 English](../../../guide/web-ui.md) · [🇨🇳 中文](../../zh-CN/guide/web-ui.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/web-ui.md) · [🇵🇹 Português](../../pt/guide/web-ui.md) · [🇮🇹 Italiano](../../it/guide/web-ui.md) · [🇩🇪 Deutsch](../../de/guide/web-ui.md) · [🇳🇴 Norsk](../../nb/guide/web-ui.md)

Vous préférez cliquer ? Une interface web locale enveloppe le même moteur — sans
ligne de commande.

```bash
pip install 'ekte[web]'     # ou : uv tool install 'ekte[web]'
ekte serve                        # ouvre http://localhost:8000
```

Le formulaire guide la configuration :

1. Choisissez le **Relais / fournisseur** : un fournisseur de la base de
   connaissances ou un relais que vous avez enregistré. Son URL de base est
   remplie (les autres URL connues du fournisseur sont proposées en
   suggestions). Pour tout autre relais, choisissez **Autre (saisir l'URL)** et
   saisissez l'**URL du relais**.
2. Ajoutez la **Clé API** si le relais en demande une.
3. ekte liste lui-même les modèles du relais (au choix d'un relais et à chaque
   changement d'URL ou de clé ; **Actualiser les modèles** redemande). Choisissez
   le **Modèle demandé**. Un relais sans liste de modèles revient à la saisie de
   l'identifiant (**Saisir manuellement**).
4. Choisissez en option le **Modèle annoncé** parmi les modèles de la base de
   connaissances : le modèle que le relais dit servir. Si le modèle demandé est
   dans la base, il est présélectionné ; ne le changez que si le relais vend le
   modèle sous un autre nom. Le profil de fournisseur utilisé pour l'audit en
   découle.

Un relais absent de la liste peut être conservé avec **Enregistrer dans la
base** sous le nom de votre choix ; la fois suivante, il suffit de le choisir.
La référence de confiance (**Comparer à une référence de confiance**) et les
audits d'embedding et de rerank se configurent de la même façon.

Puis **Lancer l'audit**
et suivez les vérifications **en direct** : chaque vérification affiche son score
et sa durée, et une vérification avec des constats se déplie pour montrer les
preuves. Le résultat est un rapport de verdict partageable : note, **Contrôles par
dimension** avec leurs barèmes, constats en langage clair, section performance et
**Journal d'exécution** de chaque détecteur.

Tout s'exécute sur votre machine : une clé saisie dans le navigateur n'atteint
que votre serveur ekte local et le relais audité, jamais un tiers. Voir
[Confidentialité et données locales](privacy.md#confidentialité-et-données-locales).

## Pages

L'interface web est servie à la racine de l'adresse qu'ouvre `ekte serve`, la page d'audit se trouvant à `/`. Les adresses antérieures redirigent vers la page correspondante jusqu'à 1.0.0 (voir [Web UI addresses](../../../reference/stability.md#surface-web-addresses)).

| Page | Adresse | À quoi elle sert |
|---|---|---|
| **Audit** | `/` | Auditer un relais (éventuellement face à une référence) et lire le rapport ; les audits d'embedding et de rerank démarrent aussi ici, via le sélecteur de type d'endpoint |
| **Surveillances** | `/watches` | Ré-audits planifiés avec alertes webhook |
| **Historique** | `/history` | Chaque audit exécuté sur cette machine, groupé par relais + modèle annoncé, avec tendances |
| **Analyses** | `/analytics` | Relais et modèles comparés dans le temps : indicateurs, graphiques avec tableaux de données, classements |
| **Connaissances** | `/kb` | La base de connaissances en trois onglets — modèles, fournisseurs, relais : parcourir, activer/désactiver, ajouter les vôtres |

Sur les pages, en outre : des filtres et des tendances configurables (score,
note, latence p50, tokens/s) dans l'**Historique** ; **Planifier comme
surveillance** et **Relancer l'audit** sur chaque exécution de l'Historique ; **Télécharger le rapport**
dans tous les formats ; et un sélecteur de thème (Automatique / Clair / Sombre).
Chaque page sauf Accessibilité affiche un avis juste
sous son introduction, coloré selon son importance (information, succès,
avertissement, critique) : p. ex. le dernier audit terminé sur **Audit**, la clé
maîtresse sur **Surveillances**, les exécutions encore en traitement sur
**Historique** et **Analyses**, les entrées ignorées sur **Connaissances**.

**Audits en arrière-plan.** Un audit lancé depuis la page
**Audit** continue quand vous changez de page ou fermez l'onglet ; **Continuer en
arrière-plan** l'y envoie volontairement. L'**Historique** liste chaque audit en
file d'attente ou en cours (et chaque surveillance en cours) avec sa
progression ; **Suivre en direct** rouvre la vue en direct, qui rattrape tout ce
qui s'est déjà passé. Les audits d'un même relais s'exécutent l'un après
l'autre, pour ne jamais fausser leurs mesures de latence ou de fiabilité (toutes
les adresses loopback comptent comme un seul hôte : les modèles servis par votre
propre machine attendent aussi) ; les audits de relais différents s'exécutent
en parallèle, quatre au plus à la fois (`EKTE_MAX_PARALLEL_AUDITS`). Les
surveillances attendent leur relais de la même façon.

**Analyses.** `/analytics` transforme l'historique
local en comparaisons : des indicateurs pour la période choisie (exécutions,
score médian, part à risque élevé, taux de réussite, TTFT, vitesse de sortie,
ratios de facturation) avec l'écart par rapport à la période de même durée qui
précède ; un graphique de n'importe quelle métrique par relais, modèle ou
relais × modèle, par heure, jour ou semaine (ligne médiane avec la bande
p25–p75, jusqu'à quatre séries, chaque graphique aussi en tableau de données) ;
et un classement des relais pour un modèle, ou des modèles d'un relais. Les
relais sont regroupés selon leur entrée de la base de connaissances (relais
enregistrés et fournisseurs) : renommer un relais regroupe son historique. Les
intervalles de moins de 3 exécutions sont atténués — un audit isolé peut être
une valeur aberrante ; une surveillance fournit des mesures régulières. Les
exécutions plus anciennes montrent ce qu'elles ont mesuré : la page indique sur
combien d'exécutions repose une valeur. Par défaut, elle compare une suite et
un mode de sonde (les plus fréquents), pour ne pas mélanger des exécutions
différentes ; filtres et vue sont gardés dans l'URL, une vue peut donc être
mise en favori ou partagée. Rien ne quitte la machine.

D'autres panneaux répondent à des questions plus précises : **heures de
pointe** (une carte de chaleur jour de la semaine × heure du TTFT, de la latence et de la vitesse de décodage
(médiane et queues p95 / p5), de la gigue entre tokens, des temps réseau et du relais,
du taux de réussite ou d'erreur dans votre fuseau horaire — un relais
ralentit-il ou échoue-t-il davantage aux heures chargées ? Par jour de la semaine ou, avec 90 jours d'exécutions, sur un
cycle de 4 semaines et, avec 180 jours, par semaine du mois), **erreurs et
fiabilité** (appels en échec par cause — limitation de débit (HTTP 429),
erreurs serveur (5xx), délais dépassés, erreurs réseau — dans le temps et par
relais ou modèle, à partir des enregistrements de requêtes stockés, avec le
nombre d'audits qui en disposent), **intégrité du modèle** (résultats des
vérifications d'identité, de fenêtre de contexte et de capacités par relais ×
modèle, part des audits dont le modèle renvoyé diffère et part mesurée de la
fenêtre de contexte déclarée), **facturation et tokens** (ratios de
facturation dans le temps par rapport à la ligne des 100 % — au-dessus, le
relais déclare plus de tokens qu'ekte n'en a comptés — ainsi que les parts de
tokens de raisonnement et d'entrée en cache) et **surcharge du relais** (le
temps de traitement déclaré par le relais à côté de l'aller-retour réseau).

**Onglets et liens de partage (Analyses).** Les panneaux sont répartis en cinq
onglets — **Vue d'ensemble** (indicateurs, classement), **Tendances**
(comparaison dans le temps, heures de pointe), **Fiabilité** (erreurs, surcoût
du relais), **Intégrité du modèle** et **Facturation** — sous l'en-tête de la
page et un panneau de filtres commun ; seul l'onglet affiché est chargé. L'URL
conserve l'onglet, les filtres et chaque option des graphiques
(`#tab=reliability&range=30&relay=…&eb=dow_hour`), et **Copier le lien vers
cette vue** la copie (ou l'affiche dans un champ à copier si le navigateur ne
le permet pas) : le lien rouvre exactement cette vue. Le panneau de filtres est
le même sur **Historique**, **Surveillances** et **Analyses** : fermé, il indique combien de
filtres sont actifs et les nomme sur une ligne (p. ex. « 30 derniers jours ·
standard · Streaming · Example Relay »), si bien qu'une vue partagée dit ce
qu'elle montre.

## Langues

Un menu de langue dans l'en-tête de chaque page bascule l'interface entre
**🇬🇧 anglais** (par défaut), **🇨🇳 chinois** (l'interface d'origine),
**🇫🇷 français**, **🇪🇸 espagnol**, **🇵🇹 portugais**, **🇮🇹 italien**,
**🇩🇪 allemand** et **🇳🇴 norvégien** (bokmål) ; le choix est mémorisé par navigateur.

Les rapports téléchargés depuis l'interface (**Télécharger le rapport** : JSON,
Markdown, HTML ou PDF) suivent la langue choisie : les clés JSON, les valeurs
d'énumération (`risk_level`, `status`, `severity`, …), les identifiants et les
preuves restent exactement ceux du rapport de la CLI (le JSON reste un rapport
ekte valide), tandis que les valeurs lisibles (titre et résumé du verdict, titres
et résumés des constats, recommandations, noms des détecteurs, notes) sont
traduites, et le nom du fichier porte la langue (`ekte-report.fr.json`,
`ekte-report.fr.pdf`). Les titres de section des fichiers Markdown/HTML/PDF
restent en anglais. Les rapports de la CLI `--format json|md|html|pdf` restent en
anglais.

**Les prompts envoyés à l'endpoint audité ne suivent pas la langue de
l'interface.** Tout texte qu'ekte envoie à une API de LLM est en anglais, afin
que le même relais obtienne le même verdict quel que soit le lecteur du rapport
(les vérifications de réponses et les estimations de tokens sont calibrées sur
ces textes exacts). Seules exceptions : les empreintes de la base de
connaissances dont la langue *est* la mesure — par exemple les sondes de
fluidité en chinois, de tokenizer et d'auto-identification des modèles chinois.
Chaque rapport consigne les langues de sonde réellement utilisées
(`prompt_languages`, p. ex. `["en", "zh"]`).
Chaque rapport consigne aussi la manière dont l'endpoint a été interrogé : le
protocole (`target.api` : `openai`, `anthropic` ou `responses`), si `--api auto`
l'a détecté (`target.api_auto`) et le mode de requête de la sonde de performance
(`stream_mode` : `stream`, `non_stream` ou `both` pour la suite complète). La page
d'historique de l'interface web peut filtrer sur les trois.
`started_at` consigne le début de l'audit (UTC) ; le `start_ms` de chaque
enregistrement de requête compte à partir de ce moment.
