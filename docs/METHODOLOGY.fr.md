# zing — Méthodologie

> [🇬🇧 English](METHODOLOGY.md) · [🇨🇳 中文](METHODOLOGY.zh-CN.md) · **🇫🇷 Français** · [🇪🇸 Español](METHODOLOGY.es.md) · [🇵🇹 Português](METHODOLOGY.pt.md) · [🇮🇹 Italiano](METHODOLOGY.it.md) · [🇩🇪 Deutsch](METHODOLOGY.de.md)

Ce document explique comment **zing** parvient à son verdict : quelles sondes
en boîte noire chaque détecteur envoie, comment leurs résultats deviennent des
points, comment les points deviennent des scores de dimension et un score
global, et comment le verdict de risque est décidé. Il décrit l'implémentation
actuelle ; chaque tableau de notation ci-dessous est le barème publié du
détecteur (`SCALE` dans `zing/detectors/*.py`), avec la formulation exacte que
l'interface web affiche sous **Barème**.

> zing fournit **des preuves en boîte noire d'écarts et de risques, pas une
> preuve cryptographique de fraude.** Voir [Limites et utilisation responsable](#limites-et-utilisation-responsable).

---

## Position de principe

Un relais peut légitimement dériver, mettre à jour ses instantanés, mutualiser
sa capacité ou mettre en tampon un amont qui ne sait pas streamer. zing traite
donc chaque signal isolé comme un *indicateur de risque*, jamais comme un
verdict : les constats s'appuient sur des preuves, sont formulés avec prudence,
et un résultat ambigu reste **non concluant** au lieu d'être forcé en réussite
ou en échec. Le verdict de risque n'atteint « élevé » que sur des preuves
solides de gravité élevée, et la meilleure confirmation reste toujours le
**mode comparaison** (`zing compare`) : exécuter les mêmes sondes, au même
moment, contre une *référence de confiance du modèle annoncé*.

## Comment zing note

### Score du détecteur

Chaque détecteur publie son **barème** (`DetectorResult.scoring`, construit
avec `zing/detectors/scale.py`) : chaque résultat possible de chacune de ses
vérifications, avec statut, gravité et effet sur le score. Chaque constat
enregistre l'`outcome` atteint, de sorte que rapport et comportement ne peuvent
diverger. Un barème utilise l'une de deux méthodes :

- **Moyenne des vérifications** (`Scale`, méthode `mean_of_checks`) : chaque
  vérification rapporte des points ; le score du détecteur est la moyenne des
  vérifications comptées. Un résultat marqué **Non compté** (typiquement une
  vérification non concluante) ne relève ni n'abaisse le score.
- **Déductions** (`DeductionScale`, méthode `deductions`) : le score part de
  100, les constats retirent des points (`Finding.deduction`) et/ou le
  plafonnent (`Finding.cap`) ; le plafond le plus bas l'emporte.

Une vérification *paramétrée* applique un même jeu de lignes à de nombreux
sujets (par exemple chaque attribut de réponse) : chaque sujet est noté
séparément, le barème est publié une fois par vérification et les rapports
listent les sujets sous leur vérification.

### Score et statut d'une dimension

zing note dix dimensions. Le score d'une dimension est la **moyenne à poids
égal des scores de ses détecteurs** : un détecteur riche en vérifications ne
pèse pas plus qu'un détecteur qui en a peu, et un détecteur sans score
numérique est laissé de côté. Son statut est le pire statut conclu par ses
détecteurs, sauf qu'un constat de gravité ÉLEVÉE/CRITIQUE impose **Échec** et
qu'un constat de gravité MOYENNE fait passer **Réussi** à **Avertissement**,
quel que soit le score. Chaque rapport consigne ce calcul par dimension
(`DimensionScore.breakdown` : le score de chaque détecteur, s'il a compté, et
tout changement de statut avec les constats qui l'ont causé) et l'affiche sous
**Dimension details** (Markdown/HTML/PDF) et dans les lignes dépliables des
**Contrôles par dimension** de l'interface web. Un détecteur qui plante est
rapporté avec le statut **Erreur** et n'interrompt jamais l'audit.

### Score global, note et poids

Le **score de santé global** est la moyenne pondérée des dimensions qui ont
produit un score (`DIMENSION_WEIGHTS` dans `zing/scoring.py`). Une dimension
qui ne s'est pas exécutée (absente de la suite ou non choisie dans une
exécution `custom`) sort du calcul et les poids restants sont renormalisés. La
note est A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) ou F.

| Dimension | Id | Poids | Rôle |
|---|---|---|---|
| Identité du modèle | `model_identity` | 21 | cœur |
| Fenêtre de contexte | `context_window` | 19 | cœur |
| Capacités annoncées | `capability` | 13 | cœur |
| Conformité du protocole | `protocol` | 8 |  |
| Facturation et consommation | `billing` | 8 |  |
| Connectivité | `connectivity` | 7 |  |
| Authenticité du streaming | `streaming` | 6 |  |
| Fiabilité en concurrence | `reliability` | 6 |  |
| Sécurité du transport | `security` | 6 |  |
| Performance | `performance` | 6 |  |

Les trois **dimensions cœur** sont celles dont l'échec révèle le plus
directement une tromperie sur la marchandise.

### Verdict de risque

Le niveau de risque dépend de la **gravité des constats**, pas du score. Les
constats de la dimension connectivité sont exclus : un relais injoignable ou
limité n'a pas pu être évalué, ce qui ne prouve pas qu'un autre modèle répond.

| Risque | Libellé dans l'interface | Quand |
|---|---|---|
| `inconclusive` | Signal insuffisant | Aucune dimension cœur n'a produit de résultat exploitable (Réussi, Avertissement ou Échec) — par exemple relais injoignable, modèle sans profil, ou exécution `custom` sans dimension cœur |
| `high` | Tromperie sur la marchandise | Un constat CRITIQUE, un constat ÉLEVÉ/CRITIQUE dans une dimension cœur, ou au moins deux constats ÉLEVÉS |
| `medium` | Écarts détectés | Exactement un constat ÉLEVÉ hors des dimensions cœur, ou un constat MOYEN dans une dimension cœur |
| `low` | Globalement fiable | Tout autre constat MOYEN |
| `clean` | Cohérent (probablement authentique) | Aucun des cas ci-dessus |

### Confiance du verdict

- **Faible** — le modèle annoncé est absent de la base de connaissances, ou
  moins de deux dimensions cœur ont produit un résultat exploitable ;
- **Moyenne** — au moins deux dimensions cœur ont produit un résultat
  exploitable ;
- **Élevée** — une référence a été utilisée *et* les trois dimensions cœur ont
  produit un résultat exploitable, ou la confiance était moyenne et le juge LLM
  a rendu un verdict exploitable.

## Suites, détecteurs et modes

| Détecteur | Id | Dimension | À partir de la suite |
|---|---|---|---|
| Connectivité et complétion de base | `connectivity` | Connectivité | `smoke` |
| Conformité à la compatibilité OpenAI | `protocol` | Conformité du protocole | `standard` |
| Prise en charge des attributs de requête | `protocol_request` | Conformité du protocole | `standard` |
| Disponibilité des attributs de réponse | `protocol_response` | Conformité du protocole | `standard` |
| Déterminisme et exactitude du cache | `determinism` | Conformité du protocole | `deep` |
| Fenêtre de contexte réelle et troncature | `context_window` | Fenêtre de contexte | `deep` |
| Identité du modèle et empreinte de déclassement | `model_identity` | Identité du modèle | `standard` |
| Évaluation de qualité / déclassement par un LLM juge | `quality_judge` | Identité du modèle | `deep` (uniquement avec `--judge`) |
| Vérification des capacités annoncées | `capability` | Capacités annoncées | `standard` |
| Vérification de la capacité multimodale (vision) | `vision` | Capacités annoncées | `deep` |
| Authenticité du streaming | `streaming` | Authenticité du streaming | `standard` |
| Audit de facturation des tokens | `billing` | Facturation et consommation | `standard` |
| Fiabilité et latence en concurrence | `reliability` | Fiabilité en concurrence | `standard` |
| Signaux de transport et de gestion des secrets | `security` | Sécurité du transport | `smoke` |
| Détection de prompt système injecté | `injected_prompt` | Sécurité du transport | `deep` |
| Intégrité des réponses / falsification | `integrity` | Sécurité du transport | `deep` |
| Cache de préfixe de prompt (timing) | `prompt_cache` | Sécurité du transport | `deep` |
| Sonde de performance | `performance` | Performance | `deep` (en `standard` uniquement avec une référence, 5 requêtes) |

