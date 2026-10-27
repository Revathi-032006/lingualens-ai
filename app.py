import hashlib
import io
import json
import os
from datetime import datetime

import pandas as pd
import speech_recognition as sr
import streamlit as st
from google import genai
from gtts import gTTS
from PIL import Image
from streamlit_mic_recorder import mic_recorder

MODEL = "gemini-2.5-flash"
USERS_FILE = "users.csv"
RESULTS_FILE = "results.csv"
TEACHER_CODE = "TEACH123"  # change this to your own secret code

st.set_page_config(
    page_title="LinguaLens AI",
    page_icon="🎓",
    layout="centered"
)


# =============================
# Helper functions
# =============================
def speech_to_text(audio_bytes, lang_code):
    r = sr.Recognizer()
    with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
        audio = r.record(source)
    return r.recognize_google(audio, language=lang_code)


def text_to_speech(text, lang):
    code = "ta" if lang == "Tamil" else "en"
    tts = gTTS(text=text, lang=code)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    return buf.getvalue()


def save_result(name, topic, score, total, weak):
    row = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "student": name,
        "topic": topic,
        "score": score,
        "total": total,
        "percent": round(score / total * 100, 1),
        "weak_topics": ", ".join(weak.keys())
    }
    pd.DataFrame([row]).to_csv(
        RESULTS_FILE, mode="a", index=False,
        header=not os.path.exists(RESULTS_FILE)
    )


def hash_pw(password, salt):
    return hashlib.sha256((salt + password).encode()).hexdigest()


def load_users():
    if os.path.exists(USERS_FILE):
        return pd.read_csv(USERS_FILE, dtype=str).fillna("")
    return pd.DataFrame(
        columns=["username", "salt", "password_hash", "role", "child"]
    )


def register_user(username, password, role, child, code):
    username = username.strip().lower()
    child = child.strip().lower()
    users = load_users()

    if not username or not password:
        return False, "Username and password are required."
    if len(password) < 4:
        return False, "Password must be at least 4 characters."
    if username in users["username"].values:
        return False, "Username already exists."
    if role == "Teacher" and code != TEACHER_CODE:
        return False, "Wrong teacher code."
    if role == "Parent":
        students = users[users["role"] == "Student"]["username"].values
        if child not in students:
            return False, "Child username not found. Student must register first."

    salt = os.urandom(8).hex()
    row = {
        "username": username,
        "salt": salt,
        "password_hash": hash_pw(password, salt),
        "role": role,
        "child": child if role == "Parent" else ""
    }
    pd.DataFrame([row]).to_csv(
        USERS_FILE, mode="a", index=False,
        header=not os.path.exists(USERS_FILE)
    )
    return True, "Registered successfully. Please login."


def login_user(username, password):
    username = username.strip().lower()
    users = load_users()
    match = users[users["username"] == username]
    if match.empty:
        return None
    u = match.iloc[0]
    if hash_pw(password, u["salt"]) == u["password_hash"]:
        return {"username": u["username"], "role": u["role"], "child": u["child"]}
    return None


# =============================
# Login / Register page
# =============================
def auth_page():
    st.title("🎓 LinguaLens AI")
    st.write("Multilingual Learning Assistant with OCR and Weak Topic Detection")
    st.divider()

    tab_login, tab_reg = st.tabs(["🔐 Login", "📝 Register"])

    with tab_login:
        u = st.text_input("Username", key="login_user")
        p = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login", use_container_width=True):
            user = login_user(u, p)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with tab_reg:
        role = st.selectbox("Register as", ["Student", "Teacher", "Parent"])
        ru = st.text_input("Choose username", key="reg_user")
        rp = st.text_input("Choose password", type="password", key="reg_pass")
        child, code = "", ""
        if role == "Parent":
            child = st.text_input("Your child's username")
        if role == "Teacher":
            code = st.text_input("Teacher code", type="password")
        if st.button("Register", use_container_width=True):
            ok, msg = register_user(ru, rp, role, child, code)
            if ok:
                st.success(msg)
            else:
                st.error(msg)


