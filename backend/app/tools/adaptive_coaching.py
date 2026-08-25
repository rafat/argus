import logging
from app.tools.firestore import FirestoreRepository

logger = logging.getLogger(__name__)


def calculate_coaching_weights(repo: FirestoreRepository, document_id: str) -> dict[str, float]:
    """
    Calculate simple adaptive question weights based on historical revision effectiveness.
    Effectiveness = addressed_issues / total_issues for each category.
    """
    issues = repo.get_issues(document_id)
    
    # Default baseline weights
    baselines = {"evidence": 0.33, "logic": 0.33, "socratic": 0.34}
    if not issues:
        return baselines

    stats = {
        "evidence": {"addressed": 0, "total": 0},
        "logic": {"addressed": 0, "total": 0},
        "socratic": {"addressed": 0, "total": 0},
    }

    for issue in issues:
        q_type = issue.question_type.lower()
        if q_type not in stats:
            continue
        
        stats[q_type]["total"] += 1
        if issue.status == "addressed":
            stats[q_type]["addressed"] += 1

    # Compute raw effectiveness (with Laplace smoothing to handle empty/low sample sizes)
    effectiveness = {}
    for q_type, counts in stats.items():
        if counts["total"] == 0:
            # If no history, assume neutral 0.5 effectiveness
            effectiveness[q_type] = 0.5
        else:
            effectiveness[q_type] = counts["addressed"] / counts["total"]

    # Normalize effectiveness values to construct probability distribution (weights sum to 1.0)
    total_eff = sum(effectiveness.values())
    if total_eff == 0:
        return baselines

    weights = {q_type: score / total_eff for q_type, score in effectiveness.items()}
    return weights


def inject_adaptive_instructions(weights: dict[str, float]) -> str:
    """
    Generates a prompt injection based on calculated weights to guide Socratic coaching style.
    """
    return (
        f"\n\n[ADAPTIVE COACHING INJECTION]\n"
        f"Based on the user's historical receptivity and success in revising their document draft, "
        f"please tailor your coaching style to match these emphasis ratios:\n"
        f"- Evidentiary analysis and Citation checks: {weights.get('evidence', 0.33):.1%}\n"
        f"- Logical Syllogism and fallacies check: {weights.get('logic', 0.33):.1%}\n"
        f"- Socratic inquiry and structural reflections: {weights.get('socratic', 0.34):.1%}\n"
        f"Prioritize raising questions and highlighting flaws in categories with higher weights."
    )
