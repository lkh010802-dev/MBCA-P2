import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# .env 파일에 저장된 환경변수를 불러온다.
load_dotenv()

# .env의 DATABASE_URL 값을 가져온다.
DATABASE_URL = os.getenv("DATABASE_URL")

# DATABASE_URL이 없으면 잘못된 DB로 연결되는 것을 막기 위해 바로 오류를 발생시킨다.
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL이 .env에 설정되어 있지 않습니다.")


# SQLAlchemy가 MySQL과 통신할 때 사용할 Engine을 생성한다.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


# DB 작업에 사용할 Session 생성기
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