# =============================
# Learning section (Student)
# =============================
def learning_section(api_key, language, difficulty):
    st.header("📖 Learn")

    input_type = st.radio(
        "Select Input Type",
        ["✍️ Type Question", "📷 Upload Image", "🎤 Voice Question"]
    )

    question = ""
    uploaded_file = None

    if input_type == "✍️ Type Question":
        question = st.text_area(
            "Enter your academic question",
            placeholder="Example: What is Artificial Intelligence?"
        )

    elif input_type == "📷 Upload Image":
        uploaded_file = st.file_uploader(
            "Upload Textbook / Notes Image",
            type=["jpg", "jpeg", "png"]
        )
        if uploaded_file is not None:
            st.image(uploaded_file, caption="Uploaded Image",
                     use_container_width=True)

    else:
        audio = mic_recorder(
            start_prompt="🎙️ Start Recording",
            stop_prompt="⏹️ Stop",
            format="wav",
            key="voice"
        )
        if audio:
            try:
                lang_code = "ta-IN" if language == "Tamil" else "en-IN"
                st.session_state.voice_question = speech_to_text(
                    audio["bytes"], lang_code
                )
            except Exception:
                st.session_state.voice_question = ""
                st.error("Could not understand audio. Try again.")
        question = st.session_state.get("voice_question", "")
        if question:
            st.success(f"You asked: {question}")

    if st.button("🤖 Explain", use_container_width=True):
        if not api_key:
            st.warning("Please enter your Gemini API key (left sidebar).")
        elif input_type == "📷 Upload Image" and uploaded_file is None:
            st.warning("Please upload an image.")
        elif input_type != "📷 Upload Image" and not question:
            st.warning("Please enter or speak a question.")
        else:
            try:
                client = genai.Client(api_key=api_key)
                rules = f"""
Language: {language}
Difficulty Level: {difficulty}

Rules:
1. Use simple words.
2. Give a clear definition.
3. Give an example if useful.
4. Keep the explanation easy for students.
5. Use bullet points when appropriate.
"""
                if input_type == "📷 Upload Image":
                    prompt = (
                        "You are an educational learning assistant.\n"
                        "Read the text in this image (English or Tamil), "
                        "then explain it simply.\n" + rules
                    )
                    contents = [prompt, Image.open(uploaded_file)]
                else:
                    contents = (
                        "You are an educational learning assistant.\n"
                        "Explain the student's question simply.\n"
                        + rules + f"\nStudent Question:\n{question}"
                    )

                response = client.models.generate_content(
                    model=MODEL, contents=contents
                )
                st.subheader("📖 AI Explanation")
                st.write(response.text)

                try:
                    st.audio(text_to_speech(response.text, language),
                             format="audio/mp3")
                except Exception:
                    st.info("Audio could not be generated (check internet).")

            except Exception as e:
                st.error("Something went wrong.")
                st.write("Error:", e)