- **smoke** exécute connectivité et sécurité ; **standard** ajoute les
  détecteurs de protocole, d'identité, de capacités, de streaming, de
  facturation et de fiabilité ; **deep** ajoute les sondes de contexte long, de
  déterminisme, de vision, de prompt injecté, d'intégrité, de cache de prompt
  et de performance (et le juge avec `--judge`) ; **full** exécute les mêmes
  détecteurs que deep et mesure la performance avec et sans streaming ;
  **custom** exécute tous les détecteurs des dimensions choisies, à la
  profondeur de deep.
- **Code pur (par défaut) :** tous les détecteurs sauf `quality_judge` décident
  par du code déterministe — vérifications de texte et d'expressions
  régulières, arithmétique, statistiques de temps. Aucun second modèle requis.
- **Hybride code + LLM (`--judge`) :** `quality_judge` demande à un modèle juge
  de confiance, configuré séparément (jamais la cible), si les réponses de la
  cible ressemblent au modèle annoncé. Sans `--judge-base-url`, le mode
  comparaison utilise la référence comme juge.
- **Mode comparaison** (`zing compare`) donne aux sondes une référence de
  confiance : `model_identity` consigne l'auto-identification de la référence à
  côté de celle de la cible, `protocol_request` renvoie les paramètres rejetés
  à la référence, `integrity` porte à CRITIQUE une substitution que la référence
  ne fait pas, `quality_judge` montre les deux côtés au juge, et `performance`
  sonde les deux endpoints en alternance. La confiance ne peut être élevée
  qu'avec une référence.
- **Base de connaissances :** le profil du modèle annoncé
  (`zing/knowledge/data/*.yaml` et vos propres entrées dans `kb.db`) fournit la
  fenêtre de contexte annoncée, la sortie maximale, le tokenizer, les capacités,
  les mots-clés d'identité et les empreintes comportementales auxquels les
  sondes sont comparées. Chaque rapport consigne le profil utilisé
  (`knowledge`).
- **Langue des prompts :** chaque texte de sonde se trouve dans
  `zing/prompts/en.json` et reste en anglais quelle que soit la langue de
  l'interface ; seules les empreintes dont la langue *est* la mesure déclarent
  `prompt_lang` et `language_bound`. Chaque rapport liste les langues des
  sondes utilisées (`prompt_languages`).
- **Modèles de raisonnement :** une sonde courte qui s'arrête à sa limite de
  sortie avec une réponse absente, ou coupée après que le raisonnement a pris au
  moins la moitié de la limite (`reasoning_tokens` signalés), est répétée une fois
  avec une limite de 4 096 tokens, pour qu'un modèle qui réfléchit avant de
  répondre ne soit pas lu comme un échec. Les sondes dont la limite ou le
  chronométrage est la mesure (performance, cache de prompt, fiabilité, prompt
  injecté, sortie maximale, l'attribut de requête `max_tokens`) ne sont jamais répétées.
  Dès qu'un endpoint est connu pour raisonner (son profil indique
  `reasoning: true`, ou après sa première répétition de ce type), les sondes
  courtes partent d'emblée avec la limite de 4 096 tokens au lieu de deux fois.

---

## `connectivity` — Connectivité

**Détecte.** Aucune astuce directement : c'est la porte dont dépendent tous
les autres détecteurs. Elle distingue une clé morte ou mal configurée d'un
relais qui mérite un audit.

**Fonctionnement.** `GET /v1/models` (note si le modèle annoncé est listé) et
une complétion de chat à `temperature=0` demandant au modèle de répéter un
canari exact ; relève la latence et le champ `model` renvoyé.

**Barème** (`zing/detectors/connectivity.py`) :

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `connectivity.models` | La liste des modèles (/v1/models) a répondu. | Réussi | 100 pts |
|  | La liste des modèles (/v1/models) n'a pas répondu ; certains relais la désactivent. | Avertissement · Faible | 60 pts |
| `connectivity.chat` | Une complétion de chat a renvoyé du contenu et répété le canari. | Réussi | 100 pts |
|  | Une complétion de chat a renvoyé du contenu, sans répéter le canari. | Réussi | 85 pts |
|  | La complétion de chat a échoué ou n'a renvoyé aucun contenu. | Échec · Élevée | 0 pts |

**Mises en garde.** L'absence de `/v1/models` est bénigne ; beaucoup de relais
le désactivent. Une erreur réseau passagère ou un 5xx peut faire échouer la
vérification de chat : relancez. La connectivité ne prouve rien sur *quel*
modèle a répondu. Ses constats ne relèvent jamais le verdict de risque.

---

## `protocol` — Conformité du protocole

**Détecte.** Les relais dont le middleware casse le contrat du protocole (tours
perdus, séquences d'arrêt ignorées, erreurs malformées, champs de réponse
absents ou à zéro, paramètres de requête supprimés) et, via le déterminisme,
`cache.ignore-temperature`. Couvre en partie `capability.json-tool-fakery`.

### `protocol` — Conformité à la compatibilité OpenAI

**Fonctionnement.** Trois sondes : une conversation multi-tours qui doit se
souvenir d'une couleur d'un tour précédent ; une séquence `stop` qui doit
tronquer la sortie ; et une requête volontairement invalide (`messages` vide)
qui doit être rejetée par un 4xx, idéalement avec un corps d'erreur de style
OpenAI.

La Responses API n'a pas de paramètre `stop` : face à une cible Responses API,
la sonde d'arrêt n'est donc pas envoyée et la vérification est notée non
applicable (non comptée) au lieu d'incriminer le relais.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `protocol.multi_turn` | La couleur d'un tour précédent a été retrouvée. | Réussi | 100 pts |
|  | La couleur d'un tour précédent n'a pas été retrouvée. | Avertissement · Moyenne | 55 pts |
|  | Aucune réponse exploitable pour juger. | Non concluant · Faible | Non compté |
| `protocol.stop` | La sortie s'est arrêtée à la séquence d'arrêt. | Réussi | 100 pts |
|  | La gestion de l'arrêt n'a pas pu être confirmée d'après le texte. | Avertissement · Faible | 70 pts |
|  | Du texte après la séquence d'arrêt a été renvoyé. | Avertissement · Faible | 60 pts |
|  | Aucune réponse exploitable pour juger. | Non concluant · Faible | Non compté |
|  | La Responses API n'a pas de paramètre stop ; non vérifié, non compté. | Info | Non compté |
| `protocol.error_schema` | Rejetée avec un 4xx et un corps d'erreur de style OpenAI. | Réussi | 100 pts |
|  | Rejetée avec un 4xx, mais le corps n'est pas de style OpenAI. | Avertissement · Faible | 80 pts |
|  | Pas de réponse HTTP ; la gestion des erreurs client n'a pas pu être confirmée. | Avertissement · Faible | 55 pts |
|  | Un autre statut HTTP ; la gestion des erreurs client n'a pas pu être confirmée. | Avertissement · Faible | 55 pts |
|  | La requête invalide a provoqué une erreur serveur (5xx). | Échec · Moyenne | 35 pts |
|  | La requête invalide a été acceptée (2xx). | Échec · Moyenne | 30 pts |

