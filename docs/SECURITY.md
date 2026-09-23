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

## Limites

Le jeton applicatif protège un usage personnel, mais ne remplace pas une
solution d’identité complète. Pour un accès durable ou multi-utilisateur,
préférer Cloudflare Access avec authentification et journalisation.
