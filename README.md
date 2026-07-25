# Lasme LLM

Application locale de chat et d’assistance au développement basée sur Ollama.

<p align="center">
  <img
    src="docs/assets/lasme-llm-demo.gif"
    alt="Démonstration de Lasme LLM : recherche Web, streaming, sources et formule LaTeX"
    width="960"
  >
</p>

<p align="center">
  <em>Recherche Web, réponse en streaming, citations et rendu LaTeX — démonstration locale accélérée.</em>
</p>

<details>
  <summary>Afficher une capture statique</summary>
  <br>
  <img
    src="docs/assets/lasme-llm-grounded-chat.png"
    alt="Réponse scientifique sourcée avec formule de diffusion de Rayleigh"
    width="960"
  >
</details>

## Architecture

```text
Navigateur
   │ HTTP + SSE
   ▼
FastAPI — http://127.0.0.1:8000
   ├── conversations, compaction et mémoire personnelle SQLite
   ├── RAG persistant, isolé par conversation
   ├── recherche Web : recherche → extraction → vérification
   ├── données structurées : météo, actions et crypto
   ├── génération d’images externe facultative
   └── espace de développement local sécurisé
             │
             ▼
Ollama — http://127.0.0.1:11434
   ├── gemma-4-chat:latest — Q4_0
   └── gemma-4-fable:latest — Q6_K
```

Cloudflared est uniquement un tunnel HTTPS vers FastAPI. Ce n’est pas un
serveur d’inférence supplémentaire.

## Modèles

| Nom affiché | Identifiant Ollama | Usage | Contexte applicatif |
| --- | --- | --- | --- |
| Gemma 4 Chat | `gemma-4-chat` | Conversation générale | 65 536 tokens |
| Gemma 4 Fable | `gemma-4-fable` | Raisonnement, code et tâches agentiques | 65 536 tokens |

Les fichiers GGUF ne sont pas conservés dans ce dépôt. Ollama gère son propre
stockage. L’application n’installe ni ne télécharge automatiquement de modèle.

L’analyse d’images est désactivée tant que `VISION_MODEL` ne référence pas un
modèle Ollama compatible. Cette désactivation évite de réintroduire implicitement
un ancien modèle Qwen.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn chat.server.main:app --host 127.0.0.1 --port 8000
```

Ouvrir ensuite <http://127.0.0.1:8000/>.

## Recherche Web

Le bouton Web possède trois états :

- `Web auto` : recherche seulement pour les informations actuelles, les
  demandes explicites de vérification et les relances qui nécessitent une mise
  à jour ;
- `Web` : recherche forcée, sauf pour une salutation triviale ;
- `Web off` : aucune requête externe.

Tavily est utilisé lorsque `TAVILY_API_KEY` est défini. DuckDuckGo prend
automatiquement le relais. L’orchestrateur classe les candidats, extrait le
contenu des meilleures pages dans un délai borné, puis reclasse les preuves
réellement disponibles. Le nombre de sources varie donc selon la difficulté et
la qualité des résultats, au lieu d’être fixé arbitrairement à quatre.

Les demandes de météo, de cours boursiers et de crypto-actifs peuvent utiliser
des API structurées avant la recherche Web générale. Les URL locales, privées
et réservées restent bloquées.

## Mémoire et continuité

Deux niveaux complémentaires évitent de renvoyer tout l’historique au modèle :

- une compaction progressive propre à chaque conversation conserve les
  décisions, corrections, contraintes et tâches en cours ;
- une mémoire personnelle inter-conversations retient uniquement des
  préférences durables.

La mémoire personnelle est consultable depuis l’en-tête. Chaque élément peut
être corrigé, désactivé ou supprimé, et l’enregistrement automatique peut être
coupé entièrement. Les anciens extraits Web et documents ne sont jamais
recopiés tels quels dans les résumés.

## Raisonnement

L’interface expose quatre niveaux :

- Rapide : pas de thinking, sortie limitée ;
- Équilibré : reasoning `medium` lorsqu’il est utile ;
- Approfondi : reasoning `high` ;
- Maximum : reasoning `max` et budget de sortie maximal.

Le raisonnement interne fourni séparément par Ollama n’est ni affiché ni stocké
dans la mémoire. Seule la réponse finale est conservée.

## Performances et streaming

Le chemin de génération est conçu pour réduire à la fois la latence réelle et
la latence perçue :

- le client HTTP vers Ollama est persistant et réutilise ses connexions ;
- l’historique est limité aux messages récents et pertinents, complétés par une
  mémoire compacte ;
- le mode Rapide désactive le raisonnement et les autres niveaux n’augmentent
  le budget de calcul que lorsque cela est demandé ;
- `Web auto` évite une recherche externe pour les questions stables, tout en
  conservant la recherche pour les relances liées à un sujet actuel ;
- les tâches secondaires comme le titre et la mémoire sont exécutées sans
  bloquer le flux principal ;
- les événements SSE sont affichés progressivement dès leur réception ;
- le rendu Markdown est regroupé par trames pour éviter un recalcul coûteux à
  chaque token ;
- chaque conversation possède son propre contrôleur de génération : changer de
  conversation n’interrompt plus automatiquement le flux précédent ;
- l’interface affiche l’occupation du contexte et propose trois relances
  facultatives après une réponse.

Sur la configuration de référence — RTX 4070 Ti SUPER 16 Go — le débit observé
se situe généralement autour de 45 à 60 tokens par seconde. Ce chiffre dépend
du modèle, de la longueur du contexte, du niveau de raisonnement et de
l’utilisation de la recherche Web.

## Documents

Les fichiers PDF, TXT et Markdown sont limités à 10 Mo. Le texte extrait est
stocké dans SQLite et indexé localement avec BM25. Chaque conversation possède
son propre espace documentaire. Supprimer une conversation supprime aussi ses
documents.

## Accès distant avec Cloudflared

Les API provenant d’un proxy exigent `LASME_ACCESS_TOKEN`. Les routes
`/api/coding/*` restent interdites à distance par défaut.

1. Définir un long jeton aléatoire dans `.env`.
2. Redémarrer FastAPI.
3. Lancer le tunnel vers `http://127.0.0.1:8000`.
4. Sur le téléphone, ouvrir une seule fois :

```text
https://adresse-du-tunnel.trycloudflare.com/?token=VOTRE_JETON
```

Le navigateur retire immédiatement le jeton de l’URL et le garde uniquement
pour la session courante.

Ne pas activer `LASME_ALLOW_REMOTE_CODING` sur un tunnel public. Voir
[docs/SECURITY.md](docs/SECURITY.md).

## Vie privée

Le chat et l’inférence sont locaux. Deux fonctions peuvent envoyer du contenu
hors de la machine :

- la recherche Web envoie la requête à Tavily ou DuckDuckGo ;
- la génération d’images envoie le prompt à Pollinations.

La génération externe peut être coupée avec
`LASME_ENABLE_EXTERNAL_IMAGE_GENERATION=false`.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q chat core coding tests
node --check chat\web\app.js
.\.venv\Scripts\python.exe -m pip check
```

Un test comparatif manuel des deux modèles est disponible avec :

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_models
```

Les dossiers `python_academy`, `pylearn`, `app` et `templates` sont des
prototypes séparés. Ils ne sont pas démarrés par l’application de chat.

## Licence

Ce projet original est distribué sous
[Apache License 2.0](LICENSE), une licence permissive qui inclut une concession
explicite de brevets. Les fonctionnalités de l’application ont été conçues et
implémentées indépendamment. Voir [NOTICE](NOTICE).
