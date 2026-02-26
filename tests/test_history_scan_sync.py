import os


def _touch(path: str, data: bytes = b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_scan_and_sync_aligns_by_index(history_service, sample_outline, temp_history_dir):
    # Create a record associated with a task dir
    task_id = "task_testscan"
    record_id = history_service.create_record("Scan Align", sample_outline, task_id=task_id)

    # Create task directory and only some images (missing index 1)
    task_dir = os.path.join(temp_history_dir, task_id)
    _touch(os.path.join(task_dir, "0.png"))
    _touch(os.path.join(task_dir, "2.png"))

    result = history_service.scan_and_sync_task_images(task_id)
    assert result["success"] is True
    assert result["record_id"] == record_id
    assert result["status"] == "partial"
    assert result["images_count"] == 2
    assert result["images"] == ["0.png", None, "2.png"]

    record = history_service.get_record(record_id)
    assert record["images"]["task_id"] == task_id
    assert record["images"]["generated"] == ["0.png", None, "2.png"]
    assert record["thumbnail"] == "0.png"


def test_scan_and_sync_marks_completed_only_when_all_present(history_service, temp_history_dir):
    outline = {
        "raw": "x",
        "pages": [
            {"index": 0, "type": "cover", "content": "c"},
            {"index": 1, "type": "content", "content": "p1"},
            {"index": 2, "type": "summary", "content": "s"},
        ],
    }
    task_id = "task_full"
    record_id = history_service.create_record("Full", outline, task_id=task_id)

    task_dir = os.path.join(temp_history_dir, task_id)
    _touch(os.path.join(task_dir, "0.png"))
    _touch(os.path.join(task_dir, "1.png"))
    _touch(os.path.join(task_dir, "2.png"))

    result = history_service.scan_and_sync_task_images(task_id)
    assert result["success"] is True
    assert result["record_id"] == record_id
    assert result["status"] == "completed"
    assert result["images_count"] == 3
    assert result["images"] == ["0.png", "1.png", "2.png"]


def test_scan_and_sync_rejects_unsafe_task_id(history_service):
    result = history_service.scan_and_sync_task_images("..")
    assert result["success"] is False
    assert "路径不安全" in result["error"]

