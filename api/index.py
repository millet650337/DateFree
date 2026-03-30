from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime
from pymongo import MongoClient

# ==========================================
# 1. 伺服器與「真實」資料庫連線設定
# ==========================================
app = FastAPI(
    title="Date Free 核心系統 API",
    description="專為台中大學生打造的「高效率、深社交」媒合系統後端"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import os
MONGO_URI = os.getenv("MONGO_URI", "如果您本機測試用的字串可以暫放這裡")

try:
    client = MongoClient(MONGO_URI)
    db = client["datefree_db"]        # 建立/選擇名為 datefree_db 的資料庫
    users_collection = db["users"]    # 建立/選擇名為 users 的資料表 (Collection)
    print("✅ 成功連線至 MongoDB 真實資料庫！")
except Exception as e:
    print(f"❌ 資料庫連線失敗：{e}")


# ==========================================
# 2. 資料結構定義 (Pydantic Models)
# ==========================================
class SurveyData(BaseModel):
    gender: str = Field(..., example="男")
    future_status: str = Field(..., example="大學在讀")
    dealbreakers: List[str] = Field(default=[], example=["抽菸習慣", "冷暴力"])
    bad_habits: List[str] = Field(default=[], example=["抽菸習慣"])
    money_view: str = Field(..., example="絕對 AA 制")
    boundaries: str = Field(..., example="【報備信任型】")
    dating_goal: str = Field(..., example="【穩定關係】")

class UserLogin(BaseModel):
    email: EmailStr = Field(..., example="student@thu.edu.tw")
    name: str = Field(..., example="王同學")


# ==========================================
# 3. 三觀配對演算法 (核心大腦)
# ==========================================
def calculate_match_score(user_a_survey: dict, user_b_survey: dict) -> int:
    a_dealbreakers = set(user_a_survey.get("dealbreakers", []))
    b_habits = set(user_b_survey.get("bad_habits", []))
    b_dealbreakers = set(user_b_survey.get("dealbreakers", []))
    a_habits = set(user_a_survey.get("bad_habits", []))

    if a_dealbreakers.intersection(b_habits) or b_dealbreakers.intersection(a_habits):
        return 0 

    total_score = 0
    total_weight = 0
    
    rules = [
        {"key": "money_view", "weight": 5},    
        {"key": "boundaries", "weight": 5},    
        {"key": "dating_goal", "weight": 4},   
        {"key": "future_status", "weight": 3}, 
    ]

    for rule in rules:
        key = rule["key"]
        weight = rule["weight"]
        total_weight += weight
        
        if user_a_survey.get(key) == user_b_survey.get(key):
            total_score += weight 

    if total_weight == 0: return 0
    return round((total_score / total_weight) * 100)


# ==========================================
# 4. API 路由與 MongoDB 實作
# ==========================================

@app.get("/api")
async def root():
    return {"message": "Date Free 伺服器運作正常！資料庫已連線。"}

@app.post("/api/auth/google")
async def google_login_simulation(user: UserLogin):
    """模擬 Google 登入並驗證校園信箱，存入 MongoDB"""
    if not user.email.endswith(".edu.tw"):
        raise HTTPException(status_code=403, detail="目前僅限台灣學術網路 (.edu.tw) 信箱註冊！")
    
    # 在 MongoDB 中尋找是否有這個信箱
    existing_user = users_collection.find_one({"email": user.email})
    
    
    if not existing_user:
        # 如果是新用戶，寫入資料庫
        new_user_data = {
            "email": user.email, 
            "name": user.name, 
            "is_verified_student": True,
            "survey": None,
            "created_at": datetime.now()
        }
        users_collection.insert_one(new_user_data)
        
        # 移除 MongoDB 自動生成的 _id (因為 Pydantic 預設不認識它) 以方便回傳
        new_user_data.pop("_id", None)
        return {"message": "身分驗證成功，歡迎進入校園社交圈！", "user": new_user_data}
    else:
        existing_user.pop("_id", None)
        return {"message": "歡迎回來！", "user": existing_user}

@app.post("/api/survey/{user_email}")
async def submit_survey(user_email: str, survey: SurveyData):
    """接收使用者的問卷，並更新到 MongoDB"""
    # 尋找並更新該使用者的 survey 欄位
    result = users_collection.update_one(
        {"email": user_email},
        {"$set": {"survey": survey.model_dump()}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="找不到該使用者，請先登入。")
    
    return {"message": "問卷分析完成，已安全存入大數據庫！"}

@app.get("/api/match/{user_email}")
async def get_weekly_match(user_email: str):
    """從 MongoDB 撈取所有用戶進行配對計算"""
    target_user = users_collection.find_one({"email": user_email})
    
    if not target_user or not target_user.get("survey"):
        raise HTTPException(status_code=400, detail="請先完成深度三觀問卷，系統才能為您配對。")

    best_match = None
    highest_score = 0

    # 從資料庫撈出「不是自己」且「已經填完問卷」的所有使用者
    other_users = users_collection.find({
        "email": {"$ne": user_email},
        "survey": {"$ne": None}
    })

    # 進行演算法比對
    for other_user in other_users:
        score = calculate_match_score(target_user["survey"], other_user["survey"])
        
        if score > highest_score:
            highest_score = score
            best_match = other_user["name"]

    if not best_match:
        return {"message": "目前隱形池中還沒有適合您的對象，請耐心等候下週開獎！"}

    return {
        "message": "配對成功！",
        "match_result": {
            "partner_name": best_match,
            "similarity_score": f"{highest_score}%",
            "reward_eligible": "已解鎖 200 元線下約會補貼金資格 ☕"
        }
    }