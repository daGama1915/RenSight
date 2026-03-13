"""
exporters/survey/question_mapper.py
-------------------------------------
Question catalogue for player feedback surveys.

All question strings and set definitions live here.  The survey builder
imports ``generate_questions()`` and ``ALL_QUESTION_SETS``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Question sets
# ---------------------------------------------------------------------------

ALL_QUESTION_SETS = (
    "clarity", "preference", "narrative_impact", "moral_tension",
    "writing_quality", "character_expression", "consequence_anticipation",
    "agency_and_control", "emotional_resonance", "replayability",
    "context_and_pacing",
)

# Questions appended to every survey regardless of set selection.
_UNIVERSAL_QUESTIONS: List[str] = [
    "Which option would you choose and why?",
    "Did any option feel confusing or unclear? Which one, and why?",
    "Is there anything you wish you could say that isn't offered here?",
]

_QUESTION_CATALOGUE: Dict[str, List[str]] = {
    "clarity": [
        "Which option is the easiest to understand at a glance?",
        "Which option, if any, feels ambiguous or vague?",
        "Do the choices feel meaningfully distinct from one another?",
        "Which option best reflects what your character would realistically say?",
        "Is there any option whose wording feels out of place or unnatural?",
        "Do the options cover the range of feelings you might have at this moment?",
        "Which option feels most in line with the tone of the scene?",
        "Would any option benefit from a shorter or longer phrasing?",
        "Which option feels most direct and to the point?",
        "Which option feels most like something a real person would say?",
    ],
    "preference": [
        "Which option would you be most likely to pick on a first playthrough?",
        "Which option would you pick if you wanted the most dramatic outcome?",
        "Which option feels most satisfying to choose?",
        "Which option would you avoid, and why?",
        "Which option aligns most with how you want to play your character?",
        "If you could replay this moment, would you make a different choice?",
        "Which option feels most rewarding in terms of player expression?",
        "Which option best fits a 'good' playthrough?",
        "Which option best fits a 'bad' or morally grey playthrough?",
        "Which option do you think most players would default to?",
    ],
    "narrative_impact": [
        "Which option do you think has the most significant story consequences?",
        "Which option feels like it matters most to the plot?",
        "Which option do you think the game wants you to choose?",
        "Which option feels most likely to change a relationship?",
        "Which option feels the most pivotal?",
        "Which option adds the most tension to the story?",
        "Which option feels like it would lead to the most interesting outcome?",
        "Which option feels like the 'default' or 'safe' choice?",
        "Does this moment feel like an important narrative decision? Why or why not?",
        "Which option do you think NPCs would react to most strongly?",
    ],
    "moral_tension": [
        "Which option feels most morally difficult to choose?",
        "Which option makes you feel most uncomfortable?",
        "Which option do you think is 'the right thing to do'?",
        "Is there an option that feels ethically ambiguous?",
        "Which option would you feel guilty about choosing?",
        "Does this moment present a meaningful moral dilemma?",
        "Which option do you think is the cruelest?",
        "Which option feels most selfless?",
        "Which option challenges your personal values the most?",
        "Would your real-life values affect your choice here?",
    ],
    "writing_quality": [
        "Which option has the strongest or most memorable phrasing?",
        "Which option feels most true to the character's voice?",
        "Is there any option that feels generic or flat?",
        "Do the options feel like they were written by the same voice?",
        "Which option best reflects the emotional state of this scene?",
        "Is there any option that feels too formal or too casual for the context?",
        "Does the wording of each option match the scene's tone?",
        "Which option, if rewritten, could be significantly improved?",
        "Do any options feel repetitive or too similar to each other?",
        "Which option has the best rhythm or cadence when read aloud?",
    ],
    "character_expression": [
        "Which option best expresses your character's personality?",
        "Which option feels most authentic to who your character is?",
        "Is there an option that feels out of character?",
        "Which option gives you the strongest sense of agency over your character?",
        "Which option would define your character the most?",
        "Does this moment help you understand your character better?",
        "Which option feels like the most 'you' choice?",
        "Is there an option you would only choose for roleplay reasons?",
        "Which option makes your character feel more human or relatable?",
        "Which option best expresses vulnerability?",
    ],
    "consequence_anticipation": [
        "Which option do you think will have the most unexpected consequences?",
        "Which option feels 'safe' in terms of future story outcomes?",
        "Which option are you most curious about in terms of what happens next?",
        "Which option feels like it could lock you out of future content?",
        "Did the choices feel like they had real weight or felt decorative?",
        "Which option feels like it could lead to regret later?",
        "Which option would you choose if you wanted to explore a new path?",
        "Do the consequences of these options feel foreseeable or surprising?",
        "Which option do you think the writer intended as the 'canon' choice?",
        "Which option felt riskiest?",
    ],
    "agency_and_control": [
        "Did this moment feel like a meaningful decision or just a formality?",
        "Did you feel in control of your character during this choice?",
        "Did you feel that any option was 'forced' on you by the narrative?",
        "Were there enough options to express what you wanted to say?",
        "Did any option feel like it didn't belong here?",
        "Did the options feel like genuine alternatives or was one clearly 'right'?",
        "Did you feel respected as a player during this moment?",
        "Did this choice make you feel more or less invested in the story?",
        "Was the pacing right for this decision — did you have enough context?",
        "Would more options have improved this moment, or fewer?",
    ],
    "emotional_resonance": [
        "Which option triggered the strongest emotional response in you?",
        "Did this moment make you feel tense, nervous, or excited?",
        "Which option felt the most emotionally honest?",
        "Did any option feel emotionally manipulative?",
        "Did this moment evoke any real-life memories or feelings?",
        "Which option feels the most heartfelt?",
        "Which option do you think is the saddest?",
        "Which option feels the most hopeful?",
        "Did this choice make you feel more connected to any character?",
        "Which option had the biggest emotional impact on you?",
    ],
    "replayability": [
        "Would you replay this scene just to try a different option?",
        "Which option are you most curious to explore on a second playthrough?",
        "Does this moment feel worth replaying?",
        "Which option seems like it would lead to the most interesting alternate path?",
        "Would knowing the consequences change which option you pick?",
        "Which option feels least explored or most hidden in terms of outcomes?",
        "Does this moment reward multiple playthroughs?",
        "Which option would you explore last, and why?",
        "Is there an option you would never pick on any playthrough?",
        "Does the variety of options feel sufficient for replay value?",
    ],
    "context_and_pacing": [
        "Did the preceding dialogue prepare you well for this choice?",
        "Did the scene move too fast or too slow before this decision?",
        "Was there enough information to make an informed choice?",
        "Did the context make you feel pressure to choose a specific option?",
        "Did the scene feel complete before reaching this choice?",
        "Was anything missing from the context that would have helped?",
        "Did the emotional tone of the scene match the options offered?",
        "Did the context make any option feel more or less appropriate?",
        "Was the timing of this choice in the scene satisfying?",
        "Did the setup make this feel like an important moment?",
    ],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_questions(
    question_sets: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Build a flat list of question strings from the selected sets.

    Args:
        question_sets:
            * ``None``  → all optional sets + universals (full survey).
            * ``[]``    → universal questions only (3 questions).
            * list      → named sets + universals.

    Returns:
        Ordered list of question strings.
    """
    if question_sets is None:
        selected = list(ALL_QUESTION_SETS)
    elif len(question_sets) == 0:
        # Explicitly empty — universals only
        logger.info("No optional question sets selected — survey will contain "
                    "only the universal questions.")
        selected = []
    else:
        selected = [s for s in question_sets if s in _QUESTION_CATALOGUE]
        unknown  = [s for s in question_sets if s not in _QUESTION_CATALOGUE]
        if unknown:
            logger.warning("Unknown question set(s) ignored: %s", unknown)

    questions: List[str] = []
    for s in selected:
        questions.extend(_QUESTION_CATALOGUE[s])
    questions.extend(_UNIVERSAL_QUESTIONS)

    logger.debug("generate_questions: %d question(s) from sets: %s",
                 len(questions), selected)
    return questions
