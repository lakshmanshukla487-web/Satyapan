class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, retry_after: int | None = None):
        self.code, self.message, self.status_code = code, message, status_code
        self.retry_after = retry_after  # seconds; sent as the Retry-After header (429 / 503)
        super().__init__(message)
