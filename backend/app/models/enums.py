"""ORM 枚举按业务值存储，与接口和数据库设计保持一致。"""


def enum_values(enum_class):
    return [member.value for member in enum_class]
