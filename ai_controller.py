import os
import json
import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient

from extensions import db
from models import Product, Order, User, OrderItem
from sqlalchemy import or_

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ── Twilio Setup ──────────────────────────────────────────────────────────────
twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID")
twilio_token = os.environ.get("TWILIO_AUTH_TOKEN")

if twilio_sid and twilio_token and "your_twilio_sid_here" not in twilio_sid:
    twilio_client = TwilioClient(twilio_sid, twilio_token)
else:
    twilio_client = None
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# ── JWT Setup ─────────────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", "change_me_in_prod")
JWT_ALGO = "HS256"
JWT_EXPIRY_HOURS = 24

# ── Gemini Setup ──────────────────────────────────────────────────────────────
import google.generativeai as genai
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# ══════════════════════════════════════════════════════════════════════════════
# TOOL FUNCTIONS — these are called by Gemini AI
# ══════════════════════════════════════════════════════════════════════════════

def tool_search_products(query="", category="", max_results=5):
    """Search products from database"""
    try:
        placeholder = "cat_placeholder_%"
        query_obj = Product.query.filter(~Product.p_name.like(placeholder))

        if category:
            query_obj = query_obj.filter_by(category=category)
        if query:
            query_obj = query_obj.filter(or_(Product.p_name.like(f"%{query}%"), Product.features.like(f"%{query}%")))

        products_data = query_obj.limit(int(max_results)).all()
        
        products = []
        for p in products_data:
            disc = float(p.discount) if p.discount else 0
            price = float(p.price)
            products.append({
                "product_id": p.product_id,
                "p_name": p.p_name,
                "price": price,
                "discount": disc,
                "stock": p.stock,
                "features": p.features,
                "warranty": p.warranty,
                "category": p.category,
                "effective_price": round(price * (1 - disc / 100), 2)
            })

        return {"products": products, "count": len(products)}
    except Exception as e:
        return {"error": str(e)}


def tool_get_order_status(order_id=None, user_email=None, verified_user_id=None):
    """Get order status from database"""
    if not verified_user_id:
        return {"error": "Please login first to view order details."}

    try:
        orders_query = Order.query.filter_by(user_id=verified_user_id)
        if order_id:
            orders_query = orders_query.filter_by(order_id=order_id)
        elif user_email:
            orders_query = orders_query.join(User).filter(User.email == user_email).order_by(Order.order_date.desc()).limit(5)
        else:
            return {"error": "Please provide order ID or email."}

        orders_data = orders_query.all()
        
        orders = []
        for o in orders_data:
            item_names = ", ".join([item.product.p_name for item in o.items])
            orders.append({
                "order_id": o.order_id,
                "order_date": o.order_date.isoformat() if isinstance(o.order_date, datetime) else o.order_date,
                "total_amount": float(o.total_amount),
                "username": o.user.username,
                "email": o.user.email,
                "items": item_names,
                "status": o.status or 'Processing'
            })

        return {"orders": orders, "count": len(orders)}
    except Exception as e:
        return {"error": str(e)}


def tool_get_categories():
    """Get all product categories"""
    try:
        categories = db.session.query(Product.category).filter(~Product.p_name.like('cat_placeholder_%')).distinct().order_by(Product.category).all()
        cats = [c[0] for c in categories if c[0]]
        return {"categories": cats}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# TOOL DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def dispatch_tool(name, args, verified_user_id=None):
    if name == "search_products":
        result = tool_search_products(**args)
    elif name == "get_order_status":
        result = tool_get_order_status(**args, verified_user_id=verified_user_id)
    elif name == "get_categories":
        result = tool_get_categories()
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result, default=str)


# ══════════════════════════════════════════════════════════════════════════════
# GEMINI AI AGENT
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are Nova, a friendly AI customer support agent for TechMart, an online electronics store.

You can help customers with:
- Product search, prices, stock, features, warranty
- Order status tracking (only for logged in users)
- Product category listing
- Product recommendations based on budget and needs