### `protocol_response` — Disponibilité des attributs de réponse

**Fonctionnement.** Un appel normal sans streaming ; chaque attribut du
protocole de la cible (OpenAI Chat Completions, Anthropic Messages ou OpenAI
Responses ; catalogue dans `zing/detectors/wire_attrs.py`) est jugé sur le
corps brut. Les attributs essentiels sont par exemple `model`,
`choices[0].message.role/content`, `finish_reason`, `usage.prompt_tokens`,
`usage.completion_tokens` et `usage.total_tokens` (qui doit égaler la somme des
deux) ; les secondaires sont `id`, `object`, `created`/`created_at`,
`choices[0].index` et `type`. Un zéro là où un compte doit être positif
(`completion_tokens: 0` pour une réponse non vide) compte comme zéro, pas comme
valide.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `protocol_response.core` (Attributs de réponse essentiels) | Présent avec une valeur valide. | Réussi | 100 pts |
|  | Présent mais nul ou vide (p. ex. completion_tokens: 0). | Échec · Moyenne | 20 pts |
|  | Présent avec un type ou une valeur incorrects (p. ex. total ≠ somme des parties). | Avertissement · Moyenne | 40 pts |
|  | Absent de la réponse. | Échec · Moyenne | 0 pts |
| `protocol_response.minor` (Attributs de réponse secondaires) | Présent avec une valeur valide. | Réussi | 100 pts |
|  | Présent mais nul ou vide. | Avertissement · Faible | 50 pts |
|  | Présent avec un type ou une valeur incorrects. | Avertissement · Faible | 70 pts |
|  | Absent de la réponse. | Avertissement · Faible | 60 pts |
| `protocol_response.call` (Sonde des attributs de réponse) | L'appel de sonde n'a renvoyé aucun corps de réponse à évaluer. | Non concluant · Faible | Non compté |

### `protocol_request` — Prise en charge des attributs de requête

