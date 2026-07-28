# Runner Python isolé

Le runner exécute les blocs Python de Canvas dans un conteneur temporaire :

- aucun accès réseau ;
- système de fichiers du conteneur en lecture seule ;
- limites CPU, mémoire, processus et durée ;
- seuls les fichiers écrits dans `LASME_OUTPUT_DIR` sont récupérés.

Construction locale :

```powershell
docker build -t lasme-python-runner:latest infra/runner
```

Dans le code exécuté :

```python
import json
import os
from pathlib import Path

inputs = json.loads(Path(os.environ["LASME_INPUT_FILE"]).read_text())
output = Path(os.environ["LASME_OUTPUT_DIR"])
```