Rules:
- Always be friendly and use simple language
- Use emojis occasionally to be warm 😊
- Never make up product details — always use the tools
- For order details, always verify the user is authenticated
- End every conversation with: Is there anything else I can help you with? 😊
- Keep replies short and helpful
"""

TOOLS_GEMINI = {
    "function_declarations": [
        {
            "name": "search_products",
            "description": "Search products by keyword or category. Returns price, stock, features, warranty.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword to search"},
                    "category": {"type": "string", "description": "Product category"},
                    "max_results": {"type": "integer", "description": "Max results to return"},
                },
            },
        },
        {
            "name": "get_order_status",
            "description": "Get order status for authenticated user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "Order ID number"},
                    "user_email": {"type": "string", "description": "User email address"},
                },
            },
        },
        {
            "name": "get_categories",
            "description": "Get all available product categories.",
            "parameters": {"type": "object", "properties": {}},
        },
    ]
}


def run_agent(user_message, conversation_history, verified_user_id=None):
    """Main AI agent function"""
    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=SYSTEM_PROMPT,
            tools=[TOOLS_GEMINI],
        )

        gemini_history = []
        for h in conversation_history:
            role = "user" if h["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [h["content"]]})

        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(user_message)

        for _ in range(5):
            fn_calls = [p for p in response.parts if hasattr(p, "function_call") and p.function_call.name]
            if not fn_calls:
                break

            tool_results = []
            for part in fn_calls:
                fc = part.function_call
                args = dict(fc.args)
                result = dispatch_tool(fc.name, args, verified_user_id)
                tool_results.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fc.name,
                            response={"result": json.loads(result)},
                        )
                    )
                )
            response = chat.send_message(tool_results)

        text_parts = [p.text for p in response.parts if hasattr(p, "text") and p.text]
        return " ".join(text_parts) or "I'm sorry, I could not process your request. Please try again."

    except Exception as e:
        print(f"[AI Agent Error]: {e}")
        return "I'm sorry, I'm having trouble right now. Please try again in a moment."


# ══════════════════════════════════════════════════════════════════════════════
# JWT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def generate_jwt(user_id):
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_jwt(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return str(payload["user_id"])
    except jwt.PyJWTError:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def send_whatsapp_message(to_number, message):
    """Send WhatsApp message via Twilio"""
    if not twilio_client:
        print(f"[WhatsApp Bypass] Twilio not configured. Would have sent: {message}")
        return False
        
    try:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_number}",
            body=message,
        )
        return True
    except Exception as e:
        print(f"[WhatsApp Error]: {e}")
        return False


def notify_order_status_change(order_id, new_status):
    """Send WhatsApp notification when order status changes"""
    try:
        order = Order.query.get(order_id)
        if not order or not order.user or type(order.user).__name__ == "Admin": # Added check for user object
            print(f"[WhatsApp] No order or user found for order {order_id}")
            return False
            
        user = order.user

        if not hasattr(user, 'phone') or not user.phone: # No phone field in user model yet
            print(f"[WhatsApp] No phone number found for order {order_id}")
            return False

        status_emoji = {
            "Processing": "⏳",
            "Shipped": "🚚",
            "Delivered": "✅",
            "Cancelled": "❌",
        }.get(new_status, "📦")

        msg = (
            f"Hello {user.username}! {status_emoji}\n\n"
            f"Your order #{order_id} has been updated!\n"
            f"Status: *{new_status}*\n"
            f"Total: ₹{float(order.total_amount):.2f}\n\n"
            f"Visit our website for more details.\n"
            f"Thank you for shopping with TechMart! 😊"
        )
        return send_whatsapp_message(user.phone, msg)
    except Exception as e:
        print(f"[WhatsApp DB Error]: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP WEBHOOK HANDLER
# ══════════════════════════════════════════════════════════════════════════════

_whatsapp_sessions = {}


def handle_whatsapp_webhook(form_data):
    """Handle incoming WhatsApp messages from Twilio"""
    from_number = form_data.get("From", "").replace("whatsapp:", "")
    body = form_data.get("Body", "").strip()

    session = _whatsapp_sessions.setdefault(from_number, {
        "history": [],
        "verified_user_id": None,
        "awaiting_token": False,
    })

    # Auth flow
    if session.get("awaiting_token"):
        user_id = verify_jwt(body)
        if user_id:
            session["verified_user_id"] = user_id
            session["awaiting_token"] = False
            reply = "✅ Identity verified! You can now ask about your orders."
        else:
            reply = "❌ Invalid token. Please try again or type 'help'."
        _whatsapp_sessions[from_number] = session
        return _twiml_reply(reply)

    # Special commands
    if body.lower() in ("login", "auth"):
        session["awaiting_token"] = True
        _whatsapp_sessions[from_number] = session
        return _twiml_reply(
            "To verify your identity, please send your JWT token.\n"
            "Get it from your account page on our website."
        )

    if body.lower() in ("logout", "signout"):
        session["verified_user_id"] = None
        session["history"] = []
        _whatsapp_sessions[from_number] = session
        return _twiml_reply("👋 You have been logged out successfully.")

    if body.lower() == "help":
        return _twiml_reply(
            "👋 Hello! I'm Nova, TechMart's AI assistant!\n\n"
            "I can help you with:\n"
            "🛍️ Product search and prices\n"
            "📦 Order tracking (type 'login' first)\n"
            "📋 Product categories\n"
            "💡 Product recommendations\n\n"
            "Just type your question and I'll help! 😊"
        )

    # Run AI agent
    reply = run_agent(
        user_message=body,
        conversation_history=session["history"],
        verified_user_id=session.get("verified_user_id"),
    )

    session["history"].append({"role": "user", "content": body})
    session["history"].append({"role": "assistant", "content": reply})
    session["history"] = session["history"][-20:]
    _whatsapp_sessions[from_number] = session

    return _twiml_reply(reply)


def _twiml_reply(message):
    """Convert message to TwiML XML format for Twilio"""
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{safe}</Message>
</Response>"""
def get_smart_recommendations(user_id=None):
    """Get personalized or trending product recommendations"""
    try:
        if user_id:
            # Recommend based on previous orders or cart items if any
            categories = db.session.query(Product.category).join(OrderItem).join(Order).filter(Order.user_id == user_id).distinct().all()
            cats = [c[0] for c in categories if c[0]]
            
            if cats:
                recs = Product.query.filter(Product.category.in_(cats)).order_by(Product.price.desc()).limit(3).all()
                if recs: 
                    return [{"product_id": r.product_id, "p_name": r.p_name, "price": float(r.price), "image": r.image, "category": r.category} for r in recs]

        # Fallback to trending
        recs = Product.query.order_by(Product.price.desc()).limit(3).all()
        return [{"product_id": r.product_id, "p_name": r.p_name, "price": float(r.price), "image": r.image, "category": r.category} for r in recs]
    except Exception as e:
        print(e)
        return []

def send_whatsapp_invoice(order_id):
    """Generate and send an invoice via WhatsApp"""
    try:
        order = Order.query.get(order_id)
        if not order: return False
        
        # Build message
        msg = f"🧾 *INVOICE: TechMart Electronics*\n\n"
        msg += f"Order ID: {order.order_id}\n"
        msg += f"Customer: {order.user.username}\n"
        msg += f"---------------------------\n"
        for item in order.items:
            msg += f"• {item.product.p_name} x{item.quantity} - ₹{float(item.product.price):.2f}\n"
        msg += f"---------------------------\n"
        msg += f"Total: ₹{float(order.total_amount):.2f}\n\n"
        msg += "Thank you for shopping with us!"
        
        # In a real app, user phone would be in DB. Using a dummy for now.
        dummy_phone = "whatsapp:+910000000000" 
        send_whatsapp_message(dummy_phone, msg)
        return True
    except Exception as e:
        print(f"Error in send_whatsapp_invoice: {e}")
        return False
