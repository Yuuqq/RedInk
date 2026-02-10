"""
Tests for backend/services/history.py - HistoryService

Covers CRUD operations, pagination, filtering, search, statistics,
and existence checks for history records.
"""

import os
import json
import pytest

from backend.services.history import HistoryService, RecordStatus


@pytest.fixture
def history_service(temp_history_dir):
    """Create a HistoryService that writes to a temp directory."""
    service = HistoryService()
    service.history_dir = temp_history_dir
    service.index_file = os.path.join(temp_history_dir, "index.json")
    service._init_index()
    return service


@pytest.fixture
def sample_outline():
    """Minimal outline for record creation."""
    return {
        "raw": "test outline text",
        "pages": [
            {"index": 0, "type": "cover", "content": "Cover page"},
            {"index": 1, "type": "content", "content": "Content page"},
        ],
    }


# ---------- create_record ----------

class TestCreateRecord:
    def test_create_record(self, history_service, sample_outline):
        """Creating a record returns an ID and persists a JSON file."""
        record_id = history_service.create_record("Test Topic", sample_outline)

        assert record_id is not None
        assert isinstance(record_id, str)
        assert len(record_id) > 0

        # The record JSON file must exist on disk
        record_path = history_service._get_record_path(record_id)
        assert os.path.exists(record_path)

        # The index must contain the new record
        index = history_service._load_index()
        ids_in_index = [r["id"] for r in index["records"]]
        assert record_id in ids_in_index

    def test_create_record_initial_status_is_draft(self, history_service, sample_outline):
        """New records start in DRAFT status."""
        record_id = history_service.create_record("Draft check", sample_outline)
        record = history_service.get_record(record_id)

        assert record["status"] == RecordStatus.DRAFT

    def test_create_record_stores_outline(self, history_service, sample_outline):
        """The full outline is persisted inside the record."""
        record_id = history_service.create_record("Outline check", sample_outline)
        record = history_service.get_record(record_id)

        assert record["outline"] == sample_outline

    def test_create_record_with_task_id(self, history_service, sample_outline):
        """An optional task_id is stored in the images payload."""
        record_id = history_service.create_record(
            "With task", sample_outline, task_id="task_abc123"
        )
        record = history_service.get_record(record_id)

        assert record["images"]["task_id"] == "task_abc123"
        assert record["images"]["generated"] == []


# ---------- get_record ----------

class TestGetRecord:
    def test_get_record(self, history_service, sample_outline):
        """Retrieving a record returns its full data."""
        record_id = history_service.create_record("Get test", sample_outline)
        record = history_service.get_record(record_id)

        assert record is not None
        assert record["id"] == record_id
        assert record["title"] == "Get test"
        assert "created_at" in record
        assert "updated_at" in record

    def test_get_record_not_found(self, history_service):
        """Non-existent IDs return None rather than raising."""
        result = history_service.get_record("nonexistent-id-999")

        assert result is None


# ---------- update_record ----------

class TestUpdateRecord:
    def test_update_status(self, history_service, sample_outline):
        """Updating status changes both the record file and the index."""
        record_id = history_service.create_record("Update status", sample_outline)

        success = history_service.update_record(record_id, status=RecordStatus.GENERATING)
        assert success is True

        record = history_service.get_record(record_id)
        assert record["status"] == RecordStatus.GENERATING

        # Index should also reflect the new status
        index = history_service._load_index()
        idx_entry = next(r for r in index["records"] if r["id"] == record_id)
        assert idx_entry["status"] == RecordStatus.GENERATING

    def test_update_outline(self, history_service, sample_outline):
        """Updating the outline replaces the previous one."""
        record_id = history_service.create_record("Update outline", sample_outline)
        new_outline = {
            "raw": "revised outline",
            "pages": [{"index": 0, "type": "cover", "content": "New cover"}],
        }

        success = history_service.update_record(record_id, outline=new_outline)
        assert success is True

        record = history_service.get_record(record_id)
        assert record["outline"] == new_outline

    def test_update_images(self, history_service, sample_outline):
        """Updating images stores the generated file list."""
        record_id = history_service.create_record("Update images", sample_outline)
        images_payload = {"task_id": "task_xyz", "generated": ["0.png", "1.png"]}

        success = history_service.update_record(record_id, images=images_payload)
        assert success is True

        record = history_service.get_record(record_id)
        assert record["images"] == images_payload

    def test_update_refreshes_timestamp(self, history_service, sample_outline):
        """Every update bumps updated_at."""
        record_id = history_service.create_record("Timestamp check", sample_outline)
        original = history_service.get_record(record_id)
        original_ts = original["updated_at"]

        history_service.update_record(record_id, status=RecordStatus.COMPLETED)
        updated = history_service.get_record(record_id)

        assert updated["updated_at"] >= original_ts

    def test_update_nonexistent_returns_false(self, history_service):
        """Updating a missing record returns False."""
        result = history_service.update_record("no-such-id", status=RecordStatus.ERROR)

        assert result is False


# ---------- delete_record ----------

