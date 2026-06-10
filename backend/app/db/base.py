from __future__ import annotations

from sqlalchemy import BigInteger
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # All money is integer cents and the migrations use BigInteger; map plain
    # `Mapped[int]` columns to BigInteger so metadata-created schemas (tests,
    # tooling) match the live DB and never cap a *_cents column at $21.4M.
    type_annotation_map = {int: BigInteger}
