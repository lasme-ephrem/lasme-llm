# Sécurité de Lasme LLM

## Frontières de confiance

- FastAPI et le runtime llama.cpp (`llama-server`) doivent écouter sur
  `127.0.0.1`.
- Cloudflared peut exposer le chat, mais toutes les API distantes nécessitent
  `LASME_ACCESS_TOKEN`.
- Les routes de développement et les fichiers sont locaux uniquement, sauf
  activation explicite fortement déconseillée.
- Les outils de fichiers sont confinés à `LASME_WORKSPACE_ROOT`.
- Le terminal agent est entièrement désactivé par défaut. S’il est
  explicitement activé, il utilise `shell=False`, une liste d’exécutables
  autorisés et un répertoire de travail confiné.
- Les suppressions et déplacements autonomes sont désactivés par défaut.

## Jeton distant

Utiliser au minimum 32 octets aléatoires. Exemple PowerShell :

```powershell
[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

Placer le résultat dans `.env` :

```text
LASME_ACCESS_TOKEN=...
```

Ne jamais publier `.env`, les bases SQLite, les journaux Cloudflared, les
images générées ou les fichiers GGUF.

## Contenu non fiable

Les réponses Web, documents RAG et sorties de modèles sont non fiables :

- les URL privées sont bloquées pour éviter les requêtes réseau internes ;
- le HTML du modèle est nettoyé avec DOMPurify ;
- les mini-applications Canvas utilisent une URL éphémère, une CSP sans réseau
  et un iframe `sandbox` sans accès à l’origine de l’application ;
- Mermaid est exécuté avec `securityLevel: strict` ;
- les liens externes utilisent `noopener noreferrer` ;
- les documents et résultats Web sont délimités comme données dans le prompt.

## Fichiers et exécution

- les fichiers de projet sont limités à 25 Mo et à une liste blanche de
  formats ; HTML, SVG et exécutables ne sont pas acceptés comme documents ;
- le serveur vérifie l’extension, la signature réelle, la structure des
  archives Office et leurs limites avant stockage, sans faire confiance au
  type MIME fourni par le client ;
- les noms sont normalisés, les chemins sont résolus sous
  `.runtime/project_files` et les doublons sont détectés par SHA-256 ;
- l’exécution Python s’exécute dans un conteneur Docker sans réseau (pool
  chaud réutilisé entre tâches via `docker exec`, sinon un conteneur à
  froid par tâche), en lecture seule, sous un UID non privilégié, sans
  capacités Linux et avec des limites de temps, mémoire, CPU, processus et
  volume de sortie ;
- seuls les fichiers simples écrits dans le dossier de sortie dédié peuvent
  être téléchargés ;
- le runner, le terminal et les routes de développement restent locaux par
  défaut.

## Données et migrations

- les projets isolent conversations, fichiers, index RAG et artefacts ;
- la suppression d’un projet supprime ces données dans une transaction SQLite
  unique, puis retire son stockage local ;
- les migrations sont versionnées et une sauvegarde SQLite cohérente est
  créée dans `.runtime/db_backups` avant toute migration d’une base existante.

## Dépendances navigateur (surface d'attaque)

Le front n'a **pas de build** : les bibliothèques sont versionnées telles
quelles sous `chat/web/vendor/` (DOMPurify, marked, KaTeX, highlight.js,
Mermaid), chacune accompagnée de son texte de licence. Conséquences :

- il n'existe **pas de chaîne de dépendances transitive** côté navigateur : ce
  qui est dans `vendor/` est exactement ce qui s'exécute, rien de plus. C'est
  une simplification de la surface d'attaque, au prix d'une mise à jour
  manuelle ;
- **DOMPurify est le composant critique** : c'est lui qui nettoie le HTML
  produit par le modèle. Une faille y est une faille directe du produit. Sa
  mise à jour se fait en remplaçant le fichier, en vérifiant la licence, et en
  changeant le paramètre `?v=` correspondant dans `chat/web/index.html` (le
  numéro de version dans l'URL est aussi le cache-buster du navigateur) ;
- `css` et `js` sont servis uniquement depuis l'origine locale : la CSP pose
  `default-src 'self'` et `script-src 'self'`, sans exception.

## Réponses du modèle considérées comme non fiables

Le contenu produit par le modèle n'est jamais traité comme une garantie :

- sur les sujets sensibles (prix, versions, benchmarks, disponibilité), une
  valeur numérique absente des preuves collectées est retirée de la réponse —
  le reste du texte est conservé tel quel, jamais sacrifié ;
- une URL citée doit avoir été réellement vue par l'agent (résultat de
  recherche ou page lue) ; sinon le marqueur de citation est supprimé ;
- une section « Sources » inventée en fin de réponse est retirée, la preuve
  devant vivre dans le texte ;
- le mode *strict* refuse explicitement de répondre de mémoire lorsque la
  question porte sur une donnée vivante.

## Tests et données locales

- la suite de tests utilise des bases temporaires ou une base dédiée
  (`LASME_DATABASE_PATH`) ; aucune donnée de l'utilisateur ne doit être
  nécessaire à la CI ;
- `.models/logs/agent_evals.json` est un artefact généré : il n'est plus
  versionné, pour éviter qu'un résultat local soit pris pour une référence ;
- le journal WAL (`lasme_llm.db-wal`) n'est **jamais** supprimé à la main :
  il contient les écritures non encore reportées. Voir ADR-001.

## Limites

Le jeton applicatif protège un usage personnel, mais ne remplace pas une
solution d'identité complète. Pour un accès durable ou multi-utilisateur,
préférer Cloudflare Access avec authentification et journalisation.

Enfin : **activer la génération d'images externe rompt la promesse de
confidentialité**. `LASME_ENABLE_EXTERNAL_IMAGE_GENERATION=true` envoie le
prompt à un service tiers (Pollinations). C'est un choix explicite, jamais un
comportement par défaut.