class TestDeleteRecord:
    def test_delete_record(self, history_service, sample_outline):
        """Deleting removes both the JSON file and the index entry."""
        record_id = history_service.create_record("Delete me", sample_outline)
        assert history_service.record_exists(record_id) is True

        success = history_service.delete_record(record_id)
        assert success is True

        # Record file is gone
        assert history_service.get_record(record_id) is None
        assert history_service.record_exists(record_id) is False

        # Index no longer contains the ID
        index = history_service._load_index()
        ids = [r["id"] for r in index["records"]]
        assert record_id not in ids

    def test_delete_nonexistent_returns_false(self, history_service):
        """Deleting a non-existent record returns False."""
        result = history_service.delete_record("ghost-record-id")

        assert result is False


# ---------- list_records ----------

class TestListRecords:
    def test_list_records_pagination(self, history_service, sample_outline):
        """Pagination returns the correct slice and metadata."""
        # Create 5 records
        for i in range(5):
            history_service.create_record(f"Record {i}", sample_outline)

        result = history_service.list_records(page=1, page_size=2)

        assert result["total"] == 5
        assert result["page"] == 1
        assert result["page_size"] == 2
        assert len(result["records"]) == 2
        assert result["total_pages"] == 3  # ceil(5/2)

    def test_list_records_second_page(self, history_service, sample_outline):
        """Second page contains the expected records."""
        for i in range(5):
            history_service.create_record(f"Record {i}", sample_outline)

        result = history_service.list_records(page=2, page_size=2)

        assert len(result["records"]) == 2
        assert result["page"] == 2

    def test_list_records_last_page_partial(self, history_service, sample_outline):
        """Last page may contain fewer items than page_size."""
        for i in range(5):
            history_service.create_record(f"Record {i}", sample_outline)

        result = history_service.list_records(page=3, page_size=2)

        assert len(result["records"]) == 1

    def test_list_records_empty(self, history_service):
        """An empty history returns zero records."""
        result = history_service.list_records()

        assert result["total"] == 0
        assert result["records"] == []
        assert result["total_pages"] == 0

    def test_list_records_with_status_filter(self, history_service, sample_outline):
        """Status filter only returns matching records."""
        id1 = history_service.create_record("Draft one", sample_outline)
        id2 = history_service.create_record("Completed one", sample_outline)
        history_service.update_record(id2, status=RecordStatus.COMPLETED)

        drafts = history_service.list_records(status=RecordStatus.DRAFT)
        assert drafts["total"] == 1
        assert drafts["records"][0]["id"] == id1

        completed = history_service.list_records(status=RecordStatus.COMPLETED)
        assert completed["total"] == 1
        assert completed["records"][0]["id"] == id2

    def test_list_records_filter_no_match(self, history_service, sample_outline):
        """Filtering by a status with no records returns empty."""
        history_service.create_record("Only draft", sample_outline)

        result = history_service.list_records(status=RecordStatus.ERROR)

        assert result["total"] == 0
        assert result["records"] == []


# ---------- search_records ----------

class TestSearchRecords:
    def test_search_records(self, history_service, sample_outline):
        """Search returns records whose title contains the keyword."""
        history_service.create_record("Autumn Fashion Guide", sample_outline)
        history_service.create_record("Summer Beach Tips", sample_outline)
        history_service.create_record("autumn recipes", sample_outline)

        results = history_service.search_records("autumn")

        assert len(results) == 2
        titles = [r["title"] for r in results]
        assert "Autumn Fashion Guide" in titles
        assert "autumn recipes" in titles

    def test_search_case_insensitive(self, history_service, sample_outline):
        """Search is case-insensitive."""
        history_service.create_record("Hello World", sample_outline)

        assert len(history_service.search_records("hello")) == 1
        assert len(history_service.search_records("HELLO")) == 1
        assert len(history_service.search_records("Hello")) == 1

    def test_search_no_results(self, history_service, sample_outline):
        """Search with no matches returns an empty list."""
        history_service.create_record("Something else", sample_outline)

        results = history_service.search_records("nonexistent_keyword_xyz")

        assert results == []


# ---------- get_statistics ----------

class TestGetStatistics:
    def test_get_statistics(self, history_service, sample_outline):
        """Statistics correctly count records by status."""
        id1 = history_service.create_record("Stat 1", sample_outline)
        id2 = history_service.create_record("Stat 2", sample_outline)
        id3 = history_service.create_record("Stat 3", sample_outline)

        history_service.update_record(id1, status=RecordStatus.COMPLETED)
        history_service.update_record(id2, status=RecordStatus.COMPLETED)
        # id3 stays DRAFT

        stats = history_service.get_statistics()

        assert stats["total"] == 3
        assert stats["by_status"].get(RecordStatus.COMPLETED) == 2
        assert stats["by_status"].get(RecordStatus.DRAFT) == 1

    def test_get_statistics_empty(self, history_service):
        """Statistics on empty history returns zero total."""
        stats = history_service.get_statistics()

        assert stats["total"] == 0
        assert stats["by_status"] == {}


# ---------- record_exists ----------

class TestRecordExists:
    def test_record_exists_true(self, history_service, sample_outline):
        """Returns True for an existing record."""
        record_id = history_service.create_record("Exists check", sample_outline)

        assert history_service.record_exists(record_id) is True

    def test_record_exists_false(self, history_service):
        """Returns False for a non-existent record."""
        assert history_service.record_exists("no-such-record-id") is False

    def test_record_exists_after_delete(self, history_service, sample_outline):
        """Returns False after a record has been deleted."""
        record_id = history_service.create_record("Soon deleted", sample_outline)
        history_service.delete_record(record_id)

        assert history_service.record_exists(record_id) is False
