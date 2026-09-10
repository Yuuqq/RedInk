# Code Review

This document contains a code review of the RedInk repository. Findings are organized by severity (CRITICAL, HIGH, MEDIUM, LOW) and include the file path, impact, and a concrete fix suggestion.

## HIGH

### 1. Insecure Token Storage
**File:** `frontend/src/api/http.ts`, `frontend/src/api/index.ts`, `frontend/src/stores/generator.ts`
**Impact:** The authentication token is stored in `localStorage` and synchronized to a non-HttpOnly cookie. This exposes the token to XSS attacks, allowing malicious scripts to steal the token and impersonate the user.
**Fix Suggestion:** Store the authentication token in a secure, `HttpOnly` cookie set by the server. Remove the token from `localStorage` and do not expose it to JavaScript. Implement an authentication session endpoint if needed.

### 2. Google GenAI Unpinned IP SSRF Risk
**File:** `backend/generators/google_genai.py`
**Impact:** While `safe_http_request` enforces IP pinning to prevent DNS rebinding SSRF, the Google GenAI SDK (`google-genai`) manages its own underlying HTTP connections. It does not allow us to pin the validated IP address, meaning it remains vulnerable to DNS rebinding if custom base URLs are allowed.
**Fix Suggestion:** By default, disallow custom `base_url` for Google GenAI unless the environment is explicitly configured to trust unpinned providers (e.g., `REDINK_ALLOW_UNPINNED_PROVIDER_URLS=1`). This fallback has already been correctly implemented in the code but needs to be documented here as a residual risk for those who opt in.

### 3. Extremely Low Test Coverage on Core Logic
**File:** `backend/generators/*.py`, `backend/services/image.py`
**Impact:** Test coverage for `backend/services/image.py` is at 11%, `google_genai.py` at 14%, `image_api.py` at 22%, and `openai_compatible.py` at 24%. The core value proposition of this application (interacting with LLMs to generate text/images) is largely untested, making refactoring or upgrading dependencies highly risky.
**Fix Suggestion:** Implement integration tests using `vcrpy` or mocking (e.g., `pytest-mock`) to simulate API responses from Google GenAI, OpenAI, etc. This will verify the data parsing, error handling, and retry logic without requiring real API keys.

## MEDIUM

### 1. Exception Details Leakage
**File:** `backend/routes/*.py`
**Impact:** Many API routes catch generic `Exception` objects and return `str(e)` directly to the client in the 500 error response. This can leak sensitive internal details, paths, or database states to end users.
**Fix Suggestion:** Catch specific exceptions when possible. For generic unhandled exceptions, log the error trace internally and return a generic "Internal Server Error" message to the client rather than `str(e)`.

### 2. In-Memory Thread Lock for File System Operations
**File:** `backend/services/history.py` and `backend/config.py`
**Impact:** The `HistoryService` and `Config` classes use `threading.RLock()` to protect concurrent reads/writes to `index.json` and config YAML files. However, if the Flask app is deployed using a WSGI server like Gunicorn with multiple *worker processes* (not just threads), `threading.RLock()` will not prevent concurrent file corruption across processes.
**Fix Suggestion:** Replace the `threading.RLock()` with a file-based lock using a library like `filelock` when reading/writing `index.json` and config files.

### 3. Plaintext API Keys in Config Files
**File:** `backend/config.py`
**Impact:** API keys for external services are stored in plaintext in `text_providers.yaml` and `image_providers.yaml`. If a developer commits these files accidentally, or if a local file inclusion (LFI) vulnerability is found, the keys are exposed.
**Fix Suggestion:** Use environment variables for sensitive secrets (e.g., `REDINK_OPENAI_API_KEY`) and use the YAML files only for defining the provider structure and model names. Alternatively, encrypt the YAML files at rest.

## LOW

### 1. Synchronous Requests in Request-Response Cycle
**File:** `backend/generators/*.py`, `backend/utils/remote_image.py`
**Impact:** Image generation and API calls use synchronous `requests` calls inside the Flask request-response cycle (even with SSE streams, it occupies a worker thread). Under high load, this will block all available Gunicorn/Werkzeug workers, leading to denial of service.
**Fix Suggestion:** Consider migrating to `httpx` for asynchronous requests and converting the Flask app to an ASGI app (e.g., Quart or FastAPI), or use a task queue like Celery/RQ for long-running image generation tasks.

### 2. Missing Strict Input Validation on Large JSONs
**File:** `backend/routes/image_routes.py`
**Impact:** The application checks `if not isinstance(data, dict)` but doesn't strictly validate the structure or maximum size of the `pages` array before processing, which could lead to excessive memory consumption.
**Fix Suggestion:** Integrate `pydantic` or `marshmallow` schemas to strictly validate the payload structure, array lengths, and string bounds at the API boundary.
