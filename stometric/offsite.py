"""Private infrastructure is excluded. See docs/OPERATIONS.md for backups."""
class OffsiteError(ValueError):
    pass


def status(c):
    return {'configured': False, 'enabled': False, 'bucket': '', 'endpoint': '', 'region': ''}


def configure(*args, **kwargs):
    raise OffsiteError('Настройте резервные копии по docs/OPERATIONS.md на своём сервере.')


def run(*args, **kwargs):
    raise OffsiteError('Автоматический перенос в хранилище не настроен.')
