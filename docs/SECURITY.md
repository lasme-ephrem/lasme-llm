# Sécurité de Lasme LLM

## Frontières de confiance

- FastAPI et Ollama doivent écouter sur `127.0.0.1`.
- Cloudflared peut exposer le chat, mais toutes les API distantes nécessitent
  `LASME_ACCESS_TOKEN`.
- Les routes de développement, le terminal et les fichiers sont locaux
  uniquement, sauf activation explicite fortement déconseillée.
- Les outils de fichiers sont confinés à `LASME_WORKSPACE_ROOT`.
- Le terminal utilise `shell=False` et une liste d’exécutables autorisés.
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
- Mermaid est exécuté avec `securityLevel: strict` ;
- les liens externes utilisent `noopener noreferrer` ;
- les documents et résultats Web sont délimités comme données dans le prompt.

## Limites

Le jeton applicatif protège un usage personnel, mais ne remplace pas une
solution d’identité complète. Pour un accès durable ou multi-utilisateur,
préférer Cloudflare Access avec authentification et journalisation.
