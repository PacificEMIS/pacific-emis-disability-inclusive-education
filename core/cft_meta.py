from django.utils.translation import gettext_lazy as _
from core.models import (
    YES_NO_CHOICES,
    DIFFICULTY_CHOICES_4,
    EMOTIONAL_FREQ_CHOICES_5,
)


CFT_QUESTION_META = [
    # --- SEEING ---
    (
        "cft1_wears_glasses",
        "CFT1",
        _("Does %(name)s wear glasses or contact lenses?"),
        YES_NO_CHOICES,
    ),
    (
        "cft2_difficulty_seeing_with_glasses",
        "CFT2",
        _(
            "When wearing his/her glasses or contact lenses, does %(name)s have difficulty seeing?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft3_difficulty_seeing",
        "CFT3",
        _("Does %(name)s have difficulty seeing?"),
        DIFFICULTY_CHOICES_4,
    ),
    # --- HEARING ---
    (
        "cft4_has_hearing_aids",
        "CFT4",
        _("Does %(name)s use a hearing aid?"),
        YES_NO_CHOICES,
    ),
    (
        "cft5_difficulty_hearing_with_aids",
        "CFT5",
        _(
            "When using his/her hearing aid, does %(name)s have difficulty hearing sounds like people’s voices or music?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft6_difficulty_hearing",
        "CFT6",
        _(
            "Does %(name)s have difficulty hearing sounds like people's voices or music?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    # --- WALKING / MOBILITY ---
    (
        "cft7_uses_walking_equipment",
        "CFT7",
        _("Does %(name)s use any equipment or receive assistance for walking?"),
        YES_NO_CHOICES,
    ),
    (
        "cft8_difficulty_walking_without_equipment",
        "CFT8",
        _(
            "Without his/her equipment or assistance, does %(name)s have difficulty walking?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft9_difficulty_walking_with_equipment",
        "CFT9",
        _(
            "With his/her equipment or assistance, does %(name)s have difficulty walking?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft10_difficulty_walking_compare_to_others",
        "CFT10",
        _(
            "Compared with children of the same age, does %(name)s have difficulty walking?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    # --- FINE MOTOR / COMMUNICATION ---
    (
        "cft11_difficulty_picking_up_small_objects",
        "CFT11",
        _(
            "Compared with children of the same age, does %(name)s have difficulty picking up small objects, for example a pencil, with his/her hand?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft12_difficulty_being_understood",
        "CFT12",
        _(
            "Compared with children of the same age, when %(name)s speaks, does he/she have difficulty being understood by others?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    # --- COGNITION / LEARNING ---
    (
        "cft13_difficulty_learning",
        "CFT13",
        _(
            "Compared with children of the same age, does %(name)s have difficulty learning things?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft14_difficulty_remembering",
        "CFT14",
        _(
            "Compared with children of the same age, does %(name)s have difficulty remembering things?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft15_difficulty_concentrating",
        "CFT15",
        _(
            "Compared with children of the same age, does %(name)s have difficulty concentrating on an activity that he/she enjoys doing?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft16_difficulty_accepting_change",
        "CFT16",
        _(
            "Compared with children of the same age, does %(name)s have difficulty accepting changes in his/her routine?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    # --- BEHAVIOUR / SOCIAL ---
    (
        "cft17_difficulty_controlling_behaviour",
        "CFT17",
        _(
            "Compared with children of the same age, does %(name)s have difficulty controlling his/her behaviour?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    (
        "cft18_difficulty_making_friends",
        "CFT18",
        _(
            "Compared with children of the same age, does %(name)s have difficulty making friends?"
        ),
        DIFFICULTY_CHOICES_4,
    ),
    # --- EMOTIONAL STATES ---
    (
        "cft19_anxious_frequency",
        "CFT19",
        _("How often does %(name)s seem very anxious, nervous, or worried?"),
        EMOTIONAL_FREQ_CHOICES_5,
    ),
    (
        "cft20_depressed_frequency",
        "CFT20",
        _("How often does %(name)s seem very sad or depressed?"),
        EMOTIONAL_FREQ_CHOICES_5,
    ),
]


def build_cft_meta_for_name(display_name=None):
    """
    Return a version of CFT_QUESTION_META where %(name)s is replaced.

    If no display_name is provided, we fall back to a neutral phrase.

    Only used in the edit view (add new news handled in browser with Javascript)
    """
    if not display_name:
        display_name = _("the child")

    meta = []
    ctx = {"name": display_name}
    for field_name, code, label, choices in CFT_QUESTION_META:
        # label is a lazy translation that uses % formatting
        try:
            label_with_name = label % ctx
        except (TypeError, ValueError):
            # If anything is weird, just keep the original label
            label_with_name = label
        meta.append((field_name, code, label_with_name, choices))
    return meta
