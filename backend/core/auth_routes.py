import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import create_access_token, decode_access_token, hash_password, verify_password
from database import get_db
from db_models import User
from models import AccessTokenResponse, LoginRequest, SignupRequest, UserResponse


router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


# 인증 실패 응답 형식을 한곳에서 통일한다.
def unauthorized_error():
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증에 실패했습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# 보호된 API에서 Bearer 토큰을 검증하고 현재 사용자 객체를 반환한다.
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    if credentials is None:
        raise unauthorized_error()

    try:
        user_id = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized_error()

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized_error()

    return user


# 로그인 여부가 선택적인 API용 의존성이다. 토큰이 없으면 익명 사용자로 처리한다.
def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    if credentials is None:
        return None

    try:
        user_id = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized_error()

    user = db.get(User, user_id)
    if user is None:
        raise unauthorized_error()

    return user


@router.post(
    "/auth/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(request: SignupRequest, db: Session = Depends(get_db)):
    # DB 제약조건 예외 전에 동일 이메일을 먼저 확인해 명확한 409 응답을 제공한다.
    existing_user = db.scalar(
        select(User).where(User.email == request.email)
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일입니다.",
        )

    # 비밀번호 원문은 저장하지 않고 해시값만 사용자 레코드에 기록한다.
    user = User(
        email=request.email,
        password_hash=hash_password(request.password),
        nickname=request.nickname,
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 이메일입니다.",
        ) from error

    db.refresh(user)
    return user


@router.post("/auth/login", response_model=AccessTokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    # 이메일과 비밀번호를 검증한 뒤 성공한 경우에만 access token을 발급한다.
    user = db.scalar(
        select(User).where(User.email == request.email)
    )
    if user is None or not verify_password(request.password, user.password_hash):
        raise unauthorized_error()

    return AccessTokenResponse(
        access_token=create_access_token(user.id),
    )


@router.get("/users/me", response_model=UserResponse)
def read_current_user(user: User = Depends(get_current_user)):
    return user
