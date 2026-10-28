"""Verified-purchaser report reviews + public product availability (F10-P15).

Public:
  GET  /api/report-products/availability     {slug: active} from the registry
  GET  /api/reviews/product/<slug>           published reviews, count, average
  POST /api/reviews/eligibility  {token}      who may review what (token = emailed link)
  POST /api/reviews/submit       {token, rating, body, display_name?}
Admin (admin_or_bridge_required):
  GET  /api/admin/reviews?status=PENDING|PUBLISHED|REJECTED  (or ?order_id=N, any status)
  POST /api/admin/reviews/<id>/moderate  {action: publish|reject|delete, reason?}
Tokens travel in JSON bodies (the emailed link puts them in the URL fragment),
never in query strings, so they do not land in access logs.
"""
from flask import Blueprint, jsonify, request

from routes.routes_app_version import admin_or_bridge_required
from modules.reviews import rate_limit
from modules.reviews.review_service import (
    ReviewError, eligibility_payload, list_for_moderation, moderate,
    product_availability, product_summary, submit_review,
)

routes_reviews = Blueprint("routes_reviews", __name__)


def _error(exc: ReviewError):
    return jsonify({"error": exc.code}), exc.http_status


MAX_BODY_BYTES = 16 * 1024  # a review is at most 2000 chars; refuse anything far larger before parsing


def _too_large() -> bool:
    return request.content_length is None or request.content_length > MAX_BODY_BYTES


def _limited(bucket: str, limit: int, window: int) -> bool:
    key = rate_limit.client_key(request.remote_addr, request.headers.get("X-Forwarded-For"))
    return not rate_limit.allow(bucket, key, limit, window)


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@routes_reviews.route("/api/report-products/availability", methods=["GET"])
def report_product_availability():
    response = jsonify({"products": product_availability()})
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@routes_reviews.route("/api/reviews/product/<slug>", methods=["GET"])
def reviews_for_product(slug):
    if len(slug) > 100:
        return jsonify({"error": "unknown_product"}), 404
    try:
        response = jsonify(product_summary(slug))
    except ReviewError as exc:
        return _error(exc)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@routes_reviews.route("/api/reviews/eligibility", methods=["POST"])
def review_eligibility():
    if _limited("eligibility", 30, 600):
        return jsonify({"error": "rate_limited"}), 429
    if _too_large():
        return jsonify({"error": "payload_too_large"}), 413
    try:
        return jsonify(eligibility_payload(_json_body().get("token")))
    except ReviewError as exc:
        return _error(exc)


@routes_reviews.route("/api/reviews/submit", methods=["POST"])
def review_submit():
    if _limited("submit", 10, 3600):
        return jsonify({"error": "rate_limited"}), 429
    if _too_large():
        return jsonify({"error": "payload_too_large"}), 413
    data = _json_body()
    try:
        review = submit_review(data.get("token"), data.get("rating"), data.get("body"), data.get("display_name"))
    except ReviewError as exc:
        return _error(exc)
    return jsonify({"review": review}), 200


@routes_reviews.route("/api/admin/reviews", methods=["GET"])
@admin_or_bridge_required
def admin_list_reviews():
    try:
        order_id = request.args.get("order_id")
        if order_id is not None and not order_id.isdigit():
            return jsonify({"error": "invalid_order_id"}), 400
        return jsonify({"reviews": list_for_moderation(request.args.get("status", "PENDING"),
                                                       order_id=int(order_id) if order_id else None)})
    except ReviewError as exc:
        return _error(exc)


@routes_reviews.route("/api/admin/reviews/<int:review_id>/moderate", methods=["POST"])
@admin_or_bridge_required
def admin_moderate_review(review_id):
    data = _json_body()
    try:
        return jsonify(moderate(review_id, data.get("action"), data.get("reason")))
    except ReviewError as exc:
        return _error(exc)
