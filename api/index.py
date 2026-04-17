from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pymongo import MongoClient
from jose import jwt, JWTError
from google.oauth2 import id_token
from google.auth.transport import requests
import urllib.parse
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

client = MongoClient(MONGO_URI)
db = client["datefree_db"]
users_collection = db["users"]
messages_collection = db["messages"]

users_collection.create_index("email", unique=True)
security = HTTPBearer()

def create_jwt(user_email: str):
    payload = { "sub": user_email, "exp": datetime.utcnow() + timedelta(days=1) }
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
class SurveyData(BaseModel):
    gender: str = ""
    height: str = ""
    weight: str = ""
    dept: str = ""
    grade: str = ""
    future_status: str = ""
    city: str = ""
    target_gender: str = ""
    target_height: List[str] = []
    target_age_diff: str = ""
    target_future_status: List[str] = []
    target_smoking: str = ""
    target_drinking: str = ""
    target_tattoo: str = ""
    lunch_budget: str = ""
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
    height: Optional[int] = None   
    weight: Optional[int] = None
    department: str = None
    grade: str = None
    smoking: str = None
    drinking: str = None
    tattoo: str = None
    enrollment_cert_base64: Optional[str] = None
    mbti: str = None
    tags: List[str] = []
    birthday: str = None
    hometown: str = None
    zodiac: str = None
    blood_type: str = None
    pet: str = None
    fitness: str = None
    diet: str = None

# ==========================================
# 🧠 深度相似度雙向配對演算法 (嚴謹版)
# ==========================================
def calculate_rigorous_score(user_a: dict, user_b: dict) -> int:
    a = user_a.get("survey")
    b = user_b.get("survey")
    if not a or not b: return 0

    # --- 1. 硬性過濾 (Hard Filters) ---
    # 1.1 性別偏好
    if a.get("target_gender") and a.get("target_gender") != "不限" and a.get("target_gender") != b.get("gender"): return 0
    if b.get("target_gender") and b.get("target_gender") != "不限" and b.get("target_gender") != a.get("gender"): return 0

    # 1.2 嗜好硬性過濾 (抽菸/喝酒/紋身)
    if a.get("target_smoking") == "不接受" and user_b.get("smoking") == "是": return 0
    if b.get("target_smoking") == "不接受" and user_a.get("smoking") == "是": return 0
    
    if a.get("target_tattoo") == "不接受" and user_b.get("tattoo") == "是": return 0
    if b.get("target_tattoo") == "不接受" and user_a.get("tattoo") == "是": return 0

    # 1.3 地雷區過濾 (Dealbreakers)
    a_db, b_db = set(a.get("dealbreakers", [])), set(b.get("dealbreakers", []))

    def hit_dealbreaker(db_list, person, other_person):
        if "【作息極端不合】" in db_list and person.get("chronotype") != other_person.get("chronotype"): return True
        if "【金錢觀極度計較】" in db_list and other_person.get("money_view") == "絕對 AA 制": return True
        if "【冷暴力/不溝通】" in db_list and other_person.get("conflict") == "逃避包容型": return True
        if "【異性邊界感模糊】" in db_list and other_person.get("boundaries") in ["社交自由型", "開放式關係"]: return True
        # 由於完整判斷較多，可依據業務需求逐步加入其他 12 項地雷的具體判定
        return False

    if hit_dealbreaker(a_db, a, b) or hit_dealbreaker(b_db, b, a):
        return 0

    # --- 2. 相似度計算 (計算選項一致的百分比) ---
    total_weight = 0
    match_weight = 0

    # 設定各題目的權重
    attributes = [
        ("marriage", 15), ("dating_goal", 15), ("ldr", 10),
        ("boundaries", 10), ("money_view", 10), ("conflict", 10),
        ("chronotype", 5), ("social_energy", 5),
        ("int_energy", 4), ("int_active", 4), ("int_vibe", 4),
        ("int_nerd", 4), ("int_life", 4)
    ]

    for key, weight in attributes:
        val_a = a.get(key)
        val_b = b.get(key)
        if val_a and val_b:  
            total_weight += weight
            if val_a == val_b:
                match_weight += weight

    if total_weight == 0:
        return 0

    return int((match_weight / total_weight) * 100)


# ==========================================
# 💬 WebSocket 管理器
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
                new_msg = { "sender": email, "receiver": receiver, "content": content, "timestamp": datetime.utcnow().isoformat() }
                result = messages_collection.insert_one(new_msg.copy())
                new_msg["_id"] = str(result.inserted_id)
                await manager.send_personal_message(new_msg, receiver)
                await manager.send_personal_message(new_msg, email)
    except WebSocketDisconnect:
        manager.disconnect(email)


# ==========================================
# 🌐 路由 API (Endpoints)
# ==========================================

# Google Redirect Callback (解決 iOS Safari 白畫面與 LINE 登入問題)
@app.post("/api/auth/google/callback")
async def google_login_callback(request: Request):
    try:
        body = await request.body()
        parsed = urllib.parse.parse_qs(body.decode('utf-8'))
        credential = parsed.get("credential", [None])[0]
        
        if not credential:
            return RedirectResponse(url="/index.html?error=missing_credential", status_code=303)

        idinfo = id_token.verify_oauth2_token(credential, requests.Request(), GOOGLE_CLIENT_ID)
        email = idinfo["email"]
        name = idinfo.get("name", "")
        
        user = users_collection.find_one({"email": email})
        if not user:
            user_data = { "email": email, "name": name, "survey": None, "current_match": None, "created_at": datetime.utcnow() }
            users_collection.insert_one(user_data)
        
        token = create_jwt(email)
        
        encoded_name = urllib.parse.quote(name)
        encoded_email = urllib.parse.quote(email)
        redirect_url = f"/dashboard.html?token={token}&name={encoded_name}&email={encoded_email}"
        
        return RedirectResponse(url=redirect_url, status_code=303)
        
    except Exception as e:
        print("Google Callback Error:", e)
        return RedirectResponse(url="/index.html?error=auth_failed", status_code=303)


