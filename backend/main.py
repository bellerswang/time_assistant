from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import json
import tempfile
import logging
# Load .env file from backend directory explicitly using absolute path
backend_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(backend_dir, ".env"))

# Use uvicorn's error logger so logs appear nicely in --reload subprocess consoles
logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="ChronoAI Backend Server v2.0")

# CORS config: allow local browser files and LAN mobile devices
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

openai_key = os.getenv("OPENAI_API_KEY")
if not openai_key:
    # Try reading from openai_key.txt in project root as fallback
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        txt_path = os.path.join(root_dir, "openai_key.txt")
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                openai_key = f.read().strip()
                logger.info("Loaded OPENAI_API_KEY from openai_key.txt")
    except Exception as e:
        logger.error(f"Failed to read openai_key.txt: {e}")

# Handle comma-separated keys like: time_assistant,sk-proj-...
if openai_key and "," in openai_key:
    openai_key = openai_key.split(",")[1].strip()
    logger.info("Parsed comma-separated API key successfully")

if not openai_key or not openai_key.startswith("sk-"):
    logger.warning("OPENAI_API_KEY is not configured or invalid! Server will run but API calls will fail with 401/402.")

client = AsyncOpenAI(api_key=openai_key if openai_key and openai_key.startswith("sk-") else "placeholder")

class ParseRequest(BaseModel):
    text: str

SYSTEM_PROMPT = """
You are the advanced parsing engine for ChronoAI v2.0.
The user will provide a natural language text input describing a task. You must extract structured information and return a strict JSON object with the following fields:
{
  "name": "Task name, concise and under 10 Chinese/English characters. Strip away all time-related words (e.g. '下午', '晚上', '点半', '两小时', '2 hours', 'tomorrow') and keep only the core action, e.g. '写代码', '健身运动', '周报复盘', '看书学习'.",
  "category": "Must be exactly one of: 'work' (for professional or academic brain activities, e.g., coding, reports, meetings, analysis, deep learning, homework), 'health' (for physical health/exercise/rest, e.g., gym, running, yoga, meditation, sleep, medical), or 'personal' (for personal life/entertainment/chores, e.g., reading, shopping, chores, kids, friends, cooking, playing games).",
  "estMins": 30, // Estimated duration in minutes as a positive integer. Convert '1.5 hours', 'two hours', '半小时', etc. accurately. Default to 30 if not mentioned.
  "anchorTime": "15:00", // A specific starting time in 24-hour 'HH:MM' format if explicitly specified in the input (e.g., '下午三点', '15:00', '9:30', '10 o'clock'). Otherwise, return null.
  "confidence": "high" // Set to 'high' if the parsing is highly reliable, otherwise 'medium' or 'low'.
}

Example 1:
Input: "下午三点写量化策略报告两小时"
Output: {"name": "写策略报告", "category": "work", "estMins": 120, "anchorTime": "15:00", "confidence": "high"}

Example 2:
Input: "现在开始健身半小时"
Output: {"name": "健身运动", "category": "health", "estMins": 30, "anchorTime": null, "confidence": "high"}

Example 3:
Input: "读一小时小说"
Output: {"name": "看小说", "category": "personal", "estMins": 60, "anchorTime": null, "confidence": "high"}

Do NOT wrap the output in markdown formatting. Return ONLY a valid raw JSON object.
"""

