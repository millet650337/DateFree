from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pymongo import MongoClient
from jose import jwt, JWTError
from google.oauth2 import id_token
from google.auth.transport import requests
import os
import json

# ==========================================
# 🔧 環境設定
# ==========================================
MONGO_URI = os.getenv("MONGO_URI")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")
JWT_ALGORITHM = "HS256"

if not MONGO_URI or not GOOGLE_CLIENT_ID:
    raise Exception("❌ 請設定 MONGO_URI 與 GOOGLE_CLIENT_ID (Vercel 環境變數)")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化 MongoDB 連線
client = MongoClient(MONGO_URI)
db = client["datefree_db"]
users_collection = db["users"]
messages_collection = db["messages"] # 聊天紀錄資料表

users_collection.create_index("email", unique=True)
security = HTTPBearer()

# ==========================================
# 🔐 驗證與輔助函式
# ==========================================
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
# 📊 資料模型 (Models)
# ==========================================
class GoogleLoginRequest(BaseModel):
    credential: str

class SurveyData(BaseModel):
    gender: str = ""
    height: str = ""
    weight: str = ""
    dept: str = ""
    grade: str = ""
    future_status: str = ""
    city: str = ""
    target_gender: str = ""
    target_height: str = ""
    target_age_diff: str = ""
    
    # ----- 新增的問卷欄位開始 -----
    target_future_status: List[str] = []
    target_smoking: str = ""
    target_drinking: str = ""
    target_tattoo: str = ""
    lunch_budget: str = ""
    # ----- 新增的問卷欄位結束 -----
    
    dealbreakers: List[str] = []
    money_view: str = ""
    gift_view: str = ""
    conflict: str = ""
    boundaries: str = ""
    ldr: str = ""
    marriage: str = ""
    chronotype: str = ""
    social_energy: str = ""
    int_energy: str = ""
    int_active: str = ""
    int_vibe: str = ""
    int_nerd: str = ""
    int_life: str = ""
    dating_goal: str = ""

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
# 🧠 深度三觀配對演算法
# ==========================================
def calculate_match_score(a: dict, b: dict) -> int:
    score = 40  # 基礎分數

    # 1. 絕對硬性過濾 (性別不符直接 0 分)
    if a.get("target_gender") and a.get("target_gender") != "不限" and a.get("target_gender") != b.get("gender"): return 0
    if b.get("target_gender") and b.get("target_gender") != "不限" and b.get("target_gender") != a.get("gender"): return 0

    a_db, b_db = set(a.get("dealbreakers", [])), set(b.get("dealbreakers", []))

    # 2. 地雷秒殺機制
    if "【作息極端不合】" in a_db and a.get("chronotype") != b.get("chronotype"): score -= 25
    if "【金錢觀極度計較】" in a_db and b.get("money_view") == "絕對 AA 制": score -= 25
    if "【冷暴力/不溝通】" in a_db and b.get("conflict") == "逃避包容型": score -= 25
    if "【異性邊界感模糊】" in a_db and b.get("boundaries") in ["社交自由型", "開放式關係"]: score -= 30
    
    if "【作息極端不合】" in b_db and b.get("chronotype") != a.get("chronotype"): score -= 25
    if "【金錢觀極度計較】" in b_db and a.get("money_view") == "絕對 AA 制": score -= 25
    if "【冷暴力/不溝通】" in b_db and a.get("conflict") == "逃避包容型": score -= 25
    if "【異性邊界感模糊】" in b_db and a.get("boundaries") in ["社交自由型", "開放式關係"]: score -= 30

    # 3. 核心價值觀加權加分
    if a.get("marriage") == b.get("marriage"): score += 15
    if a.get("dating_goal") == b.get("dating_goal"): score += 15
    if a.get("ldr") == b.get("ldr"): score += 10
    if a.get("boundaries") == b.get("boundaries"): score += 10
    if a.get("money_view") == b.get("money_view"): score += 10
    if a.get("conflict") == b.get("conflict"): score += 5
    if a.get("chronotype") == b.get("chronotype"): score += 5
    if a.get("social_energy") == b.get("social_energy"): score += 5

    # 4. 興趣嗜好微調 (+2 分/項)
    interests = ["int_energy", "int_active", "int_vibe", "int_nerd", "int_life"]
    for i in interests:
        if a.get(i) and a.get(i) == b.get(i): score += 2

    return max(0, min(score, 100))

