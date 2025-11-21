from django.db import transaction


class CreatedUpdatedAuditMixin:
    """
    - On create: set created_by if empty; always set last_updated_by.
    - For inlines: also set fields and handle deletions explicitly.
    """

    def save_model(self, request, obj, form, change):
        if not change and getattr(obj, "created_by_id", None) is None:
            obj.created_by = request.user
        if hasattr(obj, "last_updated_by_id"):
            obj.last_updated_by = request.user
        super().save_model(request, obj, form, change)

    @transaction.atomic
    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for child in instances:
            if hasattr(child, "created_by_id") and child.created_by_id is None:
                child.created_by = request.user
            if hasattr(child, "last_updated_by_id"):
                child.last_updated_by = request.user
            child.save()
        formset.save_m2m()
        for obj in formset.deleted_objects:
            obj.delete()
