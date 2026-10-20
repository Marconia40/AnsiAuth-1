class ValidationError(Exception):
    pass


class DeviceExecutionError(Exception):
    def __init__(self, mensaje: str, resumen: "str | None" = None):
        super().__init__(mensaje)
        self.resumen = resumen


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class TransicionInvalidaError(Exception):
    pass


class SiteHasDevicesError(Exception):
    def __init__(self, site_id: int, device_count: int):
        super().__init__(
            f"Site {site_id} still contains {device_count} device(s) — reassign them before deletion"
        )
        self.site_id = site_id
        self.device_count = device_count


class DefaultGroupImmutableError(ValueError):
    pass


class UnsupportedVendorError(Exception):
    def __init__(self, vendor: str, platform: str, operation: str = "port management"):
        self.vendor = vendor
        self.platform = platform
        self.operation = operation
        super().__init__(
            f"{operation} is not supported for vendor='{vendor}' platform='{platform}'"
        )
