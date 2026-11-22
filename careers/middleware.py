class PlatformHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if request.user.is_authenticated:
            response['Cache-Control'] = 'no-store, private'
        return response