# =============================
# Quiz + Revision section (Student)
# =============================
def quiz_section(api_key, language, difficulty, username):
    st.divider()
    st.header("📝 Quiz & Weak Topic Detection")

    quiz_topic = st.text_input("Quiz topic", placeholder="Example: Photosynthesis")

    if st.button("Generate Quiz", use_container_width=True):
        if not api_key:
            st.warning("Please enter your Gemini API key (left sidebar).")
        elif not quiz_topic:
            st.warning("Please enter a topic.")
        else:
            try:
                client = genai.Client(api_key=api_key)
                quiz_prompt = f"""
Create 5 multiple choice questions on: {quiz_topic}
Language: {language}
Difficulty: {difficulty}

Return ONLY valid JSON, no extra text, in this format:
[
  {{"question": "...", "options": ["A", "B", "C", "D"],
    "answer": "exact text of correct option",
    "subtopic": "short subtopic name"}}
]
"""
                res = client.models.generate_content(
                    model=MODEL, contents=quiz_prompt
                )
                text = res.text.replace("```json", "").replace("```", "").strip()
                st.session_state.quiz = json.loads(text)
                st.session_state.quiz_topic = quiz_topic
                st.session_state.pop("last_result", None)
            except Exception as e:
                st.error("Quiz generation failed.")
                st.write("Error:", e)

    if "quiz" in st.session_state:
        answers = {}
        for i, q in enumerate(st.session_state.quiz):
            answers[i] = st.radio(
                f"Q{i+1}. {q['question']}",
                q["options"],
                index=None,
                key=f"q{i}"
            )

        if st.button("Submit Quiz", use_container_width=True):
            score = 0
            weak = {}
            for i, q in enumerate(st.session_state.quiz):
                if answers[i] == q["answer"]:
                    score += 1
                else:
                    weak[q["subtopic"]] = weak.get(q["subtopic"], 0) + 1

            total = len(st.session_state.quiz)
            topic = st.session_state.get("quiz_topic", quiz_topic)
            save_result(username, topic, score, total, weak)
            st.session_state.last_result = {
                "score": score, "total": total, "weak": weak, "topic": topic
            }

    # Show result + revision (kept in session so it survives reruns)
    res = st.session_state.get("last_result")
    if res:
        st.success("Result saved ✅")
        st.subheader(f"Score: {res['score']} / {res['total']}")

        if res["weak"]:
            st.error("⚠️ Weak Topics:")
            for t, c in res["weak"].items():
                st.write(f"- {t} ({c} mistake)")

            st.subheader("🔁 Revise Weak Topic")
            pick = st.selectbox("Choose a topic to revise", list(res["weak"].keys()))
            if st.button("📖 Revise this topic", use_container_width=True):
                if not api_key:
                    st.warning("Please enter your Gemini API key.")
                else:
                    try:
                        client = genai.Client(api_key=api_key)
                        rev_prompt = f"""
You are a friendly teacher. The student is weak in: {pick}
(Main topic: {res['topic']}).

Language: {language}
Difficulty Level: {difficulty}

Give:
1. A very simple explanation.
2. One easy real-life example.
3. 3 key points to remember.
4. One practice question (with the answer at the end).
"""
                        out = client.models.generate_content(
                            model=MODEL, contents=rev_prompt
                        )
                        st.write(out.text)
                        try:
                            st.audio(text_to_speech(out.text, language),
                                     format="audio/mp3")
                        except Exception:
                            pass
                    except Exception as e:
                        st.error("Revision failed.")
                        st.write("Error:", e)
        else:
            st.success("🎉 No weak topics. Excellent!")


# =============================
# Dashboard (all roles)
# =============================
def dashboard_section(user):
    st.divider()
    st.header("📊 Progress Dashboard")

    if not os.path.exists(RESULTS_FILE):
        st.info("No quiz results saved yet.")
        return

    df = pd.read_csv(RESULTS_FILE)
    df["student"] = df["student"].astype(str).str.lower()
    role = user["role"]

    if role == "Student":
        df = df[df["student"] == user["username"]]
    elif role == "Parent":
        st.caption(f"Showing progress of: {user['child']}")
        df = df[df["student"] == user["child"]]
    else:  # Teacher
        names = ["All students"] + sorted(df["student"].unique().tolist())
        who = st.selectbox("View student", names)
        if who != "All students":
            df = df[df["student"] == who]

    if df.empty:
        st.info("No data yet.")
        return

    st.metric("Average Score", f"{df['percent'].mean():.1f}%")
    st.metric("Quizzes Taken", len(df))

    # Min-Max Normalization (base paper concept)
    mn, mx = df["percent"].min(), df["percent"].max()
    df["normalized"] = 0.0 if mx == mn else (df["percent"] - mn) / (mx - mn)

    st.subheader("Progress over time")
    st.line_chart(df.set_index("date")["percent"])

    st.subheader("Average by topic")
    st.bar_chart(df.groupby("topic")["percent"].mean())

    st.subheader("⚠️ Weak Topics")
    weak_list = df["weak_topics"].dropna().astype(str).str.split(", ").explode()
    weak_list = weak_list[weak_list != ""]
    if weak_list.empty:
        st.success("No weak topics 🎉")
    else:
        st.bar_chart(weak_list.value_counts())

    if role == "Teacher":
        st.subheader("All records")
        st.dataframe(df)


# =============================
# Main
# =============================
if "user" not in st.session_state:
    auth_page()
    st.stop()

user = st.session_state.user

with st.sidebar:
    st.write(f"👤 **{user['username']}**")
    st.write(f"Role: {user['role']}")
    if st.button("Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.title("🎓 LinguaLens AI")

if user["role"] == "Student":
    with st.sidebar:
        st.divider()
        api_key = st.text_input("🔑 Gemini API Key", type="password")
        language = st.selectbox("🌐 Language", ["English", "Tamil"])
        difficulty = st.selectbox("📚 Difficulty", ["Easy", "Medium", "Advanced"])

    learning_section(api_key, language, difficulty)
    quiz_section(api_key, language, difficulty, user["username"])

dashboard_section(user)
