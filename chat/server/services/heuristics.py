"""Heuristiques de conversation : social, profondeur, actualité.

Extraits de ``chat/server/main.py`` (refonte modulaire) : classificateurs
déterministes FR/EN, sans appel modèle.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from typing import List, Optional

from chat.contracts.schemas import ChatMessage


def _fallback_contextual_search_query(messages: List[ChatMessage]) -> str:
    """Build a useful standalone query if the LLM rewriter is unavailable."""
    if not messages:
        return ""

    last_msg = messages[-1].content.strip()
    previous_user_prompts = [
        message.content.strip()
        for message in messages[:-1]
        if message.role == "user" and message.content.strip()
    ]
    if not previous_user_prompts:
        return last_msg

    follow_up_pattern = re.compile(
        r"\b(maintenant|à présent|bonne réponse|mets? à jour|actualise|"
        r"vérifie|encore|alors|et lui|et elle|et ça|et cela|c['’]est faux|"
        r"tu te trompes|réponds|reponds|qui a|quand|où|combien|"
        r"buts?|passes?|bilan|statistiques?|a-t-il|a-t-elle)\b",
        flags=re.IGNORECASE,
    )
    refinement_pattern = re.compile(
        r"\b(concentre|concentrez|focalise|focalisez|performances?|"
        r"tarifs?|prix|couts?|techniques?|criteres?)\b",
        flags=re.IGNORECASE,
    )
    current_year = datetime.date.today().year
    refers_to_recent_period = any(
        int(year) >= current_year - 1
        for year in re.findall(r"\b(20\d{2})\b", last_msg)
    )
    if (
        follow_up_pattern.search(last_msg)
        or refinement_pattern.search(last_msg)
        or refers_to_recent_period
        or len(last_msg.split()) <= 6
    ):
        today = datetime.date.today().isoformat()
        # Keep several user turns so a chain such as “who won?” → “how was the
        # match?” → “top scorer?” does not lose the original competition.
        topic_history = " | ".join(previous_user_prompts[-3:])
        return (
            f"Contexte du sujet : {topic_history}. "
            f"Relance utilisateur : {last_msg}. Informations à jour au {today}"
        )[:600]

    return last_msg


# Salutations de premier contact, pas seulement le mot « bonjour ».
_GREETING_ANCHORS = frozenset({
    "bonjour", "bonsoir", "salut", "hello", "hi", "hey", "coucou",
    "yo", "slt", "cc", "wesh", "kikou", "lut", "hola", "welcome",
    "bienvenue", "morning", "evening", "afternoon", "good",
})
_CONTACT_ANCHORS = _GREETING_ANCHORS | frozenset({
    "merci", "bye", "ciao", "enchante", "revoir", "bientot", "ravi",
})
_SOCIAL_FILLERS = _CONTACT_ANCHORS | frozenset({
    "a", "allez", "ami", "amis", "apres", "au", "beaucoup", "bien",
    "bonne", "ca", "comment", "cv", "de", "des", "equipe", "es",
    "etes", "faire", "here", "ici", "je", "journee", "juste", "la",
    "lasme", "le", "les", "midi", "moi", "monde", "nuit", "nouveau",
    "nouvelle", "plaisir", "plait", "please", "plus", "present",
    "presente", "qui", "rencontre", "rencontrer", "salutations",
    "sil", "soiree", "stp", "svp", "te", "there", "toi", "tous",
    "tout", "tu", "un", "une", "va", "vas", "vous", "you",
    # Mots d'adresse et d'affection : « yo mon gars », « salut mon pote »
    # sont des salutations, pas des demandes de travail.
    "mon", "ma", "mes", "ton", "ta", "tes", "notre", "votre", "nos", "vos",
    "gars", "gros", "grosse", "mec", "mecs", "pote", "potes", "poto",
    "bro", "frere", "freres", "frerot", "soeur", "belle", "beau", "vieux",
    "vieille", "chef", "captain", "capitaine", "team", "famille", "bg",
    "meuf", "cousin", "cousine", "copain", "copine", "mate",
})
_TASK_WORDS = frozenset({
    "aide", "aider", "analyse", "calcule", "calcul", "cherche",
    "code", "combien", "comment", "compare", "cours", "dis",
    "donne", "donner", "ecris", "ecrire", "explique", "expliquer",
    "fais", "liste", "montre", "pourquoi", "prix", "quel", "quelle",
    "quelles", "quels", "quand", "redige", "recherche", "rechercher",
    "resume", "traduis", "traduire", "trouve", "trouver",
})


def is_social_turn(query: str) -> bool:
    """True for a first-contact greeting, thanks, or goodbye.

    Covers salut, hello, coucou, « ça va », « salut tout le monde »,
    and the same with a first name. A real request that only starts
    with a greeting stays a request.
    """
    text = unicodedata.normalize("NFKD", query or "")
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    words = re.findall(r"[a-z0-9]+", text.casefold())
    if not words or len(words) > 16 or any(word.isdigit() for word in words):
        return False
    # Signaux de connexion courts (« ping », « test ») : pas une demande
    # de travail quand ils sont le message entier. « lance un test » reste
    # une demande, car il contient d'autres mots.
    if len(words) == 1 and words[0] in {
        "ping", "pong", "test", "ok", "okay", "top", "cool", "super",
        "parfait", "impec", "impeccable", "genial", "sympa",
    }:
        return True
    vocabulary = set(words)
    how_are_you = (
        "comment" in vocabulary
        and bool(vocabulary & {"va", "vas", "allez"})
    )
    if any(
        word in _TASK_WORDS and not (word == "comment" and how_are_you)
        for word in words
    ):
        return False
    contact = bool(vocabulary & _CONTACT_ANCHORS) or how_are_you
    contact = contact or {"qui", "es"} <= vocabulary or "presente" in vocabulary
    contact = contact or {"a", "plus"} <= vocabulary
    contact = contact or (
        "bonne" in vocabulary
        and bool(vocabulary & {"nuit", "journee", "soiree", "midi"})
    )
    if not contact:
        return False
    leftover = [word for word in words if word not in _SOCIAL_FILLERS]
    return len(leftover) <= 1


def is_simple_factual_lookup(query: str) -> bool:
    """Recognize short lookups that need evidence, not long hidden reasoning."""
    clean = re.sub(r"[^\w\s]", " ", (query or "").casefold()).strip()
    words = clean.split()
    if not words or len(words) > 16:
        return False
    complex_markers = {
        "analyse", "compare", "comparaison", "comment", "démontre",
        "demontre", "détaillé", "detaille", "explique", "impact",
        "impacts", "pourquoi", "rapport", "synthèse", "synthese",
    }
    if set(words).intersection(complex_markers):
        return False
    factual_markers = {
        "actuel", "actuelle", "combien", "date", "dernier", "dernière",
        "derniere", "latest", "prix", "quand", "quel", "quelle", "qui",
        "score", "version", "vainqueur", "winner",
    }
    return bool(set(words).intersection(factual_markers))


def response_presentation_profile(query: str) -> tuple[str, str]:
    """Select a useful answer shape without forcing every reply into a template."""
    normalized = unicodedata.normalize("NFKD", (query or "").casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    words = set(re.findall(r"[a-z0-9_-]+", normalized))
    if not words:
        return "direct", "Réponds naturellement et brièvement."

    if words.intersection({"cours", "chapitre", "lecon", "enseigne", "pedagogique"}):
        return (
            "course",
            "Construis un véritable mini-cours : une introduction qui situe la "
            "notion, une progression numérotée du fondamental vers l’avancé, des "
            "définitions précises, au moins un exemple utile, puis une conclusion "
            "qui synthétise les acquis. Ajoute formules ou code uniquement si la "
            "demande ou la matière le justifie.",
        )
    if words.intersection(
        {"tutoriel", "procedure", "etapes", "guide", "installer", "configurer", "realiser"}
    ):
        return (
            "tutorial",
            "Présente un guide exécutable : résultat attendu, prérequis courts, "
            "étapes numérotées avec vérification à chaque étape, puis contrôle final "
            "et pièges fréquents. Les commandes doivent être directement copiables.",
        )
    if words.intersection({"rapport", "audit", "etude", "dossier", "recherche"}):
        return (
            "report",
            "Structure comme un rapport professionnel : résumé initial, périmètre "
            "et méthode, constats étayés, limites, recommandations priorisées, puis "
            "conclusion. Sépare clairement faits, inférences et recommandations.",
        )
    if words.intersection(
        {
            "compare", "comparaison", "comparatif", "comparatifs", "versus",
            "difference", "choisir",
        }
    ):
        return (
            "comparison",
            "Donne d'abord une synthèse décisionnelle brève. Compare ensuite les "
            "options sur des critères homogènes dans un tableau lisible. N'affiche "
            "jamais une estimation comme un prix exact et marque explicitement les "
            "données non vérifiées. Termine par les deux ou trois conclusions qui "
            "changent réellement la décision.",
        )
    if (
        "mermaid" in words
        or "diagramme" in words
        or "mindmap" in words
        or {"carte", "mentale"}.issubset(words)
        or {"graphe", "visuel"}.intersection(words)
    ):
        return (
            "visualization",
            "Crée une visualisation Mermaid valide et autonome dans un unique bloc "
            "```mermaid```. Choisis mindmap pour une carte mentale, flowchart pour "
            "un processus ou une architecture, sequenceDiagram pour des échanges, "
            "timeline pour une chronologie et xychart-beta pour des données. Utilise "
            "des libellés courts, échappe les ponctuations complexes et n’invente "
            "aucune valeur absente de la demande.",
        )
    if words.intersection(
        {"canvas", "artefact", "artifact", "html", "application", "dashboard", "simulateur"}
    ):
        return (
            "artifact",
            "Fournis un livrable exploitable, autonome et cohérent. Pour un artefact "
            "HTML, produis une page complète responsive avec HTML, CSS et JavaScript "
            "dans un seul fichier, sans dépendance réseau sauf demande explicite.",
        )
    if words.intersection({"tableau", "csv", "excel", "donnees", "statistiques"}):
        return (
            "data",
            "Présente les données avec unités, définitions de colonnes et ordre "
            "logique. Utilise un tableau Markdown lorsque cela rend réellement la "
            "comparaison plus précise, puis résume les enseignements importants.",
        )
    if words.intersection(
        {"explique", "comprendre", "theorie", "notion", "principe", "comment", "pourquoi"}
    ):
        return (
            "explanation",
            "Explique d’abord l’idée centrale en langage clair, puis développe par "
            "étapes avec un exemple concret. Conclus par l’essentiel à retenir ; "
            "évite les sections artificielles si la réponse reste courte.",
        )
    return (
        "direct",
        "Réponds directement et naturellement. N’ajoute ni introduction formelle "
        "ni conclusion artificielle à une question simple.",
    )


def response_depth_instruction(
    query: str,
    requested_level: Optional[str] = "balanced",
) -> str:
    """Turn the UI effort setting into an explicit, predictable answer length."""
    normalized = unicodedata.normalize("NFKD", (query or "").casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    words = set(re.findall(r"[a-z0-9_-]+", normalized))
    if words.intersection({"bref", "breve", "court", "courte", "concis", "resume"}):
        return (
            "L'utilisateur demande une réponse courte : donne le résultat en "
            "quelques phrases, sans préambule ni développement optionnel."
        )
    if words.intersection(
        {"approfondi", "approfondie", "complet", "complete", "detaille", "detaillee"}
    ):
        return (
            "L'utilisateur demande de la profondeur : couvre les hypothèses, les "
            "preuves, les nuances et les limites utiles, sans répétition."
        )

    level = (requested_level or "balanced").strip().lower()
    if level in {"none", "off", "fast", "minimal"}:
        return (
            "Mode rapide : réponds d'abord, en 2 à 5 courts paragraphes au plus. "
            "Ne développe que ce qui est indispensable pour éviter une ambiguïté."
        )
    if level in {"high", "deep", "max"}:
        return (
            "Mode approfondi : donne une réponse rigoureuse et substantielle, "
            "avec hypothèses, preuves, nuances et limites lorsque la demande le "
            "justifie. La profondeur ne doit jamais devenir du remplissage."
        )
    return (
        "Mode équilibré : adapte fortement la longueur à la difficulté. Une "
        "question simple mérite 1 à 3 phrases ; une comparaison ou une analyse "
        "mérite une synthèse structurée de longueur moyenne avec les seuls "
        "détails qui changent la compréhension ou la décision."
    )


def should_enable_reasoning(
    query: str,
    model: str,
    requested_level: Optional[str] = "high",
    has_external_context: bool = False,
) -> bool | str:
    """Select reasoning effort without wasting latency on trivial turns.

    Standard scale: low / medium / high, passed through as chosen — the
    user's explicit level is always respected. Legacy labels (max, deep)
    collapse onto high; "balanced" keeps its adaptive heuristics.
    """
    level = (requested_level or "high").strip().lower()
    if level in {"none", "off", "fast", "minimal"}:
        return False
    if level in {"low", "medium", "high"}:
        return level
    if level in {"max", "deep"}:
        return "high"

    clean = re.sub(r"[^\w\s]", "", (query or "").lower()).strip()
    greetings = {
        "bonjour", "salut", "hello", "coucou", "hi", "bonsoir",
        "merci", "ok", "daccord", "au revoir", "bye",
    }
    if clean in greetings or len(clean.split()) <= 2:
        return False
    if is_simple_factual_lookup(query):
        return False

    if has_external_context or "fable" in (model or "").lower():
        return "medium"

    complex_markers = {
        "analyse", "compare", "comparaison", "comparatif", "explique",
        "pourquoi", "comment",
        "raisonne", "verifie", "vérifie", "calcule", "démontre",
        "diagnostique", "stratégie", "strategie", "plan",
    }
    words = set(clean.split())
    if len(words) >= 10 or bool(words.intersection(complex_markers)):
        return "medium"
    return False


def _normalize_recency_text(query: str) -> str:
    """Minuscule, sans accents (NFD), ponctuation -> espaces compactes."""
    text = unicodedata.normalize("NFD", query or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Détection déterministe de sensibilité temporelle : les motifs sont
# appliqués au texte normalisé (minuscule, sans accents, ponctuation
# remplacée par des espaces) afin que « dernier », « dernière »,
# « aujourd'hui » ou « président » matchent même mal accentués ou avec
# une apostrophe typographique. Une seule correspondance suffit.
_RECENCY_RULES = [
    # 1. Superlatifs temporels : « le dernier… », « en ce moment »…
    (
        "superlatif_temporel",
        re.compile(
            r"\b(?:derniers?|dernieres?|plus recents?|plus nouveaux?|"
            r"actualites?|actuellement|actuels?|actuelles?|"
            r"en ce moment|aujourd hui|ce matin|cette annee|"
            r"cette semaine|ce mois ci|ces derniers|recemment|"
            r"a l heure actuelle|a jour|mise a jour|mises a jour|"
            r"live|en direct|breaking)\b"
        ),
    ),
    # 2. Questions volatiles : vainqueurs, dirigeants, records, classements
    (
        "question_volatile",
        re.compile(
            r"\bqui a (?:remporte|gagne|battu)\b"
            r"|\b(?:vainqueur|gagnant|gagnante) (?:de|du|des)\b"
            r"|\bqui est (?:le |la |l )?"
            r"(?:presidente?|premier ministre|pdg|directeur|directrice)\b"
            r"|\bqui dirige\b"
            r"|\b(?:detenteur|detentrice) du record\b"
            r"|\brecord (?:de|du)\b"
            r"|\bclassements?\b"
            r"|\btop\s*\d+\b"
            r"|\bmeilleures?\b.{0,60}?\bde l annee\b"
        ),
    ),
    # 3. Événements récurrents, distincts à chaque édition / année
    (
        "evenement_recurrent",
        re.compile(
            r"\bballon d or\b"
            r"|\bnobel\b"
            r"|\boscars?\b"
            r"|\bcesar\b"
            r"|\bgrands? prix\b"
            r"|\bcoupe du monde\b"
            r"|\bchampionnats?\b"
            r"|\bligue des champions\b"
            r"|\bmondial\b"
            r"|\b(?:jeux )?olympiques?\b"
            r"|\belections?\b"
            r"|\blegislatives\b"
            r"|\bpresidentielles?\b"
        ),
    ),
    # 4. Données vivantes : marchés, météo, sport en continu
    (
        "donnee_vivante",
        re.compile(
            r"\bmeteo\b"
            r"|\btemperatures?\b"
            r"|\bcours (?:de|du|des)\b"
            r"|\bprix de l (?:action|essence)\b"
            r"|\bprix du baril\b"
            r"|\bbourses?\b"
            r"|\btaux (?:de|directeur)\b"
            r"|\binflation\b"
            r"|\bchomage\b"
            r"|\bpib\b"
            r"|\bcryptos?\b"
            r"|\bbitcoin\b"
            r"|\bethereum\b"
            r"|\bscores?\b"
            r"|\bresultats? du match\b"
            r"|\btransferts?\b"
            r"|\bmercato\b"
            r"|\bbilletterie\b"
        ),
    ),
    # 5. Fraîcheur numérique / produit : versions, sorties, annonces
    (
        "fraicheur_produit",
        re.compile(
            r"\bderniere (?:version|release|mise a jour)\b"
            r"|\bnouvelle version\b"
            r"|\bnouveautes?\b"
            r"|\bsorti en\b"
            r"|\bannonces?\b"
            r"|\blancee?\b"
            r"|\bdeploie\b|\bdeploiement\b"
            r"|\bpatches?\b"
            r"|\bmise en ligne\b"
            r"|\bdisponible depuis\b"
        ),
    ),
    # 6. Années explicites récentes : une année >= 2024 est présumée
    # sensible au temps (l'historique ancien ne l'est pas).
    (
        "annee_explicite",
        re.compile(r"\b(?:2024|2025|2026|2027)\b"),
    ),
]


def is_recency_sensitive(query: str) -> bool:
    """True si la question porte sur un fait sensible au temps.

    Classificateur déterministe (familles de regex sur texte normalisé) :
    superlatifs temporels, questions volatiles, événements récurrents,
    données vivantes, fraîcheur produit et années récentes. Utilisé pour
    forcer web_research sur les questions d'actualité (« dernier Ballon
    d'Or », « dernière version », « cours du bitcoin »…) dont la réponse
    en mémoire d'entraînement peut être périmée.
    """
    normalized = _normalize_recency_text(query)
    if not normalized:
        return False
    return any(pattern.search(normalized) for _family, pattern in _RECENCY_RULES)