@app.get("/api/profile")
async def get_profile(current_user=Depends(get_current_user)):
    user_data = users_collection.find_one({"email": current_user["email"]}, {"_id": 0})
    return user_data or {}


@app.post("/api/profile")
async def update_profile(profile: UserProfile, current_user=Depends(get_current_user)):
    update_data = profile.model_dump(exclude_unset=True)
    users_collection.update_one({"email": current_user["email"]}, {"$set": update_data})
    return {"message": "個人資料已更新"}


@app.get("/api/survey")
async def get_survey(current_user=Depends(get_current_user)):
    return {"survey": current_user.get("survey")}


@app.post("/api/survey")
async def submit_survey(survey: SurveyData, current_user=Depends(get_current_user)):
    users_collection.update_one({"email": current_user["email"]}, {"$set": {"survey": survey.model_dump()}})
    return {"message": "問卷已儲存"}


# ---------------------------------------------------------
# 🏆 核心配對 API (讀取固化的配對結果)
# ---------------------------------------------------------
@app.get("/api/my_matches")
async def my_matches(current_user=Depends(get_current_user)):
    match_info = current_user.get("current_match")
    
    # 如果資料庫裡面沒有配對紀錄，代表這週還沒開獎，或者沒人達到 70 分
    if not match_info:
        return {"matches": []}
    
    # 根據資料庫紀錄，抓取對方的完整資料
    target_user = users_collection.find_one({"email": match_info["email"]})
    if not target_user:
        return {"matches": []}
        
    return {"matches": [{
        "name": target_user.get("name", "Unknown"), 
        "email": target_user.get("email"),
        "score": match_info.get("score", 0), 
        "photo_base64": target_user.get("photo_base64", ""),
        "is_verified": target_user.get("is_verified", False),
        "bio": target_user.get("bio", "這個人很神秘，還沒寫自我介紹..."),
        "department": target_user.get("department", "神秘科系"),
        "grade": target_user.get("grade", ""),
        "mbti": target_user.get("mbti", ""),
        "tags": target_user.get("tags", []),
        "birthday": target_user.get("birthday", ""),
        "hometown": target_user.get("hometown", ""),
        "zodiac": target_user.get("zodiac", ""),
        "blood_type": target_user.get("blood_type", ""),
        "pet": target_user.get("pet", ""),
        "fitness": target_user.get("fitness", ""),
        "diet": target_user.get("diet", "")
    }]}


@app.get("/api/match")
async def match(current_user=Depends(get_current_user)):
    if not current_user.get("survey"): raise HTTPException(400, "請先填寫深度三觀問卷才能進行配對喔！")
    matches_data = await my_matches(current_user)
    if not matches_data["matches"]:
        return {"message": "目前還沒有三觀契合的對象，系統將在每週一為您尋找！"}
    return { "match": matches_data["matches"][0] }


# ---------------------------------------------------------
# ⏰ 管理員排程專用：執行全站每週配對 (Cron Job)
# ---------------------------------------------------------
@app.post("/api/admin/run-weekly-match")
async def run_weekly_match(request: Request):
    # 取得所有有填寫問卷的使用者
    all_users = list(users_collection.find({"survey": {"$ne": None}}))
    potential_pairs = []

    # 計算全域所有組合的分數
    for i in range(len(all_users)):
        for j in range(i + 1, len(all_users)):
            score = calculate_rigorous_score(all_users[i], all_users[j])
            
            # 只有分數 >= 70 才符合配對資格
            if score >= 70:
                potential_pairs.append({
                    "score": score,
                    "u1": all_users[i]["email"],
                    "u2": all_users[j]["email"]
                })

    # 由高分到低分排序 (貪婪綁定前置作業)
    potential_pairs.sort(key=lambda x: x["score"], reverse=True)
    
    matched_emails = set()
    match_count = 0

    # 執行全局雙向貪婪綁定
    for pair in potential_pairs:
        # 如果兩人都還沒有被綁定
        if pair["u1"] not in matched_emails and pair["u2"] not in matched_emails:
            
            # 建立配對紀錄
            match_data_1 = {"email": pair["u2"], "score": pair["score"], "matched_at": datetime.utcnow()}
            match_data_2 = {"email": pair["u1"], "score": pair["score"], "matched_at": datetime.utcnow()}
            
            # 將結果寫入雙方的資料庫 (固化配對，保護聊天室不消失)
            users_collection.update_one({"email": pair["u1"]}, {"$set": {"current_match": match_data_1}})
            users_collection.update_one({"email": pair["u2"]}, {"$set": {"current_match": match_data_2}})
            
            matched_emails.add(pair["u1"])
            matched_emails.add(pair["u2"])
            match_count += 1

    return {"status": "success", "matches_created": match_count}


@app.get("/api/messages/{target_email}")
async def get_messages(target_email: str, current_user=Depends(get_current_user)):
    my_email = current_user["email"]
    msgs = list(messages_collection.find({
        "$or": [{"sender": my_email, "receiver": target_email}, {"sender": target_email, "receiver": my_email}]
    }).sort("timestamp", 1))
    for m in msgs: m["_id"] = str(m["_id"])
    return {"messages": msgs}


@app.get("/api")
def root(): 
    return {"message": "Date Free API is running successfully!"}