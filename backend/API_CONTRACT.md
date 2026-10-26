# Refurbishment Intelligence — API Contract & Specification

**Platform:** Circular E-Waste Recovery & Refurbishment Intelligence Platform  
**Application:** Refurbishment Intelligence Application  
**Version:** v1.0.0  
**Specification Date:** October 2026  

---

## 1. Authentication & Security

All inbound partner endpoints from the Collection Application require API Key authentication via one of the following HTTP headers:
- `X-API-Key: <CIRCULAR_API_KEY>`
- `Authorization: Bearer <CIRCULAR_API_KEY>`

Requests missing or supplying an invalid API key receive `401 Unauthorized` or `403 Forbidden` responses.

---

## 2. API Endpoints

### 2.1 Ingest Incoming Device
- **Endpoint:** `POST /api/v1/refurbishment/devices` (Alias: `POST /api/v1/devices/receive`)
- **Authentication:** Required (`X-API-Key` or Bearer)
- **Idempotency:** Supported via `Idempotency-Key` HTTP header or `transfer_id` in request body.
- **Request Headers:**
  - `Content-Type: application/json`
  - `X-API-Key: <CIRCULAR_API_KEY>`
  - `Idempotency-Key: <UUID>` *(optional, falls back to transfer_id)*
- **Request Body:**
  ```json
  {
    "device_id": "EW-2026-00129",
    "transfer_id": "TRF-00850",
    "device": {
      "type": "Laptop",
      "brand": "Dell",
      "model": "Latitude 7420",
      "purchase_year": 2023,
      "age": 3,
      "condition": "Damaged",
      "power_status": "Powers on",
      "screen_condition": "Minor scratches",
      "battery_condition": "Poor · 42% capacity",
      "weight_kg": 1.4,
      "damage_description": "Worn battery and damaged keyboard. No liquid damage."
    },
    "files": [
      {
        "name": "diagnostic_report.json",
        "type": "diagnostic",
        "storage_key": "rem_EW202600129_diag"
      }
    ]
  }
  ```
- **Responses:**
  - `201 Created`: Device successfully ingested and queued.
    ```json
    {
      "status": "success",
      "message": "Device accepted and queued for refurbishment assessment",
      "device_id": "EW-2026-00129",
      "transfer_id": "TRF-00850",
      "received_at": "2026-10-15T11:00:00"
    }
    ```
  - `200 OK`: Duplicate idempotent request previously processed; cached response returned.
  - `400 Bad Request`: Missing required fields (`device_id`, `transfer_id`, `device` object, `type`, `brand`, `model`, `condition`).
  - `401 Unauthorized`: Missing API key.
  - `403 Forbidden`: Invalid API key.
  - `409 Conflict`: Device ID already registered with a different transfer ID.
  - `500 Internal Server Error`: Transaction failure (automatically rolled back).

---

### 2.2 List Devices
- **Endpoint:** `GET /api/v1/devices`
- **Authentication:** Public / Internal Workspace
- **Query Parameters:**
  - `search` (string): Search filter matching ID, brand, model, or type.
  - `status` (string): Filter by device status (`Received`, `Queued`, `Assessing`, `Assessed`, `Refurbishment Recommended`, `Parts Recovery Recommended`, `Completed`).
  - `condition` (string): Filter by physical condition (`Good`, `Fair`, `Damaged`, `Not Working`).
  - `type` (string): Filter by device category (`Laptop`, `Smartphone`, `Monitor`).
- **Response:** `200 OK`
  ```json
  {
    "devices": [
      {
        "id": "EW-2026-00128",
        "name": "Dell Latitude 5420",
        "type": "Laptop",
        "brand": "Dell",
        "model": "Latitude 5420",
        "purchase_year": 2023,
        "age": "3 years",
        "condition": "Damaged",
        "power_status": "Powers on",
        "screen_condition": "Minor scratches",
        "battery_condition": "Poor · 42% capacity",
        "weight_kg": 1.4,
        "damage_description": "Worn battery and damaged keyboard. No liquid damage.",
        "status": "Assessing",
        "score": 86.0,
        "decision": "Refurbish",
        "repair_cost": 7100.0,
        "repair_cost_fmt": "₹7,100",
        "component_recovery_value": 12100.0,
        "component_recovery_value_fmt": "₹12,100",
        "estimated_refurbished_value": 24000.0,
        "estimated_refurbished_value_fmt": "₹24,000",
        "co2_avoided_kg": 18.0,
        "co2_avoided_fmt": "18.0 kg CO₂ avoided",
        "circular_recovery_score": 82.0,
        "time": "10:42 AM",
        "received_at": "2026-10-15T10:42:00"
      }
    ],
    "total": 1
  }
  ```

---

