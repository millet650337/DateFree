from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr
from typing import List
from datetime import datetime, timedelta
from pymongo import MongoClient
from jose import jwt, JWTError
from google.oauth2 import id_token
from google.auth.transport import requests
import os

# ==========================================
# 🔧 環境設定
# ==========================================
MONGO_URI = os.getenv("MONGO_URI")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")
JWT_ALGORITHM = "HS256"

if not MONGO_URI or not GOOGLE_CLIENT_ID:
    raise Exception("❌ 請設定 MONGO_URI 與 GOOGLE_CLIENT_ID")

# ==========================================
# 🚀 FastAPI 初始化
# ==========================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 上線請改
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🗄️ MongoDB
# ==========================================
client = MongoClient(MONGO_URI)
db = client["datefree_db"]
users_collection = db["users"]

users_collection.create_index("email", unique=True)

# ==========================================
# 🔐 JWT 驗證工具
# ==========================================
security = HTTPBearer()

def create_jwt(user_email: str):
    payload = {
        "sub": user_email,
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email = payload.get("sub")
        user = users_collection.find_one({"email": email})
        if not user:
            raise HTTPException(status_code=401, detail="使用者不存在")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Token 無效")

# ==========================================
# 📊 資料模型
# ==========================================
class GoogleLoginRequest(BaseModel):
    credential: str  # 前端拿到的 Google ID Token

class SurveyData(BaseModel):
    gender: str
    future_status: str
    dealbreakers: List[str] = []
    bad_habits: List[str] = []
    money_view: str
    boundaries: str
    dating_goal: str

class UserProfile(BaseModel):
    photo_base64: str = None
    bio: str = None
    gender: str = None
    height: int = None
    weight: int = None
    department: str = None
    grade: str = None
    expected_height: str = None
    age_diff: str = None
    smoking: str = None
    drinking: str = None
    tattoo: str = None

# ==========================================
# 🧠 配對演算法（原封不動保留）
# ==========================================
def calculate_match_score(a: dict, b: dict) -> int:
    if set(a.get("dealbreakers", [])) & set(b.get("bad_habits", [])):
        return 0
    if set(b.get("dealbreakers", [])) & set(a.get("bad_habits", [])):
        return 0

    score = 0
    total = 0

    rules = [
        {"key": "money_view", "weight": 5},
        {"key": "boundaries", "weight": 5},
        {"key": "dating_goal", "weight": 4},
        {"key": "future_status", "weight": 3},
    ]

    for r in rules:
        total += r["weight"]
        if a.get(r["key"]) == b.get(r["key"]):
            score += r["weight"]

    return round((score / total) * 100) if total else 0

# ==========================================
# 🔐 Google 登入（真正驗證）
# ==========================================
@app.post("/api/auth/google")
async def google_login(data: GoogleLoginRequest):
    try:
        idinfo = id_token.verify_oauth2_token(
            data.credential,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )

        email = idinfo["email"]
        name = idinfo.get("name", "")

        user = users_collection.find_one({"email": email})

        if not user:
            user_data = {
                "email": email,
                "name": name,
                "survey": None,
                "created_at": datetime.utcnow()
            }
            users_collection.insert_one(user_data)
        else:
            user_data = user

        token = create_jwt(email)

        return {
            "message": "登入成功",
            "token": token,
            "user": {
                "email": email,
                "name": name
            }
        }

    except ValueError:
        raise HTTPException(401, "Google Token 無效")

# ==========================================
# 📝 問卷（需登入）
# ==========================================
@app.post("/api/survey")
async def submit_survey(
    survey: SurveyData,
    current_user=Depends(get_current_user)
):
    users_collection.update_one(
        {"email": current_user["email"]},
        {"$set": {"survey": survey.model_dump()}}
    )

    return {"message": "問卷已儲存"}

# ==========================================
# 💘 配對（需登入）
# ==========================================
@app.get("/api/match")
async def match(current_user=Depends(get_current_user)):
    if not current_user.get("survey"):
        raise HTTPException(400, "請先填問卷")

    best_match = None
    best_score = 0

    others = users_collection.find({
        "email": {"$ne": current_user["email"]},
        "survey": {"$ne": None}
    })

    for u in others:
        score = calculate_match_score(current_user["survey"], u["survey"])
        if score > best_score:
            best_score = score
            best_match = u

    if not best_match:
        return {"message": "暫無配對"}

    return {
        "match": {
            "name": best_match["name"],
            "email": best_match["email"],
            "score": best_score
        }
    }

# ==========================================
# ❤️ 健康檢查
# ==========================================
@app.get("/api")
def root():
    return {"message": "API running"}

# ==========================================
# 👤 個人資料設定 (讀取與更新)
# ==========================================
@app.get("/api/profile")
async def get_profile(current_user=Depends(get_current_user)):
    # 直接回傳使用者資料，過濾掉 MongoDB 原生的 _id
    user_data = users_collection.find_one(
        {"email": current_user["email"]}, 
        {"_id": 0}
    )
    if not user_data:
        return {}
    return user_data

@app.post("/api/profile")
async def update_profile(profile: UserProfile, current_user=Depends(get_current_user)):
    # 透過 Pydantic 過濾掉前端沒傳（為 null/None）的欄位，避免覆蓋既有資料
    update_data = profile.model_dump(exclude_unset=True)
    
    users_collection.update_one(
        {"email": current_user["email"]},
        {"$set": update_data}
    )
    return {"message": "個人資料已更新"}