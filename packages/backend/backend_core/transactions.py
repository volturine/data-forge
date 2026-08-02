from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Concatenate

from sqlmodel import Session


@contextmanager
def transaction(session: Session) -> Iterator[None]:
    try:
        yield
        session.commit()
    except Exception:
        session.rollback()
        raise


def committed[**Parameters, Result](
    command: Callable[Concatenate[Session, Parameters], Result],
    *,
    refresh: bool = False,
) -> Callable[Concatenate[Session, Parameters], Result]:
    @wraps(command)
    def execute(session: Session, *args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
        with transaction(session):
            result = command(session, *args, **kwargs)
        if refresh and result is not None:
            session.refresh(result)
        return result

    return execute