async def call_gpt_parser(text: str) -> dict:
    if not openai_key:
        raise HTTPException(
            status_code=401, 
            detail="后端未配置 OPENAI_API_KEY。请在 backend/.env 中配置，或者在根目录放置 openai_key.txt。"
        )
    try:
        logger.info(f"[Parser] Sending prompt to GPT-4o-mini for text: '{text}'")
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0,
            max_tokens=150,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Validation & fallback checks
        result.setdefault("name", text[:10] if text else "新日程事项")
        result.setdefault("category", "work")
        result.setdefault("estMins", 30)
        result.setdefault("anchorTime", None)
        result.setdefault("confidence", "medium")
        
        # Coerce datatypes
        result["estMins"] = max(5, min(480, int(result["estMins"])))
        if result["category"] not in ["work", "health", "personal"]:
            result["category"] = "work"
            
        logger.info(f"[Parser] Successfully parsed: {result}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[Parser] JSON decode error: {e}")
        raise HTTPException(status_code=500, detail="AI 解析返回格式异常")
    except Exception as e:
        err_str = str(e)
        logger.error(f"[Parser] OpenAI API Error: {err_str}")
        if "insufficient_quota" in err_str or "429" in err_str:
            raise HTTPException(
                status_code=402, 
                detail="OpenAI API 余额不足。请前往 platform.openai.com 充值，或改用本地正则解析（前端已自动降级）。"
            )
        raise HTTPException(status_code=500, detail=f"AI 解析请求失败: {err_str}")

@app.post("/api/parse")
async def parse_text(req: ParseRequest):
    logger.info(f"Received parse request: {req.text}")
    if not req.text.strip():
        logger.warning("Empty text request received")
        raise HTTPException(status_code=400, detail="输入文本不能为空")
    return await call_gpt_parser(req.text)

@app.post("/api/text-parse")
async def parse_text_legacy(req: ParseRequest):
    # Keep legacy endpoint for compatibility, redirecting to /api/parse
    logger.info(f"Legacy text-parse endpoint called. Redirecting to /api/parse")
    return await call_gpt_parser(req.text)

@app.post("/api/voice-parse")
async def parse_voice(file: UploadFile = File(...)):
    filename = file.filename or "recording.webm"
    ext = os.path.splitext(filename)[1] or ".webm"
    logger.info(f"[Voice-Parse] Received upload file: '{filename}', extension: '{ext}'")
    
    if not openai_key:
        raise HTTPException(
            status_code=401, 
            detail="后端未配置 OPENAI_API_KEY。请在 backend/.env 中配置，或者在根目录放置 openai_key.txt。"
        )

    temp_file_path = None
    try:
        # 1. Save uploaded audio to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
            contents = await file.read()
            temp_file.write(contents)
            temp_file_path = temp_file.name
        
        logger.info(f"[Voice-Parse] Temporary file written at: {temp_file_path}")

        # 2. Call OpenAI Whisper API for transcribing
        with open(temp_file_path, "rb") as audio_file:
            transcription = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="zh" # Guide whisper to recognize Chinese
            )
        
        text = transcription.text
        logger.info(f"[Voice-Parse] Whisper Transcript Result: '{text}'")
        
        if not text.strip():
            logger.warning("[Voice-Parse] Whisper returned empty transcription text")
            raise HTTPException(status_code=422, detail="未能从音频中识别出任何清晰文字")
        
        # 3. Call parser on transcribed text
        parsed_result = await call_gpt_parser(text)
        
        # Include transcription inside the result for frontend echo
        parsed_result["raw_text"] = text
        return parsed_result

    except Exception as e:
        err_str = str(e)
        logger.error(f"[Voice-Parse] ERROR: {err_str}")
        if "insufficient_quota" in err_str or "429" in err_str:
            raise HTTPException(
                status_code=402, 
                detail="OpenAI API 余额不足。请前往 platform.openai.com 充值，或改用本地打字正则解析。"
            )
        raise HTTPException(status_code=500, detail=f"语音听写解析失败: {err_str}")
    finally:
        # Cleanup temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"[Voice-Parse] Temporary file cleaned up: {temp_file_path}")
            except Exception as ex:
                logger.error(f"[Voice-Parse] Failed to delete temp file: {ex}")

@app.get("/health")
async def health_check():
    return {
        "status": "ok", 
        "service": "ChronoAI API Server", 
        "version": "2.0.0",
        "openai_configured": openai_key is not None and openai_key.startswith("sk-")
    }
