"""Mack Coffee: classroom marketing chatbot, demo or Gemini mode."""
import csv
import io
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
import streamlit as st

st.set_page_config(page_title="Mack Coffee Assistant", page_icon="☕")
PRODUCTS = list(csv.DictReader((Path(__file__).parent / "products.csv").open(encoding="utf-8")))

def secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""

def choose(message):
    """Select a plausible item from any row order in the classroom demo."""
    q = message.lower()
    def by_name(name):
        return next((p for p in PRODUCTS if p["name"] == name), PRODUCTS[0])
    if any(w in q for w in ("no caffeine", "caffeine free", "caffeine-free", "decaf")):
        return by_name("Herbal Iced Tea")
    if any(w in q for w in ("low caffeine", "half caf", "half-caf", "less caffeine")):
        return by_name("Half-Caf Vanilla Oat Latte")
    if "matcha" in q:
        return by_name("Matcha Oat Latte")
    if "tea" in q:
        return by_name("Peach Hibiscus Iced Tea")
    if any(w in q for w in ("cheap", "budget", "inexpensive", "under $4")):
        return min(PRODUCTS, key=lambda p: float(p["price"]))
    if "chocolate" in q or "mocha" in q:
        return by_name("Mocha Oat Latte")
    return by_name("Vanilla Oat Cold Brew")

def answer(message):
    item = choose(message)
    catalog = "\n".join(f"{p['name']}: ${p['price']}; caffeine {p['caffeine']}; sweetness {p['sweetness']}; milk {p['milk']}; {p['description']}" for p in PRODUCTS)
    key = secret("GEMINI_API_KEY")
    if not key:
        return f"Demo recommendation: {item['name']} (${item['price']}). {item['description']}. Would you like to see the menu?", item
    from google import genai
    client = genai.Client(api_key=key)
    prompt = ("You are a concise, friendly Mack Coffee sales assistant. Reply in the customer's language. "
              "Recommend only listed products and exact listed prices; do not invent discounts, dietary guarantees or stock. "
              "If preferences are unclear, ask one short clarifying question. No more than three questions before a recommendation. "
              "Offer a gentle menu CTA. Catalog:\n" + catalog + "\nRecent chat:\n" +
              "\n".join(f"{m['role']}: {m['content']}" for m in st.session_state.messages[-6:]) +
              "\ncustomer: " + message)
    result = client.models.generate_content(model="gemini-flash-latest", contents=prompt)
    return result.text or "I could not generate a reply. Please try again.", item

def event(kind, product=""):
    record = {"session_id": st.session_state.session_id, "timestamp": datetime.now(timezone.utc).isoformat(),
              "event": kind, "product": product, "variant": st.session_state.variant}
    st.session_state.events.append(record)
    url, key = secret("SUPABASE_URL"), secret("SUPABASE_PUBLISHABLE_KEY")
    if url and key:
        try:
            from supabase import create_client
            create_client(url, key).table("chatbot_events").insert(record).execute()
        except Exception:
            st.warning("Cloud event logging is unavailable; this session is still recorded locally.")

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.events = []
    st.session_state.variant = "A" if uuid.uuid4().int % 2 == 0 else "B"
    st.session_state.last_error = ""
    st.session_state.cooldown_until = 0
    st.session_state.cooldown_code = None
    event("session_start")

st.title("☕ Mack Coffee Assistant")
st.caption("Classroom demonstration: no real orders are placed. Please do not enter personal information.")
st.write("Find a drink from our sample menu. Try: ‘low caffeine and creamy’ or ‘under $4’." if st.session_state.variant == "A" else "Hello! Tell me what kind of drink would brighten your day. I can help you explore our sample menu.")
with st.expander("Sample menu"):
    st.dataframe(PRODUCTS, hide_index=True)
if st.session_state.get("last_error"):
    st.warning(st.session_state.last_error)
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"].replace("$", r"\$"))
if user := st.chat_input("What kind of drink would you like?"):
    if len(user) > 500:
        st.warning("Please use 500 characters or fewer.")
    else:
        st.session_state.messages.append({"role": "user", "content": user})
        event("message")  # Never store raw message text in the analytics table.
        st.session_state.last_error = ""
        try:
            if secret("GEMINI_API_KEY") and time.time() < st.session_state.get("cooldown_until", 0):
                code = st.session_state.get("cooldown_code")
                st.session_state.last_error = f"Service notice ({code}): Our chat assistant is temporarily unavailable."
                reply, item = "We're experiencing higher than normal demand right now. Please try again in a little while. Thank you for your understanding, coffee warriors!", None
            else:
                reply, item = answer(user)
        except Exception as exc:
            # Show a safe diagnostic without printing the API key or raw request.
            code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            kind = type(exc).__name__
            if kind in ("ModuleNotFoundError", "ImportError"):
                reason = "Python package missing. Run: python -m pip install -r requirements.txt"
            elif code == 401 or code == 403:
                reason = "Authentication or API access denied. Check your Gemini key and project access."
            elif code == 404:
                reason = "Model unavailable for this key. Check the model name and available models in AI Studio."
            elif code == 429:
                reason = "Gemini quota or rate limit reached. Try later or check AI Studio usage."
            elif code in (400, 422):
                reason = "Gemini rejected this request. Check model access and configuration."
            else:
                reason = "Check your internet connection, model availability, and Python environment."
            if code in (429, 503):
                st.session_state.cooldown_until = time.time() + 60
                st.session_state.cooldown_code = code
                st.session_state.last_error = f"Service notice ({code}): Our chat assistant is temporarily unavailable."
                reply, item = "We're experiencing higher than normal demand right now. Please try again in a little while. Thank you for your understanding, coffee warriors!", None
            else:
                st.session_state.last_error = f"Gemini request failed ({kind}" + (f", status {code}" if code else "") + f"). {reason}"
                reply, item = "I could not reach Gemini just now. Please try again after checking the error above.", None
        st.session_state.messages.append({"role": "assistant", "content": reply})
        if item:
            event("recommendation", item["name"])
        st.rerun()
if st.session_state.messages:
    if st.button("View menu / CTA"):
        event("cta_click")
        st.info("Demo CTA: in a real business, link this to the official menu or ordering page.")
    if st.button("I would consider buying"):
        event("purchase_intent")
        st.success("Thanks! This records stated intent, not an actual purchase.")
with st.sidebar:
    st.subheader("Classroom analytics")
    st.write("Mode:", "Gemini AI" if secret("GEMINI_API_KEY") else "Demo rules")
    st.write("A/B variant:", st.session_state.variant)
    st.write("Events this browser session:", len(st.session_state.events))
    data = io.StringIO()
    writer = csv.DictWriter(data, fieldnames=["session_id", "timestamp", "event", "product", "variant"])
    writer.writeheader(); writer.writerows(st.session_state.events)
    st.download_button("Download session events CSV", data.getvalue(), "mack_events.csv", "text/csv")
