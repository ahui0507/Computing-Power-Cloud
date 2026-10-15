"""携带运行时间和原因的状态字符串，兼容既有业务调用。"""


class PodStatus(str):
    def __new__(
        cls, value, *, started_at=None, finished_at=None, message=None, admission_rejected=False
    ):
        instance = super().__new__(cls, value)
        instance.started_at = started_at
        instance.finished_at = finished_at
        instance.message = message
        instance.admission_rejected = admission_rejected
        return instance
