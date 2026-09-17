from pwdlib import PasswordHash


# 비밀번호 해싱에 사용할 객체
password_hash = PasswordHash.recommended()


# 사용자가 입력한 비밀번호를 해시값으로 변환
def hash_password(password: str) -> str:
    return password_hash.hash(password)


# 사용자가 입력한 비밀번호와 DB에 저장된 해시값이 같은지 확인
def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv


load_dotenv()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY가 .env에 설정되어 있지 않습니다.")


# 로그인 성공 시 사용자에게 전달할 JWT Access Token 생성
def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "exp": expire,
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )

# JWT Access Token을 해석해서 사용자 ID를 반환
def decode_access_token(token: str) -> int:
    payload = jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "exp"]},
    )

    user_id = int(payload["sub"])

    if user_id <= 0:
        raise ValueError("JWT sub는 양의 사용자 ID여야 합니다.")

    return user_id
