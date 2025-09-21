# routes/admin_orders.py

from flask import Blueprint, jsonify
from extensions import db
from models import Order


admin_orders_bp = Blueprint('admin_orders', __name__)

@admin_orders_bp.route('/admin/api/orders', methods=['GET'])
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
def update_order(order_id):
    from flask import request

    order = Order.query.get(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    data = request.get_json()

    # ✅ update only allowed fields
    order.dob = data.get("dob", order.dob)
    order.tob = data.get("tob", order.tob)
    order.pob = data.get("pob", order.pob)
    order.latitude = data.get("latitude", order.latitude)
    order.longitude = data.get("longitude", order.longitude)

    # save changes
    db.session.commit()

    return jsonify({"message": f"Order {order_id} updated successfully"}), 200
