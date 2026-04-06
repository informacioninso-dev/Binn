from django import template

from core.navigation import build_navigation_model

register = template.Library()


@register.simple_tag(takes_context=True)
def app_navigation(context):
    request = context.get("request")
    return build_navigation_model(request)