# ==========================================
# 💬 WebSocket 管理器 (聊天室核心)
# ==========================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, email: str):
        await websocket.accept()
        self.active_connections[email] = websocket

    def disconnect(self, email: str):
        if email in self.active_connections:
            del self.active_connections[email]

    async def send_personal_message(self, message: dict, email: str):
        if email in self.active_connections:
            await self.active_connections[email].send_json(message)

manager = ConnectionManager()

@app.websocket("/api/ws/chat")
async def websocket_endpoint(websocket: WebSocket, token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email = payload.get("sub")
    except Exception:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, email)
    try:
        while True:
            data = await websocket.receive_text()
            msg_data = json.loads(data)
            receiver = msg_data.get("receiver")
            content = msg_data.get("content")

            if receiver and content:
                # 將新訊息存入 MongoDB
                new_msg = {
                    "sender": email,
                    "receiver": receiver,
                    "content": content,
                    "timestamp": datetime.utcnow().isoformat()
                }
                result = messages_collection.insert_one(new_msg.copy())
                new_msg["_id"] = str(result.inserted_id)

                # 即時推播給接收方與發送方
                await manager.send_personal_message(new_msg, receiver)
                await manager.send_personal_message(new_msg, email)

    except WebSocketDisconnect:
        manager.disconnect(email)

# ==========================================
# 🌐 路由 API (Endpoints)
# ==========================================

# 1. 登入與認證
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

# 2. 個人資料設定
@app.get("/api/profile")
async def get_profile(current_user=Depends(get_current_user)):
    user_data = users_collection.find_one({"email": current_user["email"]}, {"_id": 0})
    return user_data or {}

@app.post("/api/profile")
async def update_profile(profile: UserProfile, current_user=Depends(get_current_user)):
    update_data = profile.model_dump(exclude_unset=True)
    users_collection.update_one({"email": current_user["email"]}, {"$set": update_data})
    return {"message": "個人資料已更新"}

# 3. 問卷填寫
@app.post("/api/survey")
async def submit_survey(survey: SurveyData, current_user=Depends(get_current_user)):
    users_collection.update_one({"email": current_user["email"]}, {"$set": {"survey": survey.model_dump()}})
    return {"message": "問卷已儲存"}

# 4. 獲取單一最高分配對名單 (聊天室左側使用)
@app.get("/api/my_matches")
async def my_matches(current_user=Depends(get_current_user)):
    if not current_user.get("survey"): return {"matches": []}
    
    best_match = None
    best_score = 0
    others = users_collection.find({"email": {"$ne": current_user["email"]}, "survey": {"$ne": None}})
    
    # 計算所有人的分數，只保留最高分的那一位
    for u in others:
        score = calculate_match_score(current_user["survey"], u["survey"])
        if score > best_score:
            best_score = score
            best_match = u
            
    # 如果最高分的人都沒有達到 50 分門檻，回傳空名單
    if not best_match or best_score < 50:
        return {"matches": []}
        
    # 維持單一配對結果
    return {"matches": [{
        "name": best_match["name"], 
        "email": best_match["email"],
        "score": best_score, 
        "photo_base64": best_match.get("photo_base64", "")
    }]}

# 5. 獲取單一最高分配對 (Dashboard 彈窗使用)
@app.get("/api/match")
async def match(current_user=Depends(get_current_user)):
    if not current_user.get("survey"): raise HTTPException(400, "請先填寫深度三觀問卷才能進行配對喔！")
    
    matches_data = await my_matches(current_user)
    if not matches_data["matches"]:
        return {"message": "目前還沒有三觀契合的對象，系統將持續為您尋找！"}
    
    best = matches_data["matches"][0]
    return { "match": { "name": best["name"], "email": best["email"], "score": best["score"] } }

# 6. 獲取歷史聊天紀錄
@app.get("/api/messages/{target_email}")
async def get_messages(target_email: str, current_user=Depends(get_current_user)):
    my_email = current_user["email"]
    msgs = list(messages_collection.find({
        "$or": [
            {"sender": my_email, "receiver": target_email},
            {"sender": target_email, "receiver": my_email}
        ]
    }).sort("timestamp", 1))
    
    for m in msgs: m["_id"] = str(m["_id"])
    return {"messages": msgs}

# 7. 系統狀態檢查
@app.get("/api")
def root(): 
    return {"message": "Date Free API is running successfully!"}