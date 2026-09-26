# Modèle de description de PR.
# Objectif : qu'une relecture (la vôtre, ou la nôtre plus tard) comprenne le
# POURQUOI du changement sans avoir à lire le diff en entier.
---
## Ce que change cette PR

<!-- 2 à 4 phrases. Le problème avant, l'état après. -->

## Nature

- [ ] Correction de bug
- [ ] Fonctionnalité
- [ ] Refactorisation (comportement inchangé)
- [ ] Documentation / outillage seulement

## Vérifications

- [ ] `python -m scripts.validate_all` passe en local (les 6 étapes)
- [ ] Recette faite dans le navigateur sur un serveur réel (et pas seulement en tests)
- [ ] Aucune donnée personnelle, clé ou fichier local ajouté au suivi

## Points d'attention

<!-- Ce qui mérite un œil attentif : contrats d'API modifiés, migrations de
     base, changement de comportement du harnais d'agent. -->

## Captures

<!-- Avant / après pour tout changement visible. Supprimer cette section si
     la PR ne touche pas l'interface. -->
