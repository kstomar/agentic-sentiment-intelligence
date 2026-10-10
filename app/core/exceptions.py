"""Transport-independent errors with fixed, safe public messages."""

from enum import StrEnum


class ErrorCode(StrEnum):
    INGESTION_INTERRUPTED = "INGESTION_INTERRUPTED"
    GMAIL_NOT_CONFIGURED = "GMAIL_NOT_CONFIGURED"
    GMAIL_INVALID_STATE = "GMAIL_INVALID_STATE"
    GMAIL_OAUTH_DENIED = "GMAIL_OAUTH_DENIED"
    GMAIL_OAUTH_FAILED = "GMAIL_OAUTH_FAILED"
    GMAIL_SCOPE_INVALID = "GMAIL_SCOPE_INVALID"
    GMAIL_MAILBOX_CONFLICT = "GMAIL_MAILBOX_CONFLICT"
    GMAIL_ALREADY_CONNECTED = "GMAIL_ALREADY_CONNECTED"
    GMAIL_NOT_CONNECTED = "GMAIL_NOT_CONNECTED"
    GMAIL_RECONNECT_REQUIRED = "GMAIL_RECONNECT_REQUIRED"
    GMAIL_CAPACITY_EXCEEDED = "GMAIL_CAPACITY_EXCEEDED"
    GMAIL_PROVIDER_ERROR = "GMAIL_PROVIDER_ERROR"
    GMAIL_RATE_LIMITED = "GMAIL_RATE_LIMITED"
    GMAIL_TIMEOUT = "GMAIL_TIMEOUT"
    GMAIL_RESPONSE_INVALID = "GMAIL_RESPONSE_INVALID"
    GMAIL_SELECTION_INVALID = "GMAIL_SELECTION_INVALID"
    GMAIL_MESSAGE_INVALID = "GMAIL_MESSAGE_INVALID"
    GMAIL_MESSAGE_TOO_LARGE = "GMAIL_MESSAGE_TOO_LARGE"
    GMAIL_ATTACHMENTS_SKIPPED = "GMAIL_ATTACHMENTS_SKIPPED"
    GMAIL_JOB_NOT_FOUND = "GMAIL_JOB_NOT_FOUND"
    GMAIL_DISCONNECTED = "GMAIL_DISCONNECTED"
    GMAIL_UNAVAILABLE = "GMAIL_UNAVAILABLE"

    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    TENANT_CAPACITY_EXCEEDED = "TENANT_CAPACITY_EXCEEDED"
    WEBHOOK_DELIVERY_COLLISION = "WEBHOOK_DELIVERY_COLLISION"
    APP_AUTH_NOT_CONFIGURED = "APP_AUTH_NOT_CONFIGURED"
    GROQ_NOT_CONFIGURED = "GROQ_NOT_CONFIGURED"
    GROQ_MODEL_UNSUPPORTED = "GROQ_MODEL_UNSUPPORTED"
    GROQ_CONFIGURATION_ERROR = "GROQ_CONFIGURATION_ERROR"
    UPSTREAM_AUTHENTICATION_FAILED = "UPSTREAM_AUTHENTICATION_FAILED"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_REQUEST_REJECTED = "UPSTREAM_REQUEST_REJECTED"
    INVALID_MODEL_RESPONSE = "INVALID_MODEL_RESPONSE"
    INVALID_ACTION_SELECTION = "INVALID_ACTION_SELECTION"
    INVALID_GRAPH_STATE = "INVALID_GRAPH_STATE"
    EVIDENCE_VERIFICATION_FAILED = "EVIDENCE_VERIFICATION_FAILED"
    INVESTIGATION_TIMEOUT = "INVESTIGATION_TIMEOUT"
    BATCH_FILE_TOO_LARGE = "BATCH_FILE_TOO_LARGE"
    BATCH_UNSUPPORTED_FORMAT = "BATCH_UNSUPPORTED_FORMAT"
    BATCH_INVALID_ENCODING = "BATCH_INVALID_ENCODING"
    BATCH_INVALID_FILE = "BATCH_INVALID_FILE"
    BATCH_INVALID_COLUMNS = "BATCH_INVALID_COLUMNS"
    BATCH_INVALID_IDS = "BATCH_INVALID_IDS"
    BATCH_INVALID_TEXT = "BATCH_INVALID_TEXT"
    BATCH_EXTRACTION_LIMIT = "BATCH_EXTRACTION_LIMIT"
    BATCH_TOO_MANY_RECORDS = "BATCH_TOO_MANY_RECORDS"
    BATCH_NO_VALID_RECORDS = "BATCH_NO_VALID_RECORDS"
    BATCH_CAPACITY_EXCEEDED = "BATCH_CAPACITY_EXCEEDED"
    BATCH_JOB_NOT_FOUND = "BATCH_JOB_NOT_FOUND"
    BATCH_JOB_TIMEOUT = "BATCH_JOB_TIMEOUT"
    BATCH_UNAVAILABLE = "BATCH_UNAVAILABLE"
    BATCH_REPORT_UNAVAILABLE = "BATCH_REPORT_UNAVAILABLE"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    REQUEST_BODY_TIMEOUT = "REQUEST_BODY_TIMEOUT"
    INGRESS_CAPACITY_EXCEEDED = "INGRESS_CAPACITY_EXCEEDED"
    INGRESS_RATE_LIMITED = "INGRESS_RATE_LIMITED"
    PROCESSING_CAPACITY_EXCEEDED = "PROCESSING_CAPACITY_EXCEEDED"
    WEBHOOK_NOT_CONFIGURED = "WEBHOOK_NOT_CONFIGURED"
    WEBHOOK_AUTHENTICATION_FAILED = "WEBHOOK_AUTHENTICATION_FAILED"
    WEBHOOK_DELIVERY_CONFLICT = "WEBHOOK_DELIVERY_CONFLICT"
    WEBHOOK_CAPACITY_EXCEEDED = "WEBHOOK_CAPACITY_EXCEEDED"
    WEBHOOK_EVENT_NOT_FOUND = "WEBHOOK_EVENT_NOT_FOUND"
    WEBHOOK_PROCESSING_TIMEOUT = "WEBHOOK_PROCESSING_TIMEOUT"
    WEBHOOK_UNAVAILABLE = "WEBHOOK_UNAVAILABLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INGESTION_INTERRUPTED: 'Feedback processing was interrupted before a result was committed; it was not automatically repeated.',
    ErrorCode.GMAIL_NOT_CONFIGURED: 'Gmail OAuth is disabled or its server configuration is unavailable.',
    ErrorCode.GMAIL_INVALID_STATE: 'OAuth state is invalid, expired, cancelled, or already used.',
    ErrorCode.GMAIL_OAUTH_DENIED: 'Gmail authorization was not completed.',
    ErrorCode.GMAIL_OAUTH_FAILED: 'Google authorization could not be completed. Start a new connection attempt.',
    ErrorCode.GMAIL_SCOPE_INVALID: 'The required read-only Gmail authorization was not granted.',
    ErrorCode.GMAIL_MAILBOX_CONFLICT: 'The mailbox cannot be connected under the current ownership policy.',
    ErrorCode.GMAIL_ALREADY_CONNECTED: 'Disconnect the current Gmail connection before connecting a different account.',
    ErrorCode.GMAIL_NOT_CONNECTED: 'Gmail is not connected for this business.',
    ErrorCode.GMAIL_RECONNECT_REQUIRED: 'Gmail authorization is no longer usable. Reconnect the mailbox.',
    ErrorCode.GMAIL_CAPACITY_EXCEEDED: 'Gmail integration capacity is full. Retry after work finishes or retained state expires.',
    ErrorCode.GMAIL_PROVIDER_ERROR: 'Google did not complete the configured Gmail operation.',
    ErrorCode.GMAIL_RATE_LIMITED: 'Google is rate limiting the Gmail integration. Retry later.',
    ErrorCode.GMAIL_TIMEOUT: 'The Gmail operation exceeded its processing deadline.',
    ErrorCode.GMAIL_RESPONSE_INVALID: 'Google returned an invalid or oversized integration response.',
    ErrorCode.GMAIL_SELECTION_INVALID: 'The configured feedback label or message selection could not be verified.',
    ErrorCode.GMAIL_MESSAGE_INVALID: 'The message could not be safely decoded as bounded feedback text.',
    ErrorCode.GMAIL_MESSAGE_TOO_LARGE: 'The message exceeds the configured byte or sentiment text limit.',
    ErrorCode.GMAIL_ATTACHMENTS_SKIPPED: 'Messages containing attachments are outside this import policy.',
    ErrorCode.GMAIL_JOB_NOT_FOUND: 'The Gmail import was not found or has expired.',
    ErrorCode.GMAIL_DISCONNECTED: 'Gmail was disconnected and related import work was cancelled.',
    ErrorCode.GMAIL_UNAVAILABLE: 'Gmail processing is shutting down or unavailable.',

    ErrorCode.AUTHORIZATION_FAILED: "The authenticated credential does not permit this operation.",
    ErrorCode.TENANT_CAPACITY_EXCEEDED: "This business has reached its configured resource limit. Retry later.",
    ErrorCode.WEBHOOK_DELIVERY_COLLISION: "This delivery ID is reserved by another integration of this business.",
    ErrorCode.AUTHENTICATION_FAILED: "Missing or invalid X-API-Key.",
    ErrorCode.APP_AUTH_NOT_CONFIGURED: "Application authentication is unavailable. Configure server credentials.",
    ErrorCode.GROQ_NOT_CONFIGURED: "Sentiment analysis is unavailable. Configure GROQ_API_KEY.",
    ErrorCode.GROQ_MODEL_UNSUPPORTED: "GROQ_MODEL is not supported by this service's strict-output adapter.",
    ErrorCode.GROQ_CONFIGURATION_ERROR: "The Groq integration configuration is invalid.",
    ErrorCode.UPSTREAM_AUTHENTICATION_FAILED: (
        "The analysis provider rejected its configured credentials or permissions."
    ),
    ErrorCode.UPSTREAM_RATE_LIMITED: "The analysis provider is rate limited. Try again later.",
    ErrorCode.UPSTREAM_TIMEOUT: "The analysis provider did not complete within the configured time limit.",
    ErrorCode.UPSTREAM_UNAVAILABLE: "The analysis provider is temporarily unavailable.",
    ErrorCode.UPSTREAM_REQUEST_REJECTED: "The analysis provider rejected the configured model or request.",
    ErrorCode.INVALID_MODEL_RESPONSE: "The analysis provider returned an invalid or ungrounded response.",
    ErrorCode.INVALID_ACTION_SELECTION: "The provider did not return a valid approved investigation action.",
    ErrorCode.INVALID_GRAPH_STATE: "The investigation workflow produced an invalid state.",
    ErrorCode.EVIDENCE_VERIFICATION_FAILED: "Investigation findings could not be verified against the supplied feedback.",
    ErrorCode.INVESTIGATION_TIMEOUT: "The investigation exceeded its configured time limit.",
    ErrorCode.BATCH_FILE_TOO_LARGE: "The uploaded file or multipart request exceeds its size limit.",
    ErrorCode.BATCH_UNSUPPORTED_FORMAT: "Use a CSV or XLSX file with a compatible content type.",
    ErrorCode.BATCH_INVALID_ENCODING: "CSV files must use valid UTF-8, optionally with a BOM.",
    ErrorCode.BATCH_INVALID_FILE: "The file is malformed, unreadable, encrypted, or contains unsupported content.",
    ErrorCode.BATCH_INVALID_COLUMNS: "Use unique nonblank headers and valid distinct column mappings.",
    ErrorCode.BATCH_INVALID_IDS: "Mapped review IDs must be nonblank, unique, and at most 100 characters.",
    ErrorCode.BATCH_INVALID_TEXT: "Feedback must be nonblank text within the configured length limit, without Excel formulas.",
    ErrorCode.BATCH_EXTRACTION_LIMIT: "The file exceeds safe extraction, worksheet, or scan limits.",
    ErrorCode.BATCH_TOO_MANY_RECORDS: "The file exceeds the configured feedback record limit.",
    ErrorCode.BATCH_NO_VALID_RECORDS: "The file must contain at least one valid feedback record.",
    ErrorCode.BATCH_CAPACITY_EXCEEDED: "Batch capacity is full. Retry after running jobs finish or retained jobs expire.",
    ErrorCode.BATCH_JOB_NOT_FOUND: "The batch job was not found or has expired.",
    ErrorCode.BATCH_JOB_TIMEOUT: "The batch job exceeded its configured processing deadline.",
    ErrorCode.BATCH_UNAVAILABLE: "Batch processing is unavailable while the application is shutting down.",
    ErrorCode.BATCH_REPORT_UNAVAILABLE: "The batch report could not be verified or generated safely.",
    ErrorCode.REQUEST_TOO_LARGE: "The request exceeds the configured body-byte limit.",
    ErrorCode.REQUEST_BODY_TIMEOUT: "The request body did not arrive within the configured deadline.",
    ErrorCode.INGRESS_CAPACITY_EXCEEDED: "Request intake capacity is full. Retry after an active request finishes.",
    ErrorCode.INGRESS_RATE_LIMITED: "The instance request-rate limit is reached. Retry later.",
    ErrorCode.PROCESSING_CAPACITY_EXCEEDED: "Shared model processing capacity is full. Retry later.",
    ErrorCode.WEBHOOK_NOT_CONFIGURED: "Webhook ingestion is unavailable. Configure the integration ID and shared secret.",
    ErrorCode.WEBHOOK_AUTHENTICATION_FAILED: "Webhook authentication failed. Check signed headers, timestamp, and raw-body signature.",
    ErrorCode.WEBHOOK_DELIVERY_CONFLICT: "This integration and delivery ID already identify different payload bytes.",
    ErrorCode.WEBHOOK_CAPACITY_EXCEEDED: "Webhook queue or retained-delivery capacity is full. Retry later.",
    ErrorCode.WEBHOOK_EVENT_NOT_FOUND: "The feedback event was not found or has expired.",
    ErrorCode.WEBHOOK_PROCESSING_TIMEOUT: "The feedback event exceeded its processing deadline.",
    ErrorCode.WEBHOOK_UNAVAILABLE: "Webhook processing is not running or is shutting down.",
    ErrorCode.VALIDATION_ERROR: "Request validation failed.",
    ErrorCode.HTTP_ERROR: "The requested HTTP resource or method is unavailable.",
    ErrorCode.INTERNAL_ERROR: "An unexpected internal error occurred.",
}


class ApplicationError(Exception):
    """Expose a known code, never provider response bodies or exception text."""

    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        self.message = ERROR_MESSAGES[code]
        super().__init__(self.message)
