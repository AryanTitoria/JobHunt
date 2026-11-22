from django.conf import settings

def platform_context(request):
    from .services.ai import configured_providers
    return {'platform_name': 'JobSearch', 'demo_mode': settings.DEMO_MODE,
            'configured_ai': ', '.join(configured_providers()) or 'No hosted provider configured'}
