"""Consignes de conduite de rédaction du chat, partagées et testables.

Extraites de ``chat/server/main.py`` : la règle de déroulement « outils
d'abord, réponse ensuite » est ce qui empêche le modèle de rédiger un
brouillon avant d'appeler ses outils — brouillon que l'utilisateur verrait
streamer puis être rangé. La seconde moitié impose la fusion en UNE SEULE
réponse finale (compréhension initiale + faits vérifiés).
"""

TURN_DISCIPLINE_RULE = (
    "\n14. Déroulement de la réponse : quand des outils sont nécessaires, "
    "appelle-les EN PREMIER, sans écrire de réponse ni de brouillon de "
    "réponse — passe directement aux appels d'outils. N'écris le texte de "
    "la réponse qu'après le dernier appel d'outil. Après vérification, "
    "livre UNE SEULE réponse finale : intègre naturellement ta "
    "compréhension initiale et les faits vérifiés dans une rédaction "
    "continue, correcte et détaillée au niveau demandé. Ne recopie jamais "
    "un brouillon, ne mentionne ni la recherche, ni les étapes, ni les "
    "outils, et ne répète jamais deux fois le même contenu."
)
