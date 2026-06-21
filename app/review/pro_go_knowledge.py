from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProConcept:
    name: str
    trigger_words: tuple[str, ...]
    principle: str
    coach_question: str


PRO_CONCEPTS = [
    ProConcept(
        name="Direction of play",
        trigger_words=("whole-board", "far away", "direction", "opening", "framework", "moyo"),
        principle=(
            "A strong player asks where stones are facing and which area of the board grows naturally. "
            "The best move is often not the biggest-looking local move, but the move that makes your stones work together."
        ),
        coach_question="Before playing locally, ask: which direction makes my existing stones stronger?",
    ),
    ProConcept(
        name="Sente vs gote",
        trigger_words=("urgent", "answer", "tenuki", "initiative", "slow", "too small"),
        principle=(
            "A 9-dan style review separates urgent moves from merely big moves. "
            "If your move lets the opponent take the initiative, it may be strategically expensive even if it gains territory."
        ),
        coach_question="Did this move force a response, or did it hand the initiative to the opponent?",
    ),
    ProConcept(
        name="Tenuki judgment",
        trigger_words=("far away", "whole-board", "priority", "elsewhere"),
        principle=(
            "Tenuki means ignoring the local position to play elsewhere. Strong players tenuki when the local damage is acceptable "
            "and the outside move creates greater value."
        ),
        coach_question="Was the local area truly urgent, or was there a bigger move elsewhere?",
    ),
    ProConcept(
        name="Aji",
        trigger_words=("aji", "possibility", "cut", "defect", "latent", "weakness"),
        principle=(
            "Aji is latent potential. Strong players avoid removing their own useful possibilities too early, "
            "and they notice when the opponent has unresolved weaknesses."
        ),
        coach_question="Did this move preserve future possibilities, or did it erase useful aji?",
    ),
    ProConcept(
        name="Shape and connection",
        trigger_words=("nearby", "local", "shape", "connection", "cutting", "liberties"),
        principle=(
            "When the engine move is close to your move, the issue is usually technique: shape, liberties, connection, cutting points, "
            "or move order."
        ),
        coach_question="Are my stones connected efficiently, or am I creating cutting points?",
    ),
    ProConcept(
        name="Weak group priority",
        trigger_words=("weak", "attack", "defend", "running", "group"),
        principle=(
            "High-level Go is often about weak groups. A move that attacks while making profit is usually better than a move "
            "that only takes territory."
        ),
        coach_question="Which group is weakest, and can I attack or defend while making profit?",
    ),
    ProConcept(
        name="Joseki is not autopilot",
        trigger_words=("corner", "joseki", "sequence", "pattern"),
        principle=(
            "Joseki only makes sense when it fits the whole board. Playing a standard corner sequence blindly can still be wrong "
            "if the outside direction is bad."
        ),
        coach_question="Does this corner move fit the whole-board direction, or am I just following a pattern?",
    ),
    ProConcept(
        name="Third and fourth line balance",
        trigger_words=("side", "territory", "influence", "extension"),
        principle=(
            "Third-line moves tend toward territory and stability; fourth-line moves tend toward influence and center development. "
            "Strong play balances cash territory with outside potential."
        ),
        coach_question="Does this position call for secure territory or outside influence?",
    ),
]


def choose_concepts(raw_lines: list[str]) -> list[ProConcept]:
    text = " ".join(raw_lines).lower()
    selected: list[ProConcept] = []

    for concept in PRO_CONCEPTS:
        if any(word in text for word in concept.trigger_words):
            selected.append(concept)

    if not selected:
        selected = [
            PRO_CONCEPTS[0],
            PRO_CONCEPTS[1],
        ]

    return selected[:3]


def build_pro_style_commentary(
    base_lines: list[str],
    severity: str,
) -> list[str]:
    selected = choose_concepts(base_lines)

    output: list[str] = []
    output.extend(base_lines[:4])

    output.append("")
    output.append("9-dan concept read:")

    for concept in selected:
        output.append(f"{concept.name}: {concept.principle}")
        output.append(f"Ask: {concept.coach_question}")

    if severity in ("mistake", "blunder"):
        output.append("")
        output.append(
            "Training note: do not only ask 'was my move good?' Ask what the position demanded: urgent defense, attack, direction, or sente."
        )
    elif severity in ("excellent", "good"):
        output.append("")
        output.append(
            "Training note: this move fits the engine's priorities. Study the continuation so you understand why it works, not just where it was."
        )

    return output[:12]
