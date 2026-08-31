from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import AssessmentAnswer, AssessmentQuestion, AssessmentSection, AssessmentSubmission, AssessmentTemplate


def build_template_snapshot(template):
    """Freeze questions so completed diagnostics remain auditable after edits."""
    return {
        "template_name": template.name,
        "template_description": template.description,
        "sections": [
            {
                "title": section.title,
                "description": section.description,
                "questions": [
                    {
                        "key": question.key,
                        "label": question.label,
                        "help_text": question.help_text,
                        "question_type": question.question_type,
                        "required": question.required,
                        "choices": question.choices,
                        "config": question.config,
                    }
                    for question in section.questions.all()
                ],
            }
            for section in template.sections.prefetch_related("questions").all()
        ],
    }


def ensure_default_template():
    """Provide a usable starting point without forcing migrations per industry."""
    if AssessmentTemplate.objects.filter(is_active=True).exists():
        return
    template = AssessmentTemplate.objects.create(
        name="Estado de situacion",
        description="Diagnostico inicial para entender contexto, prioridades y siguiente paso.",
        is_default=True,
    )
    context = AssessmentSection.objects.create(template=template, title="Contexto actual", description="Como esta hoy la operacion.", position=10)
    priorities = AssessmentSection.objects.create(template=template, title="Prioridades", description="Que necesita resolver primero.", position=20)
    AssessmentQuestion.objects.bulk_create([
        AssessmentQuestion(section=context, key="situacion_actual", label="Describe la situacion actual", question_type="textarea", required=True, position=10),
        AssessmentQuestion(section=context, key="principal_reto", label="Cual es el principal reto hoy?", question_type="text", required=True, position=20),
        AssessmentQuestion(section=priorities, key="prioridad", label="Nivel de prioridad", question_type="rating", required=True, config={"min": 1, "max": 5}, position=10),
        AssessmentQuestion(section=priorities, key="siguiente_paso", label="Que resultado esperas conseguir?", question_type="textarea", required=True, position=20),
    ])


def submission_answer_map(submission):
    return {answer.question_key: answer.value.get("value") for answer in submission.answers.all()}


@transaction.atomic
def save_submission_answers(submission, cleaned_data, *, submitted_by_name="", complete=False):
    rating_values = []
    for section in submission.snapshot.get("sections", []):
        for question in section.get("questions", []):
            key = question["key"]
            value = cleaned_data.get(f"answer__{key}")
            if value is None or value == "":
                continue
            if isinstance(value, Decimal):
                serialized_value = str(value)
            else:
                serialized_value = value
            AssessmentAnswer.objects.update_or_create(
                submission=submission,
                question_key=key,
                defaults={"question_label": question.get("label", key), "value": {"value": serialized_value}},
            )
            if question.get("question_type") == "rating":
                try:
                    rating_values.append(Decimal(str(value)))
                except Exception:
                    pass

    submission.score = (sum(rating_values) / len(rating_values)) if rating_values else None
    submission.submitted_by_name = submitted_by_name[:160]
    submission.status = AssessmentSubmission.STATUS_COMPLETED if complete else AssessmentSubmission.STATUS_IN_PROGRESS
    submission.submitted_at = timezone.now() if complete else submission.submitted_at
    submission.save(update_fields=["score", "submitted_by_name", "status", "submitted_at", "updated_at"])
    return submission
