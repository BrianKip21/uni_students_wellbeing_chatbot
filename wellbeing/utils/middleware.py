from werkzeug.wrappers import Request

class MethodOverrideMiddleware:
    """
    Middleware that allows overriding HTTP methods.
    Useful for HTML forms that don't support PUT/DELETE methods.
    """
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        request = Request(environ)
        method = request.args.get('_method', '').upper()
        if method in ['PUT', 'DELETE'] and request.method == 'POST':
            environ['REQUEST_METHOD'] = method
        return self.app(environ, start_response)