"""
Unit tests for core.emails: recipient selection, rendered content, the
CFT domain flags passed to the templates, and the async wrappers.
"""

import logging

import pytest
from django.core import mail

from conftest import StudentFactory, StudentSchoolEnrolmentFactory, UserFactory
from core import emails

pytestmark = pytest.mark.django_db


@pytest.fixture
def enrolment(db, school_a, school_year, class_level):
    return StudentSchoolEnrolmentFactory(
        student=StudentFactory(first_name="Tebwe", last_name="Kaitara"),
        school=school_a, school_year=school_year, class_level=class_level,
        cft1_wears_glasses=1, cft12_difficulty_being_understood=2, cft19_anxious_frequency=3,
    )


class TestPendingUserManagerEmails:
    def test_admins_and_system_admins_only(self, admin_user, system_admin_user, system_staff_user, teacher_user):
        got = set(emails._get_pending_user_manager_emails())
        assert got == {admin_user.email, system_admin_user.email}

    def test_inactive_and_blank_emails_excluded(self, make_system_user):
        make_system_user("System Admins", username="inactive", is_active=False)
        make_system_user("System Admins", username="blank", email="")
        live = make_system_user("System Admins", username="live")
        assert emails._get_pending_user_manager_emails() == [live.email]

    def test_user_in_both_groups_listed_once(self, admin_user):
        from django.contrib.auth.models import Group

        admin_user.groups.add(Group.objects.get(name="System Admins"))
        assert emails._get_pending_user_manager_emails() == [admin_user.email]

    def test_no_groups_no_recipients(self):
        from django.contrib.auth.models import Group

        Group.objects.filter(name__in=["Admins", "System Admins"]).delete()
        assert emails._get_pending_user_manager_emails() == []


class TestStudentCreatedEmail:
    def test_recipients_are_creator_plus_admins(self, enrolment, admin_user, system_admin_user, teacher_user):
        emails.send_student_created_email(
            student=enrolment.student, enrolment=enrolment, created_by=teacher_user, student_url="http://x/students/1/"
        )
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert set(msg.to) == {teacher_user.email, admin_user.email}
        assert system_admin_user.email not in msg.to  # only the Admins group is notified
        assert msg.subject.startswith("Test EMIS Disability Inclusive Education")
        assert "Tebwe Kaitara" in msg.subject
        assert "Tebwe Kaitara" in msg.body
        html, mimetype = msg.alternatives[0]
        assert mimetype == "text/html" and "http://x/students/1/" in html

    def test_creator_in_admins_is_not_duplicated(self, enrolment, admin_user):
        emails.send_student_created_email(student=enrolment.student, enrolment=enrolment, created_by=admin_user)
        assert mail.outbox[0].to == [admin_user.email]

    def test_creator_without_email_and_no_admins_skips(self, enrolment):
        creator = UserFactory(email="")
        emails.send_student_created_email(student=enrolment.student, enrolment=enrolment, created_by=creator)
        assert mail.outbox == []

    def test_none_creator_still_notifies_admins(self, enrolment, admin_user):
        emails.send_student_created_email(student=enrolment.student, enrolment=enrolment, created_by=None)
        assert mail.outbox[0].to == [admin_user.email]

    def test_inactive_admin_not_notified(self, enrolment, admin_user, teacher_user):
        admin_user.is_active = False
        admin_user.save()
        emails.send_student_created_email(student=enrolment.student, enrolment=enrolment, created_by=teacher_user)
        assert mail.outbox[0].to == [teacher_user.email]

    def test_domain_flags_drive_template_sections(self, enrolment, admin_user, monkeypatch):
        captured = {}
        real = emails.render_to_string

        def spy(template, context):
            captured[template] = dict(context)
            return real(template, context)

        monkeypatch.setattr(emails, "render_to_string", spy)
        emails.send_student_created_email(student=enrolment.student, enrolment=enrolment, created_by=admin_user)
        ctx = captured["emails/core/student_created.txt"]
        assert ctx["has_visual"] is True  # cft1
        assert ctx["has_communication"] is True  # cft12
        assert ctx["has_emotional"] is True  # cft19
        assert ctx["has_hearing"] is False
        assert ctx["has_physical"] is False
        assert ctx["has_learning"] is False
        assert ctx["has_behaviour"] is False
        assert ctx["emis_context"] == "Test EMIS"

    def test_all_flags_false_without_enrolment(self, admin_user, monkeypatch):
        captured = {}
        real = emails.render_to_string

        def spy(template, context):
            captured[template] = dict(context)
            return real(template, context)

        monkeypatch.setattr(emails, "render_to_string", spy)
        emails.send_student_created_email(student=StudentFactory(), enrolment=None, created_by=admin_user)
        ctx = captured["emails/core/student_created.txt"]
        assert not any(ctx[k] for k in ctx if k.startswith("has_"))

    def test_async_wrapper_sends_and_swallows_errors(self, enrolment, admin_user, sync_email_threads, monkeypatch, caplog):
        emails.send_student_created_email_async(enrolment.student, enrolment, admin_user)
        assert len(mail.outbox) == 1

        def boom(**kwargs):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(emails, "send_student_created_email", boom)
        with caplog.at_level(logging.WARNING, logger="core.emails"):
            emails.send_student_created_email_async(enrolment.student, enrolment, admin_user)
        assert "error sending email" in caplog.text


class TestNewPendingUserEmail:
    def test_content_and_recipients(self, admin_user, system_admin_user):
        new_user = UserFactory(username="fresh", email="fresh@example.org", first_name="Fresh", last_name="Face")
        emails.send_new_pending_user_email(new_user=new_user, pending_users_url="http://x/pending-users/")
        msg = mail.outbox[0]
        assert set(msg.to) == {admin_user.email, system_admin_user.email}
        assert "awaiting role assignment" in msg.subject
        assert "fresh@example.org" in msg.body
        assert "http://x/pending-users/" in msg.body

    def test_no_recipients_skips(self, teacher_user):
        emails.send_new_pending_user_email(new_user=UserFactory())
        assert mail.outbox == []

    def test_async_wrapper_swallows_errors(self, admin_user, sync_email_threads, monkeypatch, caplog):
        def boom(**kwargs):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(emails, "send_new_pending_user_email", boom)
        with caplog.at_level(logging.WARNING, logger="core.emails"):
            emails.send_new_pending_user_email_async(UserFactory())
        assert "error sending email" in caplog.text


class TestTestEmail:
    def test_sends_to_recipient_with_config(self, admin_user, settings):
        emails.send_test_email(recipient="probe@example.org", sent_by=admin_user)
        msg = mail.outbox[0]
        assert msg.to == ["probe@example.org"]
        assert msg.subject == "Test EMIS Disability Inclusive Education: Test email"
        assert msg.from_email == settings.DEFAULT_FROM_EMAIL
        assert str(settings.EMAIL_HOST) in msg.body
        assert msg.alternatives[0][1] == "text/html"

    def test_failure_propagates(self, admin_user, monkeypatch):
        from django.core.mail import EmailMultiAlternatives

        def boom(self, fail_silently=False):
            raise ConnectionRefusedError("refused")

        monkeypatch.setattr(EmailMultiAlternatives, "send", boom)
        with pytest.raises(ConnectionRefusedError):
            emails.send_test_email(recipient="probe@example.org", sent_by=admin_user)
