"""KOALA — Knowledge-Oriented Australian Literary Analysis."""
__version__ = "0.22.0"
DISCLAIMER = "This article was generated with the assistance of artificial intelligence."

BOOK_DISCLAIMER = "This book manuscript was generated with the assistance of artificial intelligence."


def is_book(project):
    return project.get('brief', project).get('project_type', 'article') == 'book'


def disclaimer_for(project):
    return BOOK_DISCLAIMER if is_book(project) else DISCLAIMER