**Fonctionnement.** Chaque paramètre de requête du protocole est envoyé
(environ cinq appels). Les paramètres à effet observable ont leur propre appel
et doivent le montrer : `system`/`instructions` suivi, la limite de sortie
aboutit à `finish_reason: length`, `n: 2` renvoie deux choix, `logprobs` est
renvoyé. Les paramètres qui doivent seulement être acceptés (`temperature`,
`top_p`, `seed`, pénalités, `user`, `top_k`, `metadata`) partagent un appel et
ne sont réessayés un par un que s'il est rejeté. Un 4xx compte comme limite du
modèle (non compté) plutôt que comme rejet lorsque la base de connaissances
liste le paramètre dans `unsupported_params`, lorsqu'un paramètre
d'échantillonnage est envoyé à un modèle de raisonnement, ou lorsqu'une
référence sur le même protocole le rejette aussi. Outils et mode JSON restent
à `capability`, `stop` à `protocol`, l'usage en streaming à `streaming`.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `protocol_request.param` (Paramètres de requête) | Accepté, et son effet est visible dans la réponse. | Réussi | 100 pts |
|  | Accepté (son effet n'est pas observable sur une seule réponse). | Réussi | 100 pts |
|  | Accepté, mais son effet est absent de la réponse. | Avertissement · Faible | 50 pts |
|  | Rejeté avec un 4xx (peut-être une limite du modèle lui-même). | Avertissement · Faible | 40 pts |
|  | Rejeté avec un 4xx, alors que la référence l'accepte. | Échec · Moyenne | 15 pts |
|  | Rejeté, mais le modèle lui-même ne le prend pas en charge ; non compté. | Info | Non compté |
|  | Erreur serveur ou pas de réponse ; non compté. | Non concluant · Faible | Non compté |

### `determinism` — Déterminisme et exactitude du cache

**Fonctionnement.** Quatre prompts créatifs identiques à `temperature=1.0`
(sans seed) : un vrai modèle varie ; une sortie identique à l'octet près sur
tous les échantillons indique un cache de réponses qui ignore
l'échantillonnage. Le verdict est suspendu pour les modèles de raisonnement,
qui ignorent légitimement la température. Deux questions factuelles
identiques à `temperature=0` sont purement indicatives.

Pour conclure à un cache, au moins trois des quatre échantillons doivent être
exploitables (et tous les exploitables identiques) ; avec moins, la vérification
n'est pas concluante.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `determinism.temp1_variability` | Les échantillons répétés à temperature=1.0 différaient, comme avec un véritable échantillonnage. | Réussi | 100 pts |
|  | Les échantillons étaient identiques, mais les modèles de raisonnement ignorent légitimement temperature. | Info | 100 pts |
|  | Tous les échantillons exploitables (au moins 3) à temperature=1.0 étaient identiques à l'octet près, ce qui suggère une mise en cache des réponses. | Avertissement · Moyenne | 55 pts |
|  | Moins de 3 échantillons exploitables à temperature=1.0 pour en juger. | Non concluant · Faible | Non compté |
| `determinism.temp0_stability` | Réponses identiques à temperature=0 (attendu) ; à titre indicatif, non noté. | Info | Non compté |
|  | Les réponses différaient à temperature=0 ; à titre indicatif, non noté. | Info | Non compté |
|  | Aucune réponse exploitable pour juger. | Non concluant · Faible | Non compté |

**Mises en garde.** Les passerelles peuvent ajouter des champs propres au
fournisseur ; seuls les champs obligatoires absents ou invalides sont signalés.
La traduction entre dialectes Anthropic et OpenAI remodèle légitimement
certaines structures. Confirmez un défaut suspecté en le répétant et, si
possible, en mode comparaison.

---

## `context_window` — Fenêtre de contexte

**Détecte.** `context.window-truncation` (un relais annonce 128K/200K/1M mais
coupe le prompt en silence) et `context.lost-in-middle-rag` (une couche
RAG/résumé bon marché ne transmet qu'une partie du prompt).

**Fonctionnement.** Rappel d'une aiguille dans une botte de foin à
`temperature=0` : un marqueur unique est placé dans un texte de remplissage non
répétitif dimensionné avec l'estimation heuristique des tokens de zing, et le
modèle doit le restituer.

1. Une échelle croissante qui double à partir de 2K tokens jusqu'à la fenêtre
   annoncée, plafonnée par `--max-context-tokens` (200K par défaut), avec un
   échelon vers 90 % du sommet (sept tailles au plus). Chaque taille est d'abord
   sondée avec l'aiguille au **début** (profondeur 0,0) : une troncature qui
   garde la question en fin de prompt ne peut écarter que son début (un serveur
   local qui coupe le prompt à sa longueur de contexte en garde la fin), donc un
   rappel à cet endroit valide la taille en un seul appel. Un échec est vérifié
   à la fin (profondeur 0,95) ; si la fin est retrouvée, le début est sondé une
   fois de plus avec une aiguille neuve, et un second échec fait échouer la
   taille comme **troncature par le début** (signalée dans les preuves du
   verdict). Trois appels par taille au plus ; l'échelle s'arrête au premier
   échec confirmé.
2. Une étape de recherche dichotomique entre la dernière taille retrouvée et la
   première en échec.
3. Perte au milieu : à min(32K, fenêtre mesurée), l'aiguille est placée aux
   profondeurs 0,1, 0,5 et 0,9 ; début et fin retrouvés mais pas le milieu
   constituent un constat.
4. Un 4xx dont le message évoque la longueur de contexte est un rejet pour
   taille ; un rejet de `max_tokens` (modèles de raisonnement) est réessayé avec
   `max_completion_tokens` et n'est jamais lu comme un plafond.
5. Une sonde qui dépasse son délai arrête l'échelle sans compter comme un échec :
   la fenêtre au-delà de la dernière taille rappelée est signalée comme non
   vérifiée (non concluant), jamais comme une troncature.

La fenêtre mesurée est comparée à la fenêtre annoncée. Sans fenêtre annoncée,
la mesure est rapportée mais non notée.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `context_window.window` (Fenêtre de contexte effective) | Le rappel a tenu jusqu'à au moins 90 % de la fenêtre annoncée ; retire la part de la fenêtre non rappelée. | Réussi | jusqu'à −10 pts |
|  | Le rappel a tenu jusqu'à 50–90 % de la fenêtre annoncée ; retire la part de la fenêtre non rappelée. | Avertissement · Moyenne | jusqu'à −50 pts |
|  | Le rappel a échoué sous la moitié de la fenêtre annoncée ; retire la part de la fenêtre non rappelée. | Échec · Élevée | jusqu'à −100 pts |
|  | Même la plus petite taille de sonde n'a pas retrouvé l'aiguille. | Échec · Élevée | −100 pts |
| `context_window.lost_in_middle` | Le début et la fin ont été retrouvés, mais pas le milieu. | Avertissement · Moyenne | −15 pts |
| `context_window.rejected_below_claim` | Un prompt bien en dessous de la fenêtre annoncée a été rejeté comme trop long. | Échec · Élevée | Aucune déduction |
| `context_window.measured` | Aucune fenêtre annoncée pour comparer : mesurée seulement, non notée. | Info | Aucune déduction |
| `context_window.no_ladder` | Aucune taille de sonde ne tenait entre le plancher et le plafond. | Non concluant · Faible | Aucune déduction |
| `context_window.timed_out` | Une sonde a dépassé son délai avant d'atteindre la fenêtre annoncée : un endpoint lent, pas une preuve de troncature. | Non concluant · Faible | Aucune déduction |

**Mises en garde.** Les vrais modèles à long contexte perdent aussi des
aiguilles au milieu ; seul un échec en **bordure** est donc lu comme une
troncature. Le rappel près du plafond est probabiliste ; relancez avant de
conclure. La sonde est bornée par `--max-context-tokens`, une fenêtre plus
grande n'est donc pas entièrement exercée. Comparez à une référence de
confiance pour séparer le comportement du modèle de celui d'une couche
intermédiaire.

---

## `model_identity` — Identité du modèle

**Détecte.** `downgrade.silent-substitution` (un nom premium sur un backend
moins cher ou ouvert), ainsi que les signaux de
`downgrade.reasoning-collapse`, `downgrade.quantized-distilled` et
`downgrade.partial-probabilistic-routing` lorsqu'ils changent le comportement.

### `model_identity` — Identité du modèle et empreinte de déclassement

**Fonctionnement.** Trois signaux indépendants :

1. **Auto-identification** à `temperature=0`, comparée en mots entiers aux
   mots-clés d'identité du profil (la vraie marque) et à une liste de marques
   concurrentes (`identity_forbidden` du profil plus une liste intégrée). Une
   marque concurrente ne compte que si la vraie marque est absente ; « Je suis
   Claude, pas GPT » est un contraste bénin.
   La vraie marque, ce sont les `identity_keywords` du profil plus ses propres
   noms : la clé du fournisseur, le nom en tête du nom affiché du fournisseur,
   le premier mot de l'id et de la famille du modèle, et les autres noms de ce
   fabricant dans la liste intégrée (`z.ai` couvre aussi `zhipu`). Un modèle
   qui nomme son propre fabricant n'est donc jamais une marque concurrente,
   même quand `identity_keywords` est vide. Les noms dérivés ne l'emportent
   jamais sur `identity_forbidden`, les mots génériques (« ai », « platform »,
   …) ne comptent jamais, et la marque propre d'une plateforme ne compte pas
   pour le modèle d'un autre fabricant qu'elle sert.
2. **Empreintes comportementales** de la base de connaissances (date limite des
   connaissances, particularités du tokenizer, mise en forme, sondes liées à
   une langue, …) : jusqu'à six sondes en code pur, vérifiées par
   `expect_contains`, `expect_contains_any`, `expect_not_contains` ou
   `expect_regex` ; sortie limitée à 512 tokens. Une sonde qui
   demande plus de sortie (un test de sortie maximale, par exemple) est
   ignorée, signalée en Info, et une autre sonde prend sa place. Une
   empreinte qui s'écarte
   retire sa part de poids sur 100 points (25 au plus) ; seule, elle reste
   FAIBLE, deux ou plus ajoutent un constat agrégé MOYEN.
3. **Champ `model` renvoyé** par un appel simple : suffixes d'instantané et
   alias sont tolérés ; un mot de gamme inférieure (`mini`, `flash`, `lite`,
   `8b`, …) ou une autre famille est signalé.

Sans profil dans la base de connaissances, le détecteur est non concluant.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `model_identity.self_id` | L'auto-description a nommé la marque authentique. | Réussi | Aucune déduction |
|  | L'auto-description a nommé une marque concurrente et non la marque authentique. | Échec · Élevée | plafond 20 |
|  | L'auto-description a nommé la marque authentique et une concurrente (en général une comparaison anodine). | Avertissement · Faible | Aucune déduction |
|  | L'auto-description n'a nommé ni la marque authentique ni une concurrente. | Avertissement · Faible | Aucune déduction |
|  | Aucune réponse exploitable pour juger. | Non concluant | Aucune déduction |
| `model_identity.fp` (Empreintes comportementales) | La réponse correspondait au comportement natif du modèle annoncé. | Réussi | Aucune déduction |
|  | La réponse s'écartait du comportement natif : retire la part de poids de la sonde sur 100 points. | Avertissement · Faible | jusqu'à −25 pts |
|  | La réponse a nommé une marque concurrente et non l'authentique : retire la part de poids de la sonde. | Échec · Élevée | jusqu'à −25 pts · plafond 20 |
|  | Aucune réponse exploitable pour juger. | Non concluant | Aucune déduction |
|  | La sonde demande plus de sortie que le plafond d'identité de 512 tokens ; non exécutée. | Info | Aucune déduction |
| `model_identity.fp_aggregate` | Deux empreintes comportementales ou plus s'écartaient. | Avertissement · Moyenne | Aucune déduction |
| `model_identity.model_field` | Le champ model renvoyé correspondait au modèle demandé. | Réussi | Aucune déduction |
|  | Le champ model renvoyé désigne un modèle différent ou plus petit. | Avertissement · Moyenne | Aucune déduction |
|  | La réponse n'avait pas de champ model exploitable. | Non concluant | Aucune déduction |

### `quality_judge` — Évaluation de qualité / déclassement par un LLM juge

**Fonctionnement.** Uniquement avec `--judge` (à partir de deep). Une courte
série de prompts qui distinguent les gammes (raisonnement en plusieurs étapes,
tâche de code précise, suivi d'instructions nuancé) part vers la cible et, en
mode comparaison, vers la référence ; un juge de confiance distinct ne voit que
les réponses et rend un verdict avec une confiance. Un verdict du juge n'est
ÉLEVÉ que si une référence a corroboré l'écart et que le juge n'a pas indiqué
une confiance faible ou moyenne.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `quality_judge.verdict` (Verdict du juge LLM) | Le juge a trouvé les réponses cohérentes avec le modèle annoncé. | Réussi | 95 pts |
|  | Le juge a trouvé les réponses différentes du modèle annoncé (confiance faible/moyenne). | Avertissement · Moyenne | 50 pts |
|  | Le juge est confiant : les réponses diffèrent du modèle annoncé (sans référence). | Avertissement · Moyenne | 25 pts |
|  | Le juge est confiant et une référence de confiance a confirmé la différence. | Échec · Élevée | 25 pts |
|  | Le juge n'a donné aucune confiance et une référence de confiance a confirmé la différence. | Échec · Élevée | 50 pts |
|  | Le juge n'a pas pu trancher. | Non concluant · Faible | Non compté |
|  | Aucune réponse de la cible à juger. | Non concluant · Faible | Non compté |

**Mises en garde.** Les API officielles mettent à jour leurs instantanés en
silence ; un écart peut donc être une dérive bénigne — zing rapporte
« divergent », jamais « substitution prouvée ». Les modèles hallucinent leur
propre nom, l'auto-identification seule ne tranche donc jamais. Un relais
pourrait mémoriser une série de sondes fixe. Un verdict de confiance élevée
exige le mode comparaison contre l'instantané exact annoncé.

**Non implémenté.** L'empreinte par distance d'embeddings (style LLMmap), les
tests statistiques à deux échantillons et l'échantillonnage massif contre le
routage probabiliste sont des pistes de recherche, pas des vérifications
actuelles.

---

## `capability` — Capacités annoncées

**Détecte.** `capability.json-tool-fakery` : appel d'outils, mode JSON, schémas
stricts, longueur de sortie ou vision annoncés mais non fournis — ou
*sur*-fournis, signe d'un substitut.

### `capability` — Vérification des capacités annoncées

**Fonctionnement.** Quatre sondes à `temperature=0`, chacune jugée par rapport
aux capacités du profil :

- **Outils :** un outil proposé avec `tool_choice: "auto"` et une demande
  explicite de l'utiliser ; un appel d'outil doit revenir. Des arguments livrés
  en objet plutôt qu'en chaîne JSON, comme le fait OpenAI, sont signalés comme
  un moteur non OpenAI.
- **Mode JSON :** `response_format: json_object` doit renvoyer un objet
  analysable portant la valeur demandée.
- **Schéma strict :** un `json_schema` strict ; la conformité est vérifiée si le
  modèle l'annonce et simplement notée (à titre indicatif) sinon. Ignoré sans
  profil.
- **Sortie maximale :** une longue génération plafonnée à min(sortie maximale
  annoncée, 2048) tokens ; atteindre le plafond ou une longueur plausible
  réussit, s'arrêter sous le quart est signalé.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `capability.tools` | Un appel d'outil est revenu pour une demande explicite d'outil. | Réussi | 100 pts |
|  | L'appel d'outils est annoncé mais aucun appel d'outil n'est revenu. | Échec · Moyenne | 0 pts |
|  | Aucun appel d'outil n'est revenu, et l'appel d'outils n'est pas annoncé. | Info | Non compté |
|  | Aucune réponse exploitable pour juger. | Non concluant · Faible | Non compté |
| `capability.tools.encoding` | Les arguments de l'outil sont arrivés en objet, pas en chaîne JSON comme chez OpenAI. | Avertissement · Faible | Non compté |
| `capability.json_mode` | Le mode JSON a renvoyé un objet analysable avec la valeur demandée. | Réussi | 100 pts |
|  | Un objet JSON est revenu avec une mauvaise valeur ; le mode JSON n'est pas annoncé. | Info | 70 pts |
|  | Aucun objet JSON analysable n'est revenu ; le mode JSON n'est pas annoncé. | Avertissement | 50 pts |
|  | Le mode JSON est annoncé mais aucun objet valide avec la valeur n'est revenu. | Échec · Moyenne | 0 pts |
|  | Aucune réponse exploitable pour juger. | Non concluant · Faible | Non compté |
| `capability.json_schema` | Le schéma strict est annoncé et la réponse s'y conformait. | Réussi | 100 pts |
|  | Le schéma strict n'a pas été appliqué, conformément à l'annonce. | Info | 100 pts |
|  | La réponse s'y conformait bien que le modèle annoncé n'ait pas de schémas stricts. | Info | 90 pts |
|  | Le schéma strict est annoncé mais la réponse ne s'y conformait pas. | Avertissement · Faible | 40 pts |
|  | Aucune réponse exploitable pour juger. | Non concluant · Faible | Non compté |
| `capability.max_output` | La sortie a continué jusqu'au plafond de tokens demandé. | Réussi | 100 pts |
|  | La sortie s'est arrêtée avant le plafond, à une longueur plausible. | Réussi | 90 pts |
|  | La sortie s'est arrêtée sous le quart de la longueur demandée. | Avertissement · Faible | 70 pts |
|  | La sortie s'est arrêtée sous le quart de la demande malgré un maximum annoncé élevé. | Avertissement · Faible | 60 pts |
|  | Aucune réponse exploitable pour juger. | Non concluant · Faible | Non compté |

### `vision` — Vérification de la capacité multimodale (vision)

**Fonctionnement.** À partir de deep et seulement si le profil annonce la
vision : un petit PNG orange uni, généré à l'exécution, est envoyé en ligne avec
une question d'un mot sur sa couleur. Un substitut texte seul ne peut pas
nommer la couleur de façon fiable.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `vision.color` | Le modèle a nommé la couleur de l'image de test. | Réussi | 100 pts |
|  | La vision est annoncée mais le modèle n'a pas nommé la couleur de l'image. | Avertissement · Moyenne | 0 pts |
|  | Aucune réponse exploitable pour juger. | Non concluant | Non compté |
| `vision.not_claimed` | La vision n'est pas annoncée, donc aucune image n'a été envoyée. | Info | Non compté |

**Mises en garde.** Les vrais modèles omettent parfois un outil ou produisent
du JSON invalide ; une sonde par capacité est un signal, pas un taux. La
traduction entre dialectes remodèle légitimement le JSON des appels d'outils.
La sonde de sortie maximale n'exerce pas tout le plafond annoncé. Une seule
image est un indice, pas une preuve.

---

## `streaming` — Authenticité du streaming

**Détecte.** `stream.fake-streaming` : le relais met en tampon toute la réponse
de l'amont et la rejoue en un ou quelques fragments, perdant le gain de
latence.

**Fonctionnement.** Une requête en streaming (`max_tokens` 256,
`stream_options.include_usage`) dont on enregistre l'heure d'arrivée de chaque
fragment. Trois signaux de mise en tampon : **peu de fragments** (deux ou moins)
et **premier token tardif** (TTFT au-delà de 90 % de la durée totale), jugés
seulement à partir de 220 caractères reçus, ainsi que des **écarts uniformes**
(quatre fragments ou plus aux écarts quasi identiques, CV < 0,1, et sous 2 ms :
livrés en bloc). Un flux sans fragment d'usage est signalé à part.

Le TTFT est le premier jeton de contenu visible. Pour un modèle de raisonnement
(selon la base de connaissances, ou qui déclare des jetons de raisonnement dans
son usage), qui réfléchit avant de répondre, un premier jeton tardif est donc
seulement noté et non compté comme mise en tampon ; les signaux peu de fragments
et écarts uniformes comptent toujours. Un flux qui réussit mais ne livre aucun
contenu n'est pas concluant et n'est pas noté.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `streaming.healthy` | Beaucoup de fragments, un premier token précoce et des écarts répartis : vrai streaming. | Réussi | Aucune déduction |
| `streaming.few_chunks` | Signal de mise en tampon : le premier retire 40 points, un second 20, les suivants rien. | Avertissement · Moyenne | jusqu'à −40 pts |
| `streaming.late_ttft` | Signal de mise en tampon : le premier retire 40 points, un second 20, les suivants rien. | Avertissement · Moyenne | jusqu'à −40 pts |
| `streaming.reasoning_ttft` | Premier jeton tardif d'un modèle de raisonnement (il réfléchit avant de répondre) : informatif, non compté comme mise en tampon. | Info | Aucune déduction |
| `streaming.uniform_gaps` | Signal de mise en tampon : le premier retire 40 points, un second 20, les suivants rien. | Avertissement · Moyenne | jusqu'à −40 pts |
| `streaming.no_usage` | Aucun fragment d'usage dans le flux : retire 15 points si rien n'est mis en tampon. | Avertissement · Faible | jusqu'à −15 pts |
| `streaming.no_content` | Le flux a réussi mais n'a livré aucun contenu à juger ; non noté. | Non concluant · Faible | Non compté |
| `streaming.failed` | La requête en streaming a échoué. | Échec · Élevée | plafond 0 |

Soit : authentique 100 · usage absent 85 · un signal de mise en tampon 60 ·
deux ou plus 40 · échec 0 · aucun contenu : pas de note.

**Mises en garde.** Des sorties courtes, un petit modèle rapide ou la gigue
réseau peuvent ressembler à une rafale. Un amont qui ne sait pas streamer
oblige le relais à mettre en tampon légitimement ; lisez-le comme « le relais
ne streame pas », pas comme une malveillance. Relancez et comparez à une
référence qui streame réellement.

---

## `billing` — Facturation et consommation

**Détecte.** `billing.usage-inflation` (tokens de prompt ou de complétion
surévalués), `billing.missing-usage` (`usage` absent, partiel ou incohérent)
et, comme signal de corroboration, `prompt.injected-system-prompt`.

**Fonctionnement.** Un appel déterministe (un paragraphe connu à résumer,
`temperature=0`). Le prompt et la réponse visible sont comptés
indépendamment avec une heuristique sensible à la langue (environ ±25 %), pour
toutes les familles de modèles : zing n'utilise aucune bibliothèque de tokenizer
et n'en télécharge aucune. Des tokens de prompt rapportés au-delà de 2,5×
l'estimation et de plus de 50 tokens au-dessus comptent comme gonflement. Les
tokens de complétion d'un modèle de raisonnement incluent légitimement des
tokens de raisonnement cachés et ne sont pas signalés ; sinon, des tokens de
complétion au-delà de 3× l'estimation et de plus de 80 tokens au-dessus sont un
avertissement léger, jamais un échec, car l'estimation d'une réponse courte est
bruitée. `total` doit égaler `prompt + completion` (±2), et un total sans
répartition est signalé. Un sous-comptage (moins de la moitié de l'estimation)
est indicatif (sans préjudice pour l'acheteur).

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `billing.request-failed` | Aucune réponse exploitable pour juger. | Non concluant · Faible | Aucune déduction |
| `billing.missing-usage` | La réponse ne comportait aucune consommation de tokens. | Avertissement · Moyenne | plafond 75 |
| `billing.usage-inflation` | Les tokens de prompt déclarés dépassent largement l'estimation indépendante. | Échec · Élevée | plafond 55 |
| `billing.usage-inflation-completion` | Les tokens de complétion déclarés sont bien au-dessus d'une estimation heuristique. | Avertissement · Moyenne | plafond 70 |
| `billing.reasoning-tokens` | Les tokens de complétion dépassent le texte visible, comme attendu pour un modèle de raisonnement. | Info | Aucune déduction |
| `billing.usage-undercount-prompt` | Les tokens de prompt déclarés sont bien en dessous de l'estimation (sans préjudice pour l'acheteur). | Info | Aucune déduction |
| `billing.usage-undercount-completion` | Les tokens de complétion déclarés sont bien en dessous de l'estimation (sans préjudice pour l'acheteur). | Info | Aucune déduction |
| `billing.total-mismatch` | Le total déclaré n'est pas égal aux tokens de prompt + complétion. | Avertissement · Faible | plafond 90 |
| `billing.partial-usage` | La consommation indique un total sans répartition prompt/complétion. | Avertissement · Moyenne | plafond 80 |
| `billing.usage-consistent` | La consommation déclarée est dans la tolérance de l'estimation indépendante. | Réussi | Aucune déduction |

Une requête de sonde échouée laisse le détecteur sans score.

**Mises en garde.** Les modèles de chat et les tokens spéciaux ajoutent un
petit décalage fixe ; une égalité exacte n'est pas attendue. Si le modèle servi
diffère du modèle annoncé, le « bon » tokenizer est inconnu. Les tokens de
raisonnement cachés ne se comptent pas de l'extérieur. Une sonde mesure une
taille ; un multiplicateur qui croît avec la taille demande des exécutions
répétées ou le mode comparaison.

---

## `reliability` — Fiabilité en concurrence

**Détecte.** Une partie de `throttle.rate-limit-quality` : un relais qui échoue
ou se traîne sous un parallélisme modeste.

**Fonctionnement.** Une rafale de petites requêtes identiques
(`--reliability-requests`, 8 par défaut) à concurrence limitée
(`--concurrency`, 3 par défaut). Le taux de succès porte sur les requêtes
réellement tentées : un HTTP 429 est une limitation honnête, comptée à part. Le
score retire la part d'échecs ; une latence p95 au-delà de 30 s garde 85 % du
reste.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `reliability.success_rate` | Toutes les requêtes tentées de la rafale ont réussi. | Réussi | Aucune déduction |
|  | Jusqu'à 10 % des requêtes tentées ont échoué ; retire la part échouée. | Avertissement · Faible | jusqu'à −10 pts |
|  | Plus de 10 % des requêtes tentées ont échoué ; retire la part échouée. | Échec · Moyenne | jusqu'à −100 pts |
|  | Toutes les requêtes ont été limitées (HTTP 429) : non noté. | Non concluant · Faible | Aucune déduction |
| `reliability.latency` | Latence p95 au-delà de 30 s sous charge ; retire 15 % du score restant. | Avertissement · Faible | jusqu'à −15 pts |
| `reliability.rate_limited` | Une partie de la rafale a été limitée : limitation honnête, non comptée. | Info | Aucune déduction |
| `reliability.skipped` | La sonde de fiabilité était désactivée. | Info | Aucune déduction |

Les mesures de vitesse dédiées relèvent de la dimension `performance`.

**Mises en garde.** Les vrais fournisseurs ralentissent aussi et renvoient des
429 sous charge réelle. Un instantané rate les comportements liés à l'heure ;
`zing watch` réaudite selon un calendrier.

**Non implémenté.** La mesure de qualité dans la durée et sous charge variable
ainsi que les signaux de clé amont partagée (`infra.shared-upstream-key` :
quota qui baisse au repos, identifiants de requête amont divulgués) sont sur la
feuille de route.

---

## `security` — Sécurité du transport

**Détecte.** `prompt.injected-system-prompt`, `integrity.response-tampering`,
des indices de `privacy.prompt-logging-leakage` (mise en cache par préfixe) et
l'hygiène de base du transport et des secrets.

### `security` — Signaux de transport et de gestion des secrets

**Fonctionnement.** Vérifie que l'endpoint utilise HTTPS, que la clé d'API
n'apparaît jamais telle quelle dans une réponse, et quels en-têtes de réponse
trahissent un amont ou un proxy (`server`, `via`, `x-powered-by`,
`x-upstream-*`, `x-litellm-*`, … ; à titre indicatif). Il rappelle aussi la
limite : la journalisation des prompts et les clés amont partagées ne sont pas
prouvables de l'extérieur.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `security.tls` | Le point d'accès utilise HTTPS. | Réussi | Aucune déduction |
|  | Le point d'accès n'est pas en HTTPS ; la clé API circule en clair. | Échec · Élevée | plafond 40 |
| `security.key_echo` | La clé API n'apparaît pas dans la réponse. | Réussi | Aucune déduction |
|  | La clé API apparaît telle quelle dans la réponse. | Échec · Élevée | plafond 30 |
| `security.headers` | Aucun en-tête de réponse ne révèle l'amont (à titre indicatif). | Réussi | Aucune déduction |
|  | Des en-têtes de réponse révèlent l'amont ou le proxy (à titre indicatif). | Info · Faible | Aucune déduction |
|  | Aucun en-tête de réponse à inspecter. | Non concluant | Aucune déduction |
| `security.note` | La journalisation des prompts et les clés amont partagées ne sont pas prouvables de l'extérieur. | Info | Aucune déduction |

### `injected_prompt` — Détection de prompt système injecté

**Fonctionnement.** Deux indices indépendants. (1) Un **surcoût fixe de tokens
d'entrée** : deux messages utilisateur de tailles différentes sans message
système ; les `prompt_tokens` rapportés moins l'estimation indépendante doivent
rester faibles. Un surcoût d'au moins 30 tokens qui reste constant (à 16 près)
sur les deux tailles indique un prompt caché ajouté en tête plutôt qu'un
gonflement proportionnel. (2) Une **sonde de fuite** qui demande au modèle de
répéter toute instruction précédente. Seuls les deux ensemble atteignent
MOYENNE.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `injected_prompt.verdict` (Prompt système injecté) | Le surcoût de tokens d'entrée est faible et aucune instruction cachée n'a fuité. | Réussi | 100 pts |
|  | Un texte de type instruction a fuité sur demande (faible à lui seul). | Info · Faible | 85 pts |
|  | Un important surcoût fixe de tokens d'entrée, constant selon la taille du message. | Avertissement · Faible | 75 pts |
|  | Un surcoût fixe de tokens d'entrée et un préambule divulgué, ensemble. | Avertissement · Moyenne | 55 pts |
|  | Aucun décompte de tokens de prompt exploitable pour mesurer le surcoût. | Non concluant | Non compté |

### `integrity` — Intégrité des réponses / falsification

**Fonctionnement.** Des canaris à réponse connue dont les valeurs sont
sensibles — une URL d'installation et un paquet `pip install` épinglé — doivent
revenir mot pour mot. Un écho exact réussit, l'absence d'écho (paraphrase,
refus) est non concluante, et seule une **substitution de valeur** qui préserve
la structure compte comme falsification. En mode comparaison, une substitution
que la référence de confiance ne fait pas est CRITIQUE.
Une réponse coupée à la limite de sortie est non concluante, pas une substitution.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `integrity.verdict` (Intégrité des réponses) | Les canaris à réponse connue sont revenus intacts. | Réussi | 100 pts |
|  | Une valeur canari a été substituée (pas encore confirmé par une référence). | Échec · Moyenne | 45 pts |
|  | Une valeur canari a été substituée alors que la référence de confiance l'a gardée intacte. | Échec · Critique | 10 pts |
|  | Aucun canari n'a été répété tel quel, la falsification n'a donc pas pu être évaluée. | Non concluant | Non compté |

### `prompt_cache` — Cache de préfixe de prompt (timing)

**Fonctionnement.** Un préfixe unique d'environ 1 200 tokens est envoyé deux
fois en streaming (à froid, puis à chaud), et un préfixe témoin différent une
fois. Si le TTFT à chaud est inférieur à la moitié du TTFT à froid et de celui
du témoin, et au moins 150 ms plus rapide qu'à froid, la mise en cache par
préfixe est active. Toujours indicatif : la mise en cache par préfixe est une
optimisation légitime.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `prompt_cache.verdict` (Mise en cache par préfixe de prompt) | Un préfixe de prompt répété est revenu bien plus vite : la mise en cache par préfixe est active. | Info | Non compté |
|  | Un préfixe de prompt répété n'était pas nettement plus rapide. | Info | Non compté |
|  | Une ou plusieurs sondes de chronométrage n'ont renvoyé aucun temps exploitable. | Non concluant | Non compté |

**Mises en garde.** Les modèles inventent de faux « prompts système » quand on
leur demande de fuiter ; une fuite seule reste donc FAIBLE. La traduction entre
dialectes remodèle le JSON des appels d'outils ; seule une substitution de
*valeur* compte. Une falsification conditionnelle (seulement pour certains
mots-clés, clients ou après un préchauffage) peut échapper à un nombre fini de
sondes. La journalisation en boîte noire est **improuvable** côté client, et
zing ne peut pas montrer un partage de cache *entre utilisateurs* avec une
seule clé : l'absence de signal temporel ne prouve pas que les prompts ne sont
pas journalisés.

---

## `performance` — Performance

**Ce qu'elle mesure.** La **régularité** de l'endpoint, pas sa vitesse. Un
modèle local ou auto-hébergé lent mais régulier obtient un bon score ; la
vitesse brute ne compte que face à une référence.

**Fonctionnement.** La sonde dédiée s'exécute en deep, full et custom, et en
standard seulement en mode comparaison (5 requêtes par côté, trop peu pour les
vérifications de régularité). Par endpoint : trois pings `GET /models`, une
requête de préchauffage (rapportée comme démarrage à froid),
`--performance-requests` requêtes uniformes (100 par défaut) de
`--performance-max-tokens` tokens de sortie (128 par défaut), puis en
deep/full une rafale à `--concurrency`. Chaque requête est non cachable : un
identifiant de requête aléatoire ouvre le prompt, les sujets changent, aucun
paramètre de cache ou de raisonnement n'est envoyé ; une réponse qui revient
quand même d'un cache est signalée et exclue des statistiques. La sonde utilise
le streaming par défaut (`--performance-non-streaming` pour les relais qui ne
savent pas streamer) ; full mesure les deux modes, entrelacés. En mode
comparaison, cible et référence alternent pour que la dérive du réseau touche
les deux également.
Les tokens d'entrée en cache ne comptent que s'ils couvrent au moins la moitié
du prompt : les serveurs locaux (Ollama, llama.cpp, LM Studio) réutilisent le
modèle de chat en cache de chaque prompt, ce qui n'est pas une réponse stockée.
Chaque appel de l'audit est conservé comme enregistrement de requête
(`performance.requests`, des nombres uniquement, jamais le texte du prompt ou
de la réponse) ; son `start_ms` compte à partir du `started_at` du rapport
(UTC), ce qui permet de reconstituer l'heure de chaque appel.

La régularité utilise des rapports de queue (p90 ÷ p50 pour la latence et le
TTFT, p50 ÷ p10 pour le débit), qu'une requête aberrante ne déplace pas comme
elle déplace un écart type ; il faut au moins 10 échantillons propres. La
référence est la référence de confiance, sinon la plage
`performance.decode_tps` du profil dans la base de connaissances.

| Contrôle | Résultat | Statut | Effet |
|---|---|---|---|
| `performance.summary` | Latence, TTFT et débit ont été mesurés. | Info | Non compté |
|  | Aucune des requêtes de sonde n'a réussi. | Non concluant | Non compté |
| `performance.latency_consistency` | La latence est régulière (ratio de queue au plus 1,3). | Réussi | 100 pts |
|  | La latence est stable (ratio de queue au plus 1,75). | Réussi | 85 pts |
|  | La latence varie nettement (ratio de queue au plus 2,5). | Avertissement · Faible | 65 pts |
|  | La latence est erratique (ratio de queue au-delà de 2,5). | Échec · Faible | 40 pts |
|  | Trop peu d'échantillons pour juger de la régularité de la latence. | Info | Non compté |
| `performance.ttft_consistency` | Le délai du premier token est régulier (ratio de queue au plus 1,3). | Réussi | 100 pts |
|  | Le délai du premier token est stable (ratio de queue au plus 1,75). | Réussi | 85 pts |
|  | Le délai du premier token varie nettement (ratio de queue au plus 2,5). | Avertissement · Faible | 65 pts |
|  | Le délai du premier token est erratique (ratio de queue au-delà de 2,5). | Échec · Faible | 40 pts |
|  | Trop peu d'échantillons pour juger de la régularité du délai du premier token. | Info | Non compté |
| `performance.throughput_consistency` | Le débit est régulier (ratio de queue au plus 1,3). | Réussi | 100 pts |
|  | Le débit est stable (ratio de queue au plus 1,75). | Réussi | 85 pts |
|  | Le débit varie nettement (ratio de queue au plus 2,5). | Avertissement · Faible | 65 pts |
|  | Le débit est erratique (ratio de queue au-delà de 2,5). | Échec · Faible | 40 pts |
|  | Trop peu d'échantillons pour juger de la régularité du débit. | Info | Non compté |
| `performance.errors` | Au plus 2 % des requêtes de la sonde ont échoué. | Réussi | 100 pts |
|  | Jusqu'à 10 % des requêtes de la sonde ont échoué ou expiré. | Avertissement · Faible | 80 pts |
|  | De nombreuses requêtes de la sonde ont échoué ou expiré. | Échec · Faible | 50 pts |
| `performance.load_stability` | La latence tient sous charge concurrente (au plus 1,5x). | Réussi | 100 pts |
|  | La latence augmente sous charge concurrente (jusqu'à 3x). | Avertissement · Faible | 80 pts |
|  | La latence se dégrade fortement sous charge concurrente (au-delà de 3x). | Échec · Faible | 55 pts |
| `performance.cache_hit` | Des prompts de sonde uniques sont revenus d'un cache (exclus des statistiques). | Avertissement · Faible | 60 pts |
|  | La référence a servi des prompts uniques depuis un cache (non noté). | Info | Non compté |
| `performance.reference` | Le débit correspond à la référence pour ce modèle. | Réussi | 100 pts |
|  | Plus lent que la référence (p. ex. en local ou sur du matériel plus modeste) ; pas un échec. | Info | 80 pts |
|  | Bien plus rapide que la référence (compatible avec un modèle plus petit). | Avertissement · Faible | 60 pts |
| `performance.reasoning` | Le modèle dépense des tokens de raisonnement cachés ; le TTFT inclut la réflexion. | Info | Non compté |
| `performance.relay_overhead` | Latence comparée à la référence de confiance (à titre indicatif). | Info | Non compté |
| `performance.skipped` | La sonde de performance était désactivée. | Info | Non compté |

**Mises en garde.** La latence dépend du chemin réseau et de la charge du
fournisseur à ce moment ; répétez un mauvais résultat de régularité à un autre
moment. Les plages de la base de connaissances sont des médianes volontairement
larges des API natives, et une cible plus lente n'est jamais un échec. Tous les
constats sont au plus de gravité FAIBLE : cette dimension fait bouger le score,
jamais le verdict de risque.

---

## Correspondance astuce → détecteur

Les 16 astuces de relais issues de la recherche se répartissent ainsi dans zing.

| # | Astuce (id) | Gravité | Détecteur(s) | Couverture actuelle |
|---|---|---|---|---|
| 1 | `downgrade.silent-substitution` | critical | `model_identity`, `quality_judge` | auto-identification, empreintes, champ `model` ; juge ; mode comparaison |
| 2 | `downgrade.reasoning-collapse` | critical | `model_identity`, `quality_judge` | empreintes et juge seulement ; pas encore d'échelle de difficulté dédiée |
| 3 | `downgrade.quantized-distilled` | high | `quality_judge`, `model_identity` | juge avec une référence ; pas encore de test de distribution |
| 4 | `downgrade.partial-probabilistic-routing` | high | `model_identity` | seulement si les requêtes échantillonnées tombent sur le substitut ; l'échantillonnage massif est sur la feuille de route |
| 5 | `context.window-truncation` | high | `context_window` | échelle à aiguille en bordure + recherche dichotomique ; mesuré vs annoncé |
| 6 | `context.lost-in-middle-rag` | high | `context_window` | profondeurs 0,1/0,5/0,9 à taille moyenne |
| 7 | `stream.fake-streaming` | medium | `streaming` | nombre de fragments, moment du premier token, uniformité des écarts |
| 8 | `billing.usage-inflation` | high | `billing` | estimation heuristique indépendante des tokens d'une sonde connue |
| 9 | `billing.missing-usage` | medium | `billing`, `protocol_response`, `streaming` | présence, répartition et arithmétique de l'usage ; fragment d'usage du flux |
| 10 | `privacy.prompt-logging-leakage` | high | `prompt_cache` | mise en cache par préfixe via le TTFT (indicatif) ; partage entre utilisateurs et journalisation restent improuvables avec une clé |
| 11 | `infra.shared-upstream-key` | high | — | feuille de route (quota qui baisse au repos, identifiants de requête amont divulgués) |
| 12 | `cache.ignore-temperature` | medium | `determinism` | sortie identique à l'octet près à température 1,0 ; suspendu pour les modèles de raisonnement |
| 13 | `prompt.injected-system-prompt` | medium | `injected_prompt`, `billing` | surcoût fixe de tokens d'entrée (deux tailles) + sonde de fuite |
| 14 | `throttle.rate-limit-quality` | medium | `reliability`, `performance` | taux de succès (429 à part), latence de queue, stabilité sous charge ; la mesure dans la durée est sur la feuille de route |
| 15 | `capability.json-tool-fakery` | medium | `capability`, `protocol_request` | outils, mode JSON, schéma strict, paramètres ; une sonde chacun, pas des taux |
| 16 | `integrity.response-tampering` | critical | `integrity` | canaris URL/paquet à réponse connue ; CRITIQUE quand une référence corrobore |

---

## Limites et utilisation responsable

**zing rapporte écarts et risques, pas une preuve de fraude.** Le verdict est
formulé avec prudence (clean / low / medium / high / inconclusive), laisse les
résultats ambigus non concluants et ne passe à « élevé » que sur des preuves
solides de gravité élevée.

**Ce qu'un audit en boîte noire ne peut pas prouver :**

- **Journalisation des prompts ou conservation des données.** Un signal
  temporel prouve une mise en cache ; son absence ne prouve pas que les prompts
  ne sont pas journalisés.
- **Intégrité des réponses** sans réponses signées par le fournisseur : une
  falsification conditionnelle peut échapper à un nombre fini de sondes.
- **Clés partagées ou volées :** au mieux un *risque* de pool partagé.
- **Dérive bénigne ou substitution :** les API officielles mettent à jour leurs
  instantanés en silence.
- **Routage constant :** un relais peut router de façon probabiliste, et un
  audit ne voit que les requêtes qu'il a envoyées.

**Méthode.** Les constats qui dépendent d'une comparaison exacte utilisent
`temperature=0` et des prompts contraints. Chaque constat porte ses preuves
(entrées, valeurs observées, comptes, temps), et chaque rapport consigne le
profil, les langues des prompts et les réglages utilisés, pour qu'un résultat
soit vérifiable de façon indépendante. Un relais peut détecter les tests :
relancez à d'autres moments et préférez le mode comparaison contre une
référence de confiance de **l'instantané exact annoncé** — c'est le meilleur
moyen de séparer le comportement du modèle de celui du relais, et le seul
d'atteindre une confiance élevée.

**Divulgation responsable.** **N'accusez pas publiquement un fournisseur** sur
la base d'un rapport zing. Avant d'agir : relancez avec plus d'échantillons et à
d'autres moments, confirmez en mode comparaison, et écartez les explications de
dérive, de réseau et de charge. Si un doute sérieux subsiste, parlez-en d'abord
en privé au fournisseur, sous forme de questions sur le comportement observé,
pas d'accusations.
