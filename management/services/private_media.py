"""Existing FABRO range-delivery behavior shared by private image/PDF/video endpoints."""
import re
from django.http import HttpResponse, StreamingHttpResponse


def apply_private_range(request, response, content, size):
    requested = request.headers.get('Range')
    if requested:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
        try:
            if not match or not any(match.groups()):
                raise ValueError
            first, last = match.groups()
            start = int(first) if first else max(0, size - int(last))
            end = min(size - 1, int(last)) if first and last else size - 1
            if start >= size or start > end or (not first and int(last) <= 0):
                raise ValueError
        except ValueError:
            # This response was never sent. Closing it would emit request_finished
            # while the request/session middleware is still using its database.
            content.close()
            return HttpResponse(status=416, headers={'Content-Range': f'bytes */{size}'})
        content.seek(start)
        def chunks():
            remaining = end - start + 1
            try:
                while remaining:
                    data = content.read(min(65536, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data
            finally:
                content.close()
        headers = dict(response.items())
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
        headers['Content-Length'] = str(end - start + 1)
        response = StreamingHttpResponse(chunks(), status=206, headers=headers)
        response._resource_closers.append(content.close)
    response['Accept-Ranges'] = 'bytes'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
