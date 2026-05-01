from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql
from evr_bot.models import User

print(CreateTable(User.__table__).compile(dialect=postgresql.dialect()))
