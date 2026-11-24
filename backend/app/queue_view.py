"""
A token plus live numbers for the patient: how many people are ahead, and the
estimated wait (queueing.py). Used by main.py (GET /api/tokens/{id}) and by
the appointments pages. (It lived in main.py; it moved here so routers can use
it without importing main.)
"""

from .models import Token, TokenStatus, TokenView
from .queueing import estimate_wait_for_position
from .store import queue_key, store


def to_view(token: Token) -> TokenView:
    """
    WAITING: its place in the live queue.
    BOOKED (patient not here yet): where they would be if they checked in now,
    i.e. the waiting patients who come before them in queue order.
    """
    view = TokenView(**token.model_dump())
    if token.status in (TokenStatus.WAITING, TokenStatus.BOOKED):
        dept = store.departments[token.department_id]
        mine = queue_key(token)
        ahead = sum(1 for t in store.tokens_in(dept.id, TokenStatus.WAITING)
                    if t.id != token.id and queue_key(t) < mine)
        view.people_ahead = ahead
        view.estimated_wait_minutes = estimate_wait_for_position(ahead, dept.doctors, dept.avg_consult_minutes)
    return view
