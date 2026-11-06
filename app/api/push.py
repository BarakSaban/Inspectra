"""Push subscription endpoints for the field app's "alerts when the app is closed" switch."""
from flask import Blueprint, jsonify, request, session

from app import config
from app.services import push
from app.utils.auth import inspector_required_api

push_api = Blueprint("push_api", __name__)


@push_api.route('/api/push/key', methods=['GET'])
@inspector_required_api
def push_key():
    return jsonify({"enabled": push.enabled(), "public_key": config.VAPID_PUBLIC_KEY if push.enabled() else None})


@push_api.route('/api/push/subscribe', methods=['POST'])
@inspector_required_api
def subscribe():
    if not push.enabled():
        return jsonify({"error": "push is not set up on this server"}), 503
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    if not push.save_subscription(session.get('user'), body.get("subscription"), body.get("lang")):
        return jsonify({"error": "bad request"}), 400
    return jsonify({"success": True})


@push_api.route('/api/push/unsubscribe', methods=['POST'])
@inspector_required_api
def unsubscribe():
    body = request.get_json(silent=True)
    endpoint = body.get("endpoint") if isinstance(body, dict) else None
    if isinstance(endpoint, str):
        push.remove_subscription(endpoint)
    return jsonify({"success": True})
