from rest_framework.pagination import PageNumberPagination


class FabroPageNumberPagination(PageNumberPagination):
    """Bounded pagination shared by mobile list endpoints."""

    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 50
