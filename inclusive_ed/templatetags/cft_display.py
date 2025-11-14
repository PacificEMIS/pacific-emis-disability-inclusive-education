from django import template

register = template.Library()

# -----------------------------
# Difficulty scale (1–4)
# -----------------------------
@register.filter
def cft_difficulty_badge(value):
    if value is None:
        return '<span class="text-body-secondary">Not recorded</span>'

    mapping = {
        1: '<span class="badge text-bg-success">No difficulty</span>',
        2: '<span class="badge text-bg-warning text-dark">Some difficulty</span>',
        3: '<span class="badge" style="background-color:#fd7e14;color:white;">A lot of difficulty</span>',
        4: '<span class="badge text-bg-danger">Cannot do at all</span>',
    }
    return mapping.get(value, "")

# -----------------------------
# YES / NO (1–2)
# -----------------------------
@register.filter
def cft_yesno_badge(value):
    if value is None:
        return '<span class="text-body-secondary">Not recorded</span>'

    mapping = {
        1: '<span class="badge text-bg-success">Yes</span>',
        2: '<span class="badge text-bg-secondary">No</span>',
    }
    return mapping.get(value, "")

# -----------------------------
# Emotional frequency (1–5)
# -----------------------------
@register.filter
def cft_emotional_badge(value):
    if value is None:
        return '<span class="text-body-secondary">Not recorded</span>'

    mapping = {
        1: '<span class="badge text-bg-danger">Daily</span>',
        2: '<span class="badge text-bg-warning text-dark">Weekly</span>',
        3: '<span class="badge text-bg-info text-dark">Monthly</span>',
        4: '<span class="badge text-bg-primary">A few times a year</span>',
        5: '<span class="badge text-bg-success text-light">Never</span>',
    }
    return mapping.get(value, "")
