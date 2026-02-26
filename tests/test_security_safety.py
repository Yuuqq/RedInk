import json
import os
import uuid
from pathlib import Path


def test_history_service_rejects_record_id_traversal(temp_history_dir):
    from backend.services.history import HistoryService

    service = HistoryService()
    service.history_dir = temp_history_dir
    service.index_file = os.path.join(temp_history_dir, "index.json")
    service._init_index()

    stem = f"outside_{uuid.uuid4().hex}"
    outside_path = Path(temp_history_dir).parent / f"{stem}.json"
    outside_path.write_text(json.dumps({"pwn": True}), encoding="utf-8")
    try:
        assert service.get_record(f"../{stem}") is None
        assert service.get_record(f"..\\{stem}") is None
        assert service.update_record(f"../{stem}", status="completed") is False
        assert service.delete_record(f"..\\{stem}") is False
    finally:
        try:
            outside_path.unlink(missing_ok=True)
        except Exception:
            pass


def test_generate_rejects_unsafe_task_id(client, sample_pages):
    resp = client.post(
        "/api/generate",
        json={
            "pages": sample_pages,
            "task_id": "..\\evil",
            "full_outline": "",
            "user_images": [],
        },
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data and data.get("success") is False

