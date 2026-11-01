# Base de connaissances

> [🇬🇧 English](../../../guide/knowledge-base.md) · [🇨🇳 中文](../../zh-CN/guide/knowledge-base.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/knowledge-base.md) · [🇵🇹 Português](../../pt/guide/knowledge-base.md) · [🇮🇹 Italiano](../../it/guide/knowledge-base.md) · [🇩🇪 Deutsch](../../de/guide/knowledge-base.md) · [🇳🇴 Norsk](../../nb/guide/knowledge-base.md)

ekte juge un relais d'après le **profil** du modèle qu'il annonce : fenêtre de
contexte native, sortie maximale, date de coupure des connaissances, tokenizer,
capacités, mots-clés d'identité et empreintes comportementales. Les profils
intégrés couvrent OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM et
Moonshot (`ekte kb` les liste). Il existe trois couches, les suivantes
l'emportant :

1. Les profils **intégrés**, un fichier YAML par fournisseur dans
   [`ekte/knowledge/data/`](../../../../ekte/knowledge/data).
2. **Un répertoire de vos propres fichiers YAML** : `--kb-dir ./my-profiles`
   (répétable) ou `EKTE_KB_DIR`.
3. **Vos entrées** (`kb.db` dans le répertoire de données), ajoutées sans fichier
   YAML ni installation éditable :
   - sur la page **Connaissances** de l'interface web (`/kb`), avec un onglet
     pour **Modèles**, **Fournisseurs** et **Relais**. Chaque onglet liste
     l'ensemble complet — fournis, `EKTE_KB_DIR` et les vôtres (marqués **Les
     vôtres**) — avec un filtre, un interrupteur par élément et un formulaire
     **Ajouter …** : **Ajouter un modèle** → **Copier le prompt de recherche** dans
     l'assistant IA de votre choix, téléverser ou coller le YAML qu'il renvoie, puis
     **Vérifier et enregistrer** ; **Ajouter un fournisseur** accepte du YAML de
     fournisseur de la même façon ; **Ajouter un relais** demande un nom et une URL
     de base. **Quel profil un identifiant de modèle utilise-t-il ?** montre comment
     un id se résout ; vos entrées s'exportent en YAML ;
   - sur la page **Audit** de l'interface web : **Enregistrer
     dans la base** conserve le nom et l'URL de base d'un relais (une entrée de
     fournisseur sans modèles), listé sous **Connaissances → Relais** ;
   - en ligne de commande : `ekte kb-prompt <model>`, `ekte kb-import <file>`
     (ajoutez `--check` pour seulement vérifier) et `ekte kb-export`.

Avant d'enregistrer une entrée, ekte la vérifie : schéma et limites, expressions
régulières dangereuses, chaque prompt qu'elle enverrait, et identifiants de
modèle qui se résoudraient vers un autre profil. Un de vos modèles portant l'id
d'un modèle intégré le remplace (signalé comme le *masquant*), mais ne modifie
jamais les réglages propres d'un fournisseur intégré ; les empreintes sont
fusionnées par id. Désactiver un modèle, un fournisseur ou un relais fourni sur la
page **Connaissances** est aussi enregistré dans `kb.db` : un id de modèle désactivé
n'est plus résolu, un fournisseur désactivé emporte ses modèles et URL de base.
`ekte check` et `ekte serve` utilisent exactement les mêmes profils ;
`--no-user-kb` (ou `EKTE_NO_USER_KB=1`) laisse vos entrées et interrupteurs de côté.

Un modèle dont les `identity_keywords` sont vides n'est pas enregistré tel quel :
ekte complète ses propres mots de marque à partir des noms du fournisseur et du
modèle (par exemple `glm` et `z.ai`) et affiche
un avertissement pour les vérifier, car sans eux le contrôle d'identité pourrait
prendre son propre fabricant pour une marque concurrente. Le prompt de recherche
les demande explicitement à l'assistant IA.

Chaque rapport consigne le profil utilisé pour l'audit (`knowledge` : fournisseur,
modèle, manière dont l'id a été résolu, sa source et un instantané complet avec
son empreinte de contenu), si bien qu'un rapport reste vérifiable après une
modification de la base de connaissances.
