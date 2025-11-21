from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

import logging
logger = logging.getLogger(__name__)

from threading import Thread

def _get_inclusive_admin_emails():
    """
    Return emails of all active users in the 'InclusiveEd - Admins' group.
    """
    try:
        group = Group.objects.get(name="InclusiveEd - Admins")
    except Group.DoesNotExist:
        return []

    qs = group.user_set.filter(is_active=True).exclude(email__isnull=True).exclude(email__exact="")
    return [u.email for u in qs]


def send_student_created_email(*, student, enrolment, created_by, request=None, student_url=None):
    """
    Send HTML + text email when a new disability record is created.
    Recipients: creator + all "InclusiveEd - Admins" (but not Django ADMINS).
    """
    User = get_user_model()

    # --- Recipients: creator + InclusiveEd - Admins group ---
    recipients = set()

    if created_by and created_by.email:
        recipients.add(created_by.email)

    admins_qs = User.objects.filter(
        groups__name="InclusiveEd - Admins",
        is_active=True,
    ).distinct()

    for u in admins_qs:
        if u.email:
            recipients.add(u.email)

    if not recipients:
        logger.info("send_student_created_email: no recipients, skipping.")
        return

    # --- Domain flags for template (avoid OR in template language) ---
    has_visual = bool(
        enrolment
        and (
            enrolment.cft1_wears_glasses is not None
            or enrolment.cft2_difficulty_seeing_with_glasses is not None
            or enrolment.cft3_difficulty_seeing is not None
        )
    )

    has_hearing = bool(
        enrolment
        and (
            enrolment.cft4_has_hearing_aids is not None
            or enrolment.cft5_difficulty_hearing_with_aids is not None
            or enrolment.cft6_difficulty_hearing is not None
        )
    )

    has_physical = bool(
        enrolment
        and (
            enrolment.cft7_uses_walking_equipment is not None
            or enrolment.cft8_difficulty_walking_without_equipment is not None
            or enrolment.cft9_difficulty_walking_with_equipment is not None
            or enrolment.cft10_difficulty_walking_compare_to_others is not None
            or enrolment.cft11_difficulty_picking_up_small_objects is not None
        )
    )

    has_communication = bool(
        enrolment and enrolment.cft12_difficulty_being_understood is not None
    )

    has_learning = bool(
        enrolment
        and (
            enrolment.cft13_difficulty_learning is not None
            or enrolment.cft14_difficulty_remembering is not None
            or enrolment.cft15_difficulty_concentrating is not None
            or enrolment.cft16_difficulty_accepting_change is not None
        )
    )

    has_behaviour = bool(
        enrolment
        and (
            enrolment.cft17_difficulty_controlling_behaviour is not None
            or enrolment.cft18_difficulty_making_friends is not None
        )
    )

    has_emotional = bool(
        enrolment
        and (
            enrolment.cft19_anxious_frequency is not None
            or enrolment.cft20_depressed_frequency is not None
        )
    )

    context = {
        "student": student,
        "enrolment": enrolment,
        "created_by": created_by,
        "request": request,
        "has_visual": has_visual,
        "has_hearing": has_hearing,
        "has_physical": has_physical,
        "has_communication": has_communication,
        "has_learning": has_learning,
        "has_behaviour": has_behaviour,
        "has_emotional": has_emotional,
        "student_url": student_url,
        "emis_context": settings.EMIS["CONTEXT"]
    }

    subject = f"{settings.EMIS["CONTEXT"]} Disability Inclusive Education disability record created notification: {student.first_name} {student.last_name}"

    text_body = render_to_string("emails/inclusive_ed/student_created.txt", context)
    html_body = render_to_string("emails/inclusive_ed/student_created.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=list(recipients),
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)

def send_student_created_email_async(student, enrolment, created_by, request=None, student_url=None):
    """
    Fire-and-forget wrapper: send the email on a background thread so the
    HTTP request isn't blocked by SMTP latency.
    """

    def _worker():
        try:
            send_student_created_email(
                student=student,
                enrolment=enrolment,
                created_by=created_by,
                request=request,
                student_url=student_url
            )
        except Exception:
            logger.warning(
                "send_student_created_email_async: error sending email "
                "for student %s (created_by=%s)",
                f"{student.first_name} {student.last_name}",
                created_by,
                exc_info=True,
            )

    Thread(target=_worker, daemon=True).start()