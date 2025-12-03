# routes/routes_chat.py

"""
Unified Chat Routes (ChatPack 51 System)

Endpoints:
1) /api/chat/free            → 1 free question per day
2) /api/chat/pack            → Use paid ChatPack (8 questions)
3) /api/chat/pack/order      → Create ₹51 Razorpay order
4) /api/chat/pack/verify     → Verify payment & activate pack
5) /api/chat/pack/status     → Debug: check remaining questions

Uses:
- chat_engine.py
- free_quota_service.py
- chat_pack_service.py
"""

from flask import Blueprint, request, jsonify

# Services
from modules.services.chat_engine import chat_engine
from modules.services.free_quota_service import (
    has_free_quota,
    use_free_quota,
    get_free_quota_status,
)
from modules.services.chat_pack_service import (
    create_chatpack_order,
    verify_chatpack_payment,
    deduct_question,
    get_pack_status,
)

routes_chat = Blueprint("routes_chat", __name__)


# ----------------------------------------------------------
# 1) FREE QUESTION — 1/day
# ----------------------------------------------------------
@routes_chat.route("/api/chat/free", methods=["POST"])
def chat_free():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    birth = data.get("birth", {})
    question = data.get("question", "").strip()

    if not user_id or not question or not birth:
        return jsonify({"error": "Missing required fields"}), 400

    # Check free quota
    if not has_free_quota(user_id):
        return jsonify({
            "success": False,
            "message": "Free question already used today"
        }), 403

    # Use the free quota
    use_free_quota(user_id)

    # Get chat answer
    answer = chat_engine(birth, question)

    return jsonify({
        "success": True,
        "free_used": True,
        "answer": answer
    }), 200


# ----------------------------------------------------------
# 2) PAID PACK — deduct question
# ----------------------------------------------------------
@routes_chat.route("/api/chat/pack", methods=["POST"])
def chat_pack():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    birth = data.get("birth", {})
    question = data.get("question", "").strip()

    if not user_id or not question or not birth:
        return jsonify({"error": "Missing required fields"}), 400

    # Try to deduct one question
    result = deduct_question(user_id)

    if not result.get("success"):
        return jsonify(result), 403

    # Get chat answer
    answer = chat_engine(birth, question)

    return jsonify({
        "success": True,
        "remaining": result["remaining"],
        "answer": answer
    }), 200


# ----------------------------------------------------------
# 3) CREATE ₹51 ORDER
# ----------------------------------------------------------
@routes_chat.route("/api/chat/pack/order", methods=["POST"])
def chatpack_order():
    data = request.get_json() or {}
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    order = create_chatpack_order(user_id)
    return jsonify({"success": True, "order": order}), 200


# ----------------------------------------------------------
# 4) VERIFY PAYMENT
# ----------------------------------------------------------
@routes_chat.route("/api/chat/pack/verify", methods=["POST"])
def chatpack_verify():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    order_id = data.get("order_id")
    payment_id = data.get("payment_id")

    if not user_id or not order_id or not payment_id:
        return jsonify({"error": "Missing fields"}), 400

    result = verify_chatpack_payment(order_id, payment_id, user_id)
    return jsonify(result), 200


# ----------------------------------------------------------
# 5) PACK STATUS (Debug / Postman)
# ----------------------------------------------------------
@routes_chat.route("/api/chat/pack/status", methods=["GET"])
def chatpack_status():
    user_id = request.args.get("user_id")

    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    status = get_pack_status(user_id)
    return jsonify(status), 200


# ----------------------------------------------------------
# 6) FREE STATUS (Debug / Postman)
# ----------------------------------------------------------
@routes_chat.route("/api/chat/free/status", methods=["GET"])
def free_status():
    user_id = request.args.get("user_id")

    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    status = get_free_quota_status(user_id)
    return jsonify(status), 200

# ----------------------------------------------------------
# 7) REQUIREMENT EXTRACTOR (GPT-based)
# ----------------------------------------------------------
@routes_chat.route("/requirements", methods=["POST"])
def chat_requirements():
    from modules.services.chat_requirement_engine import get_required_data

    data = request.get_json() or {}
    question = data.get("question", "").strip()

    if not question:
        return jsonify({
            "success": False,
            "error": "Missing 'question'"
        }), 400

    try:
        requirements = get_required_data(question)

        print("\n🔥 REQUIREMENT ENGINE OUTPUT:")
        print(requirements)
        print("================================\n")

        return jsonify({
            "success": True,
            "requirements": requirements
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
    
@routes_chat.route("/api/chat/status", methods=["POST"])
def chat_status():
    data = request.get_json() or {}
    user_id = data.get("user_id")

    if not user_id:
        return {"success": False, "error": "user_id missing"}, 400

    from modules.models_user import User
    
    user = User.query.get(user_id)
    if not user:
        return {"success": False, "error": "user not found"}, 404

    return {
        "success": True,
        "free_used_today": user.free_used_today,   # boolean
        "remaining_tokens": user.tokens_left or 0
    }, 200

