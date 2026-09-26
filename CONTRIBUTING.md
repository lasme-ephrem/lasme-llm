# Contribuer

Merci de l'intérêt porté au projet. Ce dépôt est un projet personnel, mais les
règles ci-dessous sont celles qui ont réellement évité des régressions — elles
ne sont pas décoratives.

## Avant d'ouvrir une PR

1. **Une préoccupation par PR.** Une PR qui corrige un bug *et* refait une
   mise en page ne peut pas être relue ni annulée proprement.
2. **La CI locale passe.** C'est la même commande que la CI GitHub :

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.validate_all
   ```

   Six étapes : compilation Python, syntaxe de **tous** les modules du front
   (liste découverte, pas figée), tests `node:test`, matrice d'imports entre
   couches (`core/` ne dépend jamais de `chat/`), `pytest`, `pip check`.
3. **Les tests existants ne sont pas modifiés pour faire passer un
   changement de comportement.** Si une assertion doit devenir fausse, c'est
   le comportement qui est en cause : discutez-en dans l'issue d'abord.
   Un test *peut* être corrigé quand il décrivait explicitement l'ancien
   contrat — dites-le alors dans la PR.

## Recette réelle

Les tests ne montrent pas ce qu'un utilisateur voit. Toute PR qui touche
l'interface ou le harnais d'agent doit être vue tourner :

- `python -m scripts.serve start` puis uvicorn, et une vraie conversation
  dans le navigateur ;
- au minimum : un tour avec outils, un tour sans outil, un rechargement de
  page pour vérifier que le rendu restauré est identique.

## Conventions

- **Langue** : le code, les commentaires et la documentation sont en français.
  Les commentaires expliquent **pourquoi**, pas quoi — le « quoi » se lit dans
  le code. Un commentaire qui documente un piège vaut mieux que dix qui
  décrivent une évidence.
- **Découpage** : `core/` = domaine, `chat/server/modules/<domaine>/` = routes,
  `chat/web/src/` = front. La matrice d'imports est vérifiée en CI.
- **Format** : `ruff` (configuration dans `pyproject.toml`), longueur de ligne
  100, imports triés.

## Signaler une faille

Ne pas ouvrir d'issue publique : voir [`docs/SECURITY.md`](../docs/SECURITY.md).