### 2.3 Get Single Device
- **Endpoint:** `GET /api/v1/devices/<device_id>`
- **Response:** `200 OK` (with assessment and file metadata if present) or `404 Not Found`.

---

### 2.4 Get Assessment Queue
- **Endpoint:** `GET /api/v1/queue`
- **Description:** Returns pending and in-progress devices prioritized for technical evaluation.
- **Response:** `200 OK`
  ```json
  {
    "queue": [ ... ],
    "total": 3
  }
  ```

---

### 2.5 Run / Evaluate Device Assessment
- **Endpoint:** `POST /api/v1/assessments`
- **Request Body:**
  ```json
  {
    "device_id": "EW-2026-00128",
    "assessor": "Refurbishment Admin"
  }
  ```
- **Responses:**
  - `201 Created`: Assessment computed deterministically and persisted.
    ```json
    {
      "status": "success",
      "message": "Assessment evaluated and stored",
      "assessment": {
        "assessment_id": "ASM-2026-00128",
        "device_id": "EW-2026-00128",
        "repairability_score": 86.0,
        "circular_recovery_score": 82.0,
        "repair_cost": 7100.0,
        "component_recovery_value": 12100.0,
        "estimated_refurbished_value": 24000.0,
        "co2_avoided_kg": 18.0,
        "recommendation": "Refurbish",
        "technical_summary": "Laptop (Dell Latitude 5420) presented in damaged condition...",
        "reasons": [
          "Device powers on successfully",
          "Repairability score (86/100) satisfies threshold (>=70)",
          "Estimated repair cost (₹7,100) is viable against refurbished value (₹24,000)"
        ],
        "components": [
          {
            "component_name": "RAM",
            "condition": "Good",
            "recoverable": true,
            "recovery_potential": "High",
            "estimated_value": 1600.0,
            "recommended_action": "Recover"
          }
        ]
      }
    }
    ```
  - `404 Not Found`: Device not found.

---

### 2.6 Get Assessment by ID
- **Endpoint:** `GET /api/v1/assessments/<assessment_id>`
- **Response:** `200 OK` or `404 Not Found`.

---

### 2.7 Send Assessment Result (Callback to Collection Application)
- **Endpoint:** `POST /api/v1/assessment-results/send` (Alias: `POST /api/v1/assessments/send`)
- **Request Body:**
  ```json
  {
    "device_id": "EW-2026-00128"
  }
  ```
- **Outbound Request to Partner:**
  - **URL:** `{COLLECTION_API_URL}/api/v1/assessment-results`
  - **Headers:** `X-API-Key: {CIRCULAR_API_KEY}`, `Idempotency-Key: {assessment_id}`
- **Responses:**
  - `200 OK`: Partner application confirmed receipt.
  - `503 Service Unavailable`: Partner endpoint unreachable, timed out, or unconfigured (recorded as Pending in transfer audit log).

---

### 2.8 List Transfers
- **Endpoint:** `GET /api/v1/transfers`
- **Query Parameters:** `direction` (`Inbound` or `Outbound`)
- **Response:** `200 OK` (list of bidirectional transfer records).

---

### 2.9 Get Transfer Detail
- **Endpoint:** `GET /api/v1/transfers/<transfer_id>`
- **Response:** `200 OK` (includes request_payload, response_payload, retry_count, timestamps).

---

### 2.10 Retry Transfer
- **Endpoint:** `POST /api/v1/transfers/<transfer_id>/retry`
- **Description:** Re-attempts an outbound transfer using the identical idempotency key.
- **Responses:** `200 OK` or `503 Service Unavailable`.

---

### 2.11 Download PDF Assessment Report
- **Endpoint:** `GET /api/v1/reports/assessment/<device_id>`
- **MIME Type:** `application/pdf`
- **Header:** `Content-Disposition: attachment; filename="assessment_<device_id>.pdf"`
- **Response:** Real ReportLab generated binary PDF. Returns `404 Not Found` if device has not been assessed.

---

### 2.12 Download Summary CSV
- **Endpoint:** `GET /api/v1/reports/summary`
- **MIME Type:** `text/csv; charset=utf-8`
- **Header:** `Content-Disposition: attachment; filename="refurbishment_intelligence_summary.csv"`
- **Response:** Tabular CSV of all devices, scores, recovery valuations, and recommendations.

---

### 2.13 Live Health Check
- **Endpoint:** `GET /api/health`
- **Response:**
  - `200 OK`:
    ```json
    {
      "application": "Refurbishment Intelligence",
      "status": "ok",
      "database": "ok",
      "ui_build_available": true
    }
    ```
  - `503 Service Unavailable` (Degraded):
    ```json
    {
      "application": "Refurbishment Intelligence",
      "status": "degraded",
      "database": "unavailable",
      "ui_build_available": true
    }
    ```
