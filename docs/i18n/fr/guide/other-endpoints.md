# Audits d'embedding, de rerank, d'images et d'audio

> [🇬🇧 English](../../../guide/other-endpoints.md) · [🇨🇳 中文](../../zh-CN/guide/other-endpoints.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/other-endpoints.md) · [🇵🇹 Português](../../pt/guide/other-endpoints.md) · [🇮🇹 Italiano](../../it/guide/other-endpoints.md) · [🇩🇪 Deutsch](../../de/guide/other-endpoints.md) · [🇳🇴 Norsk](../../nb/guide/other-endpoints.md)

Ces endpoints renvoient des vecteurs, des classements, des images ou de l'audio au
lieu de chat ; ekte les audite donc avec des sondes dédiées au lieu des prompts de
chat. Chacun affiche un verdict et prend en charge `--json` et `--fail-on-risk`.

## Type d'endpoint (surface), surveillances d'embedding et de rerank

Chaque audit, ligne d'historique et surveillance a un **type d'endpoint**
(`surface`) : `chat` (par défaut), `embedding` ou `rerank`. Il est indépendant de
la suite. Les audits d'embedding et de rerank passent par le même runner, le même
score (0–100, A–F), l'historique, l'analytique et les surveillances que les audits
de chat ; seuls les détecteurs diffèrent. L'historique et l'analytique filtrent par
type d'endpoint, et l'analytique n'affiche que les métriques qui s'appliquent.

Pour surveiller un endpoint d'embeddings ou de rerank, auditez-le sur la page
**Audit** (choisissez **Embeddings** ou **Reclassement** dans le sélecteur de type
d'endpoint) et
choisissez **Surveiller**, ou **Planifier comme surveillance** sur sa
ligne d'historique. La surveillance relance l'audit selon son planning, avec le
même épinglage de la base de connaissances, le même seuil d'alerte et les mêmes
alertes de régression qu'une surveillance de chat, et vérifie la **dérive** par
rapport à son exécution précédente (les vecteurs d'une sonde d'embedding, le
classement et les scores d'une sonde de rerank). La dimension annoncée d'une
surveillance d'embedding se modifie sur sa carte (vide ou 0 : depuis la base de
connaissances). Les sondes de vitesse (embeddings : latence, démarrage à froid,
entrées/s, mise à l'échelle par lots ; rerank : latence, démarrage à froid,
documents/s, 4 contre 32 documents) ne tournent que dans les suites deep, full ou
custom, ou en standard avec une référence.

## Embeddings et rerank

```bash
# La dimension de vecteur attendue est résolue depuis la base de connaissances pour le modèle annoncé.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Ou indiquer directement la dimension attendue :
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank : une sonde intégrée à réponse connue — un vrai reranker doit classer
# en premier le document manifestement pertinent.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Plus poussé : ajoute la sonde de vitesse du rerank ; --no-save garde l'exécution hors de l'historique.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# Voir d'abord les vérifications et les appels estimés, sans envoyer de requête :
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` vérifie la connectivité, la **sonde à réponse connue** (le document
manifestement pertinent doit arriver en tête), le champ `model` renvoyé, le
déterminisme (la même requête deux fois donne le même classement et les mêmes
scores) et la **dérive du classement** par rapport à l'exécution enregistrée
précédente. `ekte embed` et `ekte rerank` acceptent `--suite`,
`--save/--no-save` (enregistré par défaut, pour que l'exécution suivante ait une
référence de dérive) et `--dry-run`.

`embed` vérifie la connectivité, la **correspondance de dimension** (longueur du
vecteur renvoyé face à la dimension native du modèle annoncé — le signal phare de
tromperie sur la marchandise : un relais annonçant `text-embedding-3-large` en
3072-d mais renvoyant du 1024-d sert un substitut), le déterminisme (même entrée
→ cosinus ≈ 1), la distinction (entrées sans rapport → cosinus nettement
inférieur à 1) et le champ `model` renvoyé. Profils intégrés : OpenAI
`text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Les deux se trouvent aussi dans l'interface web : ils démarrent sur la page
**Audit** via le sélecteur de type d'endpoint (**Embeddings**,
**Reclassement**). L'audit de rerank utilise toujours les sondes
intégrées, pour que chaque exécution reste comparable pour la dérive et la
surveillance.

## Génération d'images et d'audio (TTS)

Génération d'images (`POST /v1/images/generations`) et synthèse vocale
(`POST /v1/audio/speech`), décodées avec la seule bibliothèque standard de
Python — dimensions d'image à partir des octets d'en-tête (PNG/JPEG/GIF/WebP),
durée WAV via `wave`.

```bash
# Un relais annonçant DALL·E 3 renvoie-t-il vraiment le 1792x1024 demandé ? Une image
# réduite ou de mauvaise taille (ou hors des tailles natives du modèle annoncé, selon la
# base de connaissances) est le signal phare de tromperie sur la marchandise.
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Un relais annonçant tts-1-hd renvoie-t-il un vrai audio dont la durée suit l'entrée
# (pas un substitut fixe, pas du HTML/JSON déguisé en audio) ?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
```

`image` vérifie la connectivité, un format valide et décodable, la
**correspondance de taille** (largeur × hauteur décodées face à la requête et aux
tailles natives du modèle annoncé — FAIL/HIGH en cas d'écart), la distinction
(deux prompts → deux images différentes, pour démasquer un substitut fixe), le
nombre et le champ `model`. `audio` vérifie la connectivité, la validité du
conteneur/format, le respect du format, une durée non triviale qui suit la
longueur de l'entrée, la distinction et le champ `model`. La base de connaissances
fournit OpenAI DALL·E 2/3, gpt-image-1, tts-1/tts-1-hd/gpt-4o-mini-tts ainsi que
des profils image/TTS de Qwen.
