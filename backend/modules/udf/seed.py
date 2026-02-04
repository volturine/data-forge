from sqlmodel import Session

from modules.udf import service


def ensure_udf_seeds(session: Session) -> None:
    service.seed_defaults(session)
