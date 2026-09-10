# routes/admin_orders.py

from flask import Blueprint, jsonify
from extensions import db
from models import Order

# Bucket A -- Critical Fix #7. All three routes below are gated by
# admin_or_bridge_required (routes/routes_app_version.py), which tries
# the Next.js Admin BFF's X-Admin-Bridge-Key first and falls back,
# completely unmodified, to the repository's existing admin_required
# JWT + ADMIN_USER_IDS allowlist check for any other caller -- no new
# auth mechanism, no RBAC, no change to the admin login flow.
#
# Admin Orders BFF Auth Fix / Admin Orders BFF Completion: GET
# /admin/api/orders, PUT /admin/api/order/<id>, and POST
# /admin/api/resend/<id> were all previously @admin_required only --
# OrderList.tsx called each of them directly from the browser with no
# Authorization header at all, so every real GET request was silently
# rejected (401 {"msg": "Missing Authorization Header"}), which
# OrderList.tsx then handed to orders.map() unchecked, crashing the
# Admin Dashboard. All three now accept the same bridge credential the
# Next.js server-only BFF routes send (app/api/admin/orders/route.ts,
# app/api/admin/orders/[id]/route.ts, app/api/admin/orders/[id]/resend/
# route.ts) -- no business-logic change.
from routes.routes_app_version import admin_or_bridge_required


admin_orders_bp = Blueprint('admin_orders', __name__)

@admin_orders_bp.route('/admin/api/orders', methods=['GET'])
@admin_or_bridge_required
def get_all_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()

    data = []
    for o in orders:
        data.append({
            "id": o.id,
            "name": o.name,
            "email": o.email,
            "phone": o.phone,                 # ✅ NEW: phone pass to frontend
            "report_name": o.product,         # ✅ map: product → report_name            
            "payment_status": o.status,       # ✅ map: status → payment_status
            "order_time": o.created_at.isoformat() if o.created_at else None,
            "report_stage": o.report_stage or "Pending",        # ✅ placeholder (abhi column nahi)
            "pdf_url": f"/admin/download/{o.id}" if o.pdf_url else None,                   
            "language": o.language or "en" 
        })

    return jsonify(data), 200

# ------------------- RESEND ORDER ------------------- #
@admin_orders_bp.route('/admin/api/resend/<int:order_id>', methods=['POST'])
@admin_or_bridge_required
def resend_order(order_id):
    from tasks import generate_and_send_report   # ✅ NEW import

    order = Order.query.get(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    # Celery task फिर से चलाओ
    generate_and_send_report.delay(order_id)

    # Optional: stage update
    order.report_stage = "Regenerating"
    db.session.commit()

    return jsonify({"message": f"Report regeneration started for order {order_id}"}), 200

# ------------------- UPDATE ORDER ------------------- #
@admin_orders_bp.route('/admin/api/order/<int:order_id>', methods=['PUT'])
@admin_or_bridge_required
def update_order(order_id):
    from flask import request

    order = Order.query.get(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    data = request.get_json()
    print("[DEBUG] Incoming Data:", data)   # ✅ Add this line to check payload


    # ✅ update only allowed fields
    order.dob = data.get("dob", order.dob)
    order.tob = data.get("tob", order.tob)
    order.pob = data.get("pob", order.pob)
    order.latitude = data.get("latitude", order.latitude)
    order.longitude = data.get("longitude", order.longitude)

    # save changes
    db.session.commit()

    return jsonify({"message": f"Order {order_id} updated successfully"}), 200
