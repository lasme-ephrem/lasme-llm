# SearXNG local

Ce dossier configure un service SearXNG séparé, accessible uniquement depuis
la machine locale sur le port `8080`. Le code de SearXNG n'est pas copié dans
ce dépôt.

Avec Docker installé :

```powershell
$env:SEARXNG_SECRET = "une-valeur-locale-longue-et-aleatoire"
docker compose -f infra/searxng/compose.yaml up -d
```

Vérifier ensuite l'API :

```powershell
Invoke-RestMethod "http://127.0.0.1:8080/search?q=Ollama&format=json"
```

Puis définir `SEARXNG_ENABLED=true` dans `.env` et redémarrer le backend.

SearXNG est distribué sous licence AGPL-3.0. Il reste ici un service externe
non modifié, appelé par HTTP. Voir <https://github.com/searxng/searxng>.
