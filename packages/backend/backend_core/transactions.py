from collections.abc import Callable
from functools import wraps
from typing import Concatenate

from sqlmodel import Session


def committed[**Parameters, Result](
    command: Callable[Concatenate[Session, Parameters], Result],
    *,
    refresh: bool = False,
) -> Callable[Concatenate[Session, Parameters], Result]:
    @wraps(command)
    def execute(session: Session, /, *args: Parameters.args, **kwargs: Parameters.kwargs) -> Result:
        result = command(session, *args, **kwargs)
        session.commit()
        if refresh and result is not None:
            session.refresh(result)
        return result

    return execute
