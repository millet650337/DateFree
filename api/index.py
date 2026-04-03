from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = MongoClient(MONGO_URI)
db = client["datefree_db"]
users_collection = db["users"]
users_collection.create_index("email", unique=True)

security = HTTPBearer()

def create_jwt(user_email: str):
    payload = { "sub": user_email, "exp": datetime.utcnow() + timedelta(days=7) }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = users_collection.find_one({"email": payload.get("sub")})
        if not user: raise HTTPException(401, "使用者不存在")
        return user
    except JWTError:
        raise HTTPException(401, "Token 無效")

# ==========================================
# 📊 資料模型 (涵蓋問卷全欄位)
# ==========================================
class GoogleLoginRequest(BaseModel):
    credential: str

class SurveyData(BaseModel):
    # Step 1
    gender: str = ""
    height: str = ""
    weight: str = ""
    dept: str = ""
    grade: str = ""
    future_status: str = ""
    city: str = ""
    # Step 2
    target_gender: str = ""
    target_height: str = ""
    target_age_diff: str = ""
    # Step 3
    dealbreakers: List[str] = []
    # Step 4
    money_view: str = ""
    gift_view: str = ""
    conflict: str = ""
    boundaries: str = ""
    # Step 5
    ldr: str = ""
    marriage: str = ""
    chronotype: str = ""
    social_energy: str = ""
    # Step 6
    int_energy: str = ""
    int_active: str = ""
    int_vibe: str = ""
    int_nerd: str = ""
    int_life: str = ""
    # Step 7
    dating_goal: str = ""

class UserProfile(BaseModel):
    photo_base64: str = None
    bio: str = None

# ==========================================
# 🧠 全新深度三觀配對演算法
# ==========================================
def calculate_match_score(a: dict, b: dict) -> int:
    score = 40  # 基礎分數

    # 1. 絕對硬性過濾 (性別不符直接 0 分)
    if a.get("target_gender") and a.get("target_gender") != "不限" and a.get("target_gender") != b.get("gender"):
        return 0
    if b.get("target_gender") and b.get("target_gender") != "不限" and b.get("target_gender") != a.get("gender"):
        return 0

    a_db = set(a.get("dealbreakers", []))
    b_db = set(b.get("dealbreakers", []))

    # 2. 地雷秒殺機制 (踩中直接歸零或大幅扣分)
    # A 的地雷檢查 B 的特質
    if "【作息極端不合】" in a_db and a.get("chronotype") != b.get("chronotype"): score -= 25
    if "【金錢觀極度計較】" in a_db and b.get("money_view") == "絕對 AA 制": score -= 25
    if "【冷暴力/不溝通】" in a_db and b.get("conflict") == "逃避包容型": score -= 25
    if "【異性邊界感模糊】" in a_db and b.get("boundaries") in ["社交自由型", "開放式關係"]: score -= 30
    
    # B 的地雷檢查 A 的特質
    if "【作息極端不合】" in b_db and b.get("chronotype") != a.get("chronotype"): score -= 25
    if "【金錢觀極度計較】" in b_db and a.get("money_view") == "絕對 AA 制": score -= 25
    if "【冷暴力/不溝通】" in b_db and a.get("conflict") == "逃避包容型": score -= 25
    if "【異性邊界感模糊】" in b_db and a.get("boundaries") in ["社交自由型", "開放式關係"]: score -= 30

    # 3. 核心價值觀加權加分
    # 婚姻觀與未來 (高度重要)
    if a.get("marriage") == b.get("marriage"): score += 15
    if a.get("dating_goal") == b.get("dating_goal"): score += 15
    
    # 距離與邊界感
    if a.get("ldr") == b.get("ldr"): score += 10
    if a.get("boundaries") == b.get("boundaries"): score += 10
    if a.get("money_view") == b.get("money_view"): score += 10
    
    # 衝突與作息 (日常頻率)
    if a.get("conflict") == b.get("conflict"): score += 5
    if a.get("chronotype") == b.get("chronotype"): score += 5
    if a.get("social_energy") == b.get("social_energy"): score += 5

    # 4. 興趣嗜好微調 (+2 分/項，最高 +10)
    interests = ["int_energy", "int_active", "int_vibe", "int_nerd", "int_life"]
    for i in interests:
        if a.get(i) and a.get(i) == b.get(i):
            score += 2

    # 分數校正 (限制在 0-100)
    return max(0, min(score, 100))

# ==========================================
# 路由與功能實作
# ==========================================
@app.post("/api/auth/google")
async def google_login(data: GoogleLoginRequest):
    try:
        idinfo = id_token.verify_oauth2_token(data.credential, requests.Request(), GOOGLE_CLIENT_ID)
        email = idinfo["email"]
        user = users_collection.find_one({"email": email})

        if not user:
            user_data = { "email": email, "name": idinfo.get("name", ""), "survey": None, "created_at": datetime.utcnow() }
            users_collection.insert_one(user_data)

        return { "message": "登入成功", "token": create_jwt(email), "user": { "email": email, "name": idinfo.get("name", "") } }
    except ValueError:
        raise HTTPException(401, "Google Token 無效")

@app.post("/api/survey")
async def submit_survey(survey: SurveyData, current_user=Depends(get_current_user)):
    users_collection.update_one(
        {"email": current_user["email"]},
        {"$set": {"survey": survey.model_dump()}}
    )
    return {"message": "問卷已儲存"}

@app.get("/api/match")
async def match(current_user=Depends(get_current_user)):
    if not current_user.get("survey"):
        raise HTTPException(400, "請先填寫深度三觀問卷才能進行配對喔！")

    best_match = None
    best_score = 0
    others = users_collection.find({"email": {"$ne": current_user["email"]}, "survey": {"$ne": None}})

    for u in others:
        score = calculate_match_score(current_user["survey"], u["survey"])
        if score > best_score:
            best_score = score
            best_match = u

    if not best_match or best_score < 50:  # 加上基礎門檻，低於50分代表不適合
        return {"message": "目前還沒有三觀契合的對象，系統將持續為您尋找！"}

    return { "match": { "name": best_match["name"], "email": best_match["email"], "score": best_score } }

@app.get("/api/profile")
async def get_profile(current_user=Depends(get_current_user)):
    user_data = users_collection.find_one({"email": current_user["email"]}, {"_id": 0})
    return user_data or {}

@app.post("/api/profile")
async def update_profile(profile: UserProfile, current_user=Depends(get_current_user)):
    update_data = profile.model_dump(exclude_unset=True)
    users_collection.update_one({"email": current_user["email"]}, {"$set": update_data})
    return {"message": "個人資料已更新"}

@app.get("/api")
def root(): return {"message": "API running"}